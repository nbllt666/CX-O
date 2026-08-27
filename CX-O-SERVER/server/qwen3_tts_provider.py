"""统一 Qwen3 TTS Provider 实现（Task 2 共享模块唯一真相源）。

严格匹配 `public/interface_stub/qwen3_tts_provider.pyi` 的签名与 9 异常类契约，
源真理为三层契约（speech_synthesis_request/response/chunk + qwen3_tts_error_codes +
qwen3_tts_config）。

本模块同时承载：
- 异常层级（Task 3 ref_audio_store.pyi 契约 `from qwen3_tts_provider import
  InvalidRefAudioError, RefAudioNotFoundError` 引用的共享基础）。每个异常类的
  error_code / http_status 与 qwen3_tts_error_codes.json 中的错误码一一对应。
- Provider 实现（Task 2）：请求转换、运行时适配、健康检查、超时、取消、错误映射与关闭。

职责：
- 统一 Provider 请求转换、健康检查、超时、取消、错误映射与关闭。
- 支持非流式（synthesize）与流式（synthesize_stream）合成，统一 PCM/WAV 格式与
  chunk 边界（恰一个 start、一个 final，顺序稳定）。
- vLLM 私有参数（task_type 等）封装在 Provider 内，不泄漏到前端协议。
- 无参考音频的日常/情感合成走 vLLM VoiceDesign（voicedesign 运行时）；
  带参考音频的语音克隆路由 CosyVoice2（cosyvoice 运行时），
  两者不可用/超时/非法响应时降级 Qwen3-TTS Base（qwen3_base 运行时），
  并在响应 runtime 元数据中记录实际运行时（voicedesign / cosyvoice / qwen3_base）。
- 参考音频输入采样率 [8000,48000] 与合成输出 24000 的差异由 Provider 在推理前重采样。

边界：本实现仅覆盖 Provider/异常层，不接 LLM 情感指令（Task 4）、不统一语音编排
（Task 5）、不删除旧引擎（Task 7）。参考音频资产解析（RefAudioStore）属 Task 3，
Provider 通过可注入的 ref_resolver 接入，默认不可解析时抛 RefAudioNotFoundError。

编码规范：文件路径用 os.path.dirname(os.path.abspath(__file__)) 解析；配置经
get_settings() 统一访问；异步用 async/await，禁止子线程 asyncio+aiohttp；
terminal 日志带 [timestamp, [INFO/ERROR], elapsed]。
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import httpx

from server.core.utils import get_shared_http_client

logger = logging.getLogger(__name__)

__all__ = [
    "Qwen3TTSError",
    "InvalidRequestError",
    "InvalidRefAudioError",
    "RefAudioNotFoundError",
    "EmotionInstructionInvalidError",
    "RuntimeUnavailableError",
    "RuntimeUnsupportedError",
    "StreamAbortedError",
    "LegacyEngineRemovedError",
    "SystemError",
    "ProviderHealth",
    "SynthesisRequest",
    "SynthesisResponse",
    "AudioChunk",
    "ResolvedRef",
    "RefResolver",
    "Qwen3TTSProvider",
    "detect_legacy_engine",
    "detect_legacy_engine_mode",
    "get_qwen3_tts_provider",
    "synthesize",
    "synthesize_stream",
    "health_check",
    "close",
]

# 合成链路统一输出采样率（契约 const 24000）
SYNTH_SAMPLE_RATE = 24000
# 参考音频输入采样率范围 [8000,48000]（契约 ref_audio_asset.sample_rate）
REF_AUDIO_SAMPLE_RATE_MIN = 8000
REF_AUDIO_SAMPLE_RATE_MAX = 48000
# WAV 头长度（44 字节），流式 wav 输出时跳过
WAV_HEADER_SIZE = 44

VALID_OUTPUT_FORMATS = {"wav", "pcm", "mp3", "flac", "opus", "aac"}
VALID_RUNTIMES = {"voicedesign", "cosyvoice", "qwen3_base"}
# 配置层 runtime 旧值 → 运行时名映射（config.json runtime 段仍保留 "vllm"）
RUNTIME_ALIASES = {"vllm": "voicedesign"}

# 能力矩阵（Task 0 探针实证 2026-08-14，见 .trae/documents/20260813_模块0_Qwen3TTS迁移基线盘点.md §2.5）：
# - speed 变速：实测 vLLM 支持（probe speed=1.5 通过、时长缩短），直接支持无需兜底；
# - ref_audio 克隆：CustomVoice/Base 已弃用，带 refs 的语音克隆由 CosyVoice3（cosyvoice 运行时）承接；
# - 无 refs 的日常/情感合成由 vLLM VoiceDesign（voicedesign 运行时）承接；
# - qwen3_base（Qwen3-TTS Base，vLLM）为全局降级运行时：cosyvoice/voicedesign 不可用/超时/非法响应时兜底。
DEFAULT_VLLM_BASE_URL = "http://127.0.0.1:8091"
DEFAULT_VLLM_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
DEFAULT_COSYVOICE_BASE_URL = "http://127.0.0.1:8094"
DEFAULT_COSYVOICE_MODEL = "Fun-CosyVoice3-0.5B-2512"
DEFAULT_QWEN3_BASE_BASE_URL = "http://127.0.0.1:8093"
DEFAULT_QWEN3_BASE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"

# 旧引擎配置键（命中时映射 LEGACY_ENGINE_REMOVED）。
# 注意：cosyvoice 已恢复为一级运行时（cosyvoice 运行时），不得再作为旧引擎拒绝。
LEGACY_ENGINE_KEYS = ("f5_tts", "f5-tts", "f5tts", "orpheus", "cosy_voice", "emotion_refs")

# 尾部静音剔除阈值（相对该块峰值，-50 dBFS≈0.00316）与最小保留时长
_SILENCE_RATIO_THRESHOLD = 0.00316  # 10^(-50/20)
_TRIM_MIN_RETAIN_S = 0.050  # 至少保留 50ms 语音尾音，保证自然收束


def _trim_tail_silence(pcm: bytes, sample_rate: int) -> bytes:
    """裁剪 PCM（16-bit 有符号小端单声道）末尾静音采样。

    用途：消除 TTS 合成音频（CosyVoice3 等）尾部 ~100ms 静音，改善整段播放
    结尾停顿感。仅对流式 final 块末尾裁剪，不改变 chunk 顺序与契约。

    实现：从尾部回溯，跳过幅度低于 ``峰值 * _SILENCE_RATIO_THRESHOLD`` 的采样，
    但至少保留 ``_TRIM_MIN_RETAIN_S`` 时长（保护真实弱语音尾音）。

    Args:
        pcm: 裸 PCM int16 字节（小端）。
        sample_rate: 采样率（HZ），用于计算回退边界。
    Returns:
        裁剪尾部静音后的 PCM 字节；空输入返回原值。
    """
    if not pcm:
        return pcm
    step = 2  # int16 2 字节
    n = len(pcm) // step
    if n == 0:
        return pcm

    # 相对峰值（避免低音量音频误删真实语音）
    peak = 0
    for i in range(n):
        v = int.from_bytes(pcm[i * step : i * step + step], "little", signed=True)
        a = -v if v < 0 else v
        if a > peak:
            peak = a
    if peak == 0:
        return pcm  # 全静音块，原样返回（不裁剪，交由上层语义处理）

    thr = peak * _SILENCE_RATIO_THRESHOLD
    min_retain = int(sample_rate * _TRIM_MIN_RETAIN_S)  # 至少保留采样数
    # 从尾部回溯，停在第一个非静音采样或达到最小保留边界
    keep = n
    stop = max(n - min_retain, 0)
    for i in range(n - 1, stop - 1, -1):
        v = int.from_bytes(pcm[i * step : i * step + step], "little", signed=True)
        a = -v if v < 0 else v
        if a > thr:
            keep = i + 1
            break
    else:
        keep = stop  # 全为尾部静音，退到最小保留边界
    return pcm[: keep * step]


# ============================================================================
# 异常契约（对应 qwen3_tts_error_codes.json 的 9 错误码）
# ============================================================================
class Qwen3TTSError(Exception):
    """所有 Qwen3 TTS 错误的基类。error_code 对应 qwen3_tts_error_codes.json。"""

    error_code: str = "SYSTEM_ERROR"
    http_status: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message}"


class InvalidRequestError(Qwen3TTSError):
    """请求参数非法：text 缺失/为空或字段不符合请求契约。"""

    error_code: str = "INVALID_REQUEST"
    http_status: int = 400


class InvalidRefAudioError(Qwen3TTSError):
    """参考音频资产非法：格式/大小/时长/采样率/路径不安全/元数据缺失。该资产不用于推理。"""

    error_code: str = "INVALID_REF_AUDIO"
    http_status: int = 422


class RefAudioNotFoundError(Qwen3TTSError):
    """参考音频资产 ID 不存在或已删除。"""

    error_code: str = "REF_AUDIO_NOT_FOUND"
    http_status: int = 404


class EmotionInstructionInvalidError(Qwen3TTSError):
    """情感指令非法：超长/敏感内容/非法字段/低置信度，已回退中性指令。"""

    error_code: str = "EMOTION_INSTRUCTION_INVALID"
    http_status: int = 422


class RuntimeUnavailableError(Qwen3TTSError):
    """Qwen3 TTS 运行时不可用/超时/返回非法响应/模型加载失败。不静默调用旧引擎。"""

    error_code: str = "RUNTIME_UNAVAILABLE"
    http_status: int = 503


class RuntimeUnsupportedError(Qwen3TTSError):
    """当前运行时(voicedesign)不支持该能力，已路由 CosyVoice2 克隆运行时并记录 runtime metadata。"""

    error_code: str = "RUNTIME_UNSUPPORTED"
    http_status: int = 200


class StreamAbortedError(Qwen3TTSError):
    """流式合成被取消/打断，已清理资源。"""

    error_code: str = "STREAM_ABORTED"
    http_status: int = 499


class LegacyEngineRemovedError(Qwen3TTSError):
    """F5-TTS/Orpheus 已移除，不再作为可选 TTS 引擎。请改用 Qwen3 TTS。"""

    error_code: str = "LEGACY_ENGINE_REMOVED"
    http_status: int = 501


class SystemError(Qwen3TTSError):
    """系统级失败：配置缺失或内部错误。"""

    error_code: str = "SYSTEM_ERROR"
    http_status: int = 500


# ============================================================================
# 数据模型（对应契约各结构）
# ============================================================================
@dataclass
class ProviderHealth:
    """轻量连通性健康检查结果（不做耗时生成/内容请求）。"""

    ok: bool
    runtime: str  # voicedesign | cosyvoice | qwen3_base
    latency_ms: Optional[float] = None
    detail: str = ""


@dataclass
class SynthesisRequest:
    """归一化合成请求（对应 speech_synthesis_request.schema.json）。

    tts_instruction 为降维投影（仅 text，source/raw 不入 Provider 协议）。
    """

    text: str
    refs: List[str] = field(default_factory=list)
    tts_instruction: Optional[str] = None
    voice: Optional[str] = None
    language: Optional[str] = None
    stream: bool = False
    output_format: str = "wav"
    speed: float = 1.0
    volume: float = 1.0


@dataclass
class SynthesisResponse:
    """非流式响应（对应 speech_synthesis_response.schema.json）。"""

    audio: bytes
    format: str
    sample_rate: int
    channels: int = 1
    duration_seconds: Optional[float] = None
    refs_used: List[str] = field(default_factory=list)
    runtime: str = "voicedesign"


@dataclass
class AudioChunk:
    """流式音频块（对应 speech_audio_chunk.schema.json）。"""

    index: int
    data: bytes
    format: str
    sample_rate: int
    channels: int = 1
    is_start: bool = False
    is_final: bool = False


@dataclass
class ResolvedRef:
    """解析后的参考音频（原始 PCM int16 + 采样率），供 Provider 推理前重采样。"""

    asset_id: str
    data: bytes
    sample_rate: int
    ref_text: str = ""
    channels: int = 1


# 参考音频解析回调：asset_id -> ResolvedRef（由 Task 3 RefAudioStore 接入）
RefResolver = Callable[[str], Any]


# ============================================================================
# 日志辅助（terminal 日志带 [timestamp, [INFO/ERROR], elapsed]）
# ============================================================================
def _now_str() -> str:
    """返回当前时间戳字符串（YYYY-MM-DD HH:MM:SS）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(op: str, msg: str, t0: Optional[float], level: str = "INFO") -> None:
    """按 [timestamp] [LEVEL] elapsed=xx ms - 格式输出 Provider 日志。"""
    elapsed = (time.monotonic() - t0) * 1000 if t0 is not None else 0.0
    line = f"[{_now_str()}] [{level}] elapsed={elapsed:.1f}ms - Qwen3TTS {op}: {msg}"
    if level == "ERROR":
        logger.error(line)
    else:
        logger.info(line)


# ============================================================================
# 旧引擎移除检测（LegacyEngineRemovedError 映射）
# ============================================================================
def detect_legacy_engine(raw_config: dict) -> None:
    """检查配置 dict 是否含旧引擎键，命中则抛 LegacyEngineRemovedError。

    对应 qwen3_tts_config.schema.json legacy_engine_removed 语义：
    旧引擎配置不再作为可选引擎，加载含 f5_tts/orpheus/emotion_refs
    时映射 LEGACY_ENGINE_REMOVED，不得静默选择旧实现。
    """
    for key in LEGACY_ENGINE_KEYS:
        if key in raw_config:
            raise LegacyEngineRemovedError(
                f"旧引擎配置 {key} 已移除，不再作为可选 TTS 引擎。请改用 Qwen3 TTS。"
            )


def detect_legacy_engine_mode(mode: str) -> None:
    """检查旧引擎模式字符串（mode），命中则抛 LegacyEngineRemovedError。

    供迁移边界调用方在仍以旧模式配置时获得明确移除错误。
    """
    legacy_modes = ("orpheus", "f5-tts", "f5", "embedded_f5")
    if mode in legacy_modes:
        raise LegacyEngineRemovedError(
            f"旧引擎模式 {mode} 已移除，不再作为可选 TTS 引擎。请改用 Qwen3 TTS。"
        )


# ============================================================================
# Provider 实现
# ============================================================================
class Qwen3TTSProvider:
    """统一 Qwen3 TTS Provider：请求转换、运行时适配、健康检查、超时、取消、错误映射。

    支持 cosyvoice/voicedesign 首选运行时与 qwen3_base 降级运行时；vLLM 私有参数封装在本类内。
    底层 HTTP 客户端可注入（测试用 Fake/Mock），默认使用共享 httpx.AsyncClient。
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        http_client: Optional[Any] = None,
        ref_resolver: Optional[RefResolver] = None,
        settings: Optional[Any] = None,
    ) -> None:
        """初始化 Provider。

        Args:
            config: qwen3_tts 配置 dict；缺省从 get_settings().config.qwen3_tts 读取。
            http_client: 底层异步 HTTP 客户端；缺省惰性使用共享客户端。
            ref_resolver: 参考音频解析回调（Task 3 接入）；缺省不可解析。
            settings: 配置单例（测试注入用）；缺省惰性 get_settings()。
        """
        self._settings = settings
        self._cfg = config if config is not None else self._load_cfg()
        self._client = http_client
        self._owns_client = False
        self._ref_resolver = ref_resolver
        self._closed = False
        pref = self._cfg.get("runtime", "voicedesign")
        # 配置层 runtime 兼容历史值 "vllm"（Provider 内部映射为运行时名 voicedesign）
        pref = RUNTIME_ALIASES.get(pref, pref)
        self._runtime = pref if pref in VALID_RUNTIMES else "voicedesign"

    # ------------------------------------------------------------------ 配置
    def _load_cfg(self) -> Dict[str, Any]:
        """从 get_settings().config.qwen3_tts 读取配置（禁止硬编码）。"""
        if self._settings is None:
            from server.config import get_settings

            self._settings = get_settings()
        cfg = self._settings.config.qwen3_tts
        return {
            "enabled": cfg.enabled,
            "runtime": cfg.runtime,
            "vllm": {
                "base_url": cfg.vllm.base_url,
                "model": cfg.vllm.model,
                "task_type": cfg.vllm.task_type,
                "timeout_seconds": cfg.vllm.timeout_seconds,
                "sample_rate": cfg.vllm.sample_rate,
            },
            "cosyvoice": {
                "base_url": cfg.cosyvoice.base_url,
                "model": cfg.cosyvoice.model,
                "timeout_seconds": cfg.cosyvoice.timeout_seconds,
                "sample_rate": cfg.cosyvoice.sample_rate,
            },
            "qwen3_base": {
                "base_url": cfg.qwen3_base.base_url,
                "model": cfg.qwen3_base.model,
                "timeout_seconds": cfg.qwen3_base.timeout_seconds,
                "sample_rate": cfg.qwen3_base.sample_rate,
            },
            "default": {
                "voice": cfg.default.voice,
                "language": cfg.default.language,
                "output_format": cfg.default.output_format,
                "speed": cfg.default.speed,
            },
            "emotion_instruction": {
                "enabled": cfg.emotion_instruction.enabled,
                "max_length": cfg.emotion_instruction.max_length,
                "fallback_neutral": cfg.emotion_instruction.fallback_neutral,
            },
            "legacy_engine_removed": {
                "return_removed_error": cfg.legacy_engine_removed.return_removed_error,
            },
        }

    def _get_client(self) -> Any:
        """获取底层 HTTP 客户端（注入或共享单例）。"""
        if self._client is None:
            self._client = get_shared_http_client()
            self._owns_client = False
        return self._client

    def _base_url_for(self, runtime: str) -> str:
        """返回指定运行时的基础地址（去尾斜杠）。

        cosyvoice 读 cfg["cosyvoice"]（默认 8094）；qwen3_base 读 cfg["qwen3_base"]
        （默认 8093）；其余（voicedesign）读 cfg["vllm"]（默认 8091，配置段名保持 vllm）。
        """
        if runtime == "cosyvoice":
            url = self._cfg.get("cosyvoice", {}).get("base_url", DEFAULT_COSYVOICE_BASE_URL) or DEFAULT_COSYVOICE_BASE_URL
        elif runtime == "qwen3_base":
            url = self._cfg.get("qwen3_base", {}).get("base_url", DEFAULT_QWEN3_BASE_BASE_URL) or DEFAULT_QWEN3_BASE_BASE_URL
        else:
            url = self._cfg.get("vllm", {}).get("base_url", DEFAULT_VLLM_BASE_URL) or DEFAULT_VLLM_BASE_URL
        return url.rstrip("/")

    def _timeout_for(self, runtime: str) -> float:
        """返回指定运行时的请求超时（秒）。"""
        if runtime == "cosyvoice":
            return float(self._cfg.get("cosyvoice", {}).get("timeout_seconds", 120))
        if runtime == "qwen3_base":
            return float(self._cfg.get("qwen3_base", {}).get("timeout_seconds", 120))
        return float(self._cfg.get("vllm", {}).get("timeout_seconds", 60))

    # ------------------------------------------------------------ 能力/运行时
    def _needs_fallback(self, resolved: List[ResolvedRef]) -> bool:
        """判断当前请求是否需要 VoiceDesign 无法消费的能力（路由 cosyvoice 克隆运行时）。

        实测能力矩阵（2026-08-14 探针）：
        - speed：vLLM 支持，不再兜底；
        - ref_audio：vLLM VoiceDesign 任务不支持消费（已弃用 CustomVoice/Base 模型），
          请求带参考音频时首选路由 CosyVoice2（cosyvoice 运行时）进行情感语音克隆；
          CosyVoice2 不可用/超时/非法响应时降级 Qwen3-TTS Base（qwen3_base 运行时）。
          若 cosyvoice.base_url 为空则抛 RuntimeUnsupportedError。
        """
        if not resolved:
            return False
        return True  # VoiceDesign 不支持 ref_audio，有 refs 即路由 cosyvoice

    def _select_runtime(self, req: SynthesisRequest, resolved: List[ResolvedRef]) -> str:
        """选择本次请求的首选推理运行时。

        - 带 refs（VoiceDesign 无法消费的 ref_audio 能力）→ 若配置 cosyvoice.base_url
          则路由 cosyvoice；否则抛 RuntimeUnsupportedError（提示需配置 CosyVoice3）。
        - 无 refs → 返回 preferred（voicedesign）。
        """
        preferred = self._runtime
        if preferred == "voicedesign" and self._needs_fallback(resolved):
            cosyvoice = self._cfg.get("cosyvoice", {})
            if cosyvoice.get("base_url"):
                return "cosyvoice"
            raise RuntimeUnsupportedError(
                "请求携带参考音频，但 vLLM VoiceDesign 任务不支持 ref_audio 消费（需 CosyVoice3 克隆运行时），"
                "且未配置 cosyvoice 运行时。"
            )
        return preferred

    # ------------------------------------------------------------ 请求构建
    def _build_vllm_request(self, req: SynthesisRequest, resolved: List[ResolvedRef]) -> Dict[str, Any]:
        """构建 vLLM VoiceDesign 请求体（voicedesign 运行时，OpenAI 兼容 /v1/audio/speech）。

        vLLM 私有参数（task_type 等）封装在 Provider 内，不泄漏到前端协议。
        ref_audio 以裸 base64 列表发送（vLLM 消费 base64 而非 data URL）。
        """
        cfg = self._cfg.get("vllm", {})
        body: Dict[str, Any] = {
            "model": cfg.get("model", DEFAULT_VLLM_MODEL),
            "input": req.text,
            "response_format": req.output_format,
            "stream": req.stream,
            # vLLM 私有参数：task_type 仅存在于 Provider/配置契约，不泄漏前端协议
            "task_type": cfg.get("task_type", "VoiceDesign"),
        }
        if req.voice:
            body["voice"] = req.voice
        if req.language:
            body["language"] = req.language
        if req.tts_instruction:
            body["instructions"] = req.tts_instruction
        if req.speed is not None and abs(req.speed - 1.0) > 1e-6:
            body["speed"] = req.speed
        if resolved:
            body["ref_audio"] = [base64.b64encode(r.data).decode("ascii") for r in resolved]
            body["ref_text"] = [r.ref_text for r in resolved]
        return body

    def _build_cosyvoice_request(self, req: SynthesisRequest, resolved: List[ResolvedRef]) -> Dict[str, Any]:
        """构建 CosyVoice3 克隆运行时请求体（cosyvoice 运行时，OpenAI 兼容 + 扩展字段）。

        ref_audio 以 data URL 形式发送（服务端 _decode_data_url 消费），并携带
        instructions（情感指令）/ref_text（参考转写）提升克隆质量。
        Provider 层保证带 refs 才路由 cosyvoice，因此正常必有 ref_audio 字段。
        """
        cfg = self._cfg.get("cosyvoice", {})
        body: Dict[str, Any] = {
            "model": cfg.get("model", DEFAULT_COSYVOICE_MODEL),
            "input": req.text,
            "response_format": req.output_format,
            "stream": req.stream,
        }
        if req.voice:
            body["voice"] = req.voice
        if req.language:
            body["language"] = req.language
        if req.tts_instruction:
            body["instructions"] = req.tts_instruction
        if req.speed is not None:
            body["speed"] = req.speed
        if req.volume is not None:
            body["volume"] = req.volume
        if resolved:
            body["ref_audio"] = [
                "data:audio/wav;base64," + base64.b64encode(r.data).decode("ascii")
                for r in resolved
            ]
            body["ref_text"] = [r.ref_text for r in resolved]
        return body

    def _build_qwen3_base_request(self, req: SynthesisRequest, resolved: List[ResolvedRef]) -> Dict[str, Any]:
        """构建 Qwen3-TTS Base 降级运行时请求体（qwen3_base 运行时，vLLM OpenAI 兼容）。

        vLLM 消费 ref_audio 为字符串 base64 data URL（如 data:audio/wav;base64,...）、
        ref_text 为字符串——与 cosyvoice 的多 ref 列表格式不同（vLLM 仅接受单个 ref，
        取首个解析后的参考音频）。裸 PCM16（重采样路径产出）先包裹 WAV 容器头；
        wav/flac/opus/mp3/aac 容器原样透传（vLLM 按内容嗅探解码，不依赖 mime）。
        """
        cfg = self._cfg.get("qwen3_base", {})
        body: Dict[str, Any] = {
            "model": cfg.get("model", DEFAULT_QWEN3_BASE_MODEL),
            "input": req.text,
            "response_format": req.output_format,
            "stream": req.stream,
        }
        if req.voice:
            body["voice"] = req.voice
        if req.language:
            body["language"] = req.language
        if req.tts_instruction:
            body["instructions"] = req.tts_instruction
        if req.speed is not None and abs(req.speed - 1.0) > 1e-6:
            body["speed"] = req.speed
        if resolved:
            first = resolved[0]
            audio = first.data
            if not self._is_audio_container(audio):
                audio = self._wrap_pcm16_wav(audio, first.sample_rate, first.channels)
            body["ref_audio"] = "data:audio/wav;base64," + base64.b64encode(audio).decode("ascii")
            body["ref_text"] = first.ref_text
        return body

    def _build_runtime_request(self, req: SynthesisRequest, runtime: str, resolved: List[ResolvedRef]) -> Dict[str, Any]:
        """按运行时构建请求体。"""
        if runtime == "cosyvoice":
            return self._build_cosyvoice_request(req, resolved)
        if runtime == "qwen3_base":
            return self._build_qwen3_base_request(req, resolved)
        return self._build_vllm_request(req, resolved)

    # ------------------------------------------------------------ 参考音频
    async def _resolve_one(self, asset_id: str) -> ResolvedRef:
        """解析单个参考音频资产 ID 为 ResolvedRef（Task 3 接入）。"""
        if self._ref_resolver is None:
            raise RefAudioNotFoundError(
                f"参考音频解析器未接入（属 Task 3 Range），无法解析资产 {asset_id}"
            )
        result = self._ref_resolver(asset_id)
        if asyncio.iscoroutine(result):
            result = await result
        if result is None:
            raise RefAudioNotFoundError(f"参考音频资产不存在或已删除: {asset_id}")
        if isinstance(result, ResolvedRef):
            return result
        # 兼容 dict 形状
        return ResolvedRef(
            asset_id=asset_id,
            data=result.get("data", b""),
            sample_rate=result.get("sample_rate", SYNTH_SAMPLE_RATE),
            ref_text=result.get("ref_text", ""),
            channels=result.get("channels", 1),
        )

    async def _resolve_refs(self, req: SynthesisRequest) -> List[ResolvedRef]:
        """解析全部 refs 并在推理前重采样到 24kHz。"""
        if not req.refs:
            return []
        resolved: List[ResolvedRef] = []
        for asset_id in req.refs:
            bundle = await self._resolve_one(asset_id)
            resampled = self._resample_to_synth(bundle)
            resolved.append(resampled)
        return resolved

    def _resample_to_synth(self, bundle: ResolvedRef) -> ResolvedRef:
        """将参考音频重采样到合成输出采样率 24000（输入范围 [8000,48000]）。"""
        sr = bundle.sample_rate
        if sr == SYNTH_SAMPLE_RATE:
            return bundle
        if not (REF_AUDIO_SAMPLE_RATE_MIN <= sr <= REF_AUDIO_SAMPLE_RATE_MAX):
            raise InvalidRefAudioError(
                f"参考音频采样率 {sr} 越界（应为 {REF_AUDIO_SAMPLE_RATE_MIN}-{REF_AUDIO_SAMPLE_RATE_MAX}）"
            )
        data = self._resample_pcm16(bundle.data, sr, SYNTH_SAMPLE_RATE)
        return ResolvedRef(
            asset_id=bundle.asset_id,
            data=data,
            sample_rate=SYNTH_SAMPLE_RATE,
            ref_text=bundle.ref_text,
            channels=bundle.channels,
        )

    @staticmethod
    def _resample_pcm16(data: bytes, src_rate: int, dst_rate: int) -> bytes:
        """线性插值重采样（16-bit signed LE mono），src_rate -> dst_rate。"""
        if src_rate == dst_rate or not data:
            return data
        import array

        samples = array.array("h")
        samples.frombytes(data)
        n = len(samples)
        if n == 0:
            return data
        out_len = max(1, int(round(n * dst_rate / src_rate)))
        out = array.array("h", [0]) * out_len
        for i in range(out_len):
            pos = i * n / out_len
            j = int(pos)
            frac = pos - j
            j = min(j, n - 1)
            k = min(j + 1, n - 1)
            out[i] = int(round(samples[j] * (1 - frac) + samples[k] * frac))
        return out.tobytes()

    @staticmethod
    def _is_audio_container(data: bytes) -> bool:
        """判断音频字节是否带容器头（wav/flac/opus/mp3/aac），而非裸 PCM16。"""
        if not data:
            return False
        if data.startswith((b"RIFF", b"fLaC", b"OggS", b"ID3")):
            return True
        # MPEG 音频帧同步（mp3/aac）
        if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
            return True
        return False

    @staticmethod
    def _wrap_pcm16_wav(pcm: bytes, sample_rate: int, channels: int) -> bytes:
        """将裸 16-bit PCM 包裹为合法 WAV 容器（供 vLLM 内容嗅探解码）。"""
        import struct

        n_channels = max(1, int(channels))
        rate = max(1, int(sample_rate))
        block_align = n_channels * 2
        byte_rate = rate * block_align
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + len(pcm), b"WAVE",
            b"fmt ", 16, 1, n_channels,
            rate, byte_rate, block_align, 16,
            b"data", len(pcm),
        )
        return header + pcm

    # ------------------------------------------------------------ 请求校验
    def _validate_request(self, req: SynthesisRequest) -> None:
        """校验归一化请求契约，非法抛对应异常。"""
        if not req.text or not req.text.strip():
            raise InvalidRequestError("text 缺失或为空（不符合请求契约）")
        if req.output_format not in VALID_OUTPUT_FORMATS:
            raise InvalidRequestError(f"不支持的输出格式: {req.output_format}")
        if req.speed is not None and not (0.25 <= req.speed <= 4.0):
            raise InvalidRequestError(f"speed 越界（应为 0.25-4.0）: {req.speed}")
        if req.refs:
            for ref in req.refs:
                if not ref or not str(ref).startswith("ref_"):
                    raise InvalidRequestError(f"refs 须为 ref_ 前缀的资产 ID: {ref}")
        max_len = self._cfg.get("emotion_instruction", {}).get("max_length", 200)
        if req.tts_instruction and len(req.tts_instruction) > max_len:
            raise EmotionInstructionInvalidError(f"情感指令超长（上限 {max_len}）")

    # ------------------------------------------------------------ 时长估算
    @staticmethod
    def _estimate_duration(audio: bytes, fmt: str, sample_rate: int) -> Optional[float]:
        """估算音频时长（秒）；wav 读取头，pcm 按 16-bit mono 计算，其余返回 None。"""
        if not audio:
            return None
        if fmt == "wav":
            try:
                with wave.open(io.BytesIO(audio), "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    return frames / rate if rate else None
            except Exception:
                return None
        if fmt == "pcm":
            return len(audio) / (sample_rate * 2)
        return None

    # ------------------------------------------------------------ 错误映射
    def _map_http_error(self, exc: httpx.HTTPStatusError, runtime: str) -> Qwen3TTSError:
        """将运行时 HTTP 状态码映射到统一异常契约。"""
        resp = exc.response
        status = resp.status_code if resp is not None else None
        if status == 400:
            return InvalidRequestError(f"Qwen3 TTS 运行时请求非法: {exc}")
        if status == 404:
            return RefAudioNotFoundError(f"参考音频不存在: {exc}")
        if status == 422:
            return InvalidRefAudioError(f"参考音频非法: {exc}")
        if status == 503:
            return RuntimeUnavailableError(f"Qwen3 TTS 运行时不可用: {exc}")
        return RuntimeUnavailableError(f"Qwen3 TTS 运行时错误 (HTTP {status}): {exc}")

    # ------------------------------------------------------------------ 合成
    def _fallback_runtime(self, primary: str) -> Optional[str]:
        """返回首选运行时的降级目标。

        带 refs 首选 cosyvoice、无 refs 首选 voicedesign，两者均降级 qwen3_base；
        qwen3_base 自身无降级目标。仅「运行时不可用」类错误触发降级，请求非法不降级。
        """
        if primary == "qwen3_base":
            return None
        return "qwen3_base"

    async def _synthesize_once(
        self,
        req: SynthesisRequest,
        resolved: List[ResolvedRef],
        runtime: str,
        t0: float,
    ) -> SynthesisResponse:
        """单次非流式合成（供 synthesize 的首选/降级循环调用，最多执行 2 次）。"""
        body = self._build_runtime_request(req, runtime, resolved)
        base_url = self._base_url_for(runtime)
        timeout = self._timeout_for(runtime)
        client = self._get_client()
        try:
            resp = await client.post(f"{base_url}/v1/audio/speech", json=body, timeout=timeout)
            resp.raise_for_status()
            audio: bytes = resp.content
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException as exc:
            _log("synthesize", f"超时 ({runtime}) {exc}", t0, "ERROR")
            raise RuntimeUnavailableError(f"Qwen3 TTS 运行时超时: {exc}")
        except httpx.ConnectError as exc:
            _log("synthesize", f"运行时不可达 ({runtime}) {exc}", t0, "ERROR")
            raise RuntimeUnavailableError(f"Qwen3 TTS 运行时不可达: {exc}")
        except httpx.HTTPStatusError as exc:
            _log("synthesize", f"HTTP 错误 ({runtime}) {exc}", t0, "ERROR")
            raise self._map_http_error(exc, runtime)
        except httpx.HTTPError as exc:
            _log("synthesize", f"运行时错误 ({runtime}) {exc}", t0, "ERROR")
            raise RuntimeUnavailableError(f"Qwen3 TTS 运行时错误: {exc}")

        if not audio:
            _log("synthesize", f"运行时返回空音频 ({runtime})", t0, "ERROR")
            raise RuntimeUnavailableError("Qwen3 TTS 运行时返回空音频")

        duration = self._estimate_duration(audio, req.output_format, SYNTH_SAMPLE_RATE)
        _log("synthesize", f"成功 runtime={runtime} bytes={len(audio)}", t0)
        return SynthesisResponse(
            audio=audio,
            format=req.output_format,
            sample_rate=SYNTH_SAMPLE_RATE,
            channels=1,
            duration_seconds=duration,
            refs_used=list(req.refs),
            runtime=runtime,
        )

    async def synthesize(self, req: SynthesisRequest) -> SynthesisResponse:
        """非流式合成。

        首选运行时（带 refs→cosyvoice，无 refs→voicedesign）不可用/超时/非法响应
        （RuntimeUnavailableError）时降级 qwen3_base 重试一次；请求校验与 refs 解析
        仅执行一次。请求非法（InvalidRequestError 等）不降级。
        """
        t0 = time.monotonic()
        self._validate_request(req)
        resolved = await self._resolve_refs(req)
        primary = self._select_runtime(req, resolved)
        fallback = self._fallback_runtime(primary)
        try:
            return await self._synthesize_once(req, resolved, primary, t0)
        except RuntimeUnavailableError as exc:
            if fallback is None:
                raise
            _log("synthesize", f"首选运行时 {primary} 不可用，降级 {fallback}（原因: {exc}）", t0, "ERROR")
            return await self._synthesize_once(req, resolved, fallback, t0)

    async def _synthesize_stream_once(
        self,
        req: SynthesisRequest,
        resolved: List[ResolvedRef],
        runtime: str,
    ) -> AsyncIterator[AudioChunk]:
        """单次流式合成（供 synthesize_stream 的首选/降级循环调用，最多执行 2 次）。

        chunk 顺序稳定（index 递增），恰一个 start/一个 final；取消抛 StreamAbortedError。
        底层断流/超时/非法响应抛 RuntimeUnavailableError。
        """
        body = self._build_runtime_request(req, runtime, resolved)
        base_url = self._base_url_for(runtime)
        timeout = self._timeout_for(runtime)
        client = self._get_client()

        index = 0
        # 末块持有器（标记 final）：非末块在下块到达时立即下发
        pending: Optional[AudioChunk] = None
        started = False
        bytes_received = 0
        skip = WAV_HEADER_SIZE if req.output_format == "wav" else 0

        try:
            async with client.stream("POST", f"{base_url}/v1/audio/speech", json=body, timeout=timeout) as resp:
                resp.raise_for_status()
                async for raw in resp.aiter_bytes():
                    if skip > 0 and bytes_received < skip:
                        cut = min(skip - bytes_received, len(raw))
                        raw = raw[cut:]
                        bytes_received += cut
                        if not raw:
                            continue
                    if not raw:
                        continue
                    if not started:
                        # 首块立即下发（TTFT 关键：不等待下一 hop，降低首包可播放延迟）
                        started = True
                        yield AudioChunk(
                            index=index,
                            data=raw,
                            format=req.output_format,
                            sample_rate=SYNTH_SAMPLE_RATE,
                            channels=1,
                            is_start=True,
                            is_final=False,
                        )
                        index += 1
                        continue
                    if pending is not None:
                        yield pending
                    pending = AudioChunk(
                        index=index,
                        data=raw,
                        format=req.output_format,
                        sample_rate=SYNTH_SAMPLE_RATE,
                        channels=1,
                        is_start=False,
                        is_final=False,
                    )
                    index += 1
        except asyncio.CancelledError:
            pending = None
            _log("synthesize_stream", "被取消/打断，资源已清理", 0, "ERROR")
            raise StreamAbortedError("流式合成被取消/打断，资源已清理")
        except httpx.HTTPStatusError as exc:
            _log("synthesize_stream", f"HTTP 错误 ({runtime}) {exc}", 0, "ERROR")
            raise self._map_http_error(exc, runtime)
        except httpx.HTTPError as exc:
            _log("synthesize_stream", f"流式运行时错误/断流 ({runtime}) {exc}", 0, "ERROR")
            raise RuntimeUnavailableError(f"Qwen3 TTS 流式运行时错误/断流: {exc}")
        except Qwen3TTSError:
            raise
        except Exception as exc:  # noqa: BLE001 - 运行时异常统一映射
            _log("synthesize_stream", f"流式异常 ({runtime}) {exc}", 0, "ERROR")
            raise RuntimeUnavailableError(f"Qwen3 TTS 流式异常: {exc}")

        if pending is not None:
            pending.is_final = True
            # 末尾静音剔除：仅末块裁剪尾部静音（改善整段播报结尾停顿感），
            # 不改变中间块流式下发与首包延迟。
            if pending.data:
                pending.data = _trim_tail_silence(pending.data, SYNTH_SAMPLE_RATE)
            yield pending
            _log("synthesize_stream", f"成功 runtime={runtime} chunks={index}", 0)
        elif started:
            # 单块流：首块已立即下发，补发空 final 块闭合契约（恰一个 final）
            yield AudioChunk(
                index=index, data=b"", format=req.output_format,
                sample_rate=SYNTH_SAMPLE_RATE, channels=1,
                is_start=False, is_final=True,
            )
            _log("synthesize_stream", f"成功 runtime={runtime} chunks={index} (single-chunk)", 0)
        else:
            _log("synthesize_stream", f"运行时返回空/非法流 ({runtime})", 0, "ERROR")
            raise RuntimeUnavailableError("Qwen3 TTS 流式返回为空/非法响应")

    async def synthesize_stream(self, req: SynthesisRequest) -> AsyncIterator[AudioChunk]:
        """流式合成。

        首选运行时（带 refs→cosyvoice，无 refs→voicedesign）不可用/超时/断流/非法响应
        （RuntimeUnavailableError）时降级 qwen3_base 重试一次；请求校验与 refs 解析
        仅执行一次。请求非法（InvalidRequestError 等）不降级。

        中途断流契约（M 修复）：仅当首选运行时尚未产出任何 chunk 时才允许降级重发；
        一旦已向消费者产出音频，再从 fallback 从头重发会产生第二个 start 块且 index
        归零，破坏「恰一个 start / index 单调递增」的消费者契约——此时不再降级，
        原样向上传播异常终止本流（与「底层断流抛 RuntimeUnavailableError」语义一致）。
        """
        self._validate_request(req)
        resolved = await self._resolve_refs(req)
        primary = self._select_runtime(req, resolved)
        fallback = self._fallback_runtime(primary)
        produced_any_chunk = False
        try:
            async for chunk in self._synthesize_stream_once(req, resolved, primary):
                produced_any_chunk = True
                yield chunk
        except RuntimeUnavailableError as exc:
            if fallback is None or produced_any_chunk:
                # 无可降级运行时；或已产出 chunk —— 绝不 yield 新流的 start 块
                if produced_any_chunk:
                    _log(
                        "synthesize_stream",
                        f"首选运行时 {primary} 在已产出音频后中途断流，不降级（避免破坏 start/index 契约）: {exc}",
                        0,
                        "ERROR",
                    )
                raise
            _log("synthesize_stream", f"首选运行时 {primary} 不可用，降级 {fallback}（原因: {exc}）", 0, "ERROR")
            async for chunk in self._synthesize_stream_once(req, resolved, fallback):
                yield chunk

    # ------------------------------------------------------------ 健康检查
    async def health_check(self) -> ProviderHealth:
        """轻量连通性检查（仅探活，不接受耗时生成/内容请求）。

        任一 HTTP 状态码（含 4xx/5xx）均视为服务可达（ok=True）；仅连接失败视为不可用。
        """
        t0 = time.monotonic()
        runtime = self._runtime
        base_url = self._base_url_for(runtime)
        try:
            client = self._get_client()
            resp = await client.get(f"{base_url}/health", timeout=5.0)
            latency = (time.monotonic() - t0) * 1000
            _log("health_check", f"可达 runtime={runtime} HTTP {resp.status_code} ", t0)
            return ProviderHealth(ok=True, runtime=runtime, latency_ms=round(latency, 1), detail=f"/health -> HTTP {resp.status_code}")
        except Exception as exc:  # noqa: BLE001 - 探活失败仅标记不可用
            latency = (time.monotonic() - t0) * 1000
            _log("health_check", f"不可达 runtime={runtime} {exc}", t0)
            return ProviderHealth(ok=False, runtime=runtime, latency_ms=round(latency, 1), detail=str(exc))

    # ------------------------------------------------------------ 关闭
    async def close(self) -> None:
        """关闭底层客户端与资源（仅关闭 Provider 自建客户端，共享客户端交给生命周期管理）。"""
        self._closed = True
        if self._owns_client and self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None
        _log("close", "Provider 已关闭", None)


# ============================================================================
# 模块级单例函数（对接 .pyi 的 synthesize/synthesize_stream/health_check/close）
# ============================================================================
_provider: Optional[Qwen3TTSProvider] = None


def get_qwen3_tts_provider() -> Qwen3TTSProvider:
    """获取全局唯一 Qwen3TTSProvider 单例（惰性初始化）。"""
    global _provider
    if _provider is None:
        _provider = Qwen3TTSProvider()
    return _provider


async def synthesize(req: SynthesisRequest) -> SynthesisResponse:
    """模块级非流式合成入口（委托全局 Provider 单例）。"""
    return await get_qwen3_tts_provider().synthesize(req)


async def synthesize_stream(req: SynthesisRequest) -> AsyncIterator[AudioChunk]:
    """模块级流式合成入口（委托全局 Provider 单例）。"""
    async for chunk in get_qwen3_tts_provider().synthesize_stream(req):
        yield chunk


async def health_check() -> ProviderHealth:
    """模块级健康检查入口（委托全局 Provider 单例）。"""
    return await get_qwen3_tts_provider().health_check()


async def close() -> None:
    """模块级关闭入口（委托全局 Provider 单例）。"""
    await get_qwen3_tts_provider().close()