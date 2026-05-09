"""
内嵌 TTS 服务
支持 embedded（直接调用 F5-TTS 模型）和 remote（HTTP 调用）两种模式
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


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
        import f5_tts.api as _api
        _api._f5tts_instance = None
        self._initialized = False

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
        import httpx

        async with httpx.AsyncClient(timeout=120.0) as client:
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
