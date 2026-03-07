"""
WebSocket Router Module.

This module provides WebSocket endpoints for real-time streaming TTS.
"""

import asyncio
import base64
import logging
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from models.schemas import StreamChunk, WebSocketMessage
from services.inference_client import F5TTSClient

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """
    WebSocket connection manager for handling multiple client connections.
    
    Manages active connections and provides methods for broadcasting
    and sending messages to specific clients.
    """
    
    def __init__(self, tts_client: Optional[F5TTSClient] = None) -> None:
        """
        Initialize the connection manager.
        
        Args:
            tts_client: Optional F5TTSClient instance for TTS inference
        """
        self.active_connections: list[WebSocket] = []
        self._tts_client: Optional[F5TTSClient] = tts_client
    
    @property
    def tts_client(self) -> F5TTSClient:
        """
        Get the TTS client instance, creating one if necessary.
        
        Returns:
            F5TTSClient: The shared TTS client instance
        """
        if self._tts_client is None:
            from gateway.main import get_inference_client
            self._tts_client = get_inference_client()
            logger.info("Using shared F5TTSClient instance")
        return self._tts_client
    
    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept and register a new WebSocket connection.
        
        Args:
            websocket: The WebSocket connection to accept
        """
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection from the active connections list.
        
        Args:
            websocket: The WebSocket connection to remove
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def send_message(self, message: dict[str, Any], websocket: WebSocket) -> None:
        """
        Send a JSON message to a specific WebSocket connection.
        
        Args:
            message: The message dictionary to send
            websocket: The target WebSocket connection
        """
        await websocket.send_json(message)
    
    async def send_error(self, message: str, websocket: WebSocket) -> None:
        """
        Send an error message to a specific WebSocket connection.
        
        Args:
            message: The error message
            websocket: The target WebSocket connection
        """
        await self.send_message({"type": "error", "message": message}, websocket)
    
    async def send_audio_chunk(
        self,
        chunk_index: int,
        audio_data: bytes,
        websocket: WebSocket,
        is_final: bool = False,
    ) -> None:
        """
        Send an audio chunk to a specific WebSocket connection.
        
        Args:
            chunk_index: Sequential index of the chunk
            audio_data: Raw audio bytes
            websocket: The target WebSocket connection
            is_final: Whether this is the final chunk
        """
        audio_base64 = base64.b64encode(audio_data).decode("utf-8")
        await self.send_message(
            {
                "type": "audio",
                "chunk_index": chunk_index,
                "audio_data": audio_base64,
                "is_final": is_final,
            },
            websocket,
        )
    
    async def broadcast(self, message: dict[str, Any]) -> None:
        """
        Broadcast a JSON message to all active connections.
        
        Args:
            message: The message dictionary to broadcast
        """
        for connection in self.active_connections:
            await connection.send_json(message)
    
    async def close(self) -> None:
        """Close the TTS client connection."""
        if self._tts_client is not None:
            await self._tts_client.async_close()
            logger.info("Closed shared F5TTSClient instance")


manager = ConnectionManager()


@router.websocket("/stream")
async def websocket_stream(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for streaming TTS synthesis.
    
    Accepts WebSocket connections and processes incoming TTS requests
    for real-time text-to-speech streaming.
    
    Message format:
        Input: {"type": "tts", "reference_audio": "base64...", 
                "reference_text": "...", "target_text": "...", "speed": 1.0}
        Output chunks: {"type": "audio", "chunk_index": 0, 
                       "audio_data": "base64...", "is_final": false}
        Error: {"type": "error", "message": "..."}
    
    Supports multiple sequential TTS requests on the same connection.
    """
    await manager.connect(websocket)
    
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except Exception as e:
                logger.warning(f"Failed to parse JSON message: {e}")
                await manager.send_error("Invalid JSON format", websocket)
                continue
            
            message_type = data.get("type")
            
            if message_type == "control":
                content = data.get("content")
                if content == "disconnect":
                    logger.info("Client requested disconnect")
                    break
                continue
            
            if message_type == "tts":
                await _handle_tts_request(websocket, data)
            elif message_type == "text":
                await _handle_legacy_text_request(websocket, data)
            else:
                logger.warning(f"Unknown message type: {message_type}")
                await manager.send_error(f"Unknown message type: {message_type}", websocket)
    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await manager.send_error(f"Server error: {str(e)}", websocket)
        except Exception:
            pass
        manager.disconnect(websocket)


async def _handle_tts_request(websocket: WebSocket, data: dict[str, Any]) -> None:
    """
    Handle a TTS request message.
    
    Args:
        websocket: The WebSocket connection
        data: The message data containing TTS parameters
    """
    try:
        reference_audio_b64 = data.get("reference_audio")
        reference_text = data.get("reference_text")
        target_text = data.get("target_text")
        speed = data.get("speed", 1.0)
        
        if not reference_audio_b64:
            await manager.send_error("Missing 'reference_audio' field", websocket)
            return
        
        if not reference_text:
            await manager.send_error("Missing 'reference_text' field", websocket)
            return
        
        if not target_text:
            await manager.send_error("Missing 'target_text' field", websocket)
            return
        
        try:
            speed = float(speed)
            if speed < 0.5 or speed > 2.0:
                await manager.send_error("Speed must be between 0.5 and 2.0", websocket)
                return
        except (TypeError, ValueError):
            await manager.send_error("Invalid 'speed' value, must be a number", websocket)
            return
        
        logger.info(
            f"Processing TTS request: ref_text='{reference_text[:30]}...', "
            f"target_text='{target_text[:30]}...', speed={speed}"
        )
        
        try:
            reference_audio_bytes = base64.b64decode(reference_audio_b64)
        except Exception as e:
            logger.error(f"Failed to decode reference audio: {e}")
            await manager.send_error("Invalid base64 encoding for reference_audio", websocket)
            return
        
        try:
            client = manager.tts_client
            reference_audio = client._preprocess_audio(reference_audio_bytes)
        except Exception as e:
            logger.error(f"Failed to preprocess reference audio: {e}")
            await manager.send_error(f"Failed to process reference audio: {str(e)}", websocket)
            return
        
        chunk_index = 0
        try:
            async for audio_chunk in client.infer_stream(
                reference_audio,
                reference_text,
                target_text,
                chunk_size=4096,
            ):
                await manager.send_audio_chunk(
                    chunk_index=chunk_index,
                    audio_data=audio_chunk,
                    websocket=websocket,
                    is_final=False,
                )
                chunk_index += 1
            
            if chunk_index > 0:
                await manager.send_audio_chunk(
                    chunk_index=chunk_index,
                    audio_data=b"",
                    websocket=websocket,
                    is_final=True,
                )
                logger.info(f"TTS completed, sent {chunk_index} chunks")
            else:
                await manager.send_error("No audio generated", websocket)
        
        except Exception as e:
            logger.error(f"TTS inference failed: {e}", exc_info=True)
            await manager.send_error(f"TTS inference failed: {str(e)}", websocket)
    
    except Exception as e:
        logger.error(f"Unexpected error in TTS handler: {e}", exc_info=True)
        await manager.send_error(f"Unexpected error: {str(e)}", websocket)


async def _handle_legacy_text_request(websocket: WebSocket, data: dict[str, Any]) -> None:
    """
    Handle legacy text message format for backward compatibility.
    
    Args:
        websocket: The WebSocket connection
        data: The message data
    """
    try:
        message = WebSocketMessage(**data)
    except Exception as e:
        logger.warning(f"Invalid message format: {e}")
        await manager.send_error(f"Invalid message format: {str(e)}", websocket)
        return
    
    if message.type == "control" and message.content == "disconnect":
        logger.info("Client requested disconnect via legacy format")
        return
    
    if message.type == "text":
        logger.info(f"Processing legacy streaming TTS for: {message.content[:50]}...")
        
        for i in range(3):
            chunk = StreamChunk(
                chunk_index=i,
                audio_data="UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=",
                is_final=(i == 2),
            )
            await manager.send_message(
                {
                    "type": "audio",
                    "chunk_index": chunk.chunk_index,
                    "audio_data": chunk.audio_data,
                    "is_final": chunk.is_final,
                },
                websocket,
            )
            await asyncio.sleep(0.1)


@router.websocket("/echo")
async def websocket_echo(websocket: WebSocket) -> None:
    """
    WebSocket echo endpoint for testing connectivity.
    
    Echoes back any received message with a timestamp.
    """
    await manager.connect(websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            await manager.send_message(
                {
                    "echo": data,
                    "status": "received",
                },
                websocket,
            )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Echo WebSocket error: {e}")
        manager.disconnect(websocket)
