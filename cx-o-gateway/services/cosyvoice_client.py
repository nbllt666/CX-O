"""
CosyVoice 客户端
支持零样本语音克隆和情感控制
CosyVoice FastAPI 服务端使用 multipart form data
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import numpy as np

logger = logging.getLogger(__name__)


class CosyVoiceError(Exception):
    def __init__(self, message: str, status_code: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


EMOTION_INSTRUCTS: dict[str, str] = {
    "normal": "You are a helpful assistant. 请用平静、自然的语气说话。<|endofprompt|>",
    "happy": "You are a helpful assistant. 请用开心、愉快的语气说话，表达积极情绪。<|endofprompt|>",
    "sad": "You are a helpful assistant. 请用悲伤、低沉的语气说话，表达失落情绪。<|endofprompt|>",
    "angry": "You are a helpful assistant. 请用愤怒、激动的语气说话，表达不满情绪。<|endofprompt|>",
    "surprised": "You are a helpful assistant. 请用惊讶、意外的语气说话，表达震惊情绪。<|endofprompt|>",
    "tender": "You are a helpful assistant. 请用温柔、柔和的语气说话，表达关爱情绪。<|endofprompt|>",
    "fearful": "You are a helpful assistant. 请用恐惧、紧张的语气说话，表达害怕情绪。<|endofprompt|>",
    "disgusted": "You are a helpful assistant. 请用厌恶、反感的语气说话，表达不喜欢情绪。<|endofprompt|>",
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


class CosyVoiceClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 120.0,
        sample_rate: int = 22050
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
        
        error_msg = f"CosyVoice {operation} failed: {detail}"
        logger.error(error_msg)
        raise CosyVoiceError(error_msg, status_code=response.status_code, detail=detail)

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            response = await client.get(f"{self._base_url}/health")
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "error":
                    logger.warning(f"CosyVoice service error: {data.get('error')}")
                    return False
                return True
            return False
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
        prompt_text: str,
        prompt_audio: bytes | str | Path,
        speed: float = 1.0
    ) -> bytes:
        client = await self._get_client()
        
        if isinstance(prompt_audio, bytes):
            files = {
                "prompt_wav": ("prompt.wav", prompt_audio, "audio/wav")
            }
        else:
            audio_path = Path(prompt_audio)
            if not audio_path.exists():
                raise ValueError(f"Prompt audio file not found: {prompt_audio}")
            with open(audio_path, "rb") as f:
                files = {
                    "prompt_wav": ("prompt.wav", f.read(), "audio/wav")
                }
        
        data = {
            "tts_text": text,
            "prompt_text": prompt_text
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
        spk_id: str,
        instruct_text: str
    ) -> bytes:
        client = await self._get_client()
        
        data = {
            "tts_text": text,
            "spk_id": spk_id,
            "instruct_text": instruct_text
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
        instruct_text: str,
        prompt_audio: bytes | str | Path
    ) -> bytes:
        client = await self._get_client()
        
        if isinstance(prompt_audio, bytes):
            files = {
                "prompt_wav": ("prompt.wav", prompt_audio, "audio/wav")
            }
        else:
            audio_path = Path(prompt_audio)
            if not audio_path.exists():
                raise ValueError(f"Prompt audio file not found: {prompt_audio}")
            with open(audio_path, "rb") as f:
                files = {
                    "prompt_wav": ("prompt.wav", f.read(), "audio/wav")
                }
        
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
        prompt_audio: bytes | str | Path
    ) -> bytes:
        client = await self._get_client()
        
        if isinstance(prompt_audio, bytes):
            files = {
                "prompt_wav": ("prompt.wav", prompt_audio, "audio/wav")
            }
        else:
            audio_path = Path(prompt_audio)
            if not audio_path.exists():
                raise ValueError(f"Prompt audio file not found: {prompt_audio}")
            with open(audio_path, "rb") as f:
                files = {
                    "prompt_wav": ("prompt.wav", f.read(), "audio/wav")
                }
        
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

    async def generate_emotion_audio(
        self,
        emotion: str,
        prompt_audio: bytes | str | Path,
        prompt_text: str = "",
        custom_text: str | None = None,
        custom_instruct: str | None = None
    ) -> bytes:
        if emotion not in EMOTION_INSTRUCTS:
            raise ValueError(f"Unsupported emotion: {emotion}. Supported: {list(EMOTION_INSTRUCTS.keys())}")
        
        text = custom_text or EMOTION_TEXTS.get(emotion, EMOTION_TEXTS["normal"])
        instruct = custom_instruct or EMOTION_INSTRUCTS.get(emotion, EMOTION_INSTRUCTS["normal"])
        
        return await self.synthesize_instruct2(
            text=text,
            instruct_text=instruct,
            prompt_audio=prompt_audio
        )

    async def generate_all_emotion_audios(
        self,
        prompt_audio: bytes | str | Path,
        emotions: list[str] | None = None,
        custom_texts: dict[str, str] | None = None,
        custom_instructs: dict[str, str] | None = None,
        on_progress: callable | None = None
    ) -> dict[str, bytes]:
        if emotions is None:
            emotions = ["normal", "happy", "sad", "angry", "surprised", "tender"]
        
        results: dict[str, bytes] = {}
        total = len(emotions)
        
        for i, emotion in enumerate(emotions):
            try:
                custom_text = custom_texts.get(emotion) if custom_texts else None
                custom_instruct = custom_instructs.get(emotion) if custom_instructs else None
                
                audio = await self.generate_emotion_audio(
                    emotion=emotion,
                    prompt_audio=prompt_audio,
                    custom_text=custom_text,
                    custom_instruct=custom_instruct
                )
                results[emotion] = audio
                
                if on_progress:
                    on_progress(emotion, i + 1, total, success=True)
                    
            except Exception as e:
                logger.error(f"Failed to generate emotion audio for {emotion}: {e}")
                if on_progress:
                    on_progress(emotion, i + 1, total, success=False, error=str(e))
        
        return results

    @staticmethod
    def save_audio(audio_bytes: bytes, output_path: str | Path, sample_rate: int = 22050):
        import soundfile as sf
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
        sf.write(str(output_path), audio_array.astype(np.float32) / 32768.0, sample_rate)

    @staticmethod
    def load_audio(audio_path: str | Path, target_sr: int = 16000) -> bytes:
        import soundfile as sf
        audio_array, sr = sf.read(str(audio_path))
        if sr != target_sr:
            import scipy.signal
            audio_array = scipy.signal.resample_poly(audio_array, target_sr, sr)
        audio_int16 = (audio_array * 32768).astype(np.int16)
        return audio_int16.tobytes()


def get_supported_emotions() -> list[str]:
    return list(EMOTION_INSTRUCTS.keys())


def get_emotion_instruct(emotion: str) -> str:
    return EMOTION_INSTRUCTS.get(emotion, EMOTION_INSTRUCTS["normal"])


def get_emotion_text(emotion: str) -> str:
    return EMOTION_TEXTS.get(emotion, EMOTION_TEXTS["normal"])
