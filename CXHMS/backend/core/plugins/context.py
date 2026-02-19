from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from backend.core.logging_config import get_contextual_logger

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
                    import asyncio

                    asyncio.create_task(self._ws_manager.broadcast_to_channel(channel, message))
                else:
                    import asyncio

                    asyncio.create_task(self._ws_manager.broadcast(message))
            except Exception as e:
                self.log_error(f"广播消息失败: {e}")

    # 配置API
    def get_config(self, key: str, default=None):
        """获取配置项"""
        return self.config.get(key, default)

    def set_config(self, key: str, value: Any):
        """设置配置项（仅内存，不持久化）"""
        self.config[key] = value

    # 存储API（插件私有存储）
    def get_storage(self, key: str, default=None) -> Any:
        """获取存储数据"""
        # 实际实现应该使用数据库或文件存储
        # 这里简化处理，仅返回默认值
        return default

    def set_storage(self, key: str, value: Any):
        """存储数据"""
        # 实际实现应该使用数据库或文件存储
        pass
