"""
参考音频生成 API
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class PregenerateRequest(BaseModel):
    base_audio_path: str
    sample_text: str = "这是参考音频样本。"
    transition_text: str = "嗯，"
    force: bool = False


class PregenerateStatus(BaseModel):
    is_running: bool
    progress: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[str] = None


_pregenerate_status: dict = {
    "is_running": False,
    "progress": None,
    "result": None,
    "error": None
}


@router.post("/pregenerate")
async def pregenerate_refs(request: PregenerateRequest):
    """预生成所有 64 个参考音频（8 情感 + 56 过渡）"""
    global _pregenerate_status

    if _pregenerate_status["is_running"]:
        return {"status": "error", "message": "生成任务正在进行中"}

    _pregenerate_status = {
        "is_running": True,
        "progress": {"current": 0, "total": 64, "message": "开始生成..."},
        "result": None,
        "error": None
    }

    try:
        from workstation.services.emotion_ref_generator import EmotionRefGenerator
        from workstation.config import get_settings

        settings = get_settings()
        generator = EmotionRefGenerator(
            cosyvoice_url=settings.cosyvoice.url,
            output_dir=settings.output.voice_refs_dir,
        )

        result = await generator.generate_all(
            base_audio_path=request.base_audio_path,
            sample_text=request.sample_text,
            transition_text=request.transition_text,
            force=request.force,
            progress_callback=lambda c, t, m: _update_progress(c, t, m),
        )

        _pregenerate_status["is_running"] = False
        _pregenerate_status["result"] = result
        _pregenerate_status["progress"] = {"current": 64, "total": 64, "message": "生成完成"}

        return {"status": "success", "result": result}

    except Exception as e:
        logger.error(f"Failed to pregenerate refs: {e}")
        _pregenerate_status["is_running"] = False
        _pregenerate_status["error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_pregenerate_status():
    """获取参考音频生成状态"""
    return _pregenerate_status


@router.get("/cosyvoice/status")
async def get_cosyvoice_status():
    """获取 CosyVoice 服务状态"""
    try:
        from workstation.services.cosyvoice_client import CosyVoiceClient
        from workstation.config import get_settings

        settings = get_settings()
        client = CosyVoiceClient(base_url=settings.cosyvoice.url)
        healthy = await client.health_check()
        await client.close()

        return {"status": "healthy" if healthy else "unhealthy", "url": settings.cosyvoice.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/index-tts/status")
async def get_index_tts_status():
    """获取 IndexTTS 服务状态"""
    try:
        from workstation.services.index_tts_client import IndexTTSClient
        from workstation.config import get_settings

        settings = get_settings()
        client = IndexTTSClient(base_url=settings.index_tts.url)
        healthy = await client.health_check()
        await client.close()

        return {"status": "healthy" if healthy else "unhealthy", "url": settings.index_tts.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/index-tts/synthesize")
async def index_tts_synthesize(request: Request):
    """使用 IndexTTS 合成音频"""
    try:
        data = await request.json()
        text = data.get("text", "")
        if not text:
            return {"status": "error", "message": "Text is required"}

        from workstation.services.index_tts_client import IndexTTSClient
        from workstation.config import get_settings

        settings = get_settings()
        client = IndexTTSClient(base_url=settings.index_tts.url, timeout=settings.index_tts.timeout)

        audio_bytes = await client.synthesize(
            text=text,
            emotion=data.get("emotion", "neutral"),
            emotion_intensity=data.get("emotion_intensity", 0.5),
            speed=data.get("speed", 1.0),
            pitch=data.get("pitch", 0.0),
        )
        await client.close()

        import base64
        return {
            "status": "success",
            "audio_data": base64.b64encode(audio_bytes).decode("utf-8"),
            "format": "wav"
        }
    except Exception as e:
        logger.error(f"IndexTTS synthesize error: {e}")
        return {"status": "error", "message": str(e)}


def _update_progress(current: int, total: int, message: str):
    global _pregenerate_status
    _pregenerate_status["progress"] = {
        "current": current,
        "total": total,
        "message": message,
    }
