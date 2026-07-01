"""
TTS 音频处理工具函数
从 tts_service.py 拆分出来的无状态工具函数，不依赖 TTSService 实例状态。
"""
from __future__ import annotations

import io
import json
import re
import struct
import wave
from pathlib import Path


def split_text_by_sentences(text: str, max_length: int = 200) -> list[str]:
    sentence_endings = re.compile(r'([。！？.!?]+)')
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


def load_emotion_voices(emotion_refs_dir: str) -> dict:
    emotion_voices = {}
    refs_dir = Path(emotion_refs_dir)
    if not refs_dir.exists():
        return emotion_voices
    mapping_file = refs_dir / "emotion_mapping.json"
    if mapping_file.exists():
        with open(mapping_file, "r", encoding="utf-8") as f:
            emotion_voices = json.load(f)
    else:
        for emotion_dir in refs_dir.iterdir():
            if emotion_dir.is_dir():
                ref_audio = None
                ref_text = ""
                for ext in [".wav", ".mp3", ".flac"]:
                    candidate = emotion_dir / f"ref{ext}"
                    if candidate.exists():
                        ref_audio = str(candidate)
                        break
                text_file = emotion_dir / "ref.txt"
                if text_file.exists():
                    ref_text = text_file.read_text(encoding="utf-8").strip()
                if ref_audio:
                    emotion_voices[emotion_dir.name] = {
                        "ref_audio": ref_audio,
                        "ref_text": ref_text,
                    }
    return emotion_voices
