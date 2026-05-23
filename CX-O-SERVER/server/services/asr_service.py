"""
统一 ASR 服务
支持 embedded（直接调用 SenseVoice 模型）和 remote（HTTP 调用）两种模式
合并了原 ASRClient 的 base64/文件识别功能
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import httpx

from server.core.utils import get_shared_http_client, close_shared_http_client, retry_with_backoff

logger = logging.getLogger(__name__)

TARGET_FS = 16000
regex = r"<\|.*\|>"

_model_instance = None
_model_kwargs = None
_executor: Optional[ThreadPoolExecutor] = None


class ASRService:
    def __init__(self, mode: str = "remote", model_dir: str = "", device: str = "cuda", remote_url: str = "http://127.0.0.1:8001"):
        self._mode = mode
        self._model_dir = model_dir
        self._device = device
        self._remote_url = remote_url
        self._initialized = False

    @property
    def mode(self) -> str:
        return self._mode

    async def initialize(self):
        global _model_instance, _model_kwargs, _executor
        if self._mode != "embedded":
            logger.info(f"ASR service in remote mode, target: {self._remote_url}")
            self._initialized = True
            return

        if _model_instance is not None:
            self._initialized = True
            return

        logger.info(f"Loading SenseVoice model: {self._model_dir} on device: {self._device}")
        _executor = ThreadPoolExecutor(max_workers=2)

        try:
            from sensevoice.model import SenseVoiceSmall
            _model_instance, _model_kwargs = SenseVoiceSmall.from_pretrained(
                model=self._model_dir,
                device=self._device
            )
            _model_instance.eval()
            self._initialized = True
            logger.info("SenseVoice model loaded successfully in embedded mode")
        except Exception as e:
            error_msg = f"Failed to load SenseVoice model in embedded mode: {e}"
            logger.error(error_msg)
            
            logger.warning("Attempting to fallback to remote ASR mode...")
            try:
                if _executor:
                    _executor.shutdown(wait=False)
                    _executor = None
                
                self._mode = "remote"
                self._initialized = True
                logger.info(f"ASR service successfully switched to remote mode: {self._remote_url}")
            except Exception as fallback_error:
                logger.error(f"Failed to fallback to remote ASR mode: {fallback_error}")
                raise RuntimeError(f"ASR service initialization failed: {error_msg}. Fallback to remote mode also failed: {fallback_error}")

    async def shutdown(self):
        global _model_instance, _model_kwargs, _executor
        if _executor:
            _executor.shutdown(wait=False)
            _executor = None
        _model_instance = None
        _model_kwargs = None
        self._initialized = False

    async def recognize(self, audio_data: bytes, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        if self._mode == "embedded" and _model_instance is not None:
            return await self._recognize_embedded(audio_data, language, use_itn)
        else:
            return await self._recognize_remote(audio_data, language, use_itn)

    async def recognize_base64(self, audio_base64: str, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        if self._mode == "embedded" and _model_instance is not None:
            audio_data = base64.b64decode(audio_base64)
            return await self._recognize_embedded(audio_data, language, use_itn)
        else:
            return await self._recognize_remote_base64(audio_base64, language, use_itn)

    async def recognize_file(self, file_path: str | Path, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        with open(path, "rb") as f:
            audio_data = f.read()

        return await self.recognize(audio_data, language, use_itn)

    async def _recognize_embedded(self, audio_data: bytes, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        audio_tensor, success = self._process_audio(BytesIO(audio_data))
        if not success:
            return {"text": "", "error": "Failed to process audio"}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _executor,
            self._run_inference,
            [audio_tensor],
            language,
            use_itn
        )
        return result

    async def _recognize_remote(self, audio_data: bytes, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        async def _make_request():
            client = get_shared_http_client()
            files = {"file": ("audio.wav", audio_data, "audio/wav")}
            data = {"language": language, "use_itn": str(use_itn), "task": "rich"}
            response = await client.post(f"{self._remote_url}/api/v1/asr", files=files, data=data)
            if response.status_code == 200:
                result = response.json()
                if result.get("results"):
                    return {
                        "text": result["results"][0].get("text", ""),
                        "language": result["results"][0].get("language", ""),
                        "emotion": result["results"][0].get("emotion", ""),
                        "event": result["results"][0].get("event", ""),
                    }
            return {"text": "", "error": f"ASR remote error: HTTP {response.status_code}"}
        
        return await retry_with_backoff(_make_request, max_retries=3, base_delay=1.0, max_delay=30.0, service_name="ASR")

    async def _recognize_remote_base64(self, audio_base64: str, language: str = "auto", use_itn: bool = True) -> dict[str, Any]:
        async def _make_request():
            client = get_shared_http_client()
            response = await client.post(
                f"{self._remote_url}/asr",
                json={
                    "audio": audio_base64,
                    "language": language
                }
            )
            response.raise_for_status()
            return response.json()

        return await retry_with_backoff(_make_request, max_retries=3, base_delay=1.0, max_delay=30.0, service_name="ASR")

    def _process_audio(self, file_io: BytesIO) -> tuple:
        try:
            import torch
            import torchaudio
            import numpy as np
            from scipy.io import wavfile
            from scipy import signal as scipy_signal

            file_io.seek(0)
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp.write(file_io.read())
                tmp_path = tmp.name

            try:
                sr, data = wavfile.read(tmp_path)
                if data.dtype == np.int16:
                    audio_data = data.astype(np.float32) / 32768.0
                else:
                    audio_data = data.astype(np.float32)

                if audio_data.ndim > 1:
                    audio_data = audio_data.mean(axis=1)

                if sr != TARGET_FS:
                    num_samples = int(len(audio_data) * TARGET_FS / sr)
                    audio_data = scipy_signal.resample(audio_data, num_samples)

                return torch.from_numpy(audio_data), True
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            try:
                import torch
                import torchaudio
                file_io.seek(0)
                data_or_path, audio_fs = torchaudio.load(file_io)
                if audio_fs != TARGET_FS:
                    resampler = torchaudio.transforms.Resample(orig_freq=audio_fs, new_freq=TARGET_FS)
                    data_or_path = resampler(data_or_path)
                if data_or_path.dim() > 1:
                    data_or_path = data_or_path.mean(0)
                return data_or_path, True
            except Exception as e2:
                logger.error(f"Error processing audio fallback: {e2}")
                return None, False

    def _run_inference(self, audios: list, lang: str, use_itn: bool) -> dict[str, Any]:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        key = [f"audio_{i}" for i in range(len(audios))]
        res = _model_instance.inference(
            data_in=audios,
            language=lang,
            use_itn=use_itn,
            key=key,
            fs=TARGET_FS,
            **_model_kwargs,
        )

        if len(res) > 0 and len(res[0]) > 0:
            item = res[0][0]
            raw_text = item.get("text", "")
            clean_text = re.sub(regex, "", raw_text, 0, re.MULTILINE)
            text = rich_transcription_postprocess(raw_text) if use_itn else clean_text

            lang_match = re.search(r"<\|(\w+)\|>", raw_text)
            emo_match = re.search(r"<\|(HAPPY|SAD|ANGRY|NEUTRAL|FEARFUL|DISGUSTED|SURPRISED)\|>", raw_text)
            event_match = re.search(r"<\|(BGM|Speech|Applause|Laughter|Cry|Sneeze|Breath|Cough|Sing|Speech_Noise)\|>", raw_text)

            return {
                "text": text,
                "language": lang_match.group(1) if lang_match else "",
                "emotion": emo_match.group(1) if emo_match else "",
                "event": event_match.group(1) if event_match else "",
            }
        return {"text": "", "language": "", "emotion": "", "event": ""}


_asr_service: Optional[ASRService] = None


def get_asr_service() -> ASRService:
    global _asr_service
    if _asr_service is None:
        from server.config import get_settings
        settings = get_settings()
        _asr_service = ASRService(
            mode=settings.asr.mode,
            model_dir=settings.asr.model_dir,
            device=settings.asr.device,
            remote_url=settings.asr.remote_url,
        )
    return _asr_service
