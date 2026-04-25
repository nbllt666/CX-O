"""
SenseVoice 流式 ASR 客户端
支持实时音频流处理的 WebSocket 接口
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from typing import Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StreamingASRConfig:
    chunk_size: int = 1600
    hop_size: int = 400
    look_back: int = 4
    language: str = "auto"
    use_itn: bool = True
    max_pending_time: float = 1.0


@dataclass
class StreamingResult:
    task_id: str
    text: str
    clean_text: str
    language: str
    emotion: str
    event: str
    is_final: bool
    timestamp: str
    chunk_index: int = 0
    offset_ms: int = 0


class SenseVoiceStreamingClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
        config: Optional[StreamingASRConfig] = None
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._config = config or StreamingASRConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._ws_client: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._session_id: Optional[str] = None
        self._result_queue: asyncio.Queue[StreamingResult] = field(default_factory=asyncio.Queue)
        self._receive_task: Optional[asyncio.Task] = None
        self._audio_buffer: list[bytes] = []
        self._chunk_counter = 0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def connect(self) -> bool:
        try:
            import websockets
            ws_url = self._base_url.replace("http://", "ws://").replace("https://", "wss://")
            ws_url = f"{ws_url}/ws/streaming"

            self._session_id = str(uuid.uuid4())

            connection_params = {
                "session_id": self._session_id,
                "chunk_size": self._config.chunk_size,
                "hop_size": self._config.hop_size,
                "look_back": self._config.look_back,
                "language": self._config.language,
                "use_itn": self._config.use_itn,
            }

            self._ws_client = await websockets.connect(
                ws_url,
                extra_headers=connection_params
            )

            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_loop())

            logger.info(f"Streaming ASR connected: {self._session_id}")
            return True

        except Exception as e:
            logger.warning(f"WebSocket connection failed, falling back to HTTP streaming: {e}")
            return await self._connect_http_streaming()

    async def _connect_http_streaming(self) -> bool:
        self._session_id = str(uuid.uuid4())
        self._connected = True
        logger.info(f"HTTP streaming ASR session started: {self._session_id}")
        return True

    async def _receive_loop(self):
        if self._ws_client is None:
            return

        try:
            while self._connected and self._ws_client:
                try:
                    message = await asyncio.wait_for(
                        self._ws_client.recv(),
                        timeout=1.0
                    )

                    if isinstance(message, str):
                        data = json.loads(message)
                        result = StreamingResult(
                            task_id=data.get("task_id", ""),
                            text=data.get("text", ""),
                            clean_text=data.get("clean_text", ""),
                            language=data.get("language", ""),
                            emotion=data.get("emotion", ""),
                            event=data.get("event", ""),
                            is_final=data.get("is_final", True),
                            timestamp=data.get("timestamp", ""),
                            chunk_index=data.get("chunk_index", self._chunk_counter),
                            offset_ms=data.get("offset_ms", 0)
                        )
                        await self._result_queue.put(result)

                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    break

        except Exception as e:
            logger.error(f"Receive loop error: {e}")
        finally:
            self._connected = False

    async def send_audio_chunk(
        self,
        audio_data: bytes,
        is_last: bool = False
    ) -> bool:
        if not self._connected:
            logger.error("Not connected to streaming ASR")
            return False

        try:
            self._chunk_counter += 1

            audio_base64 = base64.b64encode(audio_data).decode("utf-8")

            chunk_info = {
                "session_id": self._session_id,
                "chunk_index": self._chunk_counter,
                "audio": audio_base64,
                "is_last": is_last,
                "chunk_size": self._config.chunk_size,
                "hop_size": self._config.hop_size,
                "look_back": self._config.look_back,
            }

            if self._ws_client and self._connected:
                await self._ws_client.send(json.dumps(chunk_info))
            else:
                await self._send_http_chunk(chunk_info)

            return True

        except Exception as e:
            logger.error(f"Failed to send audio chunk: {e}")
            return False

    async def _send_http_chunk(self, chunk_info: dict) -> dict:
        client = await self._get_client()

        try:
            response = await client.post(
                f"{self._base_url}/api/v1/asr/streaming",
                json=chunk_info,
                timeout=self._timeout
            )
            response.raise_for_status()

            result_data = response.json()
            result = StreamingResult(
                task_id=result_data.get("task_id", ""),
                text=result_data.get("text", ""),
                clean_text=result_data.get("clean_text", ""),
                language=result_data.get("language", ""),
                emotion=result_data.get("emotion", ""),
                event=result_data.get("event", ""),
                is_final=result_data.get("is_final", True),
                timestamp=result_data.get("timestamp", ""),
                chunk_index=chunk_info.get("chunk_index", 0),
                offset_ms=result_data.get("offset_ms", 0)
            )
            await self._result_queue.put(result)

            return result_data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP chunk request failed: {e}")
            return {}
        except Exception as e:
            logger.error(f"HTTP streaming error: {e}")
            return {}

    async def receive_result(self, timeout: Optional[float] = None) -> Optional[StreamingResult]:
        try:
            if timeout:
                return await asyncio.wait_for(self._result_queue.get(), timeout=timeout)
            else:
                return await self._result_queue.get()

        except asyncio.TimeoutError:
            return None

    async def receive_results(
        self,
        callback: Callable[[StreamingResult], Awaitable[None]],
        max_results: Optional[int] = None
    ) -> int:
        results_count = 0

        try:
            while self._connected:
                result = await self.receive_result(timeout=1.0)

                if result is not None:
                    await callback(result)
                    results_count += 1

                    if max_results and results_count >= max_results:
                        break

                if result and result.is_final:
                    break

        except Exception as e:
            logger.error(f"Error in receive loop: {e}")

        return results_count

    async def stream_audio(
        self,
        audio_chunks: list[bytes],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> list[StreamingResult]:
        results = []

        for i, chunk in enumerate(audio_chunks):
            is_last = (i == len(audio_chunks) - 1)

            success = await self.send_audio_chunk(chunk, is_last=is_last)

            if progress_callback:
                progress_callback(i + 1, len(audio_chunks))

            if success:
                result = await self.receive_result(timeout=self._config.max_pending_time)
                if result:
                    results.append(result)

        return results

    async def reset(self):
        self._audio_buffer.clear()
        self._chunk_counter = 0

        if self._session_id:
            try:
                client = await self._get_client()
                await client.post(
                    f"{self._base_url}/api/v1/asr/streaming/reset",
                    json={"session_id": self._session_id}
                )
            except Exception as e:
                logger.warning(f"Reset request failed: {e}")

        logger.info(f"Streaming ASR session reset: {self._session_id}")

    async def close(self):
        self._connected = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws_client:
            try:
                await self._ws_client.close()
            except Exception:
                pass
            self._ws_client = None

        if self._client:
            await self._client.aclose()
            self._client = None

        self._audio_buffer.clear()

        logger.info(f"Streaming ASR connection closed: {self._session_id}")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id


class MockStreamingASRClient(SenseVoiceStreamingClient):
    async def connect(self) -> bool:
        self._session_id = str(uuid.uuid4())
        self._connected = True
        self._receive_task = asyncio.create_task(self._mock_receive_loop())
        logger.info(f"Mock streaming ASR connected: {self._session_id}")
        return True

    async def _mock_receive_loop(self):
        try:
            while self._connected:
                await asyncio.sleep(0.1)

                if self._chunk_counter > 0:
                    mock_result = StreamingResult(
                        task_id=self._session_id or "",
                        text=f"模拟识别文本 {self._chunk_counter}",
                        clean_text=f"模拟识别文本 {self._chunk_counter}",
                        language="zh",
                        emotion="",
                        event="",
                        is_final=True,
                        timestamp="",
                        chunk_index=self._chunk_counter,
                        offset_ms=self._chunk_counter * self._config.hop_size
                    )
                    await self._result_queue.put(mock_result)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Mock receive loop error: {e}")

    async def _send_http_chunk(self, chunk_info: dict) -> dict:
        await asyncio.sleep(0.05)
        return {"status": "mocked"}


import httpx

try:
    import websockets
except ImportError:
    websockets = None
