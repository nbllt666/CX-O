"""
Handlers 模块
提供各类 WebSocket 消息处理器
"""

from server.handlers.chat import register_chat_handlers
from server.handlers.memory import register_memory_handlers
from server.handlers.audio import register_audio_handlers
from server.handlers.tools import register_tools_handlers
from server.handlers.acp import register_acp_handlers
from server.handlers.mcp import register_mcp_handlers
from server.handlers.plugin import register_plugin_handlers
from server.handlers.config import register_config_handlers
from server.handlers.metrics import register_metrics_handlers
from server.handlers.system import register_system_handlers


HANDLERS = [
    register_chat_handlers,
    register_memory_handlers,
    register_audio_handlers,
    register_tools_handlers,
    register_acp_handlers,
    register_mcp_handlers,
    register_plugin_handlers,
    register_config_handlers,
    register_metrics_handlers,
    register_system_handlers,
]


def register_all_handlers(manager):
    for register_handler in HANDLERS:
        register_handler(manager)


__all__ = [
    "register_chat_handlers",
    "register_memory_handlers",
    "register_audio_handlers",
    "register_tools_handlers",
    "register_acp_handlers",
    "register_mcp_handlers",
    "register_plugin_handlers",
    "register_config_handlers",
    "register_metrics_handlers",
    "register_system_handlers",
    "register_all_handlers",
]