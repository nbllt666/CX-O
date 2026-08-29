"""音频端点——ASR/TTS 音频处理与流式合成接口。"""
import base64
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger
from server.dependencies import get_asr_service, get_tts_service
from server.services.asr_service import ASRService
from server.services.tts_service import TTSService
from server.services.tts_service import TTSServiceUnavailableError

router = APIRouter()
logger = get_contextual_logger(__name__)

# 项目根（CX-O-SERVER），基于文件位置解析，避免依赖运行时工作目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 上传防呆：单次请求音频（解码后）大小上限 20MB（音频级入口兜底，参照 ref_audio_assets 上限模式）
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class TTSSynthesizeRequest(BaseModel):
    """TTS 合成请求参数

    speed / cross_fade_duration 缺省 None 时使用服务端默认；显式传值（含 1.0/0.15）
    一律保留，与流式端点（data.get 默认）口径一致。
    """

    text: str
    speed: Optional[float] = None
    cross_fade_duration: Optional[float] = None
    ref_audio: Optional[str] = None
    ref_text: Optional[str] = None
    # Qwen3 统一编排：参考音频资产 ID（ref_ 前缀）与无参考音频合成
    ref_asset_id: Optional[str] = None
    refs: Optional[list[str]] = None
    # per-agent 参考音频：未显式传 refs 时按 agent_id 取该 Agent 绑定资产（A3）
    agent_id: Optional[str] = None


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
    # H10/M：参数缺失统一 400；下游 TTS 失败 502；未预期 500
    if not request.text:
        raise HTTPException(status_code=400, detail="缺少文本内容")

    kwargs = {
        "speed": request.speed if request.speed is not None else tts_svc._speed,
        "cross_fade_duration": (
            request.cross_fade_duration
            if request.cross_fade_duration is not None
            else tts_svc._cross_fade_duration
        ),
    }
    if request.ref_asset_id:
        kwargs["ref_asset_id"] = request.ref_asset_id
    if request.refs:
        kwargs["refs"] = request.refs
    if request.ref_audio:
        kwargs["ref_audio"] = request.ref_audio
    if request.ref_text:
        kwargs["ref_text"] = request.ref_text
    if request.agent_id:
        kwargs["agent_id"] = request.agent_id

    try:
        audio_bytes = await tts_svc.synthesize(request.text, **kwargs)
    except TTSServiceUnavailableError as e:
        # H10：Provider 未装配 / Qwen3 未启用 → 502（下游能力不可用）
        logger.error(f"TTS 服务不可用: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="TTS 服务不可用")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS合成失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="TTS合成失败")

    return {
        "status": "success",
        "audio_data": base64.b64encode(audio_bytes).decode("utf-8"),
        "format": "wav"
    }


@router.post("/tts/synthesize-stream", summary="TTS流式合成")
async def tts_synthesize_stream(request: Request, tts_svc: TTSService = Depends(get_tts_service)):
    """以 SSE 流式方式合成 TTS 音频。"""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")

    text = data.get("text", "")
    if not text:
        # SSE 错误流仍保持 200（前端按 SSE 协议读 event，避免连错误流都解析失败）
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'message': '缺少文本内容'}, ensure_ascii=False)}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    # H10：入口守卫——Provider 未装配时立即以 SSE error 返回（不进入合成流程）
    try:
        tts_svc._ensure_qwen3_ready()
    except TTSServiceUnavailableError as e:
        async def unavailable_stream():
            yield f"data: {json.dumps({'type': 'error', 'message': 'TTS 服务不可用'}, ensure_ascii=False)}\n\n"
        logger.error(f"TTS 服务不可用: {e}", exc_info=True)
        return StreamingResponse(unavailable_stream(), media_type="text/event-stream")

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
    if data.get("agent_id"):
        kwargs["agent_id"] = data["agent_id"]

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
        except TTSServiceUnavailableError as e:
            logger.error(f"TTS 服务不可用: {e}", exc_info=True)
            error_data = json.dumps({"type": "error", "message": "TTS 服务不可用"}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
        except Exception as e:
            logger.error(f"TTS流式合成错误: {e}", exc_info=True)
            # 错误文案收敛：SSE 错误事件不透传内部实现细节（详情见上方日志）
            error_data = json.dumps({"type": "error", "message": "TTS流式合成失败"}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.post("/asr/speech-to-text", summary="ASR语音识别")
async def asr_speech_to_text(request: Request, asr_svc: ASRService = Depends(get_asr_service)):
    """语音识别，将上传或 base64 编码的音频转为文本。"""
    try:
        content_type = request.headers.get("content-type", "")
        language = "auto"

        if "multipart/form-data" in content_type:
            # 上传防呆：Content-Length 预检（超限直接 413，不进入读取），读取后复查实际长度
            content_length = request.headers.get("content-length", "")
            if content_length.isdigit() and int(content_length) > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="音频文件过大")
            form = await request.form()
            audio_file = form.get("file")
            language = form.get("language", "auto")
            if not audio_file:
                raise HTTPException(status_code=400, detail="未提供音频文件")
            audio_data = await audio_file.read()
            if len(audio_data) > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="音频文件过大")
        else:
            try:
                data = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
            audio_base64 = data.get("audio", "")
            language = data.get("language", "auto")
            if not audio_base64:
                raise HTTPException(status_code=400, detail="未提供音频数据")
            # 上传防呆：base64 编码长度预检（4/3 膨胀 + padding 余量），超限 413
            if len(audio_base64) > _MAX_UPLOAD_BYTES * 4 // 3 + 4:
                raise HTTPException(status_code=413, detail="音频文件过大")
            # L 优化：base64 分支直接 BytesIO，消除落盘回读的 IO 开销
            audio_data = base64.b64decode(audio_base64)
            if len(audio_data) > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="音频文件过大")

        try:
            result = await asr_svc.recognize(audio_data, language)
        except Exception as e:
            logger.error(f"ASR语音识别失败: {e}", exc_info=True)
            raise HTTPException(status_code=502, detail="语音识别失败")

        return {
            "status": "success",
            "text": result.get("text", ""),
            "language": result.get("language", "")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ASR语音识别未预期错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


def _load_tts_config() -> dict:
    """从 UnifiedConfig 读取 TTS 配置（收敛自 legacy config/settings.json）。

    返回 schema 保持与 legacy 兼容：engine 固定 qwen3（Qwen3 统一编排）、
    transition 为固定合成参数；具体值来自 UnifiedConfig.tts。
    """
    from server.config import get_settings

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

    try:
        tts = get_settings().config.tts
        return {
            "engine": "qwen3",
            "ref_audio_path": getattr(tts, "ref_audio_path", "") or "",
            "ref_text": getattr(tts, "ref_text", "") or "",
            "speed": getattr(tts, "speed", 1.0),
            "cross_fade_duration": getattr(tts, "cross_fade_duration", 0.15),
            "emotion_enabled": getattr(tts, "emotion_enabled", True),
            "effects_enabled": getattr(tts, "effects_enabled", True),
            "transition": {
                "enabled": getattr(tts, "transition_enabled", True),
                "duration": 0.5,
                "intensity": 0.7
            }
        }
    except Exception as e:
        logger.warning(f"加载 TTS 配置失败，使用默认配置: {e}")
        return default_config
