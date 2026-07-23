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

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
    # 生成模式：clone（克隆模式，默认）或 design（提示词模式）。
    # 向后兼容：未传 mode 时默认 clone，与历史调用方行为一致。
    mode: str = "clone"
    # 克隆模式高级选项：启用极致克隆（参考音频 + 文本续写）。仅在 clone 模式下生效。
    ultimate_clone: bool = False


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
    """预生成所有参考音频（8 情感 + 56 过渡，基于 VoxCPM）。

    支持两种模式：
    - clone（默认）：以 base_audio_path 为参考通过可控声音克隆生成情感参考音频；
      ultimate_clone=True 时改用极致克隆。
    - design：先用音色设计创建基础参考音频，再通过可控声音克隆生成情感参考音频。

    生成在后台异步执行，通过 GET /status 轮询进度与结果。
    """
    global _pregenerate_status
    if _pregenerate_status["is_running"]:
        raise HTTPException(
            status_code=409,
            detail="已有预生成任务正在运行，请通过 GET /status 查询进度",
        )

    if request.mode not in ("clone", "design"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {request.mode!r}, expected 'clone' or 'design'",
        )
    if request.ultimate_clone and request.mode != "clone":
        raise HTTPException(
            status_code=400,
            detail="ultimate_clone 仅在 clone 模式下可用",
        )

    _pregenerate_status = {
        "is_running": True,
        "progress": None,
        "result": None,
        "error": None,
    }
    asyncio.create_task(_run_pregenerate(request))
    return {"status": "running", "result": None}


@router.get("/status")
async def get_pregenerate_status():
    """获取参考音频生成状态"""
    return _pregenerate_status


@router.post("/export-zip")
async def export_zip(request: PregenerateRequest):
    """生成全部参考音频并打包为 zip 下载。

    复用已生成的参考音频（force=False 时跳过已存在文件），打包为 emotion_refs.zip 返回。
    """
    if request.mode not in ("clone", "design"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {request.mode!r}, expected 'clone' or 'design'",
        )
    if request.ultimate_clone and request.mode != "clone":
        raise HTTPException(
            status_code=400,
            detail="ultimate_clone 仅在 clone 模式下可用",
        )

    from workstation.services.emotion_ref_generator import EmotionRefGenerator
    from workstation.config import get_settings

    settings = get_settings()
    gen = EmotionRefGenerator(output_dir=settings.output.voice_refs_dir)
    try:
        zip_path = await gen.generate_and_pack_zip(
            base_audio_path=request.base_audio_path,
            sample_text=request.sample_text,
            transition_text=request.transition_text,
            force=request.force,
            mode=request.mode,
            ultimate_clone=request.ultimate_clone,
        )
    except Exception as e:
        logger.error(f"Failed to export emotion refs zip: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename="emotion_refs.zip",
    )


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
    _pregenerate_status["progress"] = {
        "current": current,
        "total": total,
        "message": message,
    }


async def _run_pregenerate(request: PregenerateRequest) -> None:
    """后台执行预生成任务，更新模块级 _pregenerate_status。"""
    global _pregenerate_status
    try:
        from workstation.services.emotion_ref_generator import EmotionRefGenerator
        from workstation.config import get_settings

        settings = get_settings()
        gen = EmotionRefGenerator(output_dir=settings.output.voice_refs_dir)
        result = await gen.generate_all(
            base_audio_path=request.base_audio_path,
            sample_text=request.sample_text,
            transition_text=request.transition_text,
            force=request.force,
            mode=request.mode,
            ultimate_clone=request.ultimate_clone,
            progress_callback=_update_progress,
        )
        _pregenerate_status["result"] = result
        _pregenerate_status["is_running"] = False
        logger.info(f"Pregenerate completed: {result}")
    except Exception as e:
        _pregenerate_status["error"] = str(e)
        _pregenerate_status["is_running"] = False
        logger.error(f"Pregenerate failed: {e}", exc_info=True)
