"""
WebSocket 服务端
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional, TYPE_CHECKING
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
import httpx

from server.protocol.message import (
    MessageType, create_response, create_error, create_pong,
    PingMessage, RequestMessage
)
from server.protocol.actions import get_handler_name, SystemActions
from server.gateway.gateway_config import get_config, save_config, SenseVoiceStreamingConfig
from server.gateway.health import health_checker

if TYPE_CHECKING:
    from server.services.asr import ASRService
    from server.services.tts import TTSService

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._handlers: dict[str, Callable] = {}
        self._stats = {
            "tts_count": 0,
            "asr_count": 0,
            "llm_count": 0,
            "client_count": 0,
        }

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self._connections[client_id] = websocket
        self._stats["client_count"] = len(self._connections)
        logger.info(f"Client connected: {client_id}")

    def disconnect(self, client_id: str):
        if client_id in self._connections:
            del self._connections[client_id]
            self._stats["client_count"] = len(self._connections)
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

    def increment_tts_count(self):
        self._stats["tts_count"] += 1

    def increment_asr_count(self):
        self._stats["asr_count"] += 1

    def increment_llm_count(self):
        self._stats["llm_count"] += 1

    def get_stats(self) -> dict:
        return self._stats.copy()


manager = ConnectionManager()
_tts_service: Optional["TTSService"] = None
_asr_service: Optional["ASRService"] = None


def get_tts_service() -> Optional["TTSService"]:
    return _tts_service


def get_asr_service() -> Optional["ASRService"]:
    return _asr_service


async def handle_ping(websocket: WebSocket, message: dict, client_id: str):
    timestamp = message.get("timestamp", time.time())
    await manager.send_message(client_id, create_pong(timestamp))


async def handle_live_connection(websocket: WebSocket, client_id: str):
    await websocket.accept()
    logger.info(f"Live client connected: {client_id}")

    client_config = {
        "client_type": None,
        "room_id": None,
        "supported_markers": [],
        "marker_config": {}
    }

    try:
        while True:
            msg = await websocket.receive()

            if msg.get("type") == "text":
                data = msg.get("text", "")
                try:
                    message = json.loads(data)
                    from server.handlers.live import LiveClientHandler
                    live_handler = LiveClientHandler(manager, client_id, client_config)
                    await live_handler.handle_message(websocket, message, client_id)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from live client {client_id}")

            elif msg.get("type") == "bytes":
                audio_data = msg.get("bytes", b"")
                from server.handlers.live import LiveClientHandler
                live_handler = LiveClientHandler(manager, client_id, client_config)
                await live_handler.handle_audio(websocket, audio_data, client_id)

            elif msg.get("type") == "disconnect":
                break

    except WebSocketDisconnect:
        logger.info(f"Live client disconnected: {client_id}")
    except Exception as e:
        logger.error(f"Live WebSocket error: {e}")
    finally:
        logger.info(f"Live client cleanup: {client_id}")


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

    voice_refs_dir = Path(__file__).parent.parent / "data" / "voice_refs"
    allowed_audio_extensions = {'.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac'}

    control_service_url = getattr(config.services, 'control_service_url', 'http://localhost:8765')

    app = FastAPI(
        title="CX-O Gateway",
        description="微服务网关 - 统一 WebSocket 和 HTTP API 通讯入口",
        version="1.0.0"
    )

    cors_config = config.gateway.cors
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    health_checker.register_service("asr")
    health_checker.register_service("tts")

    global _tts_service, _asr_service
    from server.services.tts import get_tts_service as get_local_tts_service
    from server.services.asr import get_asr_service as get_local_asr_service

    _tts_service = get_local_tts_service()
    _asr_service = get_local_asr_service()

    from server.handlers.chat import register_chat_handlers
    from server.handlers.memory import register_memory_handlers
    from server.handlers.audio import register_audio_handlers
    from server.handlers.tools import register_tools_handlers
    from server.handlers.acp import register_acp_handlers
    from server.handlers.mcp import register_mcp_handlers
    from server.handlers.plugin import register_plugin_handlers
    from server.handlers.config import register_config_handlers
    from server.handlers.metrics import register_metrics_handlers
    from server.handlers.system import register_system_handlers

    register_chat_handlers(manager)
    register_memory_handlers(manager)
    register_audio_handlers(manager)
    register_tools_handlers(manager)
    register_acp_handlers(manager)
    register_mcp_handlers(manager)
    register_plugin_handlers(manager)
    register_config_handlers(manager)
    register_metrics_handlers(manager)
    register_system_handlers(manager)

    from server.handlers.audio import init_interrupt_module, init_audio_stream_processor
    init_interrupt_module()
    init_audio_stream_processor()

    @app.get("/health")
    async def health_check():
        return health_checker.get_all_status()

    @app.get("/api/stats")
    async def get_stats():
        return manager.get_stats()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        import uuid
        client_id = str(uuid.uuid4())
        try:
            await websocket_handler(websocket, client_id)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")

    @app.websocket("/ws/live")
    async def live_websocket_endpoint(websocket: WebSocket):
        import uuid
        client_id = str(uuid.uuid4())
        try:
            await handle_live_connection(websocket, client_id)
        except Exception as e:
            logger.error(f"Live WebSocket error: {e}")

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

    @app.get("/api/config/services")
    async def get_services_config():
        config = get_config()
        services = config.services
        return {
            "status": "success",
            "config": {
                "asr": {
                    "url": services.asr.url,
                    "timeout": services.asr.timeout
                },
                "tts": {
                    "url": services.tts.url,
                    "timeout": services.tts.timeout
                }
            }
        }

    @app.post("/api/config/services")
    async def update_services_config(request: Request):
        try:
            data = await request.json()
            config = get_config()
            services = config.services

            if 'asr' in data:
                if 'url' in data['asr']:
                    services.asr.url = data['asr']['url']
                if 'timeout' in data['asr']:
                    services.asr.timeout = data['asr']['timeout']

            if 'tts' in data:
                if 'url' in data['tts']:
                    services.tts.url = data['tts']['url']
                if 'timeout' in data['tts']:
                    services.tts.timeout = data['tts']['timeout']

            save_config(config)

            return {"status": "success", "message": "服务配置已保存，需要重启生效"}
        except Exception as e:
            logger.error(f"Failed to update services config: {e}")
            return {"status": "error", "message": str(e)}

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

    @app.post("/api/config")
    async def update_unified_config(request: Request):
        try:
            data = await request.json()
            section = data.get("section")
            section_data = data.get("data", {})

            if not section:
                return {"status": "error", "message": "Missing section"}

            config = get_config()

            if section == "audio":
                if hasattr(config.services, 'tts'):
                    tts_config = config.services.tts
                    for key in ['ref_audio_path', 'ref_text', 'speed', 'cross_fade_duration',
                               'emotion_enabled', 'effects_enabled', 'emotion_voices']:
                        if key in section_data:
                            setattr(tts_config, key, section_data[key])
                save_config(config)
                return {"status": "success", "message": "Audio config saved"}

            elif section == "live":
                if 'danmaku' in section_data:
                    if not hasattr(config.services, 'danmaku'):
                        config.services.danmaku = type('DanmakuConfig', (), {})()
                    for key, value in section_data['danmaku'].items():
                        setattr(config.services.danmaku, key, value)

                if 'firewall' in section_data:
                    if not hasattr(config.services, 'firewall'):
                        config.services.firewall = type('FirewallConfig', (), {})()
                    for key, value in section_data['firewall'].items():
                        setattr(config.services.firewall, key, value)

                if 'vad' in section_data:
                    if not hasattr(config.services, 'vad'):
                        config.services.vad = type('VadConfig', (), {})()
                    for key, value in section_data['vad'].items():
                        setattr(config.services.vad, key, value)

                if 'sensevoice_streaming' in section_data:
                    if config.services.sensevoice_streaming is None:
                        config.services.sensevoice_streaming = SenseVoiceStreamingConfig()
                    sv_data = section_data['sensevoice_streaming']
                    for key in ['chunk_size', 'hop_size', 'look_back']:
                        if key in sv_data:
                            setattr(config.services.sensevoice_streaming, key, sv_data[key])

                if 'adaptive_polling' in section_data:
                    if config.services.adaptive_polling is None:
                        from server.gateway.gateway_config import AdaptivePollingConfig
                        config.services.adaptive_polling = AdaptivePollingConfig()
                    ap_data = section_data['adaptive_polling']
                    for key in ['offset_ms', 'window_size', 'enabled', 'min_interval_ms', 'max_interval_ms']:
                        if key in ap_data:
                            setattr(config.services.adaptive_polling, key, ap_data[key])

                save_config(config)
                return {"status": "success", "message": "Live config saved"}

            else:
                return {"status": "error", "message": f"Unknown section: {section}"}

        except Exception as e:
            logger.error(f"Failed to update unified config: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/api/config/sensevoice-streaming")
    async def get_sensevoice_streaming_config():
        config = get_config()
        sensevoice_config = getattr(config.services, 'sensevoice_streaming', None)
        if sensevoice_config is None:
            sensevoice_config = SenseVoiceStreamingConfig()
        return {
            "status": "success",
            "config": {
                "chunk_size": sensevoice_config.chunk_size,
                "hop_size": sensevoice_config.hop_size,
                "look_back": sensevoice_config.look_back
            }
        }

    @app.post("/api/config/sensevoice-streaming")
    async def update_sensevoice_streaming_config(request: Request):
        try:
            data = await request.json()
            config = get_config()

            if config.services.sensevoice_streaming is None:
                config.services.sensevoice_streaming = SenseVoiceStreamingConfig()

            sensevoice_config = config.services.sensevoice_streaming

            if 'chunk_size' in data:
                sensevoice_config.chunk_size = data['chunk_size']
            if 'hop_size' in data:
                sensevoice_config.hop_size = data['hop_size']
            if 'look_back' in data:
                sensevoice_config.look_back = data['look_back']

            save_config(config)

            return {"status": "success", "message": "SenseVoice 流式配置已保存"}
        except Exception as e:
            logger.error(f"Failed to update sensevoice streaming config: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/api/audio/files")
    async def list_audio_files():
        try:
            files = []
            for f in voice_refs_dir.iterdir():
                if f.is_file() and f.suffix.lower() in allowed_audio_extensions:
                    files.append({
                        "name": f.name,
                        "size": f.stat().st_size,
                        "modified": f.stat().st_mtime
                    })
            return {"status": "success", "files": files}
        except Exception as e:
            logger.error(f"Failed to list audio files: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/audio/upload")
    async def upload_audio_file(request: Request):
        try:
            from fastapi import UploadFile, File, Form
            import shutil

            form = await request.form()
            file = form.get("file")

            if not file:
                return {"status": "error", "message": "No file provided"}

            filename = file.filename
            ext = Path(filename).suffix.lower()

            if ext not in allowed_audio_extensions:
                return {
                    "status": "error",
                    "message": f"Invalid file type. Allowed: {', '.join(allowed_audio_extensions)}"
                }

            file_path = voice_refs_dir / filename

            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)

            return {
                "status": "success",
                "filename": filename,
                "message": "File uploaded successfully"
            }
        except Exception as e:
            logger.error(f"Failed to upload audio file: {e}")
            return {"status": "error", "message": str(e)}

    @app.get("/api/audio/files/{filename}")
    async def get_audio_file(filename: str):
        from fastapi.responses import FileResponse

        file_path = voice_refs_dir / filename

        if not file_path.exists():
            return {"status": "error", "message": "File not found"}

        return FileResponse(
            path=file_path,
            media_type="audio/wav" if filename.endswith(".wav") else "audio/mpeg",
            filename=filename
        )

    @app.delete("/api/audio/files/{filename}")
    async def delete_audio_file(filename: str):
        try:
            file_path = voice_refs_dir / filename

            if not file_path.exists():
                return {"status": "error", "message": "File not found"}

            file_path.unlink()

            return {"status": "success", "message": "File deleted"}
        except Exception as e:
            logger.error(f"Failed to delete audio file: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/tts/synthesize")
    async def tts_synthesize(request: Request):
        try:
            data = await request.json()
            text = data.get("text", "")

            if not text:
                return {"status": "error", "message": "Missing text"}

            from server.services.tts import get_tts_service
            tts_service = get_tts_service()

            if tts_service is None:
                return {"status": "error", "message": "TTS service not available"}

            kwargs = {
                "speed": data.get("speed", 1.0),
                "cross_fade_duration": data.get("cross_fade_duration", 0.15),
                "ref_audio": data.get("ref_audio"),
                "ref_text": data.get("ref_text"),
            }

            audio_bytes = await tts_service.synthesize(text, **kwargs)
            manager.increment_tts_count()

            import base64
            return {
                "status": "success",
                "audio_data": base64.b64encode(audio_bytes).decode("utf-8"),
                "format": "wav"
            }
        except Exception as e:
            logger.error(f"TTS synthesize error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/asr/speech-to-text")
    async def asr_speech_to_text(request: Request):
        try:
            content_type = request.headers.get("content-type", "")
            temp_path = None
            if "multipart/form-data" in content_type:
                form = await request.form()
                audio_file = form.get("file")
                language = form.get("language", "auto")
            else:
                data = await request.json()
                audio_base64 = data.get("audio", "")
                if audio_base64:
                    import base64
                    audio_data = base64.b64decode(audio_base64)
                    import tempfile
                    import os
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        f.write(audio_data)
                        temp_path = f.name
                    language = data.get("language", "auto")
                else:
                    return {"status": "error", "message": "No audio data"}

            from server.services.asr import get_asr_service
            asr_service = get_asr_service()

            if asr_service is None:
                return {"status": "error", "message": "ASR service not available"}

            if temp_path:
                with open(temp_path, 'rb') as f:
                    audio_data = f.read()
                os.unlink(temp_path)
            else:
                audio_data = await audio_file.read()

            result = await asr_service.recognize(audio_data, language)

            manager.increment_asr_count()

            return {
                "status": "success",
                "text": result.get("text", ""),
                "language": result.get("language", "")
            }
        except Exception as e:
            logger.error(f"ASR error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/tts/synthesize-stream")
    async def tts_synthesize_stream(request: Request):
        try:
            data = await request.json()
            text = data.get("text", "")

            if not text:
                async def error_stream():
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Missing text'}, ensure_ascii=False)}\n\n"
                return StreamingResponse(error_stream(), media_type="text/event-stream")

            from server.services.tts import get_tts_service
            tts_service = get_tts_service()

            if tts_service is None:
                async def error_stream():
                    yield f"data: {json.dumps({'type': 'error', 'message': 'TTS service not available'}, ensure_ascii=False)}\n\n"
                return StreamingResponse(error_stream(), media_type="text/event-stream")

            kwargs = {
                "speed": data.get("speed", 1.0),
                "cross_fade_duration": data.get("cross_fade_duration", 0.15),
            }

            import base64

            async def stream_generator():
                try:
                    async for chunk in tts_service.synthesize_stream(text, **kwargs):
                        audio_base64 = None
                        if chunk.get("audio_data"):
                            audio_base64 = base64.b64encode(chunk["audio_data"]).decode("utf-8")

                        chunk_data = json.dumps({
                            "type": "chunk",
                            "text_segment": chunk.get("text_segment", ""),
                            "audio_data": audio_base64,
                            "chunk_index": chunk.get("chunk_index", 0),
                            "is_final": chunk.get("is_final", False)
                        }, ensure_ascii=False)
                        yield f"data: {chunk_data}\n\n"
                except Exception as e:
                    logger.error(f"TTS stream error: {e}")
                    error_data = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
                    yield f"data: {error_data}\n\n"

            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        except Exception as e:
            logger.error(f"TTS synthesize-stream error: {e}")
            async def error_stream():
                err_data = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
                yield f"data: {err_data}\n\n"
            return StreamingResponse(error_stream(), media_type="text/event-stream")

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    async def proxy_api(request: Request, path: str):
        from server.gateway.gateway_config import get_config
        config = get_config()
        cxhms_http_url = getattr(config.services.cxhms, 'http_url', 'http://127.0.0.1:8000')

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

    @app.api_route("/control/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    async def proxy_control(request: Request, path: str):
        if not control_service_url or not control_service_url.startswith('http'):
            return Response(
                content=json.dumps({"error": "Control service not configured", "running": False}),
                status_code=503,
                media_type="application/json",
            )

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

    return app