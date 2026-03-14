"""
WebSocket 服务端
"""
import asyncio
import json
import logging
import time
from pathlib import Path
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
    
    # 定义 voice_refs_dir 和 allowed_audio_extensions
    voice_refs_dir = Path(__file__).parent.parent / "data" / "voice_refs"
    allowed_audio_extensions = {'.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac'}
    
    # 获取 control_service_url
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

    health_checker.register_service("cxhms")
    health_checker.register_service("asr")
    health_checker.register_service("tts")

    # 初始化服务客户端
    from services.cxhms_client import CXHMSClient
    from services.tts_client import TTSClient
    from services.asr_client import ASRClient
    
    cxhms_url = config.services.cxhms.url or "ws://127.0.0.1:8000/ws/default"
    cxhms_http_url = config.services.cxhms.http_url or "http://127.0.0.1:8000"
    cxhms_client = CXHMSClient(
        url=cxhms_url,
        pool_size=5
    )
    
    tts_config = config.services.tts
    tts_client = TTSClient(
        base_url=tts_config.url,
        ref_audio_path=getattr(tts_config, 'ref_audio_path', ''),
        ref_text=getattr(tts_config, 'ref_text', ''),
        timeout=tts_config.timeout,
        emotion_voices=getattr(tts_config, 'emotion_voices', {}),
        effects_dir=getattr(config.services, 'audio', None) and getattr(config.services.audio, 'effects_dir', None),
        gateway_url=getattr(tts_config, 'gateway_url', None),
        use_triton=getattr(tts_config, 'use_triton', False)
    )
    
    asr_client = ASRClient(
        base_url=config.services.asr.url or "http://127.0.0.1:8001",
        timeout=getattr(config.services.asr, 'timeout', 120)
    )
    
    # 注册 handlers
    from handlers.chat import register_chat_handlers
    from handlers.memory import register_memory_handlers
    from handlers.audio import register_audio_handlers
    
    register_chat_handlers(manager, cxhms_client)
    register_memory_handlers(manager, cxhms_client)
    register_audio_handlers(manager, asr_client, tts_client)

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

    @app.get("/api/audio/emotions/list")
    async def list_emotion_configs():
        from services.index_tts_client import get_supported_emotions, get_emotion_text, get_index_emotions
        config = get_config()
        tts_config = config.services.tts
        
        emotions = get_supported_emotions()
        result = []
        
        for emotion in emotions:
            voice_config = {}
            if hasattr(tts_config, 'emotion_voices') and tts_config.emotion_voices:
                voice_config = tts_config.emotion_voices.get(emotion, {})
            
            result.append({
                "emotion": emotion,
                "default_text": get_emotion_text(emotion),
                "ref_audio": voice_config.get("ref_audio", ""),
                "ref_text": voice_config.get("ref_text", "")
            })
        
        return {"status": "success", "emotions": result}

    @app.get("/api/index-tts/status")
    async def get_index_tts_status():
        config = get_config()
        index_tts_config = getattr(config.services, 'index_tts', None)
        
        if not index_tts_config or not getattr(index_tts_config, 'enabled', False):
            return {"status": "disabled", "message": "IndexTTS service is not enabled"}
        
        try:
            from services.index_tts_manager import get_indextts_manager
            manager = get_indextts_manager(
                base_url=index_tts_config.url,
                start_command=getattr(index_tts_config, 'start_command', ''),
                working_dir=getattr(index_tts_config, 'working_dir', 'IndexTTS'),
                auto_stop_delay=getattr(index_tts_config, 'auto_stop_delay', 300),
                startup_timeout=getattr(index_tts_config, 'startup_timeout', 180),
                root_dir=Path(__file__).parent.parent.parent
            )
            return await manager.get_status()
        except Exception as e:
            logger.error(f"IndexTTS status check failed: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/index-tts/synthesize")
    async def index_tts_synthesize(request: Request):
        config = get_config()
        index_tts_config = getattr(config.services, 'index_tts', None)
        
        if not index_tts_config or not getattr(index_tts_config, 'enabled', False):
            return {"status": "error", "message": "IndexTTS service is not enabled"}
        
        try:
            from services.index_tts_manager import get_indextts_manager
            manager = get_indextts_manager(
                base_url=index_tts_config.url,
                start_command=getattr(index_tts_config, 'start_command', ''),
                working_dir=getattr(index_tts_config, 'working_dir', 'IndexTTS'),
                auto_stop_delay=getattr(index_tts_config, 'auto_stop_delay', 300),
                startup_timeout=getattr(index_tts_config, 'startup_timeout', 180),
                root_dir=Path(__file__).parent.parent.parent
            )
            
            is_running = await manager.ensure_running()
            if not is_running:
                return {"status": "error", "message": "Failed to start IndexTTS service"}
            
            data = await request.json()
            text = data.get("text", "")
            
            if not text:
                return {"status": "error", "message": "Text is required"}
            
            from services.index_tts_client import IndexTTSClient
            client = IndexTTSClient(
                base_url=index_tts_config.url,
                timeout=getattr(index_tts_config, 'timeout', 180)
            )
            
            kwargs = {
                "emotion": data.get("emotion", "neutral"),
                "emotion_intensity": data.get("emotion_intensity", 0.5),
                "speed": data.get("speed", 1.0),
                "pitch": data.get("pitch", 0.0),
            }
            
            ref_audio = data.get("ref_audio")
            ref_text = data.get("ref_text", "")
            
            if ref_audio:
                audio_path = voice_refs_dir / ref_audio
                if not audio_path.exists():
                    await client.close()
                    return {"status": "error", "message": f"Reference audio file not found: {ref_audio}"}
                kwargs["timbre_ref"] = str(audio_path)
                kwargs["ref_text"] = ref_text
            
            audio_bytes = await client.synthesize(text, **kwargs)
            await client.close()
            manager.reset_auto_stop_timer()
            
            import base64
            return {
                "status": "success",
                "audio_data": base64.b64encode(audio_bytes).decode("utf-8"),
                "format": "wav"
            }
        except Exception as e:
            logger.error(f"IndexTTS synthesize error: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/audio/generate-emotions")
    async def generate_emotion_audios(request: Request):
        from services.index_tts_client import get_emotion_text, EMOTION_TEMPLATES
        config = get_config()
        index_tts_config = getattr(config.services, 'index_tts', None)
        
        if not index_tts_config or not getattr(index_tts_config, 'enabled', False):
            return {"status": "error", "message": "IndexTTS service is not enabled"}
        
        try:
            from services.index_tts_manager import get_indextts_manager
            manager = get_indextts_manager(
                base_url=index_tts_config.url,
                start_command=getattr(index_tts_config, 'start_command', ''),
                working_dir=getattr(index_tts_config, 'working_dir', 'IndexTTS'),
                auto_stop_delay=getattr(index_tts_config, 'auto_stop_delay', 300),
                startup_timeout=getattr(index_tts_config, 'startup_timeout', 180),
                root_dir=Path(__file__).parent.parent.parent
            )
            
            is_running = await manager.ensure_running()
            if not is_running:
                return {"status": "error", "message": "Failed to start IndexTTS service"}
            
            data = await request.json()
            ref_audio = data.get("ref_audio", "")
            ref_text = data.get("ref_text", "")
            
            if not ref_audio:
                return {"status": "error", "message": "Reference audio is required"}
            
            audio_path = voice_refs_dir / ref_audio
            if not audio_path.exists():
                return {"status": "error", "message": f"Reference audio file not found: {ref_audio}"}
            
            from services.index_tts_client import IndexTTSClient
            client = IndexTTSClient(
                base_url=index_tts_config.url,
                timeout=getattr(index_tts_config, 'timeout', 180)
            )
            
            emotions_to_generate: list[tuple[str, float]] = []
            
            if data.get("auto_full", False):
                emotions_to_generate = [
                    (e, i) 
                    for e in ["happy", "sad", "angry", "surprised", "tender", "fearful", "disgusted", "normal"]
                    for i in [0.2, 0.4, 0.6, 0.8, 1.0]
                ]
            elif data.get("template"):
                template_name = data.get("template")
                if template_name not in EMOTION_TEMPLATES:
                    await client.close()
                    return {"status": "error", "message": f"Unknown template: {template_name}"}
                emotions_to_generate = EMOTION_TEMPLATES[template_name]
            elif data.get("emotions"):
                emotions_list = data.get("emotions", [])
                for item in emotions_list:
                    if isinstance(item, dict):
                        emotion = item.get("type", "neutral")
                        intensity = item.get("intensity", 0.5)
                    else:
                        emotion = item
                        intensity = 0.5
                    emotions_to_generate.append((emotion, intensity))
            
            generated: dict[str, str] = {}
            errors: dict[str, str] = {}
            
            for emotion, intensity in emotions_to_generate:
                try:
                    audio_bytes = await client.generate_emotion_audio(
                        emotion=emotion,
                        intensity=intensity,
                        ref_audio=str(audio_path),
                        ref_text=ref_text
                    )
                    
                    base_name = Path(ref_audio).stem
                    if intensity == 0.5:
                        output_name = f"{base_name}_{emotion}.wav"
                    else:
                        output_name = f"{base_name}_{emotion}_{intensity}.wav"
                    output_path = voice_refs_dir / output_name
                    
                    IndexTTSClient.save_audio(audio_bytes, output_path)
                    
                    key = f"{emotion}_{intensity}" if intensity != 0.5 else emotion
                    generated[key] = output_name
                    
                except Exception as e:
                    logger.error(f"Failed to generate {emotion}@{intensity}: {e}")
                    errors[f"{emotion}_{intensity}"] = str(e)
            
            await client.close()
            await manager.stop()
            
            if generated:
                tts_config = config.services.tts
                if not hasattr(tts_config, 'emotion_voices') or tts_config.emotion_voices is None:
                    tts_config.emotion_voices = {}
                
                for key, filename in generated.items():
                    parts = key.rsplit("_", 1)
                    emotion = parts[0]
                    emotion_text = get_emotion_text(emotion)
                    tts_config.emotion_voices[emotion] = {
                        "ref_audio": filename,
                        "ref_text": emotion_text
                    }
                
                save_config(config)
            
            return {
                "status": "success",
                "generated": generated,
                "errors": errors,
                "config_updated": len(generated) > 0
            }
            
        except Exception as e:
            logger.error(f"Generate emotion audios failed: {e}")
            return {"status": "error", "message": str(e)}

    @app.post("/api/tts/synthesize")
    async def tts_synthesize(request: Request):
        try:
            data = await request.json()
            text = data.get("text", "")
            
            if not text:
                return {"status": "error", "message": "Missing text"}
            
            config = get_config()
            tts_config = config.services.tts
            
            from services.tts_client import TTSClient
            client = TTSClient(
                base_url=tts_config.url,
                ref_audio_path=getattr(tts_config, 'ref_audio_path', ''),
                ref_text=getattr(tts_config, 'ref_text', ''),
                timeout=tts_config.timeout,
                emotion_voices=getattr(tts_config, 'emotion_voices', {}),
                effects_dir=getattr(config.services, 'audio', None) and getattr(config.services.audio, 'effects_dir', None),
                gateway_url=getattr(tts_config, 'gateway_url', None),
                use_triton=getattr(tts_config, 'use_triton', False)
            )
            
            kwargs = {
                "speed": data.get("speed", getattr(tts_config, 'speed', 1.0)),
                "cross_fade_duration": data.get("cross_fade_duration", getattr(tts_config, 'cross_fade_duration', 0.15)),
                "ref_audio": data.get("ref_audio"),
                "ref_text": data.get("ref_text"),
            }
            
            audio_bytes = await client.synthesize(text, **kwargs)
            await client.close()
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
            # Parse multipart form data
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" in content_type:
                form = await request.form()
                audio_file = form.get("file")
                language = form.get("language", "auto")
            else:
                data = await request.json()
                # Handle base64 encoded audio
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
            
            config = get_config()
            asr_config = config.services.asr
            
            from services.asr_client import ASRClient
            client = ASRClient(base_url=asr_config.url)
            
            # Read audio file if exists
            if 'temp_path' in dir():
                with open(temp_path, 'rb') as f:
                    audio_data = f.read()
                os.unlink(temp_path)
            else:
                audio_data = await audio_file.read()
            
            result = await client.recognize(audio_data, language)
            await client.close()
            
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
            
            config = get_config()
            tts_config = config.services.tts
            
            from services.tts_client import TTSClient
            client = TTSClient(
                base_url=tts_config.url,
                ref_audio_path=getattr(tts_config, 'ref_audio_path', ''),
                ref_text=getattr(tts_config, 'ref_text', ''),
                timeout=tts_config.timeout,
                emotion_voices=getattr(tts_config, 'emotion_voices', {}),
                effects_dir=getattr(config.services, 'audio', None) and getattr(config.services.audio, 'effects_dir', None),
                gateway_url=getattr(tts_config, 'gateway_url', None),
                use_triton=getattr(tts_config, 'use_triton', False)
            )
            
            kwargs = {
                "speed": data.get("speed", getattr(tts_config, 'speed', 1.0)),
                "cross_fade_duration": data.get("cross_fade_duration", getattr(tts_config, 'cross_fade_duration', 0.15)),
            }
            
            import base64
            
            async def stream_generator():
                try:
                    async for chunk in client.synthesize_stream(text, **kwargs):
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
                finally:
                    await client.close()
            
            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        except Exception as e:
            logger.error(f"TTS synthesize-stream error: {e}")
            async def error_stream():
                err_data = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
                yield f"data: {err_data}\n\n"
            return StreamingResponse(error_stream(), media_type="text/event-stream")

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

    return app
