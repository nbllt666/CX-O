"""统一 Qwen3 TTS Provider 接口契约存根（零实现，仅签名）。

源真理: public/schema/speech_synthesis_request.schema.json + qwen3_tts_error_codes.json
完成 Skill: s0201
当前状态: 契约冻结——仅声明签名，无实现逻辑。

职责：统一 Provider 请求转换、健康检查、超时、取消、错误映射与关闭。
vLLM 私有参数封装在 Provider 内，不泄漏到前端协议；vLLM 不支持的已确认能力
接入官方 Qwen3 运行时临时路径，并在响应 runtime 元数据中记录。
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

__all__ = [
    "Qwen3TTSError", "InvalidRequestError", "InvalidRefAudioError", "RefAudioNotFoundError",
    "EmotionInstructionInvalidError", "RuntimeUnavailableError", "RuntimeUnsupportedError",
    "StreamAbortedError", "LegacyEngineRemovedError", "SystemError",
    "ProviderHealth", "SynthesisRequest", "SynthesisResponse", "AudioChunk",
    "synthesize", "synthesize_stream", "health_check", "close",
]


class Qwen3TTSError(Exception):
    """所有 Qwen3 TTS 错误的基类。error_code 对应 qwen3_tts_error_codes.json。"""
    error_code: str = "SYSTEM_ERROR"
    http_status: int = 500
    def __init__(self, message: str) -> None: ...
    def __str__(self) -> str: ...


class InvalidRequestError(Qwen3TTSError):
    error_code: str = "INVALID_REQUEST"
    http_status: int = 400

class InvalidRefAudioError(Qwen3TTSError):
    error_code: str = "INVALID_REF_AUDIO"
    http_status: int = 422

class RefAudioNotFoundError(Qwen3TTSError):
    error_code: str = "REF_AUDIO_NOT_FOUND"
    http_status: int = 404

class EmotionInstructionInvalidError(Qwen3TTSError):
    error_code: str = "EMOTION_INSTRUCTION_INVALID"
    http_status: int = 422

class RuntimeUnavailableError(Qwen3TTSError):
    error_code: str = "RUNTIME_UNAVAILABLE"
    http_status: int = 503

class RuntimeUnsupportedError(Qwen3TTSError):
    error_code: str = "RUNTIME_UNSUPPORTED"
    http_status: int = 200

class StreamAbortedError(Qwen3TTSError):
    error_code: str = "STREAM_ABORTED"
    http_status: int = 499

class LegacyEngineRemovedError(Qwen3TTSError):
    error_code: str = "LEGACY_ENGINE_REMOVED"
    http_status: int = 501

class SystemError(Qwen3TTSError):
    error_code: str = "SYSTEM_ERROR"
    http_status: int = 500


class ProviderHealth:
    """轻量连通性健康检查结果（不做耗时生成/内容请求）。"""
    ok: bool
    runtime: str  # vllm | official_qwen3
    latency_ms: Optional[float]
    detail: str


class SynthesisRequest:
    """归一化合成请求（对应 speech_synthesis_request.schema.json）。"""
    text: str
    refs: List[str]
    tts_instruction: Optional[str]
    voice: Optional[str]
    language: Optional[str]
    stream: bool
    output_format: str
    speed: float


class SynthesisResponse:
    """非流式响应（对应 speech_synthesis_response.schema.json）。"""
    audio: bytes
    format: str
    sample_rate: int
    channels: int
    duration_seconds: Optional[float]
    refs_used: List[str]
    runtime: str


class AudioChunk:
    """流式音频块（对应 speech_audio_chunk.schema.json）。"""
    index: int
    data: bytes
    format: str
    sample_rate: int
    channels: int
    is_start: bool
    is_final: bool


def synthesize(req: SynthesisRequest) -> SynthesisResponse:
    """非流式合成。Qwen3 运行时不可用/非法响应/超时抛 RuntimeUnavailableError，不静默调旧引擎。"""
    ...


def synthesize_stream(req: SynthesisRequest) -> AsyncIterator[AudioChunk]:
    """流式合成。chunk 顺序稳定，恰一个 start/一个 final；取消抛 StreamAbortedError 并清理资源。"""
    ...


def health_check() -> ProviderHealth:
    """轻量连通性检查（仅探活，不接受耗时生成/内容请求）。"""
    ...


def close() -> None:
    """关闭 Provider 底层客户端与资源。"""
    ...