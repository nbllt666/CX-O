"""插件上下文——为插件执行提供上下文与事件分发辅助。"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

import asyncio

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class PluginContext:
    """插件上下文

    提供给插件的API访问对象，插件通过此对象与系统交互
    """

    # 插件信息
    plugin_id: str
    plugin_name: str
    config: Dict[str, Any] = field(default_factory=dict)

    # 系统API（由PluginManager注入）
    _memory_manager: Optional[Any] = field(default=None, repr=False)
    _context_manager: Optional[Any] = field(default=None, repr=False)
    _llm_client: Optional[Any] = field(default=None, repr=False)
    _tool_registry: Optional[Any] = field(default=None, repr=False)
    _ws_manager: Optional[Any] = field(default=None, repr=False)
    # H3: 插件私有存储根（测试可注入 tmp；缺省落到 <server>/data/plugin_storage）
    storage_root: Optional[Path] = field(default=None, repr=False)
    # 后台异步任务引用集合，防止被GC回收
    _background_tasks: Set[asyncio.Task] = field(default_factory=set, repr=False)

    def _track_background_task(self, task: asyncio.Task) -> asyncio.Task:
        """追踪插件上下文创建的后台任务"""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def log_info(self, message: str):
        """记录信息日志"""
        logger.info(f"[{self.plugin_id}] {message}")

    def log_warning(self, message: str):
        """记录警告日志"""
        logger.warning(f"[{self.plugin_id}] {message}")

    def log_error(self, message: str):
        """记录错误日志"""
        logger.error(f"[{self.plugin_id}] {message}")

    def log_debug(self, message: str):
        """记录调试日志"""
        logger.debug(f"[{self.plugin_id}] {message}")

    # 记忆管理API
    @property
    def memory_manager(self) -> Optional[Any]:
        """获取记忆管理器"""
        return self._memory_manager

    def create_memory(self, content: str, **kwargs) -> Optional[Dict[str, Any]]:
        """创建记忆"""
        if self._memory_manager:
            try:
                memory_id = self._memory_manager.add_memory(content=content, **kwargs)
                return {"id": memory_id, "content": content}
            except Exception as e:
                self.log_error(f"创建记忆失败: {e}")
        return None

    def search_memories(self, query: str, limit: int = 10) -> list:
        """搜索记忆"""
        if self._memory_manager:
            try:
                return self._memory_manager.search(query, limit=limit)
            except Exception as e:
                self.log_error(f"搜索记忆失败: {e}")
        return []

    # 上下文管理API
    @property
    def context_manager(self) -> Optional[Any]:
        """获取上下文管理器"""
        return self._context_manager

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话"""
        if self._context_manager:
            try:
                return self._context_manager.get_session(session_id)
            except Exception as e:
                self.log_error(f"获取会话失败: {e}")
        return None

    def send_message(self, session_id: str, role: str, content: str):
        """发送消息到会话"""
        if self._context_manager:
            try:
                self._context_manager.add_message(session_id, role, content)
            except Exception as e:
                self.log_error(f"发送消息失败: {e}")

    # LLM API
    @property
    def llm_client(self) -> Optional[Any]:
        """获取LLM客户端"""
        return self._llm_client

    async def chat(self, messages: list, **kwargs) -> Optional[str]:
        """调用LLM聊天"""
        if self._llm_client:
            try:
                response = await self._llm_client.chat(messages=messages, **kwargs)
                return response.content if response else None
            except Exception as e:
                self.log_error(f"LLM调用失败: {e}")
        return None

    # 工具API
    @property
    def tool_registry(self) -> Optional[Any]:
        """获取工具注册表"""
        return self._tool_registry

    def register_tool(
        self, name: str, handler: Callable, description: str = "", parameters: dict = None
    ):
        """注册工具"""
        if self._tool_registry:
            try:
                self._tool_registry.register(
                    name=name, handler=handler, description=description, parameters=parameters or {}
                )
                self.log_info(f"工具已注册: {name}")
            except Exception as e:
                self.log_error(f"注册工具失败: {e}")

    # WebSocket API
    @property
    def ws_manager(self) -> Optional[Any]:
        """获取WebSocket管理器"""
        return self._ws_manager

    def broadcast_message(self, message: Dict[str, Any], channel: str = None):
        """广播消息"""
        if self._ws_manager:
            try:
                if channel:
                    self._track_background_task(
                        asyncio.create_task(
                            self._ws_manager.broadcast_to_channel(channel, message)
                        )
                    )
                else:
                    self._track_background_task(
                        asyncio.create_task(self._ws_manager.broadcast(message))
                    )
            except Exception as e:
                self.log_error(f"广播消息失败: {e}")

    # 配置API
    def get_config(self, key: str, default=None):
        """获取配置项"""
        return self.config.get(key, default)

    def set_config(self, key: str, value: Any):
        """设置配置项（仅内存，不持久化）"""
        self.config[key] = value

    # 存储API（插件私有存储）——H3: 旧桩实现 get_storage 恒返回默认、set_storage
    # 空操作，依赖私有存储的插件数据静默丢失。改为按 plugin 落盘 JSON
    # （<server>/data/plugin_storage/<plugin_id>/<key>.json）。
    def _storage_file(self, key: str) -> Path:
        if self.storage_root is not None:
            data_root = Path(self.storage_root)
        else:
            data_root = Path(__file__).resolve().parents[3] / "data" / "plugin_storage"
        safe_key = (
            str(key).replace("/", "_").replace("\\", "_").replace("..", "_")
        )
        return data_root / str(self.plugin_id) / f"{safe_key}.json"

    def get_storage(self, key: str, default=None) -> Any:
        """获取插件私有存储数据（缺失/读取失败返回 default）"""
        try:
            p = self._storage_file(key)
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            self.log_error(f"读取插件存储失败 {key}: {e}")
        return default

    def set_storage(self, key: str, value: Any):
        """存储插件私有数据（落盘 JSON；失败记日志不抛）"""
        try:
            p = self._storage_file(key)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            self.log_error(f"写入插件存储失败 {key}: {e}")
