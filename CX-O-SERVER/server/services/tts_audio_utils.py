"""
TTS 音频处理工具函数
从 tts_service.py 拆分出来的无状态工具函数，不依赖 TTSService 实例状态。
"""
from __future__ import annotations

import io
import os
import re
import struct
import wave


# ============================================================
# PCM 静音过滤（解决 Orpheus TTS 段间静音问题）
# ============================================================

# 24kHz 16-bit mono: 每帧 20ms = 480 samples * 2 bytes = 960 bytes
SILENCE_FRAME_SIZE: int = 960

# 静音检测阈值：振幅绝对值低于此值视为静音
# 默认 200，约 0.6% 最大振幅（32767），与 orpheus-tts/api_server.py 对齐
SILENCE_AMPLITUDE_THRESHOLD: int = int(os.environ.get("SILENCE_AMPLITUDE_THRESHOLD", "200"))

# 客户端最大连续静音帧数：超过此值则跳过（不 yield）
# 默认 5 帧 = 100ms，比服务端（10 帧 = 200ms）更严格
# 原因：客户端过滤器还要捕获跨请求边界静音（trailing + leading 合并 400ms）
# 阈值过大会保留段间长静音，阈值过小会切断自然停顿；100ms 是中文自然停顿的下限
MAX_CONSECUTIVE_SILENCE_FRAMES_CLIENT: int = int(
    os.environ.get("MAX_CONSECUTIVE_SILENCE_FRAMES_CLIENT", "5")
)


def is_silence_pcm(pcm_bytes: bytes, threshold: int = SILENCE_AMPLITUDE_THRESHOLD) -> bool:
    """检测 PCM bytes（16-bit signed LE）是否为静音帧。

    判据：所有样本的绝对值均低于 threshold（默认 200，约 0.6% 最大振幅）。

    用于过滤 Orpheus TTS 段间长静音，避免播放时出现明显间隔。
    与 orpheus-tts/api_server.py 中的同名函数保持一致。
    """
    import numpy as np

    if len(pcm_bytes) < 4:
        return True
    arr = np.frombuffer(pcm_bytes, dtype=np.int16)
    if arr.size == 0:
        return True
    return bool(np.all(np.abs(arr) < threshold))


class CrossRequestSilenceFilter:
    """跨请求 PCM 静音过滤器。

    解决 Orpheus TTS 多次请求间的边界静音问题：
    - 请求 N 末尾的 trailing silence（最多 200ms，由 orpheus-tts/api_server.py 保留）
    - 请求 N+1 开头的 leading silence（最多 200ms）
    - 合并后形成 400ms 的段间静音，影响听感

    本过滤器维护跨请求的连续静音计数器：
    - 收到静音帧 → 计数器 +1
    - 计数器 > MAX_CONSECUTIVE_SILENCE_FRAMES_CLIENT → 跳过 yield
    - 收到非静音帧 → 计数器归零，yield

    使用方式：
        filt = CrossRequestSilenceFilter()
        for chunk in pcm_stream:
            filtered = filt.feed(chunk)
            if filtered:
                yield filtered
        remaining = filt.flush()
        if remaining:
            yield remaining
    """

    def __init__(
        self,
        amplitude_threshold: int = SILENCE_AMPLITUDE_THRESHOLD,
        max_silence_frames: int = MAX_CONSECUTIVE_SILENCE_FRAMES_CLIENT,
        frame_size: int = SILENCE_FRAME_SIZE,
    ) -> None:
        self._amplitude_threshold = amplitude_threshold
        self._max_silence_frames = max_silence_frames
        self._frame_size = frame_size
        self._buffer = bytearray()
        self._consecutive_silence = 0
        self._total_silence_skipped = 0
        self._total_frames = 0

    def _is_silence_frame(self, frame: bytes) -> bool:
        import numpy as np

        arr = np.frombuffer(frame, dtype=np.int16)
        return bool(np.all(np.abs(arr) < self._amplitude_threshold))

    def feed(self, pcm_chunk: bytes) -> bytes:
        """输入一个 PCM chunk（任意大小），返回过滤后的 bytes（可能为空）。

        - 内部按 20ms 帧切分处理
        - 静音帧超过阈值则跳过
        - 非静音帧或未超阈值的静音帧保留
        - 跨调用维护状态（用于跨请求边界静音过滤）
        """
        if not pcm_chunk:
            return b""

        self._buffer.extend(pcm_chunk)
        output = bytearray()

        while len(self._buffer) >= self._frame_size:
            frame = bytes(self._buffer[:self._frame_size])
            del self._buffer[:self._frame_size]
            self._total_frames += 1

            if self._is_silence_frame(frame):
                self._consecutive_silence += 1
                if self._consecutive_silence <= self._max_silence_frames:
                    # 保留短静音（自然停顿）
                    output.extend(frame)
                else:
                    # 跳过长静音
                    self._total_silence_skipped += 1
            else:
                self._consecutive_silence = 0
                output.extend(frame)

        return bytes(output)

    def flush(self) -> bytes:
        """返回缓冲区中剩余的字节（不足一帧的尾部数据）。

        注意：只清空 buffer，不重置 consecutive_silence 计数器，
        以便跨 text_segment 调用时保持过滤状态。
        """
        if not self._buffer:
            return b""
        output = bytes(self._buffer)
        self._buffer.clear()
        return output

    def get_stats(self) -> dict:
        """返回过滤统计信息。"""
        return {
            "total_frames": self._total_frames,
            "silence_skipped": self._total_silence_skipped,
            "silence_ratio": (
                self._total_silence_skipped / self._total_frames
                if self._total_frames > 0
                else 0.0
            ),
        }


# P6: 句末标点模式预编译为模块级常量——split_text_by_sentences 处于 TTS 分句
# 热路径，每次调用重复 re.compile 纯浪费；re 模块内部虽有缓存，但显式预编译
# 免去每次调用的缓存查找与函数调用开销
_SENTENCE_ENDINGS = re.compile(r'([。！？.!?]+)')


def split_text_by_sentences(text: str, max_length: int = 200) -> list[str]:
    """按句末标点将文本切分为句子，并按 max_length 合并相邻短句。"""

    sentence_endings = _SENTENCE_ENDINGS
    parts = sentence_endings.split(text)

    sentences = []
    current = ""

    for i, part in enumerate(parts):
        current += part
        if sentence_endings.match(part) or i == len(parts) - 1:
            if current.strip():
                sentences.append(current.strip())
            current = ""

    if current.strip():
        sentences.append(current.strip())

    merged = []
    buffer = ""
    for sentence in sentences:
        if len(buffer) + len(sentence) <= max_length:
            buffer += sentence
        else:
            if buffer:
                merged.append(buffer)
            buffer = sentence
    if buffer:
        merged.append(buffer)

    return merged


def generate_silence(duration_ms: int) -> bytes:
    """生成指定时长（毫秒）的静音 WAV 音频字节。"""

    sample_rate = 22050
    num_channels = 1
    sample_width = 2
    num_frames = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * num_frames)
    return buf.getvalue()


async def concatenate_audio(audio_segments: list[bytes]) -> bytes:
    """将多个音频片段拼接为单个音频：全为 WAV 时合并 PCM 并重建头部，否则直接字节拼接。"""

    if not audio_segments:
        return b""

    if len(audio_segments) == 1:
        return audio_segments[0]

    def is_wav(data: bytes) -> bool:
        return len(data) > 44 and data[:4] == b'RIFF' and data[8:12] == b'WAVE'

    if all(is_wav(seg) for seg in audio_segments):
        first = audio_segments[0]
        num_channels = struct.unpack('<H', first[22:24])[0]
        sample_rate = struct.unpack('<I', first[24:28])[0]
        bits_per_sample = struct.unpack('<H', first[34:36])[0]

        byte_rate = sample_rate * num_channels * bits_per_sample // 8

        combined_data = bytearray()
        for seg in audio_segments:
            data_size = struct.unpack('<I', seg[40:44])[0]
            combined_data.extend(seg[44:44+data_size])

        data_size = len(combined_data)
        wav_header = bytearray(44)
        wav_header[0:4] = b'RIFF'
        wav_header[4:8] = struct.pack('<I', data_size + 36)
        wav_header[8:12] = b'WAVE'
        wav_header[12:16] = b'fmt '
        wav_header[16:20] = struct.pack('<I', 16)
        wav_header[20:22] = struct.pack('<H', 1)
        wav_header[22:24] = struct.pack('<H', num_channels)
        wav_header[24:28] = struct.pack('<I', sample_rate)
        wav_header[28:32] = struct.pack('<I', byte_rate)
        wav_header[32:34] = struct.pack('<H', num_channels * bits_per_sample // 8)
        wav_header[34:36] = struct.pack('<H', bits_per_sample)
        wav_header[36:40] = b'data'
        wav_header[40:44] = struct.pack('<I', data_size)

        return bytes(wav_header) + bytes(combined_data)
    else:
        return b"".join(audio_segments)
