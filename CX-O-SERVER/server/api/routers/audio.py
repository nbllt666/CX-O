"""音频端点——ASR/TTS 音频处理与流式合成接口。"""
import base64
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger
from server.dependencies import get_asr_service, get_tts_service
from server.services.asr_service import ASRService
from server.services.tts_service import TTSService

router = APIRouter()
logger = get_contextual_logger(__name__)

# 项目根（CX-O-SERVER），基于文件位置解析，避免依赖运行时工作目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
VOICE_REFS_DIR = _PROJECT_ROOT / "data" / "voice_refs"
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}


class TTSSynthesizeRequest(BaseModel):
    text: str
    speed: float = 1.0
    cross_fade_duration: float = 0.15
    ref_audio: Optional[str] = None
    ref_text: Optional[str] = None


def _validate_filename(filename: str) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if os.path.isabs(filename):
        raise HTTPException(status_code=400, detail="Absolute paths not allowed")
    resolved = (VOICE_REFS_DIR / filename).resolve()
    if not str(resolved).startswith(str(VOICE_REFS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    return filename

def _ensure_voice_refs_dir():
    VOICE_REFS_DIR.mkdir(parents=True, exist_ok=True)


@router.get(
    "/audio/config",
    summary="获取音频配置",
    description="获取 TTS 音频配置，包括参考音频路径、语速、情感语音等。",
)
async def get_audio_config():
    try:
        config = _load_tts_config()
        return config
    except Exception as e:
        logger.error(f"获取音频配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get(
    "/audio/files",
    summary="获取音频文件列表",
    description="获取 voice_refs 目录下的所有音频文件列表。",
)
async def get_audio_files():
    try:
        _ensure_voice_refs_dir()

        files = []
        for f in VOICE_REFS_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in ALLOWED_AUDIO_EXTENSIONS:
                stat = f.stat()
                files.append({
                    "name": f.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })

        return {"files": files}
    except Exception as e:
        logger.error(f"获取音频文件列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post(
    "/audio/upload",
    summary="上传音频文件",
    description="上传音频文件到 voice_refs 目录。",
)
async def upload_audio_file(request: Request):
    try:
        _ensure_voice_refs_dir()

        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" not in content_type:
            raise HTTPException(status_code=400, detail="需要 multipart/form-data 请求")

        form = await request.form()
        audio_file = form.get("file")
        if not audio_file:
            raise HTTPException(status_code=400, detail="未提供音频文件")

        filename = audio_file.filename
        if not filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_AUDIO_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的音频格式: {suffix}")

        file_path = VOICE_REFS_DIR / filename
        content = await audio_file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        return {"status": "success", "filename": filename, "size": len(content)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传音频文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get(
    "/audio/files/{filename}",
    summary="获取音频文件",
    description="根据文件名获取音频文件内容。",
)
async def get_audio_file(filename: str):
    try:
        _validate_filename(filename)
        _ensure_voice_refs_dir()

        file_path = VOICE_REFS_DIR / filename

        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件 '{filename}' 不存在")

        if not file_path.is_file():
            raise HTTPException(status_code=400, detail=f"'{filename}' 不是有效文件")

        media_type = "audio/wav" if filename.endswith(".wav") else "audio/mpeg"

        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取音频文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete(
    "/audio/files/{filename}",
    summary="删除音频文件",
    description="根据文件名删除指定的音频文件。",
)
async def delete_audio_file(filename: str):
    try:
        _validate_filename(filename)
        _ensure_voice_refs_dir()

        file_path = VOICE_REFS_DIR / filename

        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"文件 '{filename}' 不存在")

        if not file_path.is_file():
            raise HTTPException(status_code=400, detail=f"'{filename}' 不是有效文件")

        file_path.unlink()

        logger.info(f"已删除音频文件: {filename}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除音频文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/tts/synthesize", summary="TTS合成")
async def tts_synthesize(request: TTSSynthesizeRequest, tts_svc: TTSService = Depends(get_tts_service)):
    try:
        if not request.text:
            return {"status": "error", "message": "缺少文本内容"}

        kwargs = {
            "speed": request.speed if request.speed != 1.0 else tts_svc._speed,
            "cross_fade_duration": request.cross_fade_duration if request.cross_fade_duration != 0.15 else tts_svc._cross_fade_duration,
        }
        if request.ref_audio:
            kwargs["ref_audio"] = request.ref_audio
        if request.ref_text:
            kwargs["ref_text"] = request.ref_text

        audio_bytes = await tts_svc.synthesize(request.text, **kwargs)

        return {
            "status": "success",
            "audio_data": base64.b64encode(audio_bytes).decode("utf-8"),
            "format": "wav"
        }

    except Exception as e:
        logger.error(f"TTS合成失败: {e}", exc_info=True)
        return {"status": "error", "message": "TTS合成失败"}


@router.post("/tts/synthesize-stream", summary="TTS流式合成")
async def tts_synthesize_stream(request: Request, tts_svc: TTSService = Depends(get_tts_service)):
    try:
        data = await request.json()
        text = data.get("text", "")

        if not text:
            async def error_stream():
                yield f"data: {json.dumps({'type': 'error', 'message': '缺少文本内容'}, ensure_ascii=False)}\n\n"
            return StreamingResponse(error_stream(), media_type="text/event-stream")

        kwargs = {
            "speed": data.get("speed", tts_svc._speed),
            "cross_fade_duration": data.get("cross_fade_duration", tts_svc._cross_fade_duration),
        }

        async def stream_generator():
            try:
                async for chunk in tts_svc.synthesize_stream(text, **kwargs):
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
                logger.error(f"TTS流式合成错误: {e}", exc_info=True)
                error_data = json.dumps({"type": "error", "message": f"TTS流式合成失败: {str(e)}"}, ensure_ascii=False)
                yield f"data: {error_data}\n\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    except Exception as e:
        logger.error(f"TTS流式合成初始化失败: {e}", exc_info=True)

        async def error_stream():
            err_data = json.dumps({"type": "error", "message": "TTS流式合成初始化失败"}, ensure_ascii=False)
            yield f"data: {err_data}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")


@router.post("/asr/speech-to-text", summary="ASR语音识别")
async def asr_speech_to_text(request: Request, asr_svc: ASRService = Depends(get_asr_service)):
    temp_path = None
    try:
        content_type = request.headers.get("content-type", "")
        language = "auto"

        if "multipart/form-data" in content_type:
            form = await request.form()
            audio_file = form.get("file")
            language = form.get("language", "auto")
            if not audio_file:
                return {"status": "error", "message": "未提供音频文件"}
            audio_data = await audio_file.read()
        else:
            data = await request.json()
            audio_base64 = data.get("audio", "")
            language = data.get("language", "auto")
            if not audio_base64:
                return {"status": "error", "message": "未提供音频数据"}
            audio_bytes = base64.b64decode(audio_base64)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                temp_path = f.name
            with open(temp_path, "rb") as f:
                audio_data = f.read()

        result = await asr_svc.recognize(audio_data, language)

        return {
            "status": "success",
            "text": result.get("text", ""),
            "language": result.get("language", "")
        }
    except Exception as e:
        logger.error(f"ASR语音识别失败: {e}", exc_info=True)
        return {"status": "error", "message": "语音识别失败"}
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


def _load_tts_config() -> dict:
    config_file = _PROJECT_ROOT / "config" / "settings.json"

    default_config = {
        "engine": "f5",
        "ref_audio_path": "",
        "ref_text": "",
        "speed": 1.0,
        "cross_fade_duration": 0.15,
        "emotion_enabled": True,
        "effects_enabled": True,
        "emotion_voices": {},
        "transition": {
            "enabled": True,
            "duration": 0.5,
            "intensity": 0.7
        }
    }

    if not config_file.exists():
        return default_config

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)

        tts_config = config_data.get("tts", {})

        return {
            "engine": tts_config.get("engine", "f5"),
            "ref_audio_path": tts_config.get("ref_audio_path", ""),
            "ref_text": tts_config.get("ref_text", ""),
            "speed": tts_config.get("speed", 1.0),
            "cross_fade_duration": tts_config.get("cross_fade_duration", 0.15),
            "emotion_enabled": tts_config.get("emotion_enabled", True),
            "effects_enabled": tts_config.get("effects_enabled", True),
            "emotion_voices": tts_config.get("emotion_voices", {}),
            "transition": tts_config.get("transition", default_config["transition"])
        }
    except Exception as e:
        logger.warning(f"加载 TTS 配置失败，使用默认配置: {e}")
        return default_config


def _load_asr_config() -> dict:
    config_file = _PROJECT_ROOT / "config" / "settings.json"
    default_config = {"url": "http://127.0.0.1:5001", "timeout": 60}
    if not config_file.exists():
        return default_config
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        asr_config = config_data.get("asr", {})
        return {
            "url": asr_config.get("url", default_config["url"]),
            "timeout": asr_config.get("timeout", default_config["timeout"])
        }
    except Exception as e:
        logger.warning(f"加载 ASR 配置失败，使用默认配置: {e}")
        return default_config
