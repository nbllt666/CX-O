"""
TTS 客户端
支持 F5-TTS 和 CosyVoice 双引擎
支持情感过渡音频生成
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

import httpx

from .emotion_parser import extract_emotions_with_text, parse_text_with_emotions
from .effect_parser import EffectParser

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


class TTSClient:
    def __init__(
        self,
        base_url: str,
        ref_audio_path: str = "",
        ref_text: str = "",
        timeout: float = 120.0,
        emotion_voices: dict[str, dict[str, str]] | None = None,
        effects_dir: str | Path | None = None,
        voice_refs_dir: str | Path | None = None,
        gateway_url: str | None = None,
        use_triton: bool = False,
        engine: str = "f5-tts",
        cosyvoice_url: str | None = None,
        transition_enabled: bool = True,
        transition_text: str = "嗯，"
    ):
        self._base_url = base_url.rstrip("/")
        self._gateway_url = gateway_url.rstrip("/") if gateway_url else None
        self._use_triton = use_triton
        self._timeout = timeout
        self._ref_audio_path = ref_audio_path
        self._ref_text = ref_text
        self._ref_audio_data: bytes | None = None
        self._client: httpx.AsyncClient | None = None
        self._emotion_voices = emotion_voices or {}
        self._effect_parser = EffectParser(effects_dir)
        self._emotion_audio_cache: dict[str, bytes] = {}
        self._voice_refs_dir = Path(voice_refs_dir) if voice_refs_dir else Path(__file__).parent.parent / "data" / "voice_refs"
        self._engine = engine.lower()
        self._cosyvoice_url = cosyvoice_url
        self._cosyvoice_client = None
        self._transition_enabled = transition_enabled
        self._transition_text = transition_text
        self._transition_audio_cache: dict[tuple[str, str], bytes] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

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

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._cosyvoice_client:
            await self._cosyvoice_client.close()
            self._cosyvoice_client = None

    async def _get_cosyvoice_client(self):
        if self._cosyvoice_client is None and self._cosyvoice_url:
            from .cosyvoice_client import CosyVoiceClient, CosyVoiceMode
            self._cosyvoice_client = CosyVoiceClient(
                base_url=self._cosyvoice_url,
                timeout=self._timeout
            )
        return self._cosyvoice_client

    async def health_check(self) -> bool:
        if self._engine == "cosyvoice" and self._cosyvoice_url:
            client = await self._get_cosyvoice_client()
            if client:
                return await client.health_check()
        try:
            client = await self._get_client()
            response = await client.get(f"{self._base_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"TTS health check failed: {e}")
            return False

    async def generate_transition_audio(
        self,
        from_emotion: str,
        to_emotion: str,
        ref_audio: bytes | None = None
    ) -> bytes | None:
        if not self._transition_enabled:
            return None

        cache_key = (from_emotion, to_emotion)
        if cache_key in self._transition_audio_cache:
            return self._transition_audio_cache[cache_key]

        if self._engine == "cosyvoice" and self._cosyvoice_url:
            client = await self._get_cosyvoice_client()
            if client:
                try:
                    audio_data = ref_audio or await self._load_ref_audio()
                    transition_audio = await client.generate_transition_audio(
                        from_emotion=from_emotion,
                        to_emotion=to_emotion,
                        ref_audio=audio_data,
                        transition_text=self._transition_text
                    )
                    self._transition_audio_cache[cache_key] = transition_audio
                    logger.info(f"Generated transition audio: {from_emotion} -> {to_emotion}")
                    return transition_audio
                except Exception as e:
                    logger.error(f"Failed to generate transition audio: {e}")
                    return None
        return None

    async def synthesize(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        ref_audio: str | None = None,
        **kwargs
    ) -> bytes:
        client = await self._get_client()
        
        # 获取传入的参数或从 kwargs 中获取
        ref_audio_data = ref_audio or kwargs.get("ref_audio")
        ref_text_data = ref_text or kwargs.get("ref_text")
        
        audio_path = ref_audio_path or self._ref_audio_path
        text_ref = ref_text_data or self._ref_text
        
        if ref_audio_data:
            try:
                audio_data = base64.b64decode(ref_audio_data)
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
        
        # 使用 Triton Gateway API
        if self._use_triton and self._gateway_url:
            return await self._synthesize_triton(client, text, audio_data, text_ref, **kwargs)
        else:
            return await self._synthesize_local(client, text, audio_data, text_ref, **kwargs)
    
    async def _synthesize_triton(
        self,
        client: httpx.AsyncClient,
        text: str,
        audio_data: bytes,
        ref_text: str,
        **kwargs
    ) -> bytes:
        """使用 Triton Gateway API 进行 TTS 合成"""
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
    
    async def _synthesize_local(
        self,
        client: httpx.AsyncClient,
        text: str,
        audio_data: bytes,
        ref_text: str,
        **kwargs
    ) -> bytes:
        """使用本地 F5-TTS API 进行 TTS 合成"""
        files = {
            "ref_audio": ("ref_audio.wav", audio_data, "audio/wav")
        }
        data = {
            "ref_text": ref_text,
            "gen_text": text,
            "model_type": kwargs.get("model_type", "F5-TTS"),
            "remove_silence": str(kwargs.get("remove_silence", False)).lower(),
            "cross_fade_duration": str(kwargs.get("cross_fade_duration", 0.15)),
            "speed": str(kwargs.get("speed", 1.0)),
            "nfe_step": str(kwargs.get("nfe_step", 32)),
            "cfg_strength": str(kwargs.get("cfg_strength", 2)),
            "seed": str(kwargs.get("seed", -1))
        }
        
        response = await client.post(
            f"{self._base_url}/tts/",
            files=files,
            data=data
        )
        response.raise_for_status()
        return response.content

    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        on_chunk: Callable[[str, bytes], None] | None = None,
        **kwargs
    ) -> AsyncGenerator[dict[str, Any], None]:
        sentences = split_text_by_sentences(text)
        client = await self._get_client()
        
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
                    f"{self._base_url}/tts/",
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

        emotion_ref_path = self._voice_refs_dir / "emotions" / f"{emotion}.wav"
        if emotion_ref_path.exists():
            logger.info(f"Loading pre-generated emotion ref: {emotion}")
            with open(emotion_ref_path, "rb") as f:
                audio_data = f.read()
            self._emotion_audio_cache[emotion] = audio_data
            return audio_data

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

    async def _load_transition_audio(self, from_emotion: str, to_emotion: str) -> bytes | None:
        cache_key = (from_emotion, to_emotion)
        if cache_key in self._transition_audio_cache:
            return self._transition_audio_cache[cache_key]

        transition_ref_path = self._voice_refs_dir / "transitions" / f"{from_emotion}_to_{to_emotion}.wav"
        if transition_ref_path.exists():
            logger.info(f"Loading pre-generated transition ref: {from_emotion} -> {to_emotion}")
            with open(transition_ref_path, "rb") as f:
                audio_data = f.read()
            self._transition_audio_cache[cache_key] = audio_data
            return audio_data

        return None
    
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
    
    def _load_effect_audio(self, effect_name: str) -> bytes | None:
        effect_path = self._effect_parser.get_effect_path(effect_name)
        if effect_path is None or not effect_path.exists():
            logger.warning(f"Effect file not found: {effect_name}")
            return None
        
        with open(effect_path, "rb") as f:
            return f.read()
    
    async def synthesize_with_emotions(
        self,
        text: str,
        **kwargs
    ) -> bytes:
        emotion_text_pairs = extract_emotions_with_text(text)
        
        if not emotion_text_pairs:
            return await self.synthesize(text, **kwargs)
        
        audio_segments: list[bytes] = []
        client = await self._get_client()
        
        for emotion, text_segment in emotion_text_pairs:
            if not text_segment.strip():
                continue
            
            voice_config = self.get_emotion_voice(emotion)
            ref_audio = voice_config.get("ref_audio", self._ref_audio_path)
            ref_text = voice_config.get("ref_text", self._ref_text)
            
            if not ref_audio:
                ref_audio = self._ref_audio_path
            if not ref_text:
                ref_text = self._ref_text
            
            if not ref_audio or not ref_text:
                raise ValueError(
                    f"TTS requires reference audio and text for emotion '{emotion}'."
                )
            
            audio_data = await self._load_emotion_audio(emotion)
            
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
                f"{self._base_url}/tts/",
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
        
        client = await self._get_client()
        chunk_index = 0
        current_emotion = "normal"
        previous_emotion = None
        
        for segment in segments:
            if segment["type"] == "emotion":
                previous_emotion = current_emotion
                current_emotion = segment["emotion"]

                if previous_emotion and previous_emotion != current_emotion and self._transition_enabled:
                    transition_audio = await self._load_transition_audio(
                        from_emotion=previous_emotion,
                        to_emotion=current_emotion
                    )
                    if not transition_audio:
                        transition_audio = await self.generate_transition_audio(
                            from_emotion=previous_emotion,
                            to_emotion=current_emotion
                        )
                    if transition_audio:
                        chunk = {
                            "text_segment": "",
                            "audio_data": transition_audio,
                            "chunk_index": chunk_index,
                            "is_final": False,
                            "emotion": None,
                            "is_effect": False,
                            "is_transition": True,
                            "from_emotion": previous_emotion,
                            "to_emotion": current_emotion
                        }
                        if on_chunk:
                            on_chunk("[transition]", transition_audio)
                        yield chunk
                        chunk_index += 1
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
                            f"{self._base_url}/tts/",
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
