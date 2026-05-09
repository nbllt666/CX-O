"""
ASR (SenseVoice) 客户端
"""
from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ASRClient:
    def __init__(self, base_url: str, timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def recognize(self, audio_data: bytes, language: str = "auto") -> dict[str, Any]:
        client = await self._get_client()

        audio_base64 = base64.b64encode(audio_data).decode("utf-8")

        response = await client.post(
            f"{self._base_url}/asr",
            json={
                "audio": audio_base64,
                "language": language
            }
        )
        response.raise_for_status()
        return response.json()

    async def recognize_file(self, file_path: str | Path, language: str = "auto") -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        with open(path, "rb") as f:
            audio_data = f.read()

        return await self.recognize(audio_data, language)

    async def recognize_base64(self, audio_base64: str, language: str = "auto") -> dict[str, Any]:
        client = await self._get_client()

        response = await client.post(
            f"{self._base_url}/asr",
            json={
                "audio": audio_base64,
                "language": language
            }
        )
        response.raise_for_status()
        return response.json()
