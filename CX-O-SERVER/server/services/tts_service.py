"""
统一 TTS 服务
支持 embedded（直接调用 F5-TTS 模型）和 remote（HTTP 调用）两种模式
合并了原 TTSClient 的流式合成、情感语音、音效、Triton 推理等功能
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import struct
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

import httpx

from server.core.utils import get_shared_http_client, close_shared_http_client, retry_with_backoff
from server.services.emotion_parser import extract_emotions_with_text, parse_text_with_emotions
from server.services.effect_parser import EffectParser

logger = logging.getLogger(__name__)


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


class TTSService:
    def __init__(
        self,
        mode: str = "remote",
        model_dir: str = "",
        device: str = "cuda",
        remote_url: str = "http://127.0.0.1:5000",
        ref_audio_path: str = "",
        ref_text: str = "",
        speed: float = 1.0,
        cross_fade_duration: float = 0.15,
        emotion_voices: dict[str, dict[str, str]] | None = None,
        effects_dir: str | Path | None = None,
        voice_refs_dir: str | Path | None = None,
        gateway_url: str | None = None,
        use_triton: bool = False,
    ):
        self._mode = mode
        self._model_dir = model_dir
        self._device = device
        self._remote_url = remote_url
        self._ref_audio_path = ref_audio_path
        self._ref_text = ref_text
        self._speed = speed
        self._cross_fade_duration = cross_fade_duration
        self._initialized = False

        self._emotion_voices = emotion_voices or {}
        self._effect_parser = EffectParser(effects_dir)
        self._emotion_audio_cache: dict[str, bytes] = {}
        self._voice_refs_dir = Path(voice_refs_dir) if voice_refs_dir else Path(__file__).parent.parent / "data" / "voice_refs"
        self._gateway_url = gateway_url.rstrip("/") if gateway_url else None
        self._use_triton = use_triton
        self._ref_audio_data: bytes | None = None

    @property
    def mode(self) -> str:
        return self._mode

    async def initialize(self):
        if self._mode != "embedded":
            logger.info(f"TTS service in remote mode, target: {self._remote_url}")
            self._initialized = True
            return

        from f5_tts.api import load_model, get_f5tts
        if get_f5tts() is not None:
            self._initialized = True
            return

        logger.info(f"Loading F5-TTS model...")
        if not load_model():
            raise RuntimeError("Failed to load F5-TTS model")
        self._initialized = True
        logger.info("F5-TTS model loaded successfully")

    async def shutdown(self):
        import f5_tts.api as _api
        _api._f5tts_instance = None
        self._initialized = False

    async def _load_ref_audio(self) -> bytes:
        if self._ref_audio_data is None:
            if not self._ref_audio_path:
                raise ValueError(
                    "TTS requires reference audio. "
                    "Please provide ref_audio in request data or configure ref_audio_path in config.json"
                )
            if not Path(self._ref_audio_path).exists():
                raise ValueError(f"Reference audio file not found: {self._ref_audio_path}")
            with open(self._ref_audio_path, "rb") as f:
                self._ref_audio_data = f.read()
        return self._ref_audio_data

    def _resolve_audio_path(self, ref_audio: str) -> Path | None:
        if not ref_audio:
            return None

        if Path(ref_audio).is_absolute():
            return Path(ref_audio)

        if Path(ref_audio).exists():
            return Path(ref_audio)

        voice_refs_path = self._voice_refs_dir / ref_audio
        if voice_refs_path.exists():
            return voice_refs_path

        return None

    async def synthesize(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        ref_audio: str | None = None,
        speed: float | None = None,
        cross_fade_duration: float | None = None,
        **kwargs
    ) -> bytes:
        audio_path = ref_audio_path or self._ref_audio_path
        text_ref = ref_text or self._ref_text
        spd = speed or self._speed
        cfd = cross_fade_duration or self._cross_fade_duration

        if ref_audio:
            try:
                audio_data = base64.b64decode(ref_audio)
            except Exception as e:
                raise ValueError(f"Invalid base64 ref_audio: {e}")
        elif audio_path and Path(audio_path).exists():
            audio_data = open(audio_path, "rb").read()
        else:
            audio_data = await self._load_ref_audio()

        if not text_ref:
            raise ValueError(
                "TTS requires reference text that matches the reference audio. "
                "Please provide ref_text in request data or configure it in config.json"
            )

        if self._mode == "embedded":
            from f5_tts.api import get_f5tts
            if get_f5tts() is not None:
                return await self._synthesize_embedded(text, audio_path, text_ref, spd, cfd, **kwargs)

        if self._use_triton and self._gateway_url:
            return await self._synthesize_triton(text, audio_data, text_ref, **kwargs)
        else:
            return await self._synthesize_remote(text, audio_data, text_ref, spd, cfd, **kwargs)

    async def _synthesize_embedded(
        self, text: str, ref_audio_path: str, ref_text: str, speed: float, cross_fade_duration: float, **kwargs
    ) -> bytes:
        from f5_tts.api import infer

        ref_path = ref_audio_path
        output_fd, output_path = tempfile.mkstemp(suffix=".wav")
        os.close(output_fd)

        try:
            infer(
                ref_file=ref_path,
                ref_text=ref_text,
                gen_text=text,
                output_path=output_path,
                speed=speed,
                cross_fade_duration=cross_fade_duration,
                nfe_step=kwargs.get("nfe_step", 32),
                cfg_strength=kwargs.get("cfg_strength", 2),
                seed=kwargs.get("seed", -1),
                remove_silence=kwargs.get("remove_silence", False),
            )

            with open(output_path, "rb") as f:
                audio_data = f.read()
            return audio_data
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    async def _synthesize_remote(
        self, text: str, audio_data: bytes, ref_text: str, speed: float, cross_fade_duration: float, **kwargs
    ) -> bytes:
        async def _make_request():
            client = get_shared_http_client()

            files = {
                "ref_audio": ("ref_audio.wav", audio_data, "audio/wav")
            }
            data = {
                "ref_text": ref_text,
                "gen_text": text,
                "speed": str(speed),
                "cross_fade_duration": str(cross_fade_duration),
                "nfe_step": str(kwargs.get("nfe_step", 32)),
                "cfg_strength": str(kwargs.get("cfg_strength", 2)),
                "seed": str(kwargs.get("seed", -1)),
                "remove_silence": str(kwargs.get("remove_silence", False)).lower(),
            }

            response = await client.post(f"{self._remote_url}/tts/", files=files, data=data)
            response.raise_for_status()
            return response.content

        return await retry_with_backoff(_make_request, max_retries=3, base_delay=1.0, max_delay=30.0, service_name="TTS")

    async def _synthesize_triton(
        self,
        text: str,
        audio_data: bytes,
        ref_text: str,
        **kwargs
    ) -> bytes:
        async def _make_request():
            client = get_shared_http_client()
            ref_audio_b64 = base64.b64encode(audio_data).decode("utf-8")

            response = await client.post(
                f"{self._gateway_url}/api/v1/tts/synthesize",
                json={
                    "reference_audio": ref_audio_b64,
                    "reference_text": ref_text,
                    "target_text": text,
                    "speed": float(kwargs.get("speed", 1.0))
                }
            )
            response.raise_for_status()
            result = response.json()

            if "audio_data" in result:
                return base64.b64decode(result["audio_data"])
            elif "error" in result:
                raise ValueError(f"TTS error: {result['error']}")
            else:
                raise ValueError("TTS response missing audio_data")

        return await retry_with_backoff(_make_request, max_retries=3, base_delay=1.0, max_delay=30.0, service_name="TTS-Triton")

    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        sentences = split_text_by_sentences(text)

        audio_path = ref_audio_path or self._ref_audio_path
        text_ref = ref_text or self._ref_text

        if not audio_path:
            yield {
                "text_segment": text,
                "audio_data": None,
                "chunk_index": 0,
                "is_final": True,
                "error": "TTS requires reference audio. Please provide ref_audio in request data."
            }
            return

        if not text_ref:
            yield {
                "text_segment": text,
                "audio_data": None,
                "chunk_index": 0,
                "is_final": True,
                "error": "TTS requires reference text. Please provide ref_text in request data."
            }
            return

        try:
            if ref_audio_path and Path(ref_audio_path).exists():
                audio_data = open(ref_audio_path, "rb").read()
            else:
                audio_data = await self._load_ref_audio()
        except ValueError as e:
            yield {
                "text_segment": text,
                "audio_data": None,
                "chunk_index": 0,
                "is_final": True,
                "error": str(e)
            }
            return

        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue

            try:
                if self._mode == "embedded":
                    from f5_tts.api import get_f5tts
                    if get_f5tts() is not None:
                        audio_bytes = await self._synthesize_embedded(
                            sentence, audio_path, text_ref,
                            kwargs.get("speed", self._speed),
                            kwargs.get("cross_fade_duration", self._cross_fade_duration),
                            **kwargs
                        )
                        chunk = {
                            "text_segment": sentence,
                            "audio_data": audio_bytes,
                            "chunk_index": i,
                            "is_final": i == len(sentences) - 1
                        }
                        if on_chunk and audio_bytes:
                            on_chunk(sentence, audio_bytes)
                        yield chunk
                        continue

                client = get_shared_http_client()
                files = {
                    "ref_audio": ("ref_audio.wav", audio_data, "audio/wav")
                }
                data = {
                    "ref_text": text_ref,
                    "gen_text": sentence,
                    "model_type": kwargs.get("model_type", "F5-TTS"),
                    "remove_silence": str(kwargs.get("remove_silence", False)).lower(),
                    "cross_fade_duration": str(kwargs.get("cross_fade_duration", 0.15)),
                    "speed": str(kwargs.get("speed", 1.0)),
                    "nfe_step": str(kwargs.get("nfe_step", 32)),
                    "cfg_strength": str(kwargs.get("cfg_strength", 2)),
                    "seed": str(kwargs.get("seed", -1))
                }

                response = await client.post(
                    f"{self._remote_url}/tts/",
                    files=files,
                    data=data
                )
                response.raise_for_status()

                audio_bytes = response.content

                chunk = {
                    "text_segment": sentence,
                    "audio_data": audio_bytes,
                    "chunk_index": i,
                    "is_final": i == len(sentences) - 1
                }

                if on_chunk and audio_bytes:
                    on_chunk(sentence, audio_bytes)

                yield chunk

            except Exception as e:
                logger.error(f"TTS stream error for sentence {i}: {e}")
                yield {
                    "text_segment": sentence,
                    "audio_data": None,
                    "chunk_index": i,
                    "is_final": i == len(sentences) - 1,
                    "error": str(e)
                }

    async def synthesize_with_emotions(
        self,
        text: str,
        **kwargs
    ) -> bytes:
        segments = extract_emotions_with_text(text)

        if not segments:
            return await self.synthesize(text, **kwargs)

        audio_segments: list[bytes] = []
        current_emotion = "normal"

        for segment in segments:
            if segment["type"] == "emotion":
                current_emotion = segment["emotion"]
                continue

            if segment["type"] == "sleep":
                silence = self._generate_silence(segment["duration_ms"])
                audio_segments.append(silence)
                continue

            if segment["type"] == "text":
                text_segment = segment["content"]
                if not text_segment.strip():
                    continue

                voice_config = self.get_emotion_voice(current_emotion)
                ref_audio = voice_config.get("ref_audio", self._ref_audio_path)
                ref_text = voice_config.get("ref_text", self._ref_text)

                if not ref_audio:
                    ref_audio = self._ref_audio_path
                if not ref_text:
                    ref_text = self._ref_text

                if not ref_audio or not ref_text:
                    raise ValueError(
                        f"TTS requires reference audio and text for emotion '{current_emotion}'."
                    )

                audio_data = await self._load_emotion_audio(current_emotion)

                if self._mode == "embedded":
                    from f5_tts.api import get_f5tts
                    if get_f5tts() is not None:
                        seg_bytes = await self._synthesize_embedded(
                            text_segment, ref_audio, ref_text,
                            kwargs.get("speed", self._speed),
                            kwargs.get("cross_fade_duration", self._cross_fade_duration),
                            **kwargs
                        )
                        audio_segments.append(seg_bytes)
                        continue

                client = get_shared_http_client()
                files = {
                    "ref_audio": ("ref_audio.wav", audio_data, "audio/wav")
                }
                data = {
                    "ref_text": ref_text,
                    "gen_text": text_segment,
                    "model_type": kwargs.get("model_type", "F5-TTS"),
                    "remove_silence": str(kwargs.get("remove_silence", False)).lower(),
                    "cross_fade_duration": str(kwargs.get("cross_fade_duration", 0.15)),
                    "speed": str(kwargs.get("speed", 1.0)),
                    "nfe_step": str(kwargs.get("nfe_step", 32)),
                    "cfg_strength": str(kwargs.get("cfg_strength", 2)),
                    "seed": str(kwargs.get("seed", -1))
                }

                response = await client.post(
                    f"{self._remote_url}/tts/",
                    files=files,
                    data=data
                )
                response.raise_for_status()
                audio_segments.append(response.content)

        if not audio_segments:
            return b""

        if len(audio_segments) == 1:
            return audio_segments[0]

        return await self._concatenate_audio(audio_segments)

    async def synthesize_stream_with_emotions(
        self,
        text: str,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        segments = parse_text_with_emotions(text)

        effect_segments = []
        for seg in segments:
            if seg["type"] == "text":
                effect_result = self._effect_parser.parse_text_with_effects(seg["content"])
                effect_segments.extend(effect_result)
            else:
                effect_segments.append(seg)

        segments = effect_segments

        if not segments:
            return

        chunk_index = 0
        current_emotion = "normal"

        for segment in segments:
            if segment["type"] == "emotion":
                current_emotion = segment["emotion"]
                continue

            if segment["type"] == "sound":
                effect_name = segment["name"]
                audio_data = self._load_effect_audio(effect_name)

                if audio_data:
                    chunk = {
                        "text_segment": f"（{effect_name}）",
                        "audio_data": audio_data,
                        "chunk_index": chunk_index,
                        "is_final": False,
                        "emotion": None,
                        "is_effect": True,
                        "effect_name": effect_name
                    }

                    if on_chunk:
                        on_chunk(f"（{effect_name}）", audio_data)

                    yield chunk
                    chunk_index += 1
                continue

            if segment["type"] == "sleep":
                silence = self._generate_silence(segment["duration_ms"])
                chunk = {
                    "text_segment": "",
                    "audio_data": silence,
                    "chunk_index": chunk_index,
                    "is_final": False,
                    "emotion": current_emotion,
                    "is_effect": False,
                    "is_sleep": True,
                    "sleep_duration_ms": segment["duration_ms"]
                }
                yield chunk
                chunk_index += 1
                continue

            if segment["type"] == "text":
                text_content = segment["content"]
                if not text_content.strip():
                    continue

                sentences = split_text_by_sentences(text_content)

                voice_config = self.get_emotion_voice(current_emotion)
                ref_text = voice_config.get("ref_text", self._ref_text)

                if not ref_text:
                    ref_text = self._ref_text

                if not ref_text:
                    yield {
                        "text_segment": text_content,
                        "audio_data": None,
                        "chunk_index": chunk_index,
                        "is_final": True,
                        "emotion": current_emotion,
                        "is_effect": False,
                        "error": "TTS requires reference text."
                    }
                    return

                try:
                    audio_data = await self._load_emotion_audio(current_emotion)
                except ValueError as e:
                    yield {
                        "text_segment": text_content,
                        "audio_data": None,
                        "chunk_index": chunk_index,
                        "is_final": True,
                        "emotion": current_emotion,
                        "is_effect": False,
                        "error": str(e)
                    }
                    return

                for sentence in sentences:
                    if not sentence.strip():
                        continue

                    try:
                        if self._mode == "embedded":
                            from f5_tts.api import get_f5tts
                            if get_f5tts() is not None:
                                voice_config = self.get_emotion_voice(current_emotion)
                                ref_audio_path = voice_config.get("ref_audio", self._ref_audio_path)
                                audio_bytes = await self._synthesize_embedded(
                                    sentence, ref_audio_path, ref_text,
                                    kwargs.get("speed", self._speed),
                                    kwargs.get("cross_fade_duration", self._cross_fade_duration),
                                    **kwargs
                                )
                                chunk = {
                                    "text_segment": sentence,
                                    "audio_data": audio_bytes,
                                    "chunk_index": chunk_index,
                                    "is_final": False,
                                    "emotion": current_emotion,
                                    "is_effect": False
                                }
                                if on_chunk and audio_bytes:
                                    on_chunk(sentence, audio_bytes)
                                yield chunk
                                chunk_index += 1
                                continue

                        client = get_shared_http_client()
                        files = {
                            "ref_audio": ("ref_audio.wav", audio_data, "audio/wav")
                        }
                        data = {
                            "ref_text": ref_text,
                            "gen_text": sentence,
                            "model_type": kwargs.get("model_type", "F5-TTS"),
                            "remove_silence": str(kwargs.get("remove_silence", False)).lower(),
                            "cross_fade_duration": str(kwargs.get("cross_fade_duration", 0.15)),
                            "speed": str(kwargs.get("speed", 1.0)),
                            "nfe_step": str(kwargs.get("nfe_step", 32)),
                            "cfg_strength": str(kwargs.get("cfg_strength", 2)),
                            "seed": str(kwargs.get("seed", -1))
                        }

                        response = await client.post(
                            f"{self._remote_url}/tts/",
                            files=files,
                            data=data
                        )
                        response.raise_for_status()

                        audio_bytes = response.content

                        chunk = {
                            "text_segment": sentence,
                            "audio_data": audio_bytes,
                            "chunk_index": chunk_index,
                            "is_final": False,
                            "emotion": current_emotion,
                            "is_effect": False
                        }

                        if on_chunk and audio_bytes:
                            on_chunk(sentence, audio_bytes)

                        yield chunk
                        chunk_index += 1

                    except Exception as e:
                        logger.error(f"TTS stream error for sentence: {e}")
                        yield {
                            "text_segment": sentence,
                            "audio_data": None,
                            "chunk_index": chunk_index,
                            "is_final": False,
                            "emotion": current_emotion,
                            "is_effect": False,
                            "error": str(e)
                        }
                        chunk_index += 1

        yield {
            "text_segment": "",
            "audio_data": None,
            "chunk_index": chunk_index,
            "is_final": True,
            "emotion": current_emotion,
            "is_effect": False
        }

    async def get_voices(self) -> list[dict[str, Any]]:
        return [{"id": "default", "name": "Default Voice"}]

    def get_emotion_voice(self, emotion: str) -> dict[str, str]:
        if emotion in self._emotion_voices:
            return self._emotion_voices[emotion]
        if "normal" in self._emotion_voices:
            return self._emotion_voices["normal"]
        return {
            "ref_audio": self._ref_audio_path,
            "ref_text": self._ref_text
        }

    async def _load_emotion_audio(self, emotion: str) -> bytes:
        if emotion in self._emotion_audio_cache:
            return self._emotion_audio_cache[emotion]

        voice_config = self.get_emotion_voice(emotion)
        ref_audio = voice_config.get("ref_audio", "")

        if not ref_audio:
            return await self._load_ref_audio()

        audio_path = self._resolve_audio_path(ref_audio)

        if not audio_path or not audio_path.exists():
            logger.warning(f"Emotion audio file not found: {ref_audio}, using default")
            return await self._load_ref_audio()

        with open(audio_path, "rb") as f:
            audio_data = f.read()

        self._emotion_audio_cache[emotion] = audio_data
        return audio_data

    def _load_effect_audio(self, effect_name: str) -> bytes | None:
        return self._effect_parser._load_effect(effect_name)

    def _generate_silence(self, duration_ms: int) -> bytes:
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

    async def _concatenate_audio(self, audio_segments: list[bytes]) -> bytes:
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

    async def health_check(self) -> bool:
        try:
            client = get_shared_http_client()
            response = await client.get(f"{self._remote_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"TTS health check failed: {e}")
            return False


_tts_service: Optional[TTSService] = None


def _load_emotion_voices(emotion_refs_dir: str) -> dict:
    import json
    from pathlib import Path
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


def get_tts_service() -> TTSService:
    global _tts_service
    if _tts_service is None:
        from server.config import get_settings
        settings = get_settings()
        _tts_service = TTSService(
            mode=settings.tts.mode,
            model_dir=settings.tts.model_dir,
            device=settings.tts.device,
            remote_url=settings.tts.remote_url,
            ref_audio_path=settings.tts.ref_audio_path,
            ref_text=settings.tts.ref_text,
            speed=settings.tts.speed,
            cross_fade_duration=settings.tts.cross_fade_duration,
            emotion_voices=_load_emotion_voices(settings.tts.emotion_refs_dir) if settings.tts.emotion_enabled else {},
            effects_dir=settings.tts.transitions_dir if settings.tts.effects_enabled else None,
            voice_refs_dir=settings.tts.emotion_refs_dir if settings.tts.emotion_enabled else None,
            gateway_url=settings.tts.remote_url,
            use_triton=(settings.tts.mode == "triton"),
        )
    return _tts_service
