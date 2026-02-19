"""
消息处理器模块
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gateway.server import ConnectionManager
    from services.cxhms_client import CXHMSClient
    from services.asr_client import ASRClient
    from services.tts_client import TTSClient


def register_handlers(
    manager: "ConnectionManager",
    cxhms_client: "CXHMSClient",
    asr_client: "ASRClient",
    tts_client: "TTSClient"
):
    from handlers.chat import register_chat_handlers
    from handlers.memory import register_memory_handlers
    from handlers.tools import register_tools_handlers
    from handlers.plugin import register_plugin_handlers
    from handlers.audio import register_audio_handlers
    from handlers.acp import register_acp_handlers
    from handlers.mcp import register_mcp_handlers
    from handlers.config import register_config_handlers
    from handlers.metrics import register_metrics_handlers
    from handlers.system import register_system_handlers
    
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
