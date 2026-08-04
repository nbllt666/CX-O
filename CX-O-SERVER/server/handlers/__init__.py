"""
消息处理器模块
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager
    from server.services.asr_service import ASRService
    from server.services.tts_service import TTSService


def register_handlers(
    manager: "WebSocketManager",
    asr_service: "ASRService" = None,
    tts_service: "TTSService" = None
):
    if asr_service is None or tts_service is None:
        return

    from server.handlers.chat import register_chat_handlers
    from server.handlers.memory import register_memory_handlers
    from server.handlers.tools import register_tools_handlers
    from server.handlers.plugin import register_plugin_handlers
    from server.handlers.audio import register_audio_handlers
    from server.handlers.acp import register_acp_handlers
    from server.handlers.mcp import register_mcp_handlers
    from server.handlers.config import register_config_handlers
    from server.handlers.metrics import register_metrics_handlers
    from server.handlers.system import register_system_handlers

    register_chat_handlers(manager)
    register_memory_handlers(manager)
    register_tools_handlers(manager)
    register_plugin_handlers(manager)
    register_audio_handlers(manager, asr_service, tts_service)
    register_acp_handlers(manager)
    register_mcp_handlers(manager)
    register_config_handlers(manager)
    register_metrics_handlers(manager)
    register_system_handlers(manager)
