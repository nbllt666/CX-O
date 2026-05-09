"""
内嵌 TTS 服务
支持 embedded（直接调用 F5-TTS 模型）和 remote（HTTP 调用）两种模式
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=120.0,
                write=120.0,
                pool=10.0
            ),
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=30.0
            )
        )
    return _http_client


async def _retry_with_backoff(
    func,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    *args,
    **kwargs
):
    last_exception = None
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout) as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(f"TTS request failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"TTS request failed after {max_retries} attempts: {e}")
                raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500 and attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(f"TTS server error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                raise
        except Exception as e:
            logger.error(f"Unexpected error in TTS request: {e}")
            raise
    
    if last_exception:
        raise last_exception


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
        global _http_client
        import f5_tts.api as _api
        _api._f5tts_instance = None
        self._initialized = False
        
        if _http_client:
            await _http_client.aclose()
            _http_client = None
            logger.info("TTS HTTP client closed")

    async def synthesize(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        speed: float | None = None,
        cross_fade_duration: float | None = None,
        **kwargs
    ) -> bytes:
        audio_path = ref_audio_path or self._ref_audio_path
        text_ref = ref_text or self._ref_text
        spd = speed or self._speed
        cfd = cross_fade_duration or self._cross_fade_duration

        from f5_tts.api import get_f5tts

        if self._mode == "embedded" and get_f5tts() is not None:
            return await self._synthesize_embedded(text, audio_path, text_ref, spd, cfd, **kwargs)
        else:
            return await self._synthesize_remote(text, audio_path, text_ref, spd, cfd, **kwargs)

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
        self, text: str, ref_audio_path: str, ref_text: str, speed: float, cross_fade_duration: float, **kwargs
    ) -> bytes:
        async def _make_request():
            client = _get_http_client()
            
            files = {}
            if ref_audio_path and Path(ref_audio_path).exists():
                with open(ref_audio_path, "rb") as f:
                    files["ref_audio"] = ("ref_audio.wav", f.read(), "audio/wav")

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
        
        return await _retry_with_backoff(_make_request, max_retries=3, base_delay=1.0, max_delay=30.0)


_tts_service: Optional[TTSService] = None


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
        )
    return _tts_service
