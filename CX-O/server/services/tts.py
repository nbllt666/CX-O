import asyncio
import base64
import logging
import os
import re
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

import httpx
import numpy as np
import torch
import wave

logger = logging.getLogger(__name__)


def split_text_by_sentences(text: str, max_length: int = 200) -> list[str]:
    sentence_endings = re.compile(r"([。！？.!?]+)")
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
    _instance: Optional["TTSService"] = None

    def __init__(
        self,
        model_dir: str = "F5-TTS",
        device: str = "cuda",
        ref_audio_path: str = "",
        ref_text: str = "",
        speed: float = 1.0
    ):
        self.model_dir = model_dir
        self.device = device if torch.cuda.is_available() else "cpu"
        self.ref_audio_path = ref_audio_path
        self.ref_text = ref_text
        self.speed = speed
        self.model = None
        self.ref_audio_data: Optional[bytes] = None
        self._emotion_voices: dict[str, dict[str, str]] = {}
        self._emotion_audio_cache: dict[str, bytes] = {}
        self._voice_refs_dir = Path(__file__).parent.parent / "data" / "voice_refs"

    @classmethod
    def get_instance(cls) -> "TTSService":
        if cls._instance is None:
            from server.config import get_config
            config = get_config()
            cls._instance = cls(
                model_dir=config.tts.model_dir,
                device=config.tts.device,
                ref_audio_path=config.tts.ref_audio,
                ref_text=config.tts.ref_text,
                speed=config.tts.speed
            )
        return cls._instance

    def load_model(self):
        if self.model is None:
            logger.info(f"Loading TTS model from: {self.model_dir}")
            try:
                os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
                hf_home = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hf_download")
                os.environ.setdefault("HF_HOME", hf_home)

                from f5_tts.api import F5TTS
                self.model = F5TTS()
                logger.info("TTS model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load TTS model: {e}")
                self.model = None
        return self.model

    async def _load_ref_audio(self) -> bytes:
        if self.ref_audio_data is None:
            if not self.ref_audio_path:
                raise ValueError(
                    "TTS requires reference audio. "
                    "Please provide ref_audio in request data or configure ref_audio_path in config"
                )
            if not Path(self.ref_audio_path).exists():
                raise ValueError(f"Reference audio file not found: {self.ref_audio_path}")
            with open(self.ref_audio_path, "rb") as f:
                self.ref_audio_data = f.read()
        return self.ref_audio_data

    def _resolve_audio_path(self, ref_audio: str) -> Optional[Path]:
        if not ref_audio:
            return None

        path = Path(ref_audio)
        if path.is_absolute() and path.exists():
            return path

        if path.exists():
            return path

        voice_refs_path = self._voice_refs_dir / ref_audio
        if voice_refs_path.exists():
            return voice_refs_path

        return None

    async def synthesize(
        self,
        text: str,
        ref_audio_path: Optional[str] = None,
        ref_text: Optional[str] = None,
        ref_audio: Optional[str] = None,
        **kwargs
    ) -> bytes:
        audio_data: Optional[bytes] = None

        if ref_audio:
            try:
                audio_data = base64.b64decode(ref_audio)
            except Exception as e:
                raise ValueError(f"Invalid base64 ref_audio: {e}")
        elif ref_audio_path and Path(ref_audio_path).exists():
            with open(ref_audio_path, "rb") as f:
                audio_data = f.read()
        else:
            audio_data = await self._load_ref_audio()

        text_ref = ref_text or self.ref_text
        if not text_ref:
            raise ValueError(
                "TTS requires reference text that matches the reference audio. "
                "Please provide ref_text in request data or configure it."
            )

        speed = float(kwargs.get("speed", self.speed))
        nfe_step = int(kwargs.get("nfe_step", 32))
        cfg_strength = float(kwargs.get("cfg_strength", 2))
        seed = int(kwargs.get("seed", -1))
        remove_silence = kwargs.get("remove_silence", False)
        cross_fade_duration = float(kwargs.get("cross_fade_duration", 0.15))

        model = self.load_model()
        if model is None:
            return await self._generate_mock_audio(text)

        ref_fd, ref_path = tempfile.mkstemp(suffix=".wav")
        output_fd, output_path = tempfile.mkstemp(suffix=".wav")

        try:
            with os.fdopen(ref_fd, "wb") as tmp_file:
                tmp_file.write(audio_data)

            loop = asyncio.get_event_loop()
            wav, sr, spect = await loop.run_in_executor(
                None,
                lambda: model.infer(
                    ref_file=ref_path,
                    ref_text=text_ref,
                    gen_text=text,
                    show_info=logger.info,
                    target_rms=0.1,
                    cross_fade_duration=cross_fade_duration,
                    sway_sampling_coef=-1,
                    cfg_strength=cfg_strength,
                    nfe_step=nfe_step,
                    speed=speed,
                    remove_silence=remove_silence,
                    file_wave=output_path,
                    seed=seed
                )
            )

            with open(output_path, "rb") as f:
                return f.read()

        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
            return await self._generate_mock_audio(text)
        finally:
            try:
                if os.path.exists(ref_path):
                    os.unlink(ref_path)
                if os.path.exists(output_path):
                    os.unlink(output_path)
            except Exception:
                pass

    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: Optional[str] = None,
        ref_text: Optional[str] = None,
        on_chunk: Optional[Callable[[str, bytes], None]] = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        sentences = split_text_by_sentences(text)

        audio_path = ref_audio_path or self.ref_audio_path
        text_ref = ref_text or self.ref_text

        if not audio_path:
            yield {
                "text_segment": text,
                "audio_data": None,
                "chunk_index": 0,
                "is_final": True,
                "error": "TTS requires reference audio."
            }
            return

        if not text_ref:
            yield {
                "text_segment": text,
                "audio_data": None,
                "chunk_index": 0,
                "is_final": True,
                "error": "TTS requires reference text."
            }
            return

        try:
            if ref_audio_path and Path(ref_audio_path).exists():
                with open(ref_audio_path, "rb") as f:
                    audio_data = f.read()
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
                audio_bytes = await self.synthesize(
                    sentence,
                    ref_audio_path=ref_audio_path,
                    ref_text=text_ref,
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
        from .emotion import extract_emotions_with_text

        emotion_text_pairs = extract_emotions_with_text(text)

        if not emotion_text_pairs:
            return await self.synthesize(text, **kwargs)

        audio_segments = []

        for emotion, text_segment in emotion_text_pairs:
            if not text_segment.strip():
                continue

            voice_config = self.get_emotion_voice(emotion)
            ref_audio = voice_config.get("ref_audio", self.ref_audio_path)
            ref_text = voice_config.get("ref_text", self.ref_text)

            if not ref_audio:
                ref_audio = self.ref_audio_path
            if not ref_text:
                ref_text = self.ref_text

            if not ref_audio or not ref_text:
                raise ValueError(f"TTS requires reference audio and text for emotion '{emotion}'.")

            try:
                audio_data = await self._load_emotion_audio(emotion)
                audio_bytes = await self.synthesize(
                    text_segment,
                    ref_audio_path=self._resolve_audio_path(ref_audio) or ref_audio,
                    ref_text=ref_text,
                    **kwargs
                )
                audio_segments.append(audio_bytes)
            except Exception as e:
                logger.error(f"Emotion TTS error for {emotion}: {e}")

        if not audio_segments:
            return b""

        if len(audio_segments) == 1:
            return audio_segments[0]

        return await self._concatenate_audio(audio_segments)

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

    def get_emotion_voice(self, emotion: str) -> dict[str, str]:
        if emotion in self._emotion_voices:
            return self._emotion_voices[emotion]
        if "normal" in self._emotion_voices:
            return self._emotion_voices["normal"]
        return {
            "ref_audio": self.ref_audio_path,
            "ref_text": self.ref_text
        }

    async def _concatenate_audio(self, audio_segments: list[bytes]) -> bytes:
        if not audio_segments:
            return b""

        if len(audio_segments) == 1:
            return audio_segments[0]

        def is_wav(data: bytes) -> bool:
            return len(data) > 44 and data[:4] == b'RIFF' and data[8:12] == b'WAVE'

        if all(is_wav(seg) for seg in audio_segments):
            import struct

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

    async def _generate_mock_audio(self, text: str, duration: float = 2.0) -> bytes:
        sample_rate = 24000
        num_samples = int(sample_rate * duration)
        t = np.linspace(0, duration, num_samples, endpoint=False)

        start_freq = 200
        end_freq = 800
        freq_sweep = start_freq + (end_freq - start_freq) * t / duration

        audio_data = np.zeros_like(t)
        for i, freq in enumerate(freq_sweep):
            audio_data[i] = 0.3 * np.sin(2 * np.pi * freq * t[i])

        envelope = np.ones_like(t)
        attack_time = int(0.1 * sample_rate)
        release_time = int(0.2 * sample_rate)
        envelope[:attack_time] = np.linspace(0, 1, attack_time)
        envelope[-release_time:] = np.linspace(1, 0, release_time)
        audio_data *= envelope

        audio_data = (audio_data * 32767).astype(np.int16)

        output_fd, output_path = tempfile.mkstemp(suffix=".wav")
        try:
            with wave.open(os.fdopen(output_fd, 'wb'), 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(audio_data.tobytes())

            with open(output_path, "rb") as f:
                return f.read()
        finally:
            try:
                if os.path.exists(output_path):
                    os.unlink(output_path)
            except Exception:
                pass

    async def synthesize_stream_with_emotions(
        self,
        text: str,
        on_chunk: Optional[Callable[[str, bytes], None]] = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        from .emotion import parse_text_with_emotions
        from .effect import EffectParser

        segments = parse_text_with_emotions(text)
        effect_parser = EffectParser()

        effect_segments = []
        for seg in segments:
            if seg["type"] == "text":
                effect_result = effect_parser.parse_text_with_effects(seg["content"])
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

            if segment["type"] == "text":
                text_content = segment["content"]
                if not text_content.strip():
                    continue

                sentences = split_text_by_sentences(text_content)

                voice_config = self.get_emotion_voice(current_emotion)
                ref_text = voice_config.get("ref_text", self.ref_text)

                if not ref_text:
                    ref_text = self.ref_text

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
                        audio_bytes = await self.synthesize(
                            sentence,
                            ref_audio_path=self._resolve_audio_path(voice_config.get("ref_audio", "")) or self.ref_audio_path,
                            ref_text=ref_text,
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

    def _load_effect_audio(self, effect_name: str) -> Optional[bytes]:
        from .effect import EffectParser
        effect_parser = EffectParser()
        effect_path = effect_parser.get_effect_path(effect_name)
        if effect_path is None or not effect_path.exists():
            logger.warning(f"Effect file not found: {effect_name}")
            return None

        with open(effect_path, "rb") as f:
            return f.read()

    async def health_check(self) -> dict[str, Any]:
        model_loaded = self.model is not None
        if not model_loaded:
            try:
                self.load_model()
                model_loaded = self.model is not None
            except Exception as e:
                return {"status": "unhealthy", "model_loaded": False, "error": str(e)}

        return {
            "status": "healthy" if model_loaded else "unhealthy",
            "model_loaded": model_loaded,
            "ref_audio_configured": bool(self.ref_audio_path and self.ref_text)
        }


_tts_service: Optional[TTSService] = None


def get_tts_service() -> TTSService:
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService.get_instance()
    return _tts_service
