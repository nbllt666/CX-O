"""
WebSocket 服务端
"""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
import httpx

from protocol.message import (
    MessageType, create_response, create_error, create_pong,
    PingMessage, RequestMessage
)
from protocol.actions import get_handler_name, SystemActions
from gateway.config import get_config, save_config
from gateway.health import health_checker

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


async def handle_system_health(websocket: WebSocket, message: dict, client_id: str):
    request_id = message.get("request_id", "")
    status = health_checker.get_all_status()
    await manager.send_message(client_id, create_response(
        request_id=request_id,
        action=SystemActions.HEALTH,
        data=status
    ))


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

            if action == SystemActions.HEALTH:
                await handle_system_health(websocket, message, client_id)
                continue

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

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(client_id)


def create_app() -> FastAPI:
    config = get_config()
    
    app = FastAPI(
        title="CX-O Gateway",
        description="微服务网关 - 统一 WebSocket 和 HTTP API 通讯入口",
        version="1.0.0"
    )

    cors_config = config.gateway.cors
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_config.allow_origins,
        allow_credentials=cors_config.allow_credentials,
        allow_methods=cors_config.allow_methods,
        allow_headers=cors_config.allow_headers,
    )

    health_checker.register_service("cxhms")
    health_checker.register_service("asr")
    health_checker.register_service("tts")

    cxhms_http_url = config.services.cxhms.http_url or "http://127.0.0.1:8000"

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    async def proxy_api(request: Request, path: str):
        target_url = f"{cxhms_http_url}/api/{path}"
        
        query_params = str(request.query_params)
        if query_params:
            target_url += f"?{query_params}"
        
        headers = dict(request.headers)
        headers.pop("host", None)
        
        body = await request.body()
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body if body else None,
                )
                
                excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
                response_headers = {
                    k: v for k, v in response.headers.items()
                    if k.lower() not in excluded_headers
                }
                
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=response_headers,
                    media_type=response.headers.get("content-type"),
                )
            except httpx.RequestError as e:
                logger.error(f"Proxy error: {e}")
                return Response(
                    content=json.dumps({"error": "Proxy error", "detail": str(e)}),
                    status_code=502,
                    media_type="application/json",
                )

    control_service_url = "http://127.0.0.1:8765"

    @app.api_route("/control/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    async def proxy_control(request: Request, path: str):
        target_url = f"{control_service_url}/control/{path}"
        
        query_params = str(request.query_params)
        if query_params:
            target_url += f"?{query_params}"
        
        headers = dict(request.headers)
        headers.pop("host", None)
        
        body = await request.body()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body if body else None,
                )
                
                excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
                response_headers = {
                    k: v for k, v in response.headers.items()
                    if k.lower() not in excluded_headers
                }
                
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=response_headers,
                    media_type=response.headers.get("content-type"),
                )
            except httpx.ConnectError:
                return Response(
                    content=json.dumps({"error": "Control service not available", "running": False}),
                    status_code=503,
                    media_type="application/json",
                )
            except httpx.RequestError as e:
                logger.error(f"Control proxy error: {e}")
                return Response(
                    content=json.dumps({"error": "Proxy error", "detail": str(e)}),
                    status_code=502,
                    media_type="application/json",
                )

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        import uuid
        client_id = str(uuid.uuid4())
        await websocket_handler(websocket, client_id)

    @app.get("/health")
    async def health_check():
        return health_checker.get_all_status()

    @app.get("/api/config/audio")
    async def get_audio_config():
        config = get_config()
        tts_config = config.services.tts
        return {
            "status": "success",
            "config": {
                "ref_audio_path": getattr(tts_config, 'ref_audio_path', ''),
                "ref_text": getattr(tts_config, 'ref_text', ''),
                "speed": getattr(tts_config, 'speed', 1.0),
                "cross_fade_duration": getattr(tts_config, 'cross_fade_duration', 0.15),
                "emotion_enabled": getattr(tts_config, 'emotion_enabled', True),
                "effects_enabled": getattr(tts_config, 'effects_enabled', True),
                "emotion_voices": getattr(tts_config, 'emotion_voices', {})
            }
        }

    @app.post("/api/config/audio")
    async def update_audio_config(request: Request):
        try:
            data = await request.json()
            config = get_config()
            
            if hasattr(config.services, 'tts'):
                tts_config = config.services.tts
                if 'ref_audio_path' in data:
                    tts_config.ref_audio_path = data['ref_audio_path']
                if 'ref_text' in data:
                    tts_config.ref_text = data['ref_text']
                if 'speed' in data:
                    tts_config.speed = data['speed']
                if 'cross_fade_duration' in data:
                    tts_config.cross_fade_duration = data['cross_fade_duration']
                if 'emotion_enabled' in data:
                    tts_config.emotion_enabled = data['emotion_enabled']
                if 'effects_enabled' in data:
                    tts_config.effects_enabled = data['effects_enabled']
                if 'emotion_voices' in data:
                    tts_config.emotion_voices = data['emotion_voices']
            
            save_config(config)
            
            return {"status": "success", "message": "配置已保存"}
        except Exception as e:
            logger.error(f"Failed to update audio config: {e}")
            return {"status": "error", "message": str(e)}

    return app
