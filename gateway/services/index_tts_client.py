"""
IndexTTS 2 客户端
支持情感控制和强度细粒度调节
IndexTTS 2 FastAPI 服务端使用 JSON 请求
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
import numpy as np

logger = logging.getLogger(__name__)


class IndexTTSError(Exception):
    def __init__(self, message: str, status_code: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


EMOTION_MAP: dict[str, str] = {
    "normal": "neutral",
    "happy": "joy",
    "sad": "sadness",
    "angry": "anger",
    "surprised": "surprise",
    "tender": "tender",
    "fearful": "fear",
    "disgusted": "disgust",
}

INDEX_EMOTIONS: set[str] = {
    "neutral", "joy", "sadness", "anger", "surprise", "tender", "fear", "disgust"
}

USER_EMOTIONS: set[str] = set(EMOTION_MAP.keys())

ALL_EMOTIONS: list[str] = list(USER_EMOTIONS)

EMOTION_INTENSITY_VALUES: list[float] = [0.2, 0.4, 0.6, 0.8, 1.0]

EMOTION_TEMPLATES: dict[str, list[tuple[str, float]]] = {
    "basic": [
        ("normal", 0.5),
        ("happy", 0.5),
        ("sad", 0.5),
        ("angry", 0.5),
    ],
    "strong": [
        ("happy", 0.8),
        ("angry", 0.8),
        ("sad", 0.8),
        ("surprised", 0.8),
    ],
    "weak": [
        ("happy", 0.2),
        ("angry", 0.2),
        ("sad", 0.2),
        ("tender", 0.2),
    ],
    "full": [
        (emotion, intensity)
        for emotion in ALL_EMOTIONS
        for intensity in EMOTION_INTENSITY_VALUES
    ],
}

EMOTION_TEXTS: dict[str, str] = {
    "normal": "这是一个平静自然的语音样本。",
    "happy": "太棒了！今天真是美好的一天，我感到非常开心！",
    "sad": "有些事情让人感到难过，心情有些低落。",
    "angry": "这真是太让人气愤了，我对此非常不满！",
    "surprised": "哇！这真是太让人意外了，完全没想到！",
    "tender": "亲爱的，我会一直陪伴在你身边，照顾你。",
    "fearful": "这个情况让我感到有些害怕和紧张。",
    "disgusted": "这种行为真是让人感到厌恶和反感。",
}

NATURAL_LANGUAGE_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r"(轻|温柔|柔和|柔软).*说", re.IGNORECASE), "tender", 0.5),
    (re.compile(r"(开心|高兴|快乐|愉快|兴奋).*说", re.IGNORECASE), "joy", 0.6),
    (re.compile(r"(激动|大喊|喊叫|愤怒|生气).*喊", re.IGNORECASE), "anger", 0.9),
    (re.compile(r"(悲伤|难过|伤心|低落).*叙述", re.IGNORECASE), "sadness", 0.7),
    (re.compile(r"(惊讶|意外|震惊|吃惊).*说", re.IGNORECASE), "surprise", 0.6),
    (re.compile(r"(害怕|恐惧|紧张|害怕).*说", re.IGNORECASE), "fear", 0.6),
    (re.compile(r"(厌恶|反感|讨厌).*说", re.IGNORECASE), "disgust", 0.6),
    (re.compile(r"平静.*说", re.IGNORECASE), "neutral", 0.3),
    (re.compile(r"自然.*说", re.IGNORECASE), "neutral", 0.2),
]


class IndexTTSClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 180.0,
        sample_rate: int = 24000
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._sample_rate = sample_rate
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

        error_msg = f"IndexTTS {operation} failed: {detail}"
        logger.error(error_msg)
        raise IndexTTSError(error_msg, status_code=response.status_code, detail=detail)

    def _map_emotion(self, emotion: str) -> str:
        if emotion in INDEX_EMOTIONS:
            return emotion
        return EMOTION_MAP.get(emotion, "neutral")

    def _validate_intensity(self, intensity: float) -> float:
        return max(0.0, min(1.0, intensity))

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get(f"{self._base_url}/health")
            if response.status_code == 200:
                return True
            return False
        except Exception as e:
            logger.error(f"IndexTTS health check failed: {e}")
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

    async def synthesize(
        self,
        text: str,
        emotion: str = "neutral",
        emotion_intensity: float = 0.5,
        speed: float = 1.0,
        pitch: float = 0.0,
        timbre_ref: bytes | str | Path | None = None,
        ref_text: str = ""
    ) -> bytes:
        client = await self._get_client()

        index_emotion = self._map_emotion(emotion)
        validated_intensity = self._validate_intensity(emotion_intensity)

        payload: dict[str, Any] = {
            "text": text,
            "emotion": index_emotion,
            "emotion_intensity": validated_intensity,
            "speed": speed,
            "pitch": pitch,
        }

        files: dict[str, tuple] | None = None
        if timbre_ref is not None:
            if isinstance(timbre_ref, bytes):
                files = {
                    "timbre_ref": ("timbre.wav", timbre_ref, "audio/wav")
                }
            else:
                audio_path = Path(timbre_ref)
                if not audio_path.exists():
                    raise ValueError(f"Timbre reference audio file not found: {timbre_ref}")
                with open(audio_path, "rb") as f:
                    files = {
                        "timbre_ref": ("timbre.wav", f.read(), "audio/wav")
                    }

            if ref_text:
                payload["ref_text"] = ref_text

        if files:
            response = await client.post(
                f"{self._base_url}/tts",
                data=payload,
                files=files
            )
        else:
            response = await client.post(
                f"{self._base_url}/tts",
                json=payload
            )

        if response.status_code != 200:
            self._handle_error_response(response, "synthesis")

        return response.content

    async def synthesize_with_reference(
        self,
        text: str,
        ref_audio: bytes | str | Path,
        ref_text: str = "",
        emotion: str = "neutral",
        emotion_intensity: float = 0.5,
        speed: float = 1.0,
        pitch: float = 0.0
    ) -> bytes:
        client = await self._get_client()

        index_emotion = self._map_emotion(emotion)
        validated_intensity = self._validate_intensity(emotion_intensity)

        if isinstance(ref_audio, bytes):
            files = {
                "timbre_ref": ("ref.wav", ref_audio, "audio/wav")
            }
        else:
            audio_path = Path(ref_audio)
            if not audio_path.exists():
                raise ValueError(f"Reference audio file not found: {ref_audio}")
            with open(audio_path, "rb") as f:
                files = {
                    "timbre_ref": ("ref.wav", f.read(), "audio/wav")
                }

        payload = {
            "text": text,
            "ref_text": ref_text,
            "emotion": index_emotion,
            "emotion_intensity": validated_intensity,
            "speed": speed,
            "pitch": pitch,
        }

        response = await client.post(
            f"{self._base_url}/tts",
            data=payload,
            files=files
        )

        if response.status_code != 200:
            self._handle_error_response(response, "synthesis with reference")

        return response.content

    async def generate_emotion_audio(
        self,
        emotion: str,
        intensity: float,
        ref_audio: bytes | str | Path,
        ref_text: str = "",
        custom_text: str | None = None
    ) -> bytes:
        if emotion not in USER_EMOTIONS and emotion not in INDEX_EMOTIONS:
            supported = list(USER_EMOTIONS) + list(INDEX_EMOTIONS)
            raise ValueError(f"Unsupported emotion: {emotion}. Supported: {supported}")

        text = custom_text or EMOTION_TEXTS.get(emotion, EMOTION_TEXTS["normal"])

        return await self.synthesize_with_reference(
            text=text,
            ref_audio=ref_audio,
            ref_text=ref_text,
            emotion=emotion,
            emotion_intensity=intensity
        )

    async def generate_emotion_audios_from_template(
        self,
        template: str,
        ref_audio: bytes | str | Path,
        ref_text: str = "",
        on_progress: callable | None = None
    ) -> dict[tuple[str, float], bytes]:
        if template not in EMOTION_TEMPLATES:
            raise ValueError(f"Unknown template: {template}. Available: {list(EMOTION_TEMPLATES.keys())}")

        emotion_combinations = EMOTION_TEMPLATES[template]
        results: dict[tuple[str, float], bytes] = {}
        total = len(emotion_combinations)

        for i, (emotion, intensity) in enumerate(emotion_combinations):
            try:
                audio = await self.generate_emotion_audio(
                    emotion=emotion,
                    intensity=intensity,
                    ref_audio=ref_audio,
                    ref_text=ref_text
                )
                results[(emotion, intensity)] = audio

                if on_progress:
                    on_progress(emotion, intensity, i + 1, total, success=True)

            except Exception as e:
                logger.error(f"Failed to generate emotion audio for {emotion}@{intensity}: {e}")
                if on_progress:
                    on_progress(emotion, intensity, i + 1, total, success=False, error=str(e))

        return results

    async def generate_emotion_audios_from_list(
        self,
        emotions: list[tuple[str, float]],
        ref_audio: bytes | str | Path,
        ref_text: str = "",
        on_progress: callable | None = None
    ) -> dict[tuple[str, float], bytes]:
        results: dict[tuple[str, float], bytes] = {}
        total = len(emotions)

        for i, (emotion, intensity) in enumerate(emotions):
            try:
                audio = await self.generate_emotion_audio(
                    emotion=emotion,
                    intensity=intensity,
                    ref_audio=ref_audio,
                    ref_text=ref_text
                )
                results[(emotion, intensity)] = audio

                if on_progress:
                    on_progress(emotion, intensity, i + 1, total, success=True)

            except Exception as e:
                logger.error(f"Failed to generate emotion audio for {emotion}@{intensity}: {e}")
                if on_progress:
                    on_progress(emotion, intensity, i + 1, total, success=False, error=str(e))

        return results

    async def generate_all_emotion_combinations(
        self,
        ref_audio: bytes | str | Path,
        ref_text: str = "",
        emotions: list[str] | None = None,
        intensities: list[float] | None = None,
        on_progress: callable | None = None
    ) -> dict[tuple[str, float], bytes]:
        if emotions is None:
            emotions = ALL_EMOTIONS
        if intensities is None:
            intensities = EMOTION_INTENSITY_VALUES

        combinations = [(e, i) for e in emotions for i in intensities]

        return await self.generate_emotion_audios_from_list(
            emotions=combinations,
            ref_audio=ref_audio,
            ref_text=ref_text,
            on_progress=on_progress
        )

    @staticmethod
    def parse_natural_language_emotion(description: str) -> tuple[str, float] | None:
        for pattern, emotion, default_intensity in NATURAL_LANGUAGE_PATTERNS:
            if pattern.search(description):
                return emotion, default_intensity
        return None

    @staticmethod
    def parse_emotion_string(emotion_str: str) -> tuple[str, float]:
        emotion_str = emotion_str.strip()
        if "@" in emotion_str:
            parts = emotion_str.rsplit("@", 1)
            emotion = parts[0].strip()
            intensity = float(parts[1].strip())
            return emotion, intensity
        else:
            return emotion_str.strip(), 0.5

    @staticmethod
    def save_audio(audio_bytes: bytes, output_path: str | Path, sample_rate: int = 24000):
        import soundfile as sf
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
        sf.write(str(output_path), audio_array.astype(np.float32) / 32768.0, sample_rate)

    @staticmethod
    def load_audio(audio_path: str | Path, target_sr: int = 24000) -> bytes:
        import soundfile as sf
        audio_array, sr = sf.read(str(audio_path))
        if sr != target_sr:
            import scipy.signal
            audio_array = scipy.signal.resample_poly(audio_array, target_sr, sr)
        audio_int16 = (audio_array * 32768).astype(np.int16)
        return audio_int16.tobytes()


def get_supported_emotions() -> list[str]:
    return ALL_EMOTIONS


def get_index_emotions() -> list[str]:
    return list(INDEX_EMOTIONS)


def get_emotion_mapping(emotion: str) -> str:
    if emotion in INDEX_EMOTIONS:
        return emotion
    return EMOTION_MAP.get(emotion, "neutral")


def get_emotion_text(emotion: str) -> str:
    return EMOTION_TEXTS.get(emotion, EMOTION_TEXTS["normal"])


def get_template_names() -> list[str]:
    return list(EMOTION_TEMPLATES.keys())


def get_template(template_name: str) -> list[tuple[str, float]]:
    return EMOTION_TEMPLATES.get(template_name, [])
