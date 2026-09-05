"""语音链路延迟指标模块。

进程内 per-turn 结构化采集：VAD/ASR/LLM TTFT/TTS 首帧/端到端各段延迟，
环形缓冲保留最近 200 轮，P50/P95 聚合。对外仅暴露 tracker 单例与类型，
具体实现见 voice_latency.py（采集零阻断红线：任何打点/查询失败均静默降级）。
"""
from server.core.metrics.voice_latency import (
    DEFAULT_BUFFER_SIZE,
    DEFAULT_TURN_TIMEOUT_S,
    TurnRecord,
    VoiceLatencyEvent,
    VoiceLatencyTracker,
    get_voice_latency_tracker,
)

__all__ = [
    "DEFAULT_BUFFER_SIZE",
    "DEFAULT_TURN_TIMEOUT_S",
    "TurnRecord",
    "VoiceLatencyEvent",
    "VoiceLatencyTracker",
    "get_voice_latency_tracker",
]
