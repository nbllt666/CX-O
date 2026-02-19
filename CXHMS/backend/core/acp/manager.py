import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles

from backend.core.exceptions import ACPError
from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class ACPAgentInfo:
    id: str = ""
    name: str = ""
    host: str = ""
    port: int = 0
    status: str = "offline"
    version: str = "1.0.0"
    capabilities: List[str] = field(default_factory=list)
    last_seen: str = ""
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "status": self.status,
            "version": self.version,
            "capabilities": self.capabilities,
            "last_seen": self.last_seen,
            "metadata": self.metadata,
        }


@dataclass
class ACPConnectionInfo:
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
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "local_agent_id": self.local_agent_id,
            "remote_agent_id": self.remote_agent_id,
            "remote_agent_name": self.remote_agent_name,
            "host": self.host,
            "port": self.port,
            "status": self.status,
            "connected_at": self.connected_at,
            "last_activity": self.last_activity,
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "metadata": self.metadata,
        }


@dataclass
class ACPGroupInfo:
    id: str = ""
    name: str = ""
    description: str = ""
    creator_id: str = ""
    creator_name: str = ""
    members: List[Dict] = field(default_factory=list)
    max_members: int = 50
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "creator_id": self.creator_id,
            "creator_name": self.creator_name,
            "members": self.members,
            "max_members": self.max_members,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


@dataclass
class ACPMessageInfo:
    id: str = ""
    msg_type: str = "chat"
    from_agent_id: str = ""
    from_agent_name: str = ""
    to_agent_id: Optional[str] = None
    to_group_id: Optional[str] = None
    content: Dict = field(default_factory=dict)
    timestamp: str = ""
    is_read: bool = False
    is_sent: bool = False
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
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
    """ACP管理器

    负责管理Agents、连接、群组和消息

    Attributes:
        data_dir: 数据目录路径
        agents: Agent字典
        connections: 连接字典
        groups: 群组字典
        messages: 消息字典
        _local_agent_id: 本地Agent ID
        _local_agent_name: 本地Agent名称
    """

    def __init__(self, data_dir: str = "data/acp") -> None:
        """初始化ACP管理器

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

        self._local_agent_id = ""
        self._local_agent_name = ""

        self._discovery_task = None
        self._broadcast_task = None
        self._heartbeat_task = None
        self._discovery = None

        self._load_data()

    def initialize(self, agent_id: str, agent_name: str) -> None:
        """初始化本地Agent信息

        Args:
            agent_id: Agent ID
            agent_name: Agent名称
        """
        self._local_agent_id = agent_id
        self._local_agent_name = agent_name
        logger.info(f"ACP管理器初始化: agent_id={agent_id}, agent_name={agent_name}")

    async def start(self) -> None:
        """启动ACP管理器"""
        self._load_data()

        from backend.core.acp.discover import ACPLanDiscovery
        from config.settings import settings

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

        logger.info("ACP管理器已启动")

    async def stop(self) -> None:
        """停止ACP管理器"""
        if self._discovery:
            await self._discovery.stop()
            logger.info("ACP Discovery服务已停止")

        self._save_data()
        logger.info("ACP管理器已停止")

    def _load_data(self):
        agents_file = self.data_dir / "agents.yaml"
        connections_file = self.data_dir / "connections.yaml"
        groups_file = self.data_dir / "groups.yaml"

        if agents_file.exists():
            try:
                import yaml

                with open(agents_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    for agent_data in data.get("agents", []):
                        agent = ACPAgentInfo(**agent_data)
                        self.agents[agent.id] = agent
            except Exception as e:
                logger.warning(f"加载Agents失败: {e}")

        if connections_file.exists():
            try:
                import yaml

                with open(connections_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    for conn_data in data.get("connections", []):
                        conn = ACPConnectionInfo(**conn_data)
                        self.connections[conn.id] = conn
            except Exception as e:
                logger.warning(f"加载Connections失败: {e}")

        if groups_file.exists():
            try:
                import yaml

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

    def _save_data(self):
        import yaml

        agents_file = self.data_dir / "agents.yaml"
        connections_file = self.data_dir / "connections.yaml"
        groups_file = self.data_dir / "groups.yaml"

        with open(agents_file, "w", encoding="utf-8") as f:
            yaml.dump(
                {"agents": [a.to_dict() for a in self.agents.values()]}, f, allow_unicode=True
            )

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

    async def register_agent(self, agent: ACPAgentInfo) -> ACPAgentInfo:
        async with self._lock:
            agent.last_seen = datetime.now().isoformat()
            self.agents[agent.id] = agent
            self._save_data()
            return agent

    async def update_agent_status(self, agent_id: str, status: str) -> bool:
        async with self._lock:
            if agent_id in self.agents:
                self.agents[agent_id].status = status
                self.agents[agent_id].last_seen = datetime.now().isoformat()
                self._save_data()
                return True
            return False

    async def get_agent(self, agent_id: str) -> Optional[ACPAgentInfo]:
        return self.agents.get(agent_id)

    async def list_agents(self, online_only: bool = False) -> List[Dict]:
        async with self._lock:
            agents = list(self.agents.values())
            if online_only:
                agents = [a for a in agents if a.status == "online"]
            return [a.to_dict() for a in agents]

    async def remove_agent(self, agent_id: str) -> bool:
        async with self._lock:
            if agent_id in self.agents:
                del self.agents[agent_id]
                self._save_data()
                return True
            return False

    async def create_connection(self, connection: ACPConnectionInfo) -> ACPConnectionInfo:
        async with self._lock:
            self.connections[connection.id] = connection
            self._save_data()
            return connection

    async def get_connection(self, connection_id: str) -> Optional[ACPConnectionInfo]:
        return self.connections.get(connection_id)

    async def list_connections(self, local_only: bool = True) -> List[Dict]:
        async with self._lock:
            connections = list(self.connections.values())
            if local_only:
                connections = [c for c in connections if c.local_agent_id == self._local_agent_id]
            return [c.to_dict() for c in connections]

    async def update_connection(self, connection_id: str, **kwargs) -> bool:
        async with self._lock:
            if connection_id in self.connections:
                conn = self.connections[connection_id]
                for key, value in kwargs.items():
                    if hasattr(conn, key):
                        setattr(conn, key, value)
                self._save_data()
                return True
            return False

    async def delete_connection(self, connection_id: str) -> bool:
        async with self._lock:
            if connection_id in self.connections:
                del self.connections[connection_id]
                self._save_data()
                return True
            return False

    async def create_group(self, group: ACPGroupInfo) -> ACPGroupInfo:
        async with self._lock:
            self.groups[group.id] = group
            self.messages[group.id] = []
            self._save_data()
            return group

    async def get_group(self, group_id: str) -> Optional[ACPGroupInfo]:
        return self.groups.get(group_id)

    async def list_groups(self) -> List[Dict]:
        async with self._lock:
            return [g.to_dict() for g in self.groups.values()]

    async def update_group(self, group_id: str, **kwargs) -> bool:
        async with self._lock:
            if group_id in self.groups:
                group = self.groups[group_id]
                for key, value in kwargs.items():
                    if hasattr(group, key):
                        setattr(group, key, value)
                group.updated_at = datetime.now().isoformat()
                self._save_data()
                return True
            return False

    async def delete_group(self, group_id: str) -> bool:
        async with self._lock:
            if group_id in self.groups:
                del self.groups[group_id]
                if group_id in self.messages:
                    del self.messages[group_id]
                self._save_data()
                return True
            return False

    async def add_group_member(self, group_id: str, member: Dict) -> bool:
        async with self._lock:
            if group_id in self.groups:
                group = self.groups[group_id]
                group.members.append(member)
                group.updated_at = datetime.now().isoformat()
                self._save_data()
                return True
            return False

    async def remove_group_member(self, group_id: str, agent_id: str) -> bool:
        async with self._lock:
            if group_id in self.groups:
                group = self.groups[group_id]
                group.members = [m for m in group.members if m.get("agent_id") != agent_id]
                group.updated_at = datetime.now().isoformat()
                self._save_data()
                return True
            return False

    async def send_message(self, message: ACPMessageInfo) -> ACPMessageInfo:
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

            self._save_data()
            return message

    async def get_messages(
        self, target_id: str, group_id: str = None, limit: int = 50, unread_only: bool = False
    ) -> List[Dict]:
        async with self._lock:
            key = group_id or target_id
            messages = self.messages.get(key, [])

            if unread_only:
                messages = [m for m in messages if not m.is_read]

            return [m.to_dict() for m in messages[-limit:]]

    async def mark_messages_read(self, message_ids: List[str]) -> int:
        marked = 0
        async with self._lock:
            for messages in self.messages.values():
                for msg in messages:
                    if msg.id in message_ids and not msg.is_read:
                        msg.is_read = True
                        marked += 1
            if marked > 0:
                self._save_data()
        return marked

    async def get_statistics(self) -> Dict:
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
            }
