"""音频端点——ASR/TTS 音频处理与流式合成接口。"""
import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger
from server.dependencies import get_asr_service, get_tts_service
from server.services.asr_service import ASRService
from server.services.tts_service import TTSService

router = APIRouter()
logger = get_contextual_logger(__name__)

# 项目根（CX-O-SERVER），基于文件位置解析，避免依赖运行时工作目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class TTSSynthesizeRequest(BaseModel):
    """TTS 合成请求参数"""

    text: str
    speed: float = 1.0
    cross_fade_duration: float = 0.15
    ref_audio: Optional[str] = None
    ref_text: Optional[str] = None
    # Qwen3 统一编排：参考音频资产 ID（ref_ 前缀）与无参考音频合成
    ref_asset_id: Optional[str] = None
    refs: Optional[list[str]] = None


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


@router.post("/tts/synthesize", summary="TTS合成")
async def tts_synthesize(request: TTSSynthesizeRequest, tts_svc: TTSService = Depends(get_tts_service)):
    try:
        if not request.text:
            return {"status": "error", "message": "缺少文本内容"}

        kwargs = {
            "speed": request.speed if request.speed != 1.0 else tts_svc._speed,
            "cross_fade_duration": request.cross_fade_duration if request.cross_fade_duration != 0.15 else tts_svc._cross_fade_duration,
        }
        if request.ref_asset_id:
            kwargs["ref_asset_id"] = request.ref_asset_id
        if request.refs:
            kwargs["refs"] = request.refs
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
    """以 SSE 流式方式合成 TTS 音频。"""
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
        # Qwen3 统一编排：参考音频资产 ID（ref_ 前缀）与多参考音频列表
        if data.get("ref_asset_id"):
            kwargs["ref_asset_id"] = data["ref_asset_id"]
        if data.get("refs"):
            kwargs["refs"] = data["refs"]
        if data.get("ref_audio"):
            kwargs["ref_audio"] = data["ref_audio"]
        if data.get("ref_text"):
            kwargs["ref_text"] = data["ref_text"]

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
    """语音识别，将上传或 base64 编码的音频转为文本。"""
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
        "engine": "qwen3",
        "ref_audio_path": "",
        "ref_text": "",
        "speed": 1.0,
        "cross_fade_duration": 0.15,
        "emotion_enabled": True,
        "effects_enabled": True,
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
            "engine": tts_config.get("engine", "qwen3"),
            "ref_audio_path": tts_config.get("ref_audio_path", ""),
            "ref_text": tts_config.get("ref_text", ""),
            "speed": tts_config.get("speed", 1.0),
            "cross_fade_duration": tts_config.get("cross_fade_duration", 0.15),
            "emotion_enabled": tts_config.get("emotion_enabled", True),
            "effects_enabled": tts_config.get("effects_enabled", True),
            "transition": tts_config.get("transition", default_config["transition"])
        }
    except Exception as e:
        logger.warning(f"加载 TTS 配置失败，使用默认配置: {e}")
        return default_config
