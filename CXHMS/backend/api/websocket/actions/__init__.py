"""
Action 处理器模块
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..server import ConnectionManager


def register_all_handlers(manager: "ConnectionManager"):
    from .chat import register_chat_handlers
    from .memory import register_memory_handlers
    from .tools import register_tools_handlers
    from .plugin import register_plugin_handlers
    from .context import register_context_handlers
    from .acp import register_acp_handlers
    from .mcp import register_mcp_handlers
    from .config import register_config_handlers
    from .metrics import register_metrics_handlers
    from .system import register_system_handlers
    
    register_chat_handlers(manager)
    register_memory_handlers(manager)
    register_tools_handlers(manager)
    register_plugin_handlers(manager)
    register_context_handlers(manager)
    register_acp_handlers(manager)
    register_mcp_handlers(manager)
    register_config_handlers(manager)
    register_metrics_handlers(manager)
    register_system_handlers(manager)
