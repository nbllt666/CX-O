"""
参考音频生成 API

注意：本模块使用模块级状态 dict 缓存预生成状态（_pregenerate_status）。
在 FastAPI 多 worker 部署下，每个 worker 进程会持有独立的
_pregenerate_status，跨进程不同步，外部请求只能命中其中一个 worker。

部署要求：必须以单 worker 启动（uvicorn --workers 1），
否则前端轮询 /status 可能拿到陈旧或不准确的状态。
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

logger = logging.getLogger(__name__)
router = APIRouter()

# import_zip 上传大小限制 (100MB)
_IMPORT_ZIP_MAX_SIZE = 100 * 1024 * 1024
# ZIP 文件 magic number: PK\x03\x04
_ZIP_MAGIC_NUMBER = b"PK\x03\x04"


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

    # 使用 clear() + update() 在原 dict 上原地重置状态，避免 lambda 闭包/前端缓存
    # 持有旧对象引用后出现数据不同步的问题。
    _pregenerate_status.clear()
    _pregenerate_status.update({
        "is_running": True,
        "progress": {"current": 0, "total": 64, "message": "开始生成..."},
        "result": None,
        "error": None,
    })

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

    except BaseException as e:
        # 捕获 BaseException 以确保 asyncio.CancelledError / KeyboardInterrupt 等
        # 也会被处理，避免 _pregenerate_status["is_running"] 永远为 True 导致状态卡死。
        if isinstance(e, asyncio.CancelledError):
            logger.warning(f"pregenerate_refs cancelled: {e}")
        else:
            logger.error(f"Failed to pregenerate refs: {e}")
        _pregenerate_status["is_running"] = False
        _pregenerate_status["error"] = str(e) if e else "cancelled"
        if isinstance(e, asyncio.CancelledError):
            # 不将 CancelledError 转换为 HTTPException，重新抛出由上层处理
            raise
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_pregenerate_status():
    """获取参考音频生成状态"""
    return _pregenerate_status


@router.get("/cosyvoice/status")
async def get_cosyvoice_status():
    """获取 CosyVoice 服务状态"""
    client = None
    try:
        from workstation.services.cosyvoice_client import CosyVoiceClient
        from workstation.config import get_settings

        settings = get_settings()
        client = CosyVoiceClient(base_url=settings.cosyvoice.url)
        healthy = await client.health_check()
        return {"status": "healthy" if healthy else "unhealthy", "url": settings.cosyvoice.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"Failed to close CosyVoice client: {e}")


@router.get("/index-tts/status")
async def get_index_tts_status():
    """获取 IndexTTS 服务状态"""
    client = None
    try:
        from workstation.services.index_tts_client import IndexTTSClient
        from workstation.config import get_settings

        settings = get_settings()
        client = IndexTTSClient(base_url=settings.index_tts.url)
        healthy = await client.health_check()
        return {"status": "healthy" if healthy else "unhealthy", "url": settings.index_tts.url}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"Failed to close IndexTTS client: {e}")


@router.post("/index-tts/synthesize")
async def index_tts_synthesize(request: Request):
    """使用 IndexTTS 合成音频"""
    client = None
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

        import base64
        return {
            "status": "success",
            "audio_data": base64.b64encode(audio_bytes).decode("utf-8"),
            "format": "wav"
        }
    except Exception as e:
        logger.error(f"IndexTTS synthesize error: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                logger.warning(f"Failed to close IndexTTS client: {e}")


@router.post("/export-zip")
async def export_zip(request: PregenerateRequest):
    zip_path: Optional[str] = None
    try:
        from workstation.services.emotion_ref_generator import EmotionRefGenerator
        from workstation.config import get_settings

        settings = get_settings()
        generator = EmotionRefGenerator(
            cosyvoice_url=settings.cosyvoice.url,
            output_dir=settings.output.voice_refs_dir,
        )

        zip_path = await generator.generate_and_pack_zip(
            base_audio_path=request.base_audio_path,
            sample_text=request.sample_text,
            transition_text=request.transition_text,
            force=request.force,
        )

        def iter_file():
            with open(zip_path, "rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk

        def _cleanup_zip():
            if zip_path and os.path.exists(zip_path):
                try:
                    os.unlink(zip_path)
                    logger.debug(f"Cleaned up exported zip: {zip_path}")
                except OSError as e:
                    logger.warning(f"Failed to delete exported zip {zip_path}: {e}")

        return StreamingResponse(
            iter_file(),
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=emotion_refs.zip",
            },
            background=BackgroundTask(_cleanup_zip),
        )
    except Exception as e:
        # 若流式响应尚未开始，先主动清理临时 zip 文件
        if zip_path and os.path.exists(zip_path):
            try:
                os.unlink(zip_path)
            except OSError:
                pass
        logger.error(f"Failed to export zip: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import-zip")
async def import_zip(file: UploadFile = File(...)):
    try:
        from workstation.services.emotion_ref_generator import EmotionRefGenerator
        from workstation.config import get_settings

        settings = get_settings()

        # 先读取并校验大小限制
        content = await file.read()
        if len(content) > _IMPORT_ZIP_MAX_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"Uploaded file too large: {len(content)} > {_IMPORT_ZIP_MAX_SIZE} bytes",
            )

        # 校验 ZIP 文件头 magic number
        if not content.startswith(_ZIP_MAGIC_NUMBER):
            raise HTTPException(
                status_code=400,
                detail="Invalid file type: not a valid ZIP archive (magic number mismatch)",
            )

        # 使用 mkstemp 创建临时文件，文件句柄显式关闭确保 Windows 下不被占用
        fd, tmp_path = tempfile.mkstemp(suffix=".zip")
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(content)

            output_dir = settings.output.voice_refs_dir
            meta = EmotionRefGenerator.import_from_zip(tmp_path, output_dir)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return {"status": "success", "meta": meta}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import zip: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _update_progress(current: int, total: int, message: str):
    global _pregenerate_status
    _pregenerate_status["progress"] = {
        "current": current,
        "total": total,
        "message": message,
    }
