"""
服务客户端模块
"""
from .effect_parser import EffectParser
from .emotion_parser import extract_emotions_with_text, parse_text_with_emotions
from .firewall import FirewallService
from .vad_processor import VADProcessor, AudioStreamProcessor, get_vad_processor, get_audio_stream_processor, create_audio_stream_processor
from .context_manager import get_context_manager
from .cxhms_client import CXHMSClient
from .asr_client import ASRClient
from .tts_client import TTSClient
from .live_client import LiveClientHandler
from .adaptive_polling import AdaptivePollingManager
from .sensevoice_streaming_client import SenseVoiceStreamingClient
from .index_tts_client import IndexTTSClient
from .index_tts_manager import IndexTTSManager
from .asr_interrupt import ASRInterruptModule, get_asr_interrupt_module, create_asr_interrupt_module
from .agent_interrupt_user import AgentInterruptUser, get_agent_interrupt_module, create_agent_interrupt_module

__all__ = [
    "EffectParser",
    "extract_emotions_with_text",
    "parse_text_with_emotions",
    "FirewallService",
    "VADProcessor",
    "AudioStreamProcessor",
    "get_vad_processor",
    "get_audio_stream_processor",
    "create_audio_stream_processor",
    "get_context_manager",
    "CXHMSClient",
    "ASRClient",
    "TTSClient",
    "LiveClientHandler",
    "AdaptivePollingManager",
    "SenseVoiceStreamingClient",
    "IndexTTSClient",
    "IndexTTSManager",
    "ASRInterruptModule",
    "get_asr_interrupt_module",
    "create_asr_interrupt_module",
    "AgentInterruptUser",
    "get_agent_interrupt_module",
    "create_agent_interrupt_module",
]
