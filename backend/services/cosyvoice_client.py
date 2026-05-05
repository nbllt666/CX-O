"""
CosyVoice 客户端
作为情感参考音频生成器，为 F5-TTS 提供情感参考音频
支持生成 64 个参考音频（8 情感 + 56 过渡）
使用 CosyVoice FastAPI 服务端 API
"""
from __future__ import annotations

import asyncio
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger(__name__)


class CosyVoiceMode(str, Enum):
    ZERO_SHOT = "zero_shot"
    CROSS_LINGUAL = "cross_lingual"
    INSTRUCT = "instruct"
    INSTRUCT2 = "instruct2"


EMOTION_INSTRUCT_TEMPLATES: dict[str, str] = {
    "normal": "Speak naturally and calmly with a neutral tone.",
    "happy": "Speak with happiness and joy, sounding cheerful and upbeat.",
    "sad": "Speak with sadness, sounding melancholic, soft and slow.",
    "angry": "Speak with anger and frustration, sounding intense and firm.",
    "surprised": "Speak with surprise and amazement, sounding excited.",
    "tender": "Speak tenderly and gently, with warmth and care.",
    "fearful": "Speak with fear and nervousness, sounding shaky.",
    "disgusted": "Speak with disgust and aversion, sounding repulsed.",
}

EMOTION_MAP: dict[str, str] = {
    "normal": "normal",
    "happy": "happy",
    "sad": "sad",
    "angry": "angry",
    "surprised": "surprised",
    "tender": "tender",
    "fearful": "fearful",
    "disgusted": "disgusted",
    "joy": "happy",
    "sadness": "sad",
    "anger": "angry",
    "surprise": "surprised",
    "fear": "fearful",
    "disgust": "disgusted",
    "neutral": "normal",
}

ALL_EMOTIONS: list[str] = list(EMOTION_INSTRUCT_TEMPLATES.keys())

TRANSITION_TEMPLATES: dict[tuple[str, str], str] = {
    ("happy", "sad"): "Transition from happy to sad, gradually becoming melancholic and soft.",
    ("sad", "happy"): "Transition from sad to happy, gradually cheering up and becoming upbeat.",
    ("normal", "happy"): "Transition from neutral to happy, becoming more cheerful and energetic.",
    ("happy", "normal"): "Transition from happy to neutral, calming down to a natural tone.",
    ("normal", "sad"): "Transition from neutral to sad, becoming melancholic and soft.",
    ("sad", "normal"): "Transition from sad to neutral, recovering to a natural tone.",
    ("angry", "normal"): "Transition from angry to neutral, calming down from frustration.",
    ("normal", "angry"): "Transition from neutral to angry, becoming intense and frustrated.",
    ("tender", "happy"): "Transition from tender to happy, becoming more cheerful while keeping warmth.",
    ("happy", "tender"): "Transition from happy to tender, becoming softer and more gentle.",
    ("surprised", "normal"): "Transition from surprised to neutral, settling down from excitement.",
    ("normal", "surprised"): "Transition from neutral to surprised, becoming amazed and excited.",
}


class CosyVoiceError(Exception):
    def __init__(self, message: str, status_code: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class CosyVoiceClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:50000",
        timeout: float = 120.0,
        default_mode: CosyVoiceMode = CosyVoiceMode.INSTRUCT2,
        default_spk_id: str = "中文女"
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._default_mode = default_mode
        self._default_spk_id = default_spk_id
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _handle_error_response(self, response: httpx.Response, operation: str) -> None:
        try:
            error_data = response.json()
            detail = error_data.get("detail", error_data.get("error", str(error_data)))
        except Exception:
            detail = response.text or f"HTTP {response.status_code}"

        error_msg = f"CosyVoice {operation} failed: {detail}"
        logger.error(error_msg)
        raise CosyVoiceError(error_msg, status_code=response.status_code, detail=detail)

    def _map_emotion(self, emotion: str) -> str:
        return EMOTION_MAP.get(emotion.lower(), "normal")

    def get_emotion_instruct(self, emotion: str) -> str:
        mapped_emotion = self._map_emotion(emotion)
        return EMOTION_INSTRUCT_TEMPLATES.get(mapped_emotion, EMOTION_INSTRUCT_TEMPLATES["normal"])

    def get_transition_instruct(self, from_emotion: str, to_emotion: str) -> str:
        from_mapped = self._map_emotion(from_emotion)
        to_mapped = self._map_emotion(to_emotion)

        if from_mapped == to_mapped:
            return EMOTION_INSTRUCT_TEMPLATES[to_mapped]

        key = (from_mapped, to_mapped)
        if key in TRANSITION_TEMPLATES:
            return TRANSITION_TEMPLATES[key]

        return f"Transition from {from_mapped} to {to_mapped}, {EMOTION_INSTRUCT_TEMPLATES[to_mapped]}"

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get(f"{self._base_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"CosyVoice health check failed: {e}")
            return False

    async def get_health_status(self) -> dict:
        try:
            client = await self._get_client()
            response = await client.get(f"{self._base_url}/health")
            if response.status_code == 200:
                return response.json()
            return {"status": "error", "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def synthesize_zero_shot(
        self,
        text: str,
        ref_audio: bytes | str | Path,
        ref_text: str
    ) -> bytes:
        client = await self._get_client()

        if isinstance(ref_audio, bytes):
            files = {"prompt_wav": ("prompt.wav", ref_audio, "audio/wav")}
        else:
            audio_path = Path(ref_audio)
            if not audio_path.exists():
                raise ValueError(f"Reference audio file not found: {ref_audio}")
            with open(audio_path, "rb") as f:
                files = {"prompt_wav": ("prompt.wav", f.read(), "audio/wav")}

        data = {
            "tts_text": text,
            "prompt_text": ref_text
        }

        response = await client.post(
            f"{self._base_url}/inference_zero_shot",
            data=data,
            files=files
        )

        if response.status_code != 200:
            self._handle_error_response(response, "zero_shot synthesis")

        return response.content

    async def synthesize_instruct(
        self,
        text: str,
        spk_id: str | None = None,
        instruct_text: str | None = None
    ) -> bytes:
        client = await self._get_client()

        data = {
            "tts_text": text,
            "spk_id": spk_id or self._default_spk_id,
            "instruct_text": instruct_text or "Speak naturally."
        }

        response = await client.post(
            f"{self._base_url}/inference_instruct",
            data=data
        )

        if response.status_code != 200:
            self._handle_error_response(response, "instruct synthesis")

        return response.content

    async def synthesize_instruct2(
        self,
        text: str,
        ref_audio: bytes | str | Path,
        instruct_text: str
    ) -> bytes:
        client = await self._get_client()

        if isinstance(ref_audio, bytes):
            files = {"prompt_wav": ("prompt.wav", ref_audio, "audio/wav")}
        else:
            audio_path = Path(ref_audio)
            if not audio_path.exists():
                raise ValueError(f"Reference audio file not found: {ref_audio}")
            with open(audio_path, "rb") as f:
                files = {"prompt_wav": ("prompt.wav", f.read(), "audio/wav")}

        data = {
            "tts_text": text,
            "instruct_text": instruct_text
        }

        response = await client.post(
            f"{self._base_url}/inference_instruct2",
            data=data,
            files=files
        )

        if response.status_code != 200:
            self._handle_error_response(response, "instruct2 synthesis")

        return response.content

    async def synthesize_cross_lingual(
        self,
        text: str,
        ref_audio: bytes | str | Path
    ) -> bytes:
        client = await self._get_client()

        if isinstance(ref_audio, bytes):
            files = {"prompt_wav": ("prompt.wav", ref_audio, "audio/wav")}
        else:
            audio_path = Path(ref_audio)
            if not audio_path.exists():
                raise ValueError(f"Reference audio file not found: {ref_audio}")
            with open(audio_path, "rb") as f:
                files = {"prompt_wav": ("prompt.wav", f.read(), "audio/wav")}

        data = {
            "tts_text": text
        }

        response = await client.post(
            f"{self._base_url}/inference_cross_lingual",
            data=data,
            files=files
        )

        if response.status_code != 200:
            self._handle_error_response(response, "cross_lingual synthesis")

        return response.content

    async def synthesize(
        self,
        text: str,
        emotion: str = "normal",
        ref_audio: bytes | str | Path | None = None,
        ref_text: str | None = None,
        mode: CosyVoiceMode | None = None
    ) -> bytes:
        synthesis_mode = mode or self._default_mode
        instruct_text = self.get_emotion_instruct(emotion)

        if synthesis_mode == CosyVoiceMode.INSTRUCT2:
            if ref_audio is None:
                raise ValueError("instruct2 mode requires ref_audio")
            return await self.synthesize_instruct2(text, ref_audio, instruct_text)

        elif synthesis_mode == CosyVoiceMode.ZERO_SHOT:
            if ref_audio is None or ref_text is None:
                raise ValueError("zero_shot mode requires ref_audio and ref_text")
            return await self.synthesize_zero_shot(text, ref_audio, ref_text)

        elif synthesis_mode == CosyVoiceMode.INSTRUCT:
            return await self.synthesize_instruct(text, instruct_text=instruct_text)

        elif synthesis_mode == CosyVoiceMode.CROSS_LINGUAL:
            if ref_audio is None:
                raise ValueError("cross_lingual mode requires ref_audio")
            return await self.synthesize_cross_lingual(text, ref_audio)

        else:
            raise ValueError(f"Unknown mode: {synthesis_mode}")

    async def generate_transition_audio(
        self,
        from_emotion: str,
        to_emotion: str,
        ref_audio: bytes | str | Path,
        transition_text: str = "嗯，"
    ) -> bytes:
        transition_instruct = self.get_transition_instruct(from_emotion, to_emotion)
        logger.info(f"Generating transition audio: {from_emotion} -> {to_emotion}")

        return await self.synthesize_instruct2(
            text=transition_text,
            ref_audio=ref_audio,
            instruct_text=transition_instruct
        )

    async def synthesize_with_emotion(
        self,
        text: str,
        emotion: str,
        ref_audio: bytes | str | Path,
        ref_text: str | None = None
    ) -> bytes:
        instruct_text = self.get_emotion_instruct(emotion)
        logger.info(f"Synthesizing with emotion: {emotion}")

        return await self.synthesize_instruct2(
            text=text,
            ref_audio=ref_audio,
            instruct_text=instruct_text
        )

    async def generate_emotion_ref_audio(
        self,
        emotion: str,
        ref_audio: bytes | str | Path,
        sample_text: str = "这是参考音频样本。"
    ) -> bytes:
        instruct_text = self.get_emotion_instruct(emotion)
        logger.info(f"Generating emotion reference audio for: {emotion}")

        return await self.synthesize_instruct2(
            text=sample_text,
            ref_audio=ref_audio,
            instruct_text=instruct_text
        )

    async def generate_transition_ref_audio(
        self,
        from_emotion: str,
        to_emotion: str,
        ref_audio: bytes | str | Path,
        sample_text: str = "嗯，"
    ) -> bytes:
        transition_instruct = self.get_transition_instruct(from_emotion, to_emotion)
        logger.info(f"Generating transition reference audio: {from_emotion} -> {to_emotion}")

        return await self.synthesize_instruct2(
            text=sample_text,
            ref_audio=ref_audio,
            instruct_text=transition_instruct
        )

    async def generate_all_emotion_refs(
        self,
        ref_audio: bytes | str | Path,
        output_dir: str | Path,
        sample_text: str = "这是参考音频样本。",
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> dict[str, Path]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        results: dict[str, Path] = {}
        total = len(ALL_EMOTIONS)

        for i, emotion in enumerate(ALL_EMOTIONS):
            if progress_callback:
                progress_callback(i + 1, total, f"生成情感参考音频: {emotion}")

            output_file = output_path / f"{emotion}.wav"

            if output_file.exists():
                logger.info(f"Skipping existing emotion ref: {emotion}")
                results[emotion] = output_file
                continue

            try:
                audio_data = await self.generate_emotion_ref_audio(
                    emotion=emotion,
                    ref_audio=ref_audio,
                    sample_text=sample_text
                )

                with open(output_file, "wb") as f:
                    f.write(audio_data)

                results[emotion] = output_file
                logger.info(f"Generated emotion ref audio: {emotion} -> {output_file}")

            except Exception as e:
                logger.error(f"Failed to generate emotion ref {emotion}: {e}")

        return results

    async def generate_all_transition_refs(
        self,
        ref_audio: bytes | str | Path,
        output_dir: str | Path,
        sample_text: str = "嗯，",
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> dict[tuple[str, str], Path]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        results: dict[tuple[str, str], Path] = {}
        transitions: list[tuple[str, str]] = []

        for from_emotion in ALL_EMOTIONS:
            for to_emotion in ALL_EMOTIONS:
                if from_emotion != to_emotion:
                    transitions.append((from_emotion, to_emotion))

        total = len(transitions)

        for i, (from_emotion, to_emotion) in enumerate(transitions):
            if progress_callback:
                progress_callback(i + 1, total, f"生成过渡参考音频: {from_emotion} -> {to_emotion}")

            output_file = output_path / f"{from_emotion}_to_{to_emotion}.wav"

            if output_file.exists():
                logger.info(f"Skipping existing transition ref: {from_emotion} -> {to_emotion}")
                results[(from_emotion, to_emotion)] = output_file
                continue

            try:
                audio_data = await self.generate_transition_ref_audio(
                    from_emotion=from_emotion,
                    to_emotion=to_emotion,
                    ref_audio=ref_audio,
                    sample_text=sample_text
                )

                with open(output_file, "wb") as f:
                    f.write(audio_data)

                results[(from_emotion, to_emotion)] = output_file
                logger.info(f"Generated transition ref audio: {from_emotion} -> {to_emotion}")

            except Exception as e:
                logger.error(f"Failed to generate transition ref {from_emotion} -> {to_emotion}: {e}")

        return results

    async def generate_all_refs(
        self,
        ref_audio: bytes | str | Path,
        emotions_dir: str | Path,
        transitions_dir: str | Path,
        sample_text: str = "这是参考音频样本。",
        transition_text: str = "嗯，",
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> dict:
        emotion_results = await self.generate_all_emotion_refs(
            ref_audio=ref_audio,
            output_dir=emotions_dir,
            sample_text=sample_text,
            progress_callback=lambda c, t, m: progress_callback(c, t, m) if progress_callback else None
        )

        transition_results = await self.generate_all_transition_refs(
            ref_audio=ref_audio,
            output_dir=transitions_dir,
            sample_text=transition_text,
            progress_callback=lambda c, t, m: progress_callback(c + 8, t + 8, m) if progress_callback else None
        )

        return {
            "emotions": emotion_results,
            "transitions": transition_results,
            "total": len(emotion_results) + len(transition_results)
        }


def get_supported_emotions() -> list[str]:
    return ALL_EMOTIONS


def get_emotion_instruct(emotion: str) -> str:
    mapped = EMOTION_MAP.get(emotion.lower(), "normal")
    return EMOTION_INSTRUCT_TEMPLATES.get(mapped, EMOTION_INSTRUCT_TEMPLATES["normal"])


def get_transition_instruct(from_emotion: str, to_emotion: str) -> str:
    from_mapped = EMOTION_MAP.get(from_emotion.lower(), "normal")
    to_mapped = EMOTION_MAP.get(to_emotion.lower(), "normal")

    if from_mapped == to_mapped:
        return EMOTION_INSTRUCT_TEMPLATES[to_mapped]

    key = (from_mapped, to_mapped)
    if key in TRANSITION_TEMPLATES:
        return TRANSITION_TEMPLATES[key]

    return f"Transition from {from_mapped} to {to_mapped}, {EMOTION_INSTRUCT_TEMPLATES[to_mapped]}"


_client_instance: CosyVoiceClient | None = None


def get_cosyvoice_client(
    base_url: str = "http://127.0.0.1:50000",
    timeout: float = 120.0,
    default_mode: CosyVoiceMode = CosyVoiceMode.INSTRUCT2
) -> CosyVoiceClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = CosyVoiceClient(
            base_url=base_url,
            timeout=timeout,
            default_mode=default_mode
        )
    return _client_instance
