"""
WebSocket 服务端
"""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional
from fastapi import WebSocket

from .protocol import (
    MessageType, create_response, create_error, create_pong,
    RequestMessage
)

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._handlers: dict[str, Callable] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self._connections[client_id] = websocket
        logger.info(f"Client connected: {client_id}")

    def disconnect(self, client_id: str):
        if client_id in self._connections:
            del self._connections[client_id]
            logger.info(f"Client disconnected: {client_id}")

    def register_handler(self, action: str, handler: Callable):
        self._handlers[action] = handler
        logger.debug(f"Registered handler for action: {action}")

    async def send_message(self, client_id: str, message: dict):
        if client_id in self._connections:
            await self._connections[client_id].send_json(message)

    async def broadcast(self, message: dict):
        for client_id, connection in self._connections.items():
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send to {client_id}: {e}")

    def get_handler(self, action: str) -> Optional[Callable]:
        return self._handlers.get(action)


manager = ConnectionManager()


async def handle_ping(websocket: WebSocket, message: dict, client_id: str):
    timestamp = message.get("timestamp", time.time())
    await manager.send_message(client_id, create_pong(timestamp))


async def websocket_handler(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await manager.send_message(client_id, create_error(
                    request_id="",
                    action="",
                    code="INVALID_JSON",
                    message="Invalid JSON format"
                ))
                continue

            msg_type = message.get("type")
            
            if msg_type == MessageType.PING.value:
                await handle_ping(websocket, message, client_id)
                continue

            action = message.get("action", "")
            request_id = message.get("request_id", "")

            handler = manager.get_handler(action)
            if handler:
                try:
                    await handler(websocket, message, client_id)
                except Exception as e:
                    logger.error(f"Handler error for {action}: {e}")
                    await manager.send_message(client_id, create_error(
                        request_id=request_id,
                        action=action,
                        code="HANDLER_ERROR",
                        message=str(e)
                    ))
            else:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=action,
                    code="UNKNOWN_ACTION",
                    message=f"Unknown action: {action}"
                ))

    except Exception as e:
        logger.info(f"WebSocket disconnected: {e}")
        manager.disconnect(client_id)
