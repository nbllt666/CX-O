"""
VAD (Voice Activity Detection) 模块
后端语音活动检测，判断用户是否在说话
"""
import asyncio
import logging
import struct
import time
from typing import Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class VADMode(Enum):
    ENERGY = "energy"
    WEBRTC = "webrtc"
    SILERO = "silero"


@dataclass
class VADState:
    is_speaking: bool = False
    speech_start_time: float = 0
    last_speech_time: float = 0
    silence_duration_ms: float = 0
    speech_duration_ms: float = 0
    frame_count: int = 0


class VADProcessor:
    _instance = None

    def __init__(self):
        self.mode = VADMode.WEBRTC
        self.sample_rate = 16000
        self.frame_duration_ms = 30
        self.energy_threshold = 500
        self.silence_threshold_ms = 500
        self.speech_threshold_ms = 300
        # 双流式模式下 VAD 仅作兜底，不阻塞 ASR Partial 驱动的主流程。
        # min_silence_duration_ms 默认 150ms（Silero 模式句尾判定阈值），
        # 相比原 silence_threshold_ms=500ms 大幅降低，加速兜底修正约 350ms
        self.min_silence_duration_ms: float = 150.0
        self._state = VADState()
        self._vad: Any = None
        self._on_speech_start_callback: Optional[Callable] = None
        self._on_speech_end_callback: Optional[Callable] = None
        self._audio_buffer: bytearray = bytearray()
        self._buffer_duration_ms = 0
        self._initialized = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_config(self, config: dict):
        mode_str = config.get("mode", "webrtc")
        self.mode = VADMode(mode_str)
        self.sample_rate = config.get("sample_rate", 16000)
        self.frame_duration_ms = config.get("frame_duration_ms", 30)
        self.energy_threshold = config.get("energy_threshold", 500)
        self.silence_threshold_ms = config.get("silence_threshold_ms", 500)
        self.speech_threshold_ms = config.get("speech_threshold_ms", 300)
        # 双流式模式下 VAD 仅作兜底：min_silence_duration_ms 默认 150ms，
        # 仅 Silero 模式用于句尾判定，加速兜底修正（不阻塞 ASR Partial 主驱动）
        self.min_silence_duration_ms = config.get("min_silence_duration_ms", 150.0)

        self._init_vad()
        self._initialized = True

    def _init_vad(self):
        if self.mode == VADMode.WEBRTC:
            try:
                import webrtcvad
                self._vad = webrtcvad.Vad(3)
                logger.info("WebRTC VAD initialized")
            except ImportError:
                logger.warning("webrtcvad not installed, falling back to energy mode")
                self.mode = VADMode.ENERGY

        elif self.mode == VADMode.SILERO:
            try:
                import torch
                model, utils = torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    force_reload=False,
                    onnx=False
                )
                self._vad = model
                logger.info("Silero VAD initialized")
            except Exception as e:
                logger.warning(f"Silero VAD failed to initialize: {e}, falling back to energy mode")
                self.mode = VADMode.ENERGY

    def set_callbacks(
        self,
        on_speech_start: Optional[Callable] = None,
        on_speech_end: Optional[Callable] = None
    ):
        self._on_speech_start_callback = on_speech_start
        self._on_speech_end_callback = on_speech_end

    def process_audio(self, audio_data: bytes) -> dict:
        current_time = time.time()

        if self.mode == VADMode.ENERGY:
            is_speech = self._detect_energy(audio_data)
            speech_probability = min(1.0, self._calculate_energy(audio_data) / self.energy_threshold)
        elif self.mode == VADMode.WEBRTC:
            is_speech = self._detect_webrtc(audio_data)
            speech_probability = 1.0 if is_speech else 0.0
        elif self.mode == VADMode.SILERO:
            is_speech, speech_probability = self._detect_silero(audio_data)
        else:
            is_speech = self._detect_energy(audio_data)
            speech_probability = 0.5

        state_changed = False
        previous_speaking = self._state.is_speaking

        if is_speech:
            self._state.last_speech_time = current_time

            if not self._state.is_speaking:
                self._state.speech_start_time = current_time
                self._state.is_speaking = True
                state_changed = True

                if self._on_speech_start_callback:
                    try:
                        self._on_speech_start_callback()
                    except Exception as e:
                        logger.error(f"Speech start callback error: {e}")

            self._state.silence_duration_ms = 0
            self._state.speech_duration_ms = (current_time - self._state.speech_start_time) * 1000

        else:
            if self._state.is_speaking:
                silence_ms = (current_time - self._state.last_speech_time) * 1000
                self._state.silence_duration_ms = silence_ms

                # 双流式模式下 VAD 仅作兜底，不阻塞 ASR Partial 驱动的主流程。
                # Silero 模式优先使用 min_silence_duration_ms（默认 150ms）判定句尾，
                # 相比原 silence_threshold_ms=500ms 加速兜底约 350ms；
                # WebRTC/Energy 模式继续使用 silence_threshold_ms 保持向后兼容
                silence_threshold = (
                    self.min_silence_duration_ms
                    if self.mode == VADMode.SILERO
                    else self.silence_threshold_ms
                )

                if silence_ms > silence_threshold:
                    self._state.is_speaking = False
                    state_changed = True
                    self._state.speech_duration_ms = 0

                    if self._on_speech_end_callback:
                        try:
                            self._on_speech_end_callback()
                        except Exception as e:
                            logger.error(f"Speech end callback error: {e}")

        self._state.frame_count += 1

        return {
            "is_speaking": self._state.is_speaking,
            "speech_probability": speech_probability,
            "state_changed": state_changed,
            "speech_duration_ms": self._state.speech_duration_ms,
            "silence_duration_ms": self._state.silence_duration_ms
        }

    def _calculate_energy(self, audio_data: bytes) -> float:
        if len(audio_data) < 2:
            return 0

        samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)

        energy = sum(s * s for s in samples) / len(samples)
        return energy

    def _detect_energy(self, audio_data: bytes) -> bool:
        energy = self._calculate_energy(audio_data)
        return energy > self.energy_threshold

    def _detect_webrtc(self, audio_data: bytes) -> bool:
        if self._vad is None:
            return self._detect_energy(audio_data)

        frame_size = int(self.sample_rate * self.frame_duration_ms / 1000) * 2

        if len(audio_data) < frame_size:
            return False

        try:
            return self._vad.is_speech(audio_data[:frame_size], self.sample_rate)
        except Exception as e:
            logger.error(f"WebRTC VAD error: {e}")
            return False

    def _detect_silero(self, audio_data: bytes) -> tuple[bool, float]:
        if self._vad is None:
            return self._detect_energy(audio_data), 0.5

        try:
            import torch
            import numpy as np

            samples = np.frombuffer(audio_data, dtype=np.int16)
            audio_tensor = torch.from_numpy(samples).float() / 32768.0
            audio_tensor = audio_tensor.unsqueeze(0)

            with torch.no_grad():
                speech_prob = self._vad(audio_tensor, self.sample_rate).item()

            is_speech = speech_prob > 0.5
            return is_speech, speech_prob

        except Exception as e:
            logger.error(f"Silero VAD error: {e}")
            return self._detect_energy(audio_data), 0.5

    def reset(self):
        self._state = VADState()

    @property
    def is_speaking(self) -> bool:
        return self._state.is_speaking

    @property
    def speech_duration_ms(self) -> float:
        return self._state.speech_duration_ms


class AudioStreamProcessor:
    _instance = None

    def __init__(self):
        self.vad = VADProcessor()
        self._streaming_client: Any = None
        self._agent_interrupt: Any = None
        self._audio_buffer: bytearray = bytearray()
        self._buffer_duration_ms = 0
        self._on_result_callback: Optional[Callable] = None
        # 双流式模式主驱动回调：ASR Partial Result 产出即触发 LLM Speculative Prefill，
        # 省去等待 VAD on_end 的 500ms 静默判定，实现毫秒级首字响应
        self._on_partial_result_callback: Optional[Callable] = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_config(self, config: dict):
        vad_config = config.get("vad", {})
        self.vad.set_config(vad_config)

    def set_asr_client(self, client: Any):
        self._streaming_client = client

    def set_agent_interrupt(self, agent_interrupt: Any):
        self._agent_interrupt = agent_interrupt

    def set_callbacks(
        self,
        on_speech_start: Optional[Callable] = None,
        on_speech_end: Optional[Callable] = None,
        on_result: Optional[Callable] = None,
        on_partial_result: Optional[Callable] = None
    ):
        self.vad.set_callbacks(on_speech_start=on_speech_start, on_speech_end=on_speech_end)
        self._on_result_callback = on_result
        # 主驱动回调：Partial Result 立即触发 LLM Speculative Prefill，不等 VAD on_end
        self._on_partial_result_callback = on_partial_result

    async def process_audio_chunk(self, audio_data: bytes) -> dict:
        vad_result = self.vad.process_audio(audio_data)

        self._audio_buffer.extend(audio_data)
        chunk_duration_ms = len(audio_data) / 32
        self._buffer_duration_ms += chunk_duration_ms

        result = {
            "vad": vad_result,
            "asr": None,
            "interrupt": None
        }

        if not self._streaming_client:
            if not vad_result["is_speaking"] and self._buffer_duration_ms > 1000:
                self._audio_buffer.clear()
                self._buffer_duration_ms = 0
            return result

        try:
            is_last = not vad_result["is_speaking"]
            send_success = await self._streaming_client.send_audio_chunk(
                audio_data,
                is_last=is_last
            )

            if not send_success:
                logger.warning("Failed to send audio chunk to streaming ASR")

            streaming_result = await self._streaming_client.receive_result(timeout=0.1)

            if streaming_result:
                asr_result = {
                    "text": streaming_result.text,
                    "clean_text": streaming_result.clean_text,
                    "language": streaming_result.language,
                    "is_final": streaming_result.is_final,
                    "emotion": streaming_result.emotion
                }
                result["asr"] = asr_result

                # 主驱动：Partial Result (is_final=False) 立即触发 LLM Speculative Prefill，
                # 省去等待 VAD on_end 的 500ms 静默判定，实现低延迟首字响应。
                # 此回调不等 VAD，是双流式模式的主流程驱动器
                if not streaming_result.is_final and self._on_partial_result_callback is not None:
                    try:
                        await self._on_partial_result_callback(asr_result)
                    except Exception as e:
                        logger.error(f"on_partial_result callback error: {e}")

                # 配合 interrupt_manager 实现毫秒级全双工打断：
                # 当检测到用户在 Agent 说话期间开口（Partial Result 含有效文本），
                # 立即触发打断判定，无需等待 VAD on_end 兜底
                if self._agent_interrupt and streaming_result.text:
                    interrupt_result = await self._agent_interrupt.on_asr_partial_result(
                        streaming_result.text,
                        streaming_result.is_final
                    )
                    result["interrupt"] = interrupt_result

                    if interrupt_result.get("should_interrupt"):
                        await self._agent_interrupt.interrupt_user(
                            interrupt_result.get("reply_content", "")
                        )

                if self._on_result_callback:
                    await self._on_result_callback(result)

            if is_last:
                # VAD on_end 兜底：仅修正 Final 文本，不重启已由 Partial 启动的 LLM 流程。
                # 双流式模式下主流程已由 ASR Partial Result 驱动，此处只做收尾与状态复位，
                # 避免阻塞或重复触发 LLM Prefill
                await self._streaming_client.reset()
                self._audio_buffer.clear()
                self._buffer_duration_ms = 0

        except Exception as e:
            logger.error(f"Streaming ASR error: {e}")

        return result

    def reset(self):
        self.vad.reset()
        self._audio_buffer.clear()
        self._buffer_duration_ms = 0


def get_vad_processor() -> VADProcessor:
    return VADProcessor.get_instance()


def get_audio_stream_processor() -> AudioStreamProcessor:
    return AudioStreamProcessor.get_instance()
