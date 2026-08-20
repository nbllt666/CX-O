"""
VAD (Voice Activity Detection) 模块
后端语音活动检测，判断用户是否在说话
"""
import asyncio
import logging
import struct
import time
from typing import Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class VADMode(Enum):
    """语音活动检测模式：能量阈值 / WebRTC / Silero。"""

    ENERGY = "energy"
    WEBRTC = "webrtc"
    SILERO = "silero"


@dataclass
class VADState:
    """VAD 状态数据类：记录说话中状态、起止时间与各类时长统计。"""

    is_speaking: bool = False
    speech_start_time: float = 0
    last_speech_time: float = 0
    silence_duration_ms: float = 0
    speech_duration_ms: float = 0
    frame_count: int = 0


class VADProcessor:
    """语音活动检测处理器：按配置模式检测语音并触发起止回调。"""

    _instance = None

    def __init__(self):
        """初始化 VAD 处理器，设置默认参数与检测状态。"""
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
        self._frame_size = self._compute_frame_size()

    @classmethod
    def get_instance(cls):
        """获取全局 VAD 处理器单例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_config(self, config: dict):
        """应用 VAD 配置并重新初始化检测器。"""
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
        # sample_rate / frame_duration_ms 变化时同步刷新 WebRTC 帧大小（每帧复用）
        self._frame_size = self._compute_frame_size()

        self._init_vad()
        self._initialized = True

    def _compute_frame_size(self) -> int:
        """计算 WebRTC VAD 单帧字节数（int16 PCM，每样本 2 字节）。"""
        return int(self.sample_rate * self.frame_duration_ms / 1000) * 2

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
        """设置语音开始与结束的回调函数。"""
        self._on_speech_start_callback = on_speech_start
        self._on_speech_end_callback = on_speech_end

    def process_audio(self, audio_data: bytes) -> dict:
        """处理一帧音频，更新说话状态并返回检测结果字典。"""
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

        frame_size = self._frame_size

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
        """重置 VAD 检测状态。"""
        self._state = VADState()

    @property
    def is_speaking(self) -> bool:
        """当前是否处于说话状态。"""
        return self._state.is_speaking

    @property
    def speech_duration_ms(self) -> float:
        """当前说话持续时长（毫秒）。"""
        return self._state.speech_duration_ms


class AudioStreamProcessor:
    """音频流处理器：结合 VAD 与流式 ASR 客户端处理实时音频并产出结果。"""

    _instance = None

    def __init__(self):
        """初始化音频流处理器，创建 VAD 实例并重置缓冲状态。"""
        self.vad = VADProcessor()
        self._streaming_client: Any = None
        self._agent_interrupt: Any = None
        self._audio_buffer: bytearray = bytearray()
        self._buffer_duration_ms = 0
        self._on_result_callback: Optional[Callable] = None
        # 双流式模式主驱动回调：ASR Partial Result 产出即触发 LLM Speculative Prefill，
        # 省去等待 VAD on_end 的 500ms 静默判定，实现毫秒级首字响应
        self._on_partial_result_callback: Optional[Callable] = None
        # 后台任务引用集合：防止 _deferred_interrupt_check 等长任务被 GC 提前回收
        # （asyncio 不持有裸 create_task 的引用，任务完成前被回收会静默中断）。
        self._background_tasks: set = set()

    @classmethod
    def get_instance(cls):
        """获取全局音频流处理器单例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_config(self, config: dict):
        """应用配置并同步配置内部 VAD 处理器。"""
        vad_config = config.get("vad", {})
        self.vad.set_config(vad_config)

    def set_asr_client(self, client: Any):
        """设置流式 ASR 客户端。"""
        self._streaming_client = client

    def set_agent_interrupt(self, agent_interrupt: Any):
        """设置用于全双工打断判定的 agent interrupt 处理器。"""
        self._agent_interrupt = agent_interrupt

    def set_callbacks(
        self,
        on_speech_start: Optional[Callable] = None,
        on_speech_end: Optional[Callable] = None,
        on_result: Optional[Callable] = None,
        on_partial_result: Optional[Callable] = None
    ):
        """设置 VAD 及流式结果相关回调函数。"""
        self.vad.set_callbacks(on_speech_start=on_speech_start, on_speech_end=on_speech_end)
        self._on_result_callback = on_result
        # 主驱动回调：Partial Result 立即触发 LLM Speculative Prefill，不等 VAD on_end
        self._on_partial_result_callback = on_partial_result

    async def process_audio_chunk(self, audio_data: bytes, skip_interrupt: bool = False) -> dict:
        """处理单帧音频

        skip_interrupt: 双流式(voice.dual_stream)路径传 True。
        双流式自身已有完整 ASR→LLM→TTS pipeline 与 VAD speech_start 全双工打断，
        agent_interrupt 的"LLM 判断插话"在此场景完全冗余——每个 partial 额外触发
        一次完整 LLM chat，与主 pipeline 争夺 vLLM 仅有的并发槽，实测把 LLM/TTS
        饿死（chunk first PCM 47s）。半双工/live 路径保持默认 False 不变。
        """
        _debug = logger.isEnabledFor(logging.DEBUG)
        if _debug:
            _diag_t0 = time.time()
        vad_result = self.vad.process_audio(audio_data)
        if _debug:
            _diag_t1 = time.time()

        result = {
            "vad": vad_result,
            "asr": None,
        }

        # 音频缓冲仅在「无流式 ASR 客户端」的兜底路径被读取（is_speaking 期间累积、
        # 静默超 1s 清空）。双流式语音路径恒有 _streaming_client，缓冲累加是纯死写（每帧
        # extend + len/32 + += 均被丢弃），故下移到兜底分支，避免占用热路径。
        if not self._streaming_client:
            self._audio_buffer.extend(audio_data)
            self._buffer_duration_ms += len(audio_data) / 32
            if not vad_result["is_speaking"] and self._buffer_duration_ms > 1000:
                self._audio_buffer.clear()
                self._buffer_duration_ms = 0
            return result

        try:
            # 仅在 VAD "说话→静默" 翻转的当帧发 final（每轮语音一次）。
            # 严禁对所有静默帧发 final——ASR 服务端每次 final 都对全缓冲
            # 跑完整推理并清空（api_server.py:295），静默帧刷屏会把服务端
            # 推理队列打爆（帧速 16.7/s ≫ 推理吞吐），致 keepalive 断连、
            # 本轮识别结果全丢（2026-08-05 18:19 实测复现）。
            is_last = vad_result["state_changed"] and not vad_result["is_speaking"]

            # VAD 门控：仅说话中（及翻转当帧）的音频送 ASR 服务端。
            # 严禁转发纯静默帧——静默在服务端缓冲累积（final 清空后重新积满
            # 48KB 阈值），触发对纯静默的 partial 推理，SenseVoice 在静默上
            # 幻觉出乱码（实测产出韩文 '그.'/'아.'），且 speech_end 已重置
            # 触发标志，幻觉 partial 会二次触发完整 LLM+TTS pipeline，
            # 多轮累积致端到端延迟 4.7s→9.5s→14.3s 递增（2026-08-05 实测）。
            should_send = vad_result["is_speaking"] or is_last
            if _debug:
                _diag_t2 = time.time()
            if should_send:
                send_success = await self._streaming_client.send_audio_chunk(
                    audio_data,
                    is_last=is_last
                )
            else:
                send_success = True  # 静默帧本地消化，不转发 ASR

            if not send_success:
                logger.warning("Failed to send audio chunk to streaming ASR")

            # 非阻塞轮询（timeout=0）：ASR 结果由后台 recv task 异步推入 queue，
            # 有结果立即取走，无结果下一帧（≤60ms）再取。
            # 严禁在此传入 >0 的 timeout——每帧阻塞等待会导致处理速度（~105ms/帧）
            # 低于实时帧速（60ms/帧），队列持续积压，Partial 滞后 5~7s，
            # 端到端延迟实测暴涨至 6.5~7.7s（目标 <800ms）。
            streaming_result = await self._streaming_client.receive_result(timeout=0)
            if _debug:
                _diag_t3 = time.time()
                logger.debug(f"[DIAG-VAD] vad={(_diag_t1-_diag_t0)*1000:.1f}ms send+recv={(_diag_t3-_diag_t2)*1000:.1f}ms is_last={is_last} has_result={streaming_result is not None}")

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
                # 性能修复：on_asr_partial_result 内部调用 _check_can_interrupt → LLM chat（非流式，~8s），
                # 若 await 会阻塞 process_audio_chunk 返回，导致 on_partial_result 延迟 8s，
                # WS 端到端测试超时（spec 目标 < 800ms）。
                # 改为 asyncio.create_task 非阻塞触发整个打断判定流程，主流程立即返回 result。
                # 打断结果由 _deferred_interrupt_check 直接调用 interrupt_user 落地，
                # 不再写入 process_audio_chunk 返回值（调用方无需在 ASR 主路径上依赖此字段）。
                if self._agent_interrupt and streaming_result.text and not skip_interrupt:
                    async def _deferred_interrupt_check():
                        try:
                            interrupt_result = await self._agent_interrupt.on_asr_partial_result(
                                streaming_result.text,
                                streaming_result.is_final
                            )
                            # 【标签解耦】半双工路径无 ensure_reply 会话兜底，
                            # should_reply（Feature B）沿用 interrupt_user 保持旧行为不回归；
                            # 真打断路径（should_interrupt）行为不变。
                            if interrupt_result.get("should_interrupt") or interrupt_result.get("should_reply"):
                                await self._agent_interrupt.interrupt_user(
                                    interrupt_result.get("reply_content", "")
                                )
                        except Exception as e:
                            logger.error(f"Deferred agent interrupt check error: {e}")

                    self._track_background_task(
                        asyncio.create_task(_deferred_interrupt_check())
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
        """重置 VAD 状态并清空音频缓冲。"""
        self.vad.reset()
        self._audio_buffer.clear()
        self._buffer_duration_ms = 0


def get_vad_processor() -> VADProcessor:
    """获取全局 VAD 处理器单例。"""
    return VADProcessor.get_instance()


def get_audio_stream_processor() -> AudioStreamProcessor:
    """获取全局音频流处理器单例。"""
    return AudioStreamProcessor.get_instance()
