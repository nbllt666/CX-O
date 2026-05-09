"""
消息处理器模块
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager
    from server.services.cxhms_client import CXHMSClient
    from server.services.asr_client import ASRClient
    from server.services.tts_client import TTSClient


def register_handlers(
    manager: "ConnectionManager",
    cxhms_client: "CXHMSClient" = None,
    asr_client: "ASRClient" = None,
    tts_client: "TTSClient" = None
):
    if cxhms_client is None or asr_client is None or tts_client is None:
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

    register_chat_handlers(manager, cxhms_client)
    register_memory_handlers(manager, cxhms_client)
    register_tools_handlers(manager, cxhms_client)
    register_plugin_handlers(manager, cxhms_client)
    register_audio_handlers(manager, asr_client, tts_client)
    register_acp_handlers(manager, cxhms_client)
    register_mcp_handlers(manager, cxhms_client)
    register_config_handlers(manager, cxhms_client)
    register_metrics_handlers(manager, cxhms_client)
    register_system_handlers(manager, cxhms_client)
