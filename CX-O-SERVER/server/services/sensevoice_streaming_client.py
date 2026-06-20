"""
SenseVoice 流式 ASR 客户端
支持流式音频输入和增量识别
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, AsyncGenerator, Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)


class SenseVoiceStreamingClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
        on_partial_result: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        # 双流式模式主驱动回调：ASR Partial Result 产出即触发 LLM Speculative Prefill，
        # 不必等待 VAD on_end（原 silence_threshold_ms=500ms），可省下约 500ms 端到端延迟
        self._on_partial_result: Callable[[dict[str, Any]], Awaitable[None]] | None = on_partial_result

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def recognize_stream(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        language: str = "auto",
        chunk_size: int = 1600,
        hop_size: int = 800,
        look_back: int = 8000
    ) -> AsyncGenerator[dict[str, Any], None]:
        client = await self._get_client()

        buffer = b""
        total_offset = 0

        async for chunk in audio_chunks:
            buffer += chunk

            while len(buffer) >= chunk_size:
                audio_data = buffer[:chunk_size]
                buffer = buffer[hop_size:]

                audio_base64 = base64.b64encode(audio_data).decode("utf-8")

                try:
                    response = await client.post(
                        f"{self._base_url}/asr/stream",
                        json={
                            "audio": audio_base64,
                            "language": language,
                            "offset": total_offset,
                            "look_back": look_back
                        }
                    )
                    response.raise_for_status()
                    result = response.json()

                    if result.get("text"):
                        is_final = result.get("is_final", False)
                        partial = {
                            "text": result.get("text", ""),
                            "is_final": is_final,
                            "offset": total_offset
                        }

                        # Partial Result 主驱动：is_final=False 时立即触发 LLM Speculative Prefill，
                        # 省去等待 VAD on_end 的 500ms 静默判定，实现低延迟首字响应
                        if not is_final and self._on_partial_result is not None:
                            try:
                                await self._on_partial_result(partial)
                            except Exception as e:
                                logger.error(f"on_partial_result callback error at offset {total_offset}: {e}")

                        yield partial

                except Exception as e:
                    logger.error(f"Streaming ASR error at offset {total_offset}: {e}")

                total_offset += hop_size

        if buffer:
            audio_base64 = base64.b64encode(buffer).decode("utf-8")
            try:
                response = await client.post(
                    f"{self._base_url}/asr/stream",
                    json={
                        "audio": audio_base64,
                        "language": language,
                        "offset": total_offset,
                        "is_final": True
                    }
                )
                response.raise_for_status()
                result = response.json()

                if result.get("text"):
                    yield {
                        "text": result.get("text", ""),
                        "is_final": True,
                        "offset": total_offset
                    }
            except Exception as e:
                logger.error(f"Final streaming ASR error: {e}")

    async def recognize_chunk(
        self,
        audio_data: bytes,
        language: str = "auto",
        offset: int = 0,
        is_final: bool = False
    ) -> dict[str, Any]:
        client = await self._get_client()

        audio_base64 = base64.b64encode(audio_data).decode("utf-8")

        response = await client.post(
            f"{self._base_url}/asr/stream",
            json={
                "audio": audio_base64,
                "language": language,
                "offset": offset,
                "is_final": is_final
            }
        )
        response.raise_for_status()
        result = response.json()

        # Partial Result 主驱动：响应标记 is_final=False 时立即触发 LLM Speculative Prefill，
        # 不阻塞等待 VAD on_end 兜底，省下约 500ms 静默等待延迟
        result_is_final = result.get("is_final", is_final)
        if not result_is_final and self._on_partial_result is not None and result.get("text"):
            try:
                await self._on_partial_result(result)
            except Exception as e:
                logger.error(f"on_partial_result callback error at offset {offset}: {e}")

        return result
