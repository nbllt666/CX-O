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
    """VAD 模式"""
    ENERGY = "energy"
    WEBRTC = "webrtc"
    SILERO = "silero"


@dataclass
class VADState:
    """VAD 状态"""
    is_speaking: bool = False
    speech_start_time: float = 0
    last_speech_time: float = 0
    silence_duration_ms: float = 0
    speech_duration_ms: float = 0
    frame_count: int = 0


class VADProcessor:
    """
    VAD 处理器

    支持多种 VAD 后端：
    1. Energy - 基于音量能量检测（简单，无需额外依赖）
    2. WebRTC - WebRTC VAD（需要 webrtcvad 库）
    3. Silero - Silero VAD（需要 torch 和 silero 库）

    默认使用 WebRTC 模式
    """
    _instance = None

    def __init__(self):
        self.mode = VADMode.WEBRTC
        self.sample_rate = 16000
        self.frame_duration_ms = 30
        self.energy_threshold = 500
        self.silence_threshold_ms = 500
        self.speech_threshold_ms = 300
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
        """设置配置"""
        mode_str = config.get("mode", "webrtc")
        self.mode = VADMode(mode_str)
        self.sample_rate = config.get("sample_rate", 16000)
        self.frame_duration_ms = config.get("frame_duration_ms", 30)
        self.energy_threshold = config.get("energy_threshold", 500)
        self.silence_threshold_ms = config.get("silence_threshold_ms", 500)
        self.speech_threshold_ms = config.get("speech_threshold_ms", 300)

        self._init_vad()
        self._initialized = True

    def _init_vad(self):
        """初始化 VAD 后端"""
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
        """设置回调函数"""
        self._on_speech_start_callback = on_speech_start
        self._on_speech_end_callback = on_speech_end

    def process_audio(self, audio_data: bytes) -> dict:
        """
        处理音频数据，检测语音活动

        Args:
            audio_data: PCM 音频数据 (16-bit, 16kHz, mono)

        Returns:
            dict: {
                "is_speaking": bool,
                "speech_probability": float,
                "state_changed": bool,
                "speech_duration_ms": float
            }
        """
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

                if silence_ms > self.silence_threshold_ms:
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
        """计算音频能量"""
        if len(audio_data) < 2:
            return 0

        samples = struct.unpack(f'<{len(audio_data)//2}h', audio_data)

        energy = sum(s * s for s in samples) / len(samples)
        return energy

    def _detect_energy(self, audio_data: bytes) -> bool:
        """基于能量的语音检测"""
        energy = self._calculate_energy(audio_data)
        return energy > self.energy_threshold

    def _detect_webrtc(self, audio_data: bytes) -> bool:
        """WebRTC VAD 检测"""
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
        """Silero VAD 检测"""
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
        """重置状态"""
        self._state = VADState()

    @property
    def is_speaking(self) -> bool:
        return self._state.is_speaking

    @property
    def speech_duration_ms(self) -> float:
        return self._state.speech_duration_ms


class AudioStreamProcessor:
    """
    音频流处理器
    使用 SenseVoice 流式 ASR 进行实时语音识别
    
    支持两种打断模式：
    1. ASRInterrupt - 用户打断 TTS（TTS 播放时用户说话）
    2. AgentInterrupt - Agent 插话（用户说话时 Agent 判断是否可以插话）
    
    注意：此类不再使用单例模式，每个客户端应有独立实例
    """

    def __init__(self):
        self.vad = VADProcessor()
        self._streaming_client: Any = None
        self._asr_interrupt: Any = None
        self._agent_interrupt: Any = None
        self._audio_buffer: bytearray = bytearray()
        self._buffer_duration_ms = 0
        self._on_result_callback: Optional[Callable] = None
        self._is_tts_playing = False
        self._is_user_speaking = False

    def set_config(self, config: dict):
        """设置配置"""
        vad_config = config.get("vad", {})
        self.vad.set_config(vad_config)

    def set_streaming_client(self, client: Any):
        """设置流式 ASR 客户端"""
        self._streaming_client = client

    def set_asr_interrupt(self, asr_interrupt: Any):
        """设置 ASR 打断模块（用户打断 TTS）"""
        self._asr_interrupt = asr_interrupt

    def set_agent_interrupt(self, agent_interrupt: Any):
        """设置 Agent 打断模块（Agent 插话）"""
        self._agent_interrupt = agent_interrupt

    def set_tts_playing(self, playing: bool):
        """设置 TTS 播放状态"""
        self._is_tts_playing = playing
        if self._asr_interrupt:
            self._asr_interrupt.set_tts_playing(playing)

    def set_callbacks(
        self,
        on_speech_start: Optional[Callable] = None,
        on_speech_end: Optional[Callable] = None,
        on_result: Optional[Callable] = None
    ):
        """设置回调函数"""
        self.vad.set_callbacks(on_speech_start=on_speech_start, on_speech_end=on_speech_end)
        self._on_result_callback = on_result

    async def process_audio_chunk(self, audio_data: bytes) -> dict:
        """
        处理音频块，使用 SenseVoice 流式 ASR

        Args:
            audio_data: PCM 音频数据

        Returns:
            dict: 处理结果
        """
        vad_result = self.vad.process_audio(audio_data)
        
        if vad_result.get("state_changed"):
            if vad_result["is_speaking"]:
                self._is_user_speaking = True
                if self._agent_interrupt:
                    self._agent_interrupt.on_user_speech_start()
            else:
                self._is_user_speaking = False
                if self._agent_interrupt:
                    self._agent_interrupt.on_user_speech_end()

        self._audio_buffer.extend(audio_data)
        chunk_duration_ms = len(audio_data) / 32
        self._buffer_duration_ms += chunk_duration_ms

        result = {
            "vad": vad_result,
            "asr": None,
            "interrupt": None,
            "interrupt_type": None,
            "is_user_speaking": self._is_user_speaking,
            "is_tts_playing": self._is_tts_playing
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

                if self._is_tts_playing and self._asr_interrupt and streaming_result.text:
                    decision, should_interrupt = await self._asr_interrupt.on_asr_result(
                        streaming_result.text,
                        streaming_result.is_final
                    )
                    result["interrupt"] = {
                        "decision": decision,
                        "should_interrupt": should_interrupt,
                        "asr_text": streaming_result.text
                    }
                    result["interrupt_type"] = "user_interrupt_tts"
                    if decision == "INTERRUPT":
                        logger.info(f"User interrupt TTS: triggering interrupt, text={streaming_result.text}")
                    else:
                        logger.info(f"User interrupt TTS: user still speaking, waiting, text={streaming_result.text}")

                elif not self._is_tts_playing and self._agent_interrupt and streaming_result.text:
                    interrupt_result = await self._agent_interrupt.on_asr_partial_result(
                        streaming_result.text,
                        streaming_result.is_final
                    )
                    result["interrupt"] = interrupt_result
                    result["interrupt_type"] = "agent_interrupt_user"
                    logger.info(f"Agent interrupt user check: should_interrupt={interrupt_result.get('should_interrupt')}")

                if self._on_result_callback:
                    await self._on_result_callback(result)

            if is_last:
                await self._streaming_client.reset()
                self._audio_buffer.clear()
                self._buffer_duration_ms = 0

        except Exception as e:
            logger.error(f"Streaming ASR error: {e}")

        return result

    def reset(self):
        """重置状态"""
        self.vad.reset()
        self._audio_buffer.clear()
        self._buffer_duration_ms = 0


def get_vad_processor() -> VADProcessor:
    return VADProcessor.get_instance()


def create_audio_stream_processor() -> AudioStreamProcessor:
    return AudioStreamProcessor()


get_audio_stream_processor = create_audio_stream_processor
