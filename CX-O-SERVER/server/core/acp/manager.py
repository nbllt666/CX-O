"""ACP 自动回复管线管理器——管理 Agent 间消息分发、连接与分组。"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))，禁止相对路径）
# CX-O 迁移版：_THIS_DIR     = c:\CX-O\CX-O-SERVER\server\core\acp
#   _PROJECT_ROOT = c:\CX-O\CX-O-SERVER（上 3 级）
# 与 decision_core.py L35-37 路径锚点模式对齐。
# D14 修复（20260719）：原 L290 agents_file = os.path.join("data", "agents.json")
#   为相对路径，依赖 cwd 解析。修复为绝对路径，消除 cwd 依赖。
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))


# ACP 自动回复专用提示词已收敛至 server/prompt_builder.py（ACP_REPLY_HINT_PROMPT，
# 单入口约束见 AGENTS.md §4.9）。本文件不再重复定义。


class ACPAgentInfo(BaseModel):
    """ACP Agent 信息数据模型。"""

    id: str = ""
    name: str = ""
    host: str = ""
    port: int = 0
    status: str = "offline"
    version: str = "1.0.0"
    capabilities: List[str] = Field(default_factory=list)
    last_seen: str = ""
    metadata: Dict = Field(default_factory=dict)

    def to_dict(self) -> Dict:
        """转换为字典表示。"""
        return self.model_dump()


class ACPConnectionInfo(BaseModel):
    """ACP Agent 连接信息数据模型。"""

    id: str = ""
    local_agent_id: str = ""
    remote_agent_id: str = ""
    remote_agent_name: str = ""
    host: str = ""
    port: int = 0
    status: str = "disconnected"
    connected_at: Optional[str] = None
    last_activity: Optional[str] = None
    messages_sent: int = 0
    messages_received: int = 0
    metadata: Dict = Field(default_factory=dict)

    def to_dict(self) -> Dict:
        """转换为字典表示。"""
        return self.model_dump()


class ACPGroupInfo(BaseModel):
    """ACP 群组信息数据模型。"""

    id: str = ""
    name: str = ""
    description: str = ""
    creator_id: str = ""
    creator_name: str = ""
    members: List[Dict] = Field(default_factory=list)
    max_members: int = 50
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""
    metadata: Dict = Field(default_factory=dict)

    def to_dict(self) -> Dict:
        """转换为字典表示。"""
        return self.model_dump()


class ACPMessageInfo(BaseModel):
    """ACP 消息信息数据模型。"""

    id: str = ""
    msg_type: str = "chat"
    from_agent_id: str = ""
    from_agent_name: str = ""
    to_agent_id: Optional[str] = None
    to_group_id: Optional[str] = None
    content: Dict = Field(default_factory=dict)
    timestamp: str = ""
    is_read: bool = False
    is_sent: bool = False
    metadata: Dict = Field(default_factory=dict)

    # #30（差异审查登记）: ACP wire 契约统一以 `type` 为准（to_dict 的映射），
    # 接收侧兼容 `type`/`msg_type` 两种键，避免外部 Agent 按 `type` 上报时
    # 字段错位落默认值。
    @model_validator(mode="before")
    @classmethod
    def _wire_type_alias(cls, values):
        if isinstance(values, dict) and "type" in values and "msg_type" not in values:
            values["msg_type"] = values.pop("type")
        return values

    def to_dict(self) -> Dict:
        """转换为字典表示，保持字段名映射：msg_type -> type。"""
        return {
            "id": self.id,
            "type": self.msg_type,
            "from_agent_id": self.from_agent_id,
            "from_agent_name": self.from_agent_name,
            "to_agent_id": self.to_agent_id,
            "to_group_id": self.to_group_id,
            "content": self.content,
            "timestamp": self.timestamp,
            "is_read": self.is_read,
            "is_sent": self.is_sent,
            "metadata": self.metadata,
        }


class ACPManager:
    """ACP 管理器 (v3.1.0 - per-agent 资源隔离)

    负责管理 Agents、连接、群组和消息。

    v3.1.0 升级特性（合并自 CXHMS v3.1.0 + CX-O 适配）：
        1. per-agent Weaviate collection 懒创建（CXHMSMemory_{agent_id}）
        2. per-agent SQLite graph 懒加载（data/graph_{agent_id}.db）
        3. agent 重启端口更新修复（update_agent_port）
        4. agent 删除时资源清理（cleanup_agent_resources）
        5. 向后兼容：agent_id="default" 回退到共享 collection 与 data/graph.db
        6. 本地 CXHMS agent 注册到 ACP 网络（_register_local_cxhms_agents）
        7. 外部 agent HTTP 消息投递（_deliver_to_external_agent）
        8. 本地 agent 消息投递 + 自动回复（_deliver_to_local_agent / _trigger_auto_reply）

    Attributes:
        data_dir: 数据目录路径
        agents: Agent 字典
        connections: 连接字典
        groups: 群组字典
        messages: 消息字典
        _local_agent_id: 本地 Agent ID
        _local_agent_name: 本地 Agent 名称
        _local_http_port: 本地 HTTP 端口（供 BEACON 暴露给其他节点）
        _agent_weaviate_stores: per-agent Weaviate store 缓存
        _agent_graph_dbs: per-agent SQLite graph database 缓存
    """

    # v3.1.0 per-agent 隔离常量
    DEFAULT_AGENT_ID = "default"
    DEFAULT_WEAVIATE_COLLECTION = "CXOMemory"  # CX-O 既有共享 collection（向后兼容）
    PER_AGENT_WEAVIATE_PREFIX = "CXHMSMemory_"  # per-agent collection 前缀（spec 要求）
    # 图数据库路径基于 _PROJECT_ROOT 解析（rules-0 §三：禁止 CWD 相对路径）。
    # 与 agents_file 等路径锚点保持一致，避免依赖运行时工作目录。
    DEFAULT_GRAPH_DB = os.path.join(_PROJECT_ROOT, "data", "graph.db")  # CX-O 既有共享 graph（向后兼容）
    PER_AGENT_GRAPH_PREFIX = os.path.join(_PROJECT_ROOT, "data", "graph_")  # per-agent graph 文件前缀
    LOCAL_AGENT_SOURCES = ("cxhms_local", "cxhms_main", "cxo_local", "cxo_main")

    def __init__(self, data_dir: str = "data/acp") -> None:
        """初始化 ACP 管理器

        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.agents: Dict[str, ACPAgentInfo] = {}
        self.connections: Dict[str, ACPConnectionInfo] = {}
        self.groups: Dict[str, ACPGroupInfo] = {}
        self.messages: Dict[str, List[ACPMessageInfo]] = {}

        self._lock = asyncio.Lock()

        # 后台任务引用集合：防止 _trigger_auto_reply 等长任务被 GC 提前回收
        # （asyncio 不持有裸 create_task 的引用，任务完成前被回收会静默中断）。
        self._background_tasks: set[asyncio.Task] = set()

        self._local_agent_id = ""
        self._local_agent_name = ""

        self._discovery_task = None
        self._broadcast_task = None
        self._heartbeat_task = None
        self._discovery = None
        # #22/23（补充批注）: 心跳/离线清扫周期与超时（start 时按配置覆盖）
        self._heartbeat_interval: float = 10.0
        self._heartbeat_timeout: float = 30.0

        # v3.1.0: 本地 HTTP 端口（供 BEACON 暴露给其他节点，由 start() 从 settings 注入）
        self._local_http_port: int = 8001

        # v3.1.0: per-agent 资源隔离缓存（懒创建/懒加载）
        self._agent_weaviate_stores: Dict[str, Any] = {}
        self._agent_graph_dbs: Dict[str, Any] = {}
        self._resource_lock = asyncio.Lock()

        self._load_data()

    @property
    def local_http_port(self) -> int:
        """本地 HTTP 端口，供 BEACON 暴露给其他节点用于回送 HTTP 消息"""
        return self._local_http_port

    def initialize(self, agent_id: str, agent_name: str) -> None:
        """初始化本地 Agent 信息

        Args:
            agent_id: Agent ID
            agent_name: Agent 名称
        """
        self._local_agent_id = agent_id
        self._local_agent_name = agent_name
        logger.info(f"ACP管理器初始化: agent_id={agent_id}, agent_name={agent_name}")

    def _track_background_task(self, task: asyncio.Task) -> asyncio.Task:
        """追踪后台任务，防止被 GC 回收；任务完成后自动从集合中移除。"""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def start(self) -> None:
        """启动 ACP 管理器"""
        self._load_data()
        self._register_local_cxhms_agents()

        from server.core.acp.discover import ACPLanDiscovery
        from server.config import get_settings

        settings = get_settings()

        # 注入本地 HTTP 端口（适配 CX-O: settings.config.system.port）
        try:
            self._local_http_port = int(settings.config.system.port)
        except Exception:
            try:
                self._local_http_port = int(settings.config.gateway.port)
            except Exception:
                self._local_http_port = 8001

        if settings.config.acp.discovery.enabled:
            self._discovery = ACPLanDiscovery(
                acp_manager=self,
                broadcast_port=settings.config.acp.discovery.broadcast_port,
                discovery_port=settings.config.acp.discovery.discovery_port,
                broadcast_address=settings.config.acp.discovery.broadcast_address,
                interval=settings.config.acp.discovery.interval,
            )
            await self._discovery.start()
            logger.info("ACP Discovery服务已启动")

        # #22/23（补充批注）: 心跳/离线清扫此前从未启动——manager 只起 discovery，
        # 已发现 agent 不会自动 offline；后台任务引用也只有 discovery 真正创建。
        # 统一经 _track_background_task 登记心跳循环（连接配置 heartbeat_interval/timeout）。
        try:
            conn_cfg = settings.config.acp.connection
            self._heartbeat_interval = float(getattr(conn_cfg, "heartbeat_interval", 10) or 10)
            self._heartbeat_timeout = float(getattr(conn_cfg, "timeout", 30) or 30)
        except Exception:
            self._heartbeat_interval, self._heartbeat_timeout = 10.0, 30.0
        self._heartbeat_task = self._track_background_task(
            asyncio.create_task(self._check_agents_heartbeat_loop())
        )

        logger.info("ACP管理器已启动")

    async def stop(self) -> None:
        """停止 ACP 管理器"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self._discovery:
            await self._discovery.stop()
            logger.info("ACP Discovery服务已停止")

        await self._save_data()

        # v3.1.0: 关闭所有 per-agent 存储实例
        await self._close_all_agent_resources()

        logger.info("ACP管理器已停止")

    # ------------------------------------------------------------------ #
    # #22/23（补充批注）: 心跳/离线清扫——周期性探测过期在线的远程 agent，
    # 失败置 offline（此前 agent 被发现后永不自动下线）
    # ------------------------------------------------------------------ #
    async def _check_agents_heartbeat_loop(self) -> None:
        """周期性心跳/离线清扫循环（经 _track_background_task 登记）。"""
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                await self._check_agents_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"ACP 心跳清扫异常: {e}")

    def _is_local_agent(self, agent: ACPAgentInfo) -> bool:
        """本地 agent 判定：自身 id 或本机地址（host 为空/回环）。"""
        return (
            agent.id == self._local_agent_id
            or agent.host in ("", "127.0.0.1", "localhost")
        )

    async def _check_agents_heartbeat(self) -> None:
        async with self._lock:
            snapshot = [a for a in self.agents.values() if a.status == "online"]

        for agent in snapshot:
            if self._is_local_agent(agent):
                continue
            try:
                last = datetime.fromisoformat(agent.last_seen) if agent.last_seen else None
            except ValueError:
                last = None
            # 无 last_seen 或超时未更新 → 视为待探测
            stale = last is None or (datetime.now() - last).total_seconds() > self._heartbeat_timeout
            if not stale:
                continue
            if await self._probe_agent(agent):
                async with self._lock:
                    agent.last_seen = datetime.now().isoformat()
            else:
                async with self._lock:
                    agent.status = "offline"
                logger.info(
                    f"ACP agent {agent.id}@{agent.host}:{agent.port} 心跳探测失败，置为 offline"
                )

    async def _probe_agent(self, agent: ACPAgentInfo) -> bool:
        """探测远程 agent 存活：GET /health 200 视为存活（复用共享 HTTP 客户端）。"""
        try:
            from server.core.utils import get_shared_http_client

            client = get_shared_http_client()
            resp = await client.get(
                f"http://{agent.host}:{agent.port}/health", timeout=5.0
            )
            return resp.status_code == 200
        except Exception:
            return False

    def _register_local_cxhms_agents(self):
        """将本地 CXHMS/CX-O agent 注册到 ACP 网络，实现同实例 agent 互通。

        从 data/agents.json 加载本地 agent，注册到 self.agents 字典。
        本地 agent 标记为 host="127.0.0.1", port=0，不通过 HTTP 投递消息，
        消息只存储在本地 self.messages 字典中。

        适配 CX-O: 读取 data/agents.json（若存在），路径与 CXHMS 一致；
        若文件不存在则静默跳过，不破坏 CX-O 既有 agent 加载机制。
        """
        # 1. 注册主系统 agent（_local_agent_id）到 ACP 网络
        if self._local_agent_id and self._local_agent_id not in self.agents:
            self.agents[self._local_agent_id] = ACPAgentInfo(
                id=self._local_agent_id,
                name=self._local_agent_name or self._local_agent_id,
                host="127.0.0.1",
                port=0,
                status="online",
                version="1.0.0",
                capabilities=["chat"],
                last_seen=datetime.now().isoformat(),
                metadata={"source": "cxo_main"},
            )
            logger.info(
                f"已注册主系统 Agent 到 ACP 网络: {self._local_agent_id} ({self._local_agent_name})"
            )

        # 2. 从 data/agents.json 加载用户创建的角色卡 agent（适配 CX-O 既有数据格式）
        agents_file = os.path.join(_PROJECT_ROOT, "data", "agents.json")
        if not os.path.exists(agents_file):
            return

        try:
            with open(agents_file, "r", encoding="utf-8") as f:
                cxhms_agents = json.load(f)

            count = 0
            for agent_data in cxhms_agents:
                agent_id = agent_data.get("id", "")
                if not agent_id:
                    continue
                # 跳过已存在的外部 agent（不覆盖外部发现的 agent）
                if agent_id in self.agents:
                    existing = self.agents[agent_id]
                    if existing.metadata.get("source") not in self.LOCAL_AGENT_SOURCES:
                        continue

                self.agents[agent_id] = ACPAgentInfo(
                    id=agent_id,
                    name=agent_data.get("name", agent_id),
                    host="127.0.0.1",
                    port=0,
                    status="online",
                    version="1.0.0",
                    capabilities=["chat"],
                    last_seen=datetime.now().isoformat(),
                    metadata={"source": "cxo_local"},
                )
                count += 1

            if count:
                logger.info(f"已注册 {count} 个本地 Agent 到 ACP 网络")
        except Exception as e:
            logger.warning(f"注册本地 Agent 失败: {e}")

    def _load_data(self):
        import yaml

        agents_file = self.data_dir / "agents.yaml"
        connections_file = self.data_dir / "connections.yaml"
        groups_file = self.data_dir / "groups.yaml"

        if agents_file.exists():
            try:
                with open(agents_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    for agent_data in data.get("agents", []):
                        agent = ACPAgentInfo(**agent_data)
                        self.agents[agent.id] = agent
            except Exception as e:
                logger.warning(f"加载Agents失败: {e}")

        if connections_file.exists():
            try:
                with open(connections_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    for conn_data in data.get("connections", []):
                        conn = ACPConnectionInfo(**conn_data)
                        self.connections[conn.id] = conn
            except Exception as e:
                logger.warning(f"加载Connections失败: {e}")

        if groups_file.exists():
            try:
                with open(groups_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    for group_data in data.get("groups", []):
                        group = ACPGroupInfo(**group_data)
                        self.groups[group.id] = group
            except Exception as e:
                logger.warning(f"加载Groups失败: {e}")

        logger.info(
            f"ACP数据加载完成: agents={len(self.agents)}, connections={len(self.connections)}, groups={len(self.groups)}"
        )

    def _save_data_sync(self):
        """同步保存数据（线程安全，供 _save_data 通过 asyncio.to_thread 调用）

        排除本地动态注册的 agent（source in LOCAL_AGENT_SOURCES），
        它们由 _register_local_cxhms_agents 动态注册，不持久化。
        """
        import yaml

        agents_file = self.data_dir / "agents.yaml"
        connections_file = self.data_dir / "connections.yaml"
        groups_file = self.data_dir / "groups.yaml"

        with open(agents_file, "w", encoding="utf-8") as f:
            # 排除本地动态注册的 agent（不持久化）
            external_agents = [
                a.to_dict()
                for a in self.agents.values()
                if a.metadata.get("source") not in self.LOCAL_AGENT_SOURCES
            ]
            yaml.dump({"agents": external_agents}, f, allow_unicode=True)

        with open(connections_file, "w", encoding="utf-8") as f:
            yaml.dump(
                {"connections": [c.to_dict() for c in self.connections.values()]},
                f,
                allow_unicode=True,
            )

        with open(groups_file, "w", encoding="utf-8") as f:
            yaml.dump(
                {"groups": [g.to_dict() for g in self.groups.values()]}, f, allow_unicode=True
            )

        logger.info("ACP数据已保存")

    async def _save_data(self):
        """异步保存数据（通过 asyncio.to_thread 避免阻塞事件循环）"""
        await asyncio.to_thread(self._save_data_sync)

    async def register_agent(self, agent: ACPAgentInfo, persist: bool = True) -> ACPAgentInfo:
        """注册/更新 agent。

        Args:
            agent: agent 信息。
            persist: 是否立即落盘。批量发现场景传 False 以合并为一次落盘，
                避免逐个 agent 触发全量 YAML 重写（见 discover.py）。
        """
        async with self._lock:
            agent.last_seen = datetime.now().isoformat()
            self.agents[agent.id] = agent
            if persist:
                await self._save_data()
            return agent

    async def update_agent_status(self, agent_id: str, status: str) -> bool:
        """更新 agent 在线状态与最近活跃时间，并持久化。"""
        async with self._lock:
            if agent_id in self.agents:
                self.agents[agent_id].status = status
                self.agents[agent_id].last_seen = datetime.now().isoformat()
                await self._save_data()
                return True
            return False

    async def get_agent(self, agent_id: str) -> Optional[ACPAgentInfo]:
        """按 ID 获取 agent，不存在时返回 None。"""
        return self.agents.get(agent_id)

    async def list_agents(self, online_only: bool = False) -> List[Dict]:
        """列出全部（或仅在线）agent 的字典列表。"""
        async with self._lock:
            agents = list(self.agents.values())
            if online_only:
                agents = [a for a in agents if a.status == "online"]
            return [a.to_dict() for a in agents]

    async def remove_agent(self, agent_id: str) -> bool:
        """删除 agent

        v3.1.0: 删除 agent 时自动清理对应的 per-agent 资源（Weaviate collection + SQLite graph）。
        向后兼容：default agent 的共享资源不会被清理。
        """
        existed = False
        async with self._lock:
            if agent_id in self.agents:
                del self.agents[agent_id]
                await self._save_data()
                existed = True

        # v3.1.0: 删除 agent 时清理 per-agent 资源（锁外执行，避免长时间持锁）
        if existed:
            try:
                await self.cleanup_agent_resources(agent_id)
            except Exception as e:
                logger.warning(f"清理 agent {agent_id} 资源失败: {e}")
        return existed

    async def update_agent(
        self,
        agent_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> bool:
        """按提供的可选字段更新 agent 属性并持久化，agent 不存在时返回 False。"""
        async with self._lock:
            if agent_id not in self.agents:
                return False
            agent = self.agents[agent_id]
            if name is not None:
                agent.name = name
            if description is not None:
                meta = dict(agent.metadata or {})
                meta["description"] = description
                agent.metadata = meta
            if capabilities is not None:
                agent.capabilities = capabilities
            if status is not None:
                agent.status = "online" if status == "active" else "offline"
            agent.last_seen = datetime.now().isoformat()
            await self._save_data()
            return True

    async def create_connection(self, connection: ACPConnectionInfo) -> ACPConnectionInfo:
        """创建一条新连接并持久化。"""
        async with self._lock:
            self.connections[connection.id] = connection
            await self._save_data()
            return connection

    async def get_connection(self, connection_id: str) -> Optional[ACPConnectionInfo]:
        """按 ID 获取连接，不存在时返回 None。"""
        return self.connections.get(connection_id)

    async def list_connections(self, local_only: bool = True) -> List[Dict]:
        """列出连接，local_only 为 True 时仅返回本地 agent 的连接。"""
        async with self._lock:
            connections = list(self.connections.values())
            if local_only:
                connections = [c for c in connections if c.local_agent_id == self._local_agent_id]
            return [c.to_dict() for c in connections]

    async def update_connection(self, connection_id: str, **kwargs) -> bool:
        """按 kwargs 更新连接字段并持久化，连接不存在时返回 False。"""
        async with self._lock:
            if connection_id in self.connections:
                conn = self.connections[connection_id]
                for key, value in kwargs.items():
                    if hasattr(conn, key):
                        setattr(conn, key, value)
                await self._save_data()
                return True
            return False

    async def delete_connection(self, connection_id: str) -> bool:
        """删除连接并持久化，连接不存在时返回 False。"""
        async with self._lock:
            if connection_id in self.connections:
                del self.connections[connection_id]
                await self._save_data()
                return True
            return False

    async def create_group(self, group: ACPGroupInfo) -> ACPGroupInfo:
        """创建新群组并初始化其消息槽，然后持久化。"""
        async with self._lock:
            self.groups[group.id] = group
            self.messages[group.id] = []
            await self._save_data()
            return group

    async def get_group(self, group_id: str) -> Optional[ACPGroupInfo]:
        """按 ID 获取群组，不存在时返回 None。"""
        return self.groups.get(group_id)

    async def list_groups(self) -> List[Dict]:
        """列出全部群组的字典列表。"""
        async with self._lock:
            return [g.to_dict() for g in self.groups.values()]

    async def update_group(self, group_id: str, **kwargs) -> bool:
        """按 kwargs 更新群组字段、刷新 updated_at 并持久化。"""
        async with self._lock:
            if group_id in self.groups:
                group = self.groups[group_id]
                for key, value in kwargs.items():
                    if hasattr(group, key):
                        setattr(group, key, value)
                group.updated_at = datetime.now().isoformat()
                await self._save_data()
                return True
            return False

    async def delete_group(self, group_id: str) -> bool:
        """删除群组及其消息历史并持久化，不存在时返回 False。"""
        async with self._lock:
            if group_id in self.groups:
                del self.groups[group_id]
                if group_id in self.messages:
                    del self.messages[group_id]
                await self._save_data()
                return True
            return False

    async def add_group_member(self, group_id: str, member: Dict) -> bool:
        """向群组追加成员并持久化，群组不存在时返回 False。"""
        async with self._lock:
            if group_id in self.groups:
                group = self.groups[group_id]
                group.members.append(member)
                group.updated_at = datetime.now().isoformat()
                await self._save_data()
                return True
            return False

    async def remove_group_member(self, group_id: str, agent_id: str) -> bool:
        """从群组移除指定 agent 成员并持久化，群组不存在时返回 False。"""
        async with self._lock:
            if group_id in self.groups:
                group = self.groups[group_id]
                group.members = [m for m in group.members if m.get("agent_id") != agent_id]
                group.updated_at = datetime.now().isoformat()
                await self._save_data()
                return True
            return False

    async def send_message(self, message: ACPMessageInfo) -> ACPMessageInfo:
        """发送消息

        v3.1.0: 支持 HTTP 投递到外部 agent + 本地 agent 消息注入自动回复。
        消息先存储到 self.messages，再根据目标 agent 类型投递：
        - 外部 agent（host:port 且 port != 9999）→ HTTP 投递
        - 本地 agent（port=0 且 source in LOCAL_AGENT_SOURCES）→ 内存注入 + 自动回复
        """
        async with self._lock:
            if message.to_group_id:
                if message.to_group_id not in self.messages:
                    self.messages[message.to_group_id] = []
                self.messages[message.to_group_id].append(message)
            elif message.to_agent_id:
                agent_id = message.to_agent_id
                if agent_id not in self.messages:
                    self.messages[agent_id] = []
                self.messages[agent_id].append(message)

            # 消息仅存内存（agents/connections/groups 才持久化），此处不触发 YAML 重写，
            # 避免每条消息都产生 3 次冗余文件 I/O（ACP 自动回复热路径）。

        # v3.1.0: 若目标 Agent 是外部 Agent（有 host:port 且 port 不是发现端口 9999），通过 HTTP 投递
        if message.to_agent_id and not message.to_group_id:
            target = self.agents.get(message.to_agent_id)
            if target and target.host and target.port and target.port != 9999:
                try:
                    await self._deliver_to_external_agent(target, message)
                except Exception as e:
                    logger.warning(
                        f"向外部 Agent {message.to_agent_id} 投递消息失败: {e}"
                    )
            elif (
                target
                and target.port == 0
                and target.metadata.get("source") in self.LOCAL_AGENT_SOURCES
            ):
                # 本地 agent：注入到目标 agent session 并触发自动回复
                try:
                    await self._deliver_to_local_agent(target, message)
                except Exception as e:
                    logger.warning(
                        f"向本地 Agent {message.to_agent_id} 投递消息失败: {e}"
                    )

        return message

    async def _deliver_to_local_agent(
        self, target: ACPAgentInfo, message: ACPMessageInfo
    ) -> None:
        """向本地 agent 投递消息（移植自 CXHMS v3.1.0）

        将 ACP 消息注入到目标 agent 的聊天 session（作为 user 消息），
        然后通过目标 agent 的配置和工具触发 LLM 自动回复。

        与 _deliver_to_external_agent 对称：外部 agent 走 HTTP，本地 agent 走内存。

        适配 CX-O: 自动回复依赖 server.core.chat.stream 管线（generate_chat_stream），
        通过 try-except 守护延迟导入，依赖异常时静默跳过，不影响消息存储。
        """
        # 主系统 agent 映射到前端 default session
        if target.id == self._local_agent_id:
            target_agent_id = self.DEFAULT_AGENT_ID
        else:
            target_agent_id = target.id

        # 1. 将消息注入到目标 agent 的 session
        await self._inject_into_chat_context(message, target_agent_id=target_agent_id)

        # 2. 触发目标 agent 的自动回复（后台执行，不阻塞 send_message 返回）
        self._track_background_task(
            asyncio.create_task(self._trigger_auto_reply(message, target_agent_id=target_agent_id))
        )

        logger.info(
            f"消息已投递到本地 Agent: to={target_agent_id}, "
            f"from={message.from_agent_id}"
        )

    async def _deliver_to_external_agent(self, target: ACPAgentInfo, message: ACPMessageInfo) -> None:
        """通过 HTTP 向外部 Agent 投递消息（移植自 CXHMS v3.1.0）

        复用预热好的 shared HTTP client（见 core/utils.get_shared_http_client），
        避免每条外部消息都重新构造 httpx.AsyncClient（含连接池/系统代理探测开销）。
        """
        from server.core.utils import get_shared_http_client

        url = f"http://{target.host}:{target.port}/acp/message"
        # #30（差异审查登记）: 投递负载改为复用 to_dict()（wire 键 `type`），
        # 不再手工拼 msg_type——旧实现与线上格式（to_dict→type）双标准，
        # 外部 Agent 按 `type` 上报会字段错位。
        payload = message.to_dict()

        client = get_shared_http_client()
        resp = await client.post(url, json=payload, timeout=5.0)
        if 200 <= resp.status_code < 300:
            logger.info(f"消息已投递到外部 Agent {target.id}@{target.host}:{target.port}")
        else:
            logger.warning(
                f"外部 Agent {target.id} 返回非 2xx: {resp.status_code} {resp.text[:200]}"
            )

    async def receive_external_message(self, message: ACPMessageInfo) -> ACPMessageInfo:
        """接收外部 ACP Agent 发来的消息（移植自 CXHMS v3.1.0）

        此方法供 /acp/receive 端点调用，将外部 Agent 通过 HTTP 投递的消息存入本地历史，
        并作为 system 消息注入到本地 Agent 的聊天上下文（session_id = agent-{local_agent_id}），
        让主系统前端以系统消息形式显示，LLM 在下次对话时也能看到。
        """
        async with self._lock:
            self.messages.setdefault(message.from_agent_id, []).append(message)

        # 消息仅存内存，不触发 YAML 重写（见 send_message 注释）。

        # 注入 system 消息到本地 Agent 聊天上下文
        try:
            await self._inject_into_chat_context(message)
        except Exception as e:
            logger.warning(f"注入 ACP 消息到聊天上下文失败: {e}")

        # 立即触发 LLM 自动回复（后台任务，不阻塞接收端点返回）
        self._track_background_task(asyncio.create_task(self._trigger_auto_reply(message)))

        logger.info(
            f"接收外部消息: from={message.from_agent_id}, type={message.msg_type}"
        )
        return message

    async def _trigger_auto_reply(
        self, message: ACPMessageInfo, target_agent_id: str = None
    ) -> None:
        """通过正常聊天管线处理 ACP 消息，agent 可使用工具回复（移植自 CXHMS v3.1.0）

        在 _inject_into_chat_context 之后调用。ACP 消息已作为 user 消息注入
        session，本方法通过 generate_chat_stream 走正常聊天管线（含工具调用循环），
        agent 可自行决定是否调用 acp_send_message 工具回复。

        适配 CX-O: 依赖 server.core.chat.stream（generate_chat_stream/ChatStreamState）、
        server.core.tools.graph_tools.set_current_agent_id 与 server.chat_helpers，
        均通过 try-except 守护延迟导入，依赖异常时静默记 warning 并返回。
        """
        if not self._local_agent_id and not target_agent_id:
            return

        try:
            from server.dependencies import get_context_manager, get_model_router
        except Exception as e:
            logger.warning(f"ACP 自动回复跳过: 依赖导入失败 (dependencies): {e}")
            return

        try:
            from server.core.chat.stream import generate_chat_stream, ChatStreamState
        except Exception as e:
            logger.warning(
                f"ACP 自动回复跳过: CX-O 暂无 chat stream 管线 (server.core.chat.stream): {e}"
            )
            return

        try:
            from server.chat_helpers import get_agent_config, get_llm_client_for_agent
            from server.chat_helpers import get_tools_for_agent
            from server.prompt_builder import build_messages
        except Exception as e:
            logger.warning(
                f"ACP 自动回复跳过: chat 工具函数不可用: {e}"
            )
            return

        try:
            context_mgr = get_context_manager()
            model_router = get_model_router()

            # 决定使用哪个 agent 的配置
            effective_agent_id = target_agent_id or self.DEFAULT_AGENT_ID
            agent_config = get_agent_config(effective_agent_id) or {
                "system_prompt": "你是一个有帮助的AI助手。请用中文回答用户的问题，保持友好和专业。",
                "temperature": 0.7,
                "max_tokens": 4096,
                "enable_thinking": False,
            }

            # 根据 agent 配置获取 LLM 客户端
            llm = get_llm_client_for_agent(agent_config)
            if not llm:
                llm = model_router.get_client("main")

            if not llm:
                logger.warning(
                    f"ACP 自动回复失败: agent={effective_agent_id} 的 LLM 客户端不可用"
                )
                return

            tools = get_tools_for_agent()

            session_id = f"agent-{effective_agent_id}"

            # 收敛到 prompt_builder.build_messages 单入口（AGENTS.md §4.9）：
            # acp_context 非 None 时进入 ACP 自动回复模式——注入 ACP_REPLY_HINT_PROMPT
            # + 历史 + incoming_message，不追加 user 消息。历史在 to_thread 中预加载，
            # 避免阻塞事件循环（get_recent_messages 为同步 DB 调用）。
            history = await asyncio.to_thread(
                context_mgr.get_recent_messages, session_id, limit=50
            )
            messages = build_messages(
                agent_config=agent_config,
                context_mgr=context_mgr,
                session_id=session_id,
                user_message="",
                history=history,
                acp_context={"from_agent_id": message.from_agent_id},
            )

            logger.info(
                f"ACP 自动回复启动: from={message.from_agent_id}, "
                f"messages={len(messages)}, tools={len(tools)}"
            )

            # 设置当前工具调用上下文的 agent_id（适配 CX-O: set_current_agent_id 可能不存在）
            try:
                from server.core.tools.graph_tools import set_current_agent_id

                if effective_agent_id == self.DEFAULT_AGENT_ID:
                    set_current_agent_id(self._local_agent_id)
                else:
                    set_current_agent_id(effective_agent_id)
            except Exception as e:
                logger.debug(f"set_current_agent_id 不可用，跳过: {e}")

            # 通过 generate_chat_stream 走正常聊天管线（含工具调用循环）
            state = ChatStreamState()
            async for _ in generate_chat_stream(
                llm=llm,
                messages=messages,
                agent_config=agent_config,
                tools=tools,
                session_id=session_id,
                state=state,
                is_background=True,
            ):
                pass

            reply_text = state.accumulated_response or "(无回复内容)"

            # 保存助手响应到目标 session
            reply_metadata = {
                "source": "acp_auto_reply",
                "acp_message_id": message.id,
                "from_agent_id": message.from_agent_id,
                "tool_calls": state.tool_calls if state.tool_calls else None,
            }
            context_mgr.add_message(
                session_id=session_id,
                role="assistant",
                content=reply_text,
                content_type="acp_reply",
                metadata=reply_metadata,
            )

            # 外部消息场景：同时保存到本地系统 agent 的 ACP 协议级 session
            if not target_agent_id and self._local_agent_id:
                acp_session_id = context_mgr.ensure_session(
                    f"agent-{self._local_agent_id}",
                    workspace_id="agent-chats",
                    title=f"{self._local_agent_name} 的对话",
                    metadata={"agent_id": self._local_agent_id},
                )
                context_mgr.add_message(
                    session_id=acp_session_id,
                    role="assistant",
                    content=reply_text,
                    content_type="acp_reply",
                    metadata=reply_metadata,
                )

            logger.info(
                f"ACP 自动回复完成: from={message.from_agent_id}, "
                f"reply={reply_text[:100]}"
            )

        except Exception as e:
            logger.warning(f"ACP 自动回复失败: {e}")

    async def _inject_into_chat_context(
        self, message: ACPMessageInfo, target_agent_id: str = None
    ) -> None:
        """将 ACP 消息作为 user 消息注入到本地 Agent 聊天上下文（移植自 CXHMS v3.1.0）

        ACP 消息类似于用户消息——agent 收到后触发回复。因此注入为 user 角色，
        让 agent 通过正常聊天管线（含工具调用）处理。

        适配 CX-O: 使用 server.core.context.manager.ContextManager 的同步接口
        （create_session/get_session/add_message）；若接口缺失，本方法记 warning 并跳过，
        不影响 ACP 消息存储核心功能。
        """
        if not self._local_agent_id and not target_agent_id:
            return

        try:
            from server.dependencies import get_context_manager
        except Exception as e:
            logger.warning(f"ACP 消息注入跳过: get_context_manager 不可用: {e}")
            return

        try:
            context_mgr = get_context_manager()
        except Exception as e:
            logger.warning(f"ACP 消息注入跳过: context_manager 未初始化: {e}")
            return

        # 提取消息文本
        content_dict = message.content or {}
        if isinstance(content_dict, str):
            text = content_dict
        else:
            text = content_dict.get("text") or content_dict.get("message") or str(content_dict)

        user_content = (
            f"[ACP 消息] 来自 {message.from_agent_name or message.from_agent_id}: {text}"
        )

        msg_metadata = {
            "source": "acp_external" if not target_agent_id else "acp_local",
            "from_agent_id": message.from_agent_id,
            "from_agent_name": message.from_agent_name,
            "msg_type": message.msg_type,
            "acp_message_id": message.id,
            "timestamp": message.timestamp or datetime.now().isoformat(),
        }

        try:
            if target_agent_id:
                # 本地 agent 互通场景：只注入到目标 agent 的 session
                session_id = f"agent-{target_agent_id}"
                target_agent_name = target_agent_id
                target_info = self.agents.get(target_agent_id)
                if target_info:
                    target_agent_name = target_info.name or target_agent_id
                context_mgr.ensure_session(
                    session_id,
                    workspace_id="agent-chats",
                    title=f"{target_agent_name} 的对话",
                    metadata={"agent_id": target_agent_id},
                )
                context_mgr.add_message(
                    session_id=session_id,
                    role="user",
                    content=user_content,
                    content_type="acp_message",
                    metadata=msg_metadata,
                )
                return

            # 外部消息场景：注入到 ACP 协议级 session
            session_id = context_mgr.ensure_session(
                f"agent-{self._local_agent_id}",
                workspace_id="agent-chats",
                title=f"{self._local_agent_name} 的对话",
                metadata={"agent_id": self._local_agent_id},
            )
            context_mgr.add_message(
                session_id=session_id,
                role="user",
                content=user_content,
                content_type="acp_message",
                metadata=msg_metadata,
            )

            # 同时注入到前端默认助手 session（agent-default），确保前端可见
            default_session_id = context_mgr.ensure_session(
                f"agent-{self.DEFAULT_AGENT_ID}",
                workspace_id="agent-chats",
                title="默认助手的对话",
                metadata={"agent_id": self.DEFAULT_AGENT_ID},
            )
            context_mgr.add_message(
                session_id=default_session_id,
                role="user",
                content=user_content,
                content_type="acp_message",
                metadata=msg_metadata,
            )
        except AttributeError as e:
            # context_manager 接口缺失某些方法，记 warning 不阻断
            logger.warning(
                f"ACP 消息注入: context_manager 接口不兼容,消息仅存于 ACP 历史: {e}"
            )
        except Exception as e:
            logger.warning(f"ACP 消息注入失败: {e}")

    async def get_messages(
        self, target_id: str, group_id: str = None, limit: int = 50, unread_only: bool = False
    ) -> List[Dict]:
        """获取消息列表，可按群组/目标过滤，支持仅未读与最近 N 条截取。"""
        async with self._lock:
            key = group_id or target_id
            messages = self.messages.get(key, [])

            if unread_only:
                messages = [m for m in messages if not m.is_read]

            return [m.to_dict() for m in messages[-limit:]]

    async def mark_messages_read(self, message_ids: List[str]) -> int:
        """将指定消息标记为已读，返回本次实际标记的数量。"""
        marked = 0
        id_set = set(message_ids)
        async with self._lock:
            for messages in self.messages.values():
                for msg in messages:
                    if msg.id in id_set and not msg.is_read:
                        msg.is_read = True
                        marked += 1
            # 消息仅存内存，不触发 YAML 重写（见 send_message 注释）。
        return marked

    async def get_statistics(self) -> Dict:
        """汇总 ACP 网络的统计信息（agent/连接/群组/消息/资源计数）。"""
        async with self._lock:
            online_agents = sum(1 for a in self.agents.values() if a.status == "online")
            active_connections = sum(
                1 for c in self.connections.values() if c.status == "connected"
            )
            total_unread = sum(
                len([m for m in msgs if not m.is_read]) for msgs in self.messages.values()
            )

            return {
                "total_agents": len(self.agents),
                "online_agents": online_agents,
                "total_connections": len(self.connections),
                "active_connections": active_connections,
                "total_groups": len(self.groups),
                "total_messages": sum(len(msgs) for msgs in self.messages.values()),
                "unread_messages": total_unread,
                "local_agent_id": self._local_agent_id,
                "local_agent_name": self._local_agent_name,
                "local_http_port": self._local_http_port,
                # v3.1.0: per-agent 资源隔离统计
                "per_agent_weaviate_stores": len(self._agent_weaviate_stores),
                "per_agent_graph_dbs": len(self._agent_graph_dbs),
            }

    # ==================== v3.1.0 per-agent 资源隔离 ====================

    async def update_agent_port(self, agent_id: str, port: int) -> bool:
        """v3.1.0: 更新 agent 端口

        agent 重启使用新端口后，主系统记录的端口更新，新消息投递到新端口。

        Args:
            agent_id: Agent ID
            port: 新端口号

        Returns:
            bool: True 表示更新成功，False 表示 agent 不存在
        """
        if not isinstance(port, int) or port <= 0 or port > 65535:
            logger.warning(f"无效的端口号: {port}")
            return False

        async with self._lock:
            if agent_id not in self.agents:
                return False
            old_port = self.agents[agent_id].port
            self.agents[agent_id].port = port
            self.agents[agent_id].last_seen = datetime.now().isoformat()
            await self._save_data()

        logger.info(
            f"Agent 端口已更新: {agent_id} {old_port} -> {port}（v3.1.0 端口修复）"
        )
        return True

    async def cleanup_agent_resources(self, agent_id: str) -> bool:
        """v3.1.0: 清理 agent 资源（Weaviate collection + SQLite graph 文件）

        删除 agent 时自动调用，清理对应的 per-agent 资源：
        - per-agent Weaviate collection（CXHMSMemory_{agent_id}）
        - per-agent SQLite graph 文件（data/graph_{agent_id}.db）
        - 关闭并移除缓存的存储实例

        向后兼容：agent_id="default" 不清理共享资源（CXOMemory / data/graph.db），
        仅移除缓存引用（若有），返回 True。

        Args:
            agent_id: Agent ID

        Returns:
            bool: True 表示清理完成（或共享资源跳过清理）
        """
        if agent_id == self.DEFAULT_AGENT_ID:
            logger.info(
                "跳过 default agent 资源清理（共享资源 CXOMemory/graph.db，向后兼容）"
            )
            async with self._resource_lock:
                # default 仅移除缓存引用，不删除共享 collection/文件
                self._agent_weaviate_stores.pop(agent_id, None)
                self._agent_graph_dbs.pop(agent_id, None)
            return True

        cleaned: List[str] = []

        async with self._resource_lock:
            # 1. 清理 per-agent Weaviate collection
            store = self._agent_weaviate_stores.pop(agent_id, None)
            if store is not None:
                collection_name = f"{self.PER_AGENT_WEAVIATE_PREFIX}{agent_id}"
                try:
                    if getattr(store, "_client", None):
                        try:
                            if store._client.collections.exists(collection_name):
                                store._client.collections.delete(collection_name)
                                logger.info(f"已删除 Weaviate collection: {collection_name}")
                                cleaned.append(f"weaviate_collection:{collection_name}")
                        except Exception as e:
                            logger.warning(
                                f"删除 Weaviate collection {collection_name} 失败: {e}"
                            )
                    try:
                        store.close()
                    except Exception as e:
                        logger.debug(f"关闭 Weaviate store 连接: {e}")
                except Exception as e:
                    logger.warning(f"清理 Weaviate store 失败: {e}")

            # 2. 清理 per-agent SQLite graph
            db = self._agent_graph_dbs.pop(agent_id, None)
            if db is not None:
                try:
                    db.close()
                    cleaned.append("graph_db_connection")
                except Exception as e:
                    logger.warning(f"关闭 graph database 失败: {e}")

            # 3. 删除 per-agent SQLite 文件
            graph_path = Path(f"{self.PER_AGENT_GRAPH_PREFIX}{agent_id}.db")
            if graph_path.exists():
                try:
                    os.remove(str(graph_path))
                    logger.info(f"已删除 SQLite graph 文件: {graph_path}")
                    cleaned.append(f"graph_db_file:{graph_path}")
                except Exception as e:
                    logger.warning(f"删除 SQLite 文件 {graph_path} 失败: {e}")

            # 4. 清理可能的 -wal/-shm 侧车文件
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{self.PER_AGENT_GRAPH_PREFIX}{agent_id}.db{suffix}")
                if sidecar.exists():
                    try:
                        os.remove(str(sidecar))
                    except Exception:
                        pass

        logger.info(f"Agent {agent_id} 资源清理完成: {cleaned}")
        return True

    def get_agent_weaviate_store(self, agent_id: str):
        """v3.1.0: 获取 agent 专属 Weaviate store（懒创建）

        - agent_id="default": 返回共享 CXOMemory store（向后兼容）
        - 其他: 返回 per-agent CXHMSMemory_{agent_id} store（懒创建）

        首次访问时创建并缓存，后续直接返回缓存实例。
        若 Weaviate 不可用，返回 None（不抛异常）。

        Args:
            agent_id: Agent ID

        Returns:
            WeaviateVectorStore or None: per-agent store 实例，Weaviate 不可用时返回 None
        """
        if agent_id in self._agent_weaviate_stores:
            return self._agent_weaviate_stores[agent_id]

        if agent_id == self.DEFAULT_AGENT_ID:
            schema_class = self.DEFAULT_WEAVIATE_COLLECTION
        else:
            schema_class = f"{self.PER_AGENT_WEAVIATE_PREFIX}{agent_id}"

        try:
            store = self._create_weaviate_store(schema_class)
            if store is None:
                return None
            self._agent_weaviate_stores[agent_id] = store
            logger.info(
                f"v3.1.0 懒创建 Weaviate store: agent={agent_id}, collection={schema_class}"
            )
            return store
        except Exception as e:
            logger.error(f"创建 Weaviate store 失败: agent={agent_id}, error={e}")
            return None

    def _create_weaviate_store(self, schema_class: str):
        """创建 WeaviateVectorStore 实例，从 CX-O config 读取配置

        适配 CX-O: 从 settings.config.memory.weaviate 读取 host/port/grpc_port/
        embedded/vector_size/api_key；config 读取失败时用 WeaviateVectorStore 默认值。

        Args:
            schema_class: Weaviate collection 名

        Returns:
            WeaviateVectorStore or None
        """
        try:
            from server.core.memory.weaviate_store import WeaviateVectorStore
        except Exception as e:
            logger.error(f"导入 WeaviateVectorStore 失败: {e}")
            return None

        # 默认值（与 WeaviateConfig 默认一致）
        host = "localhost"
        port = 8080
        grpc_port = 50051
        embedded = False
        vector_size = 768
        api_key = None

        try:
            from server.config import get_settings

            settings = get_settings()
            w = settings.config.memory.weaviate
            host = getattr(w, "host", host)
            port = getattr(w, "port", port)
            grpc_port = getattr(w, "grpc_port", grpc_port)
            embedded = getattr(w, "embedded", embedded)
            vector_size = getattr(w, "vector_size", vector_size)
            api_key = getattr(w, "api_key", api_key)
        except Exception as e:
            logger.warning(f"读取 Weaviate config 失败,用默认值: {e}")

        try:
            return WeaviateVectorStore(
                host=host,
                port=port,
                grpc_port=grpc_port,
                embedded=embedded,
                vector_size=vector_size,
                schema_class=schema_class,
                api_key=api_key,
            )
        except Exception as e:
            logger.error(f"实例化 WeaviateVectorStore 失败 (schema={schema_class}): {e}")
            return None

    def get_agent_graph_database(self, agent_id: str):
        """v3.1.0: 获取 agent 专属 graph database（懒加载）

        - agent_id="default": 返回共享 data/graph.db（向后兼容）
        - 其他: 返回 per-agent data/graph_{agent_id}.db（懒加载）

        首次访问时创建并初始化表结构，后续直接返回缓存实例。
        直接实例化 Database（不通过 get_database 单例），避免与主系统共享实例冲突。

        Args:
            agent_id: Agent ID

        Returns:
            Database or None: per-agent graph database 实例，创建失败时返回 None
        """
        if agent_id in self._agent_graph_dbs:
            return self._agent_graph_dbs[agent_id]

        if agent_id == self.DEFAULT_AGENT_ID:
            db_path = self.DEFAULT_GRAPH_DB
        else:
            db_path = f"{self.PER_AGENT_GRAPH_PREFIX}{agent_id}.db"

        try:
            from server.core.graph.config import GraphConfig
            from server.core.graph.database import Database
        except Exception as e:
            logger.error(f"导入 graph Database 失败: {e}")
            return None

        try:
            # 确保父目录存在
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

            config = GraphConfig(database_path=db_path)
            db = Database(config)
            db.initialize()  # 创建表结构
            self._agent_graph_dbs[agent_id] = db
            logger.info(
                f"v3.1.0 懒加载 graph database: agent={agent_id}, path={db_path}"
            )
            return db
        except Exception as e:
            logger.error(f"创建 graph database 失败: agent={agent_id}, path={db_path}, error={e}")
            return None

    async def _close_all_agent_resources(self) -> None:
        """v3.1.0: 关闭所有 per-agent 存储实例（stop 时调用）

        注意：此方法仅关闭缓存实例的连接，不删除 collection/文件。
        资源删除由 cleanup_agent_resources 显式调用。
        """
        async with self._resource_lock:
            # 关闭所有 Weaviate store
            for agent_id, store in list(self._agent_weaviate_stores.items()):
                try:
                    if getattr(store, "_client", None):
                        store.close()
                except Exception as e:
                    logger.debug(f"关闭 Weaviate store (agent={agent_id}): {e}")
            self._agent_weaviate_stores.clear()

            # 关闭所有 graph database
            for agent_id, db in list(self._agent_graph_dbs.items()):
                try:
                    db.close()
                except Exception as e:
                    logger.debug(f"关闭 graph database (agent={agent_id}): {e}")
            self._agent_graph_dbs.clear()

        logger.info("v3.1.0: 所有 per-agent 存储实例已关闭")
