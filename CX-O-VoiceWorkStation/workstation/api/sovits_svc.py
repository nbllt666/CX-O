"""
So-VITS-SVC 推理与模型列表 API

瘦身后职责（spec：split-audio-workstation-cxfc-modelstation）：
- POST /infer  ：翻唱变声推理（输入白名单根 data/input/ 等，输出落 infer_output_dir）
- GET  /models ：模型列表（只读扫描 ModelStation 模型目录 models_dir）

训练全链路（preprocess/train/stop/status）与 trainer 单例已迁至
CXO-ModelStation（端口 8300），本模块不再持有任何训练状态。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class SVCInferRequest(BaseModel):
    audio_path: str
    model_path: Optional[str] = None
    speaker_id: int = 0
    transpose: int = 0
    cluster_model_path: Optional[str] = None


@router.post("/infer")
async def infer(request: SVCInferRequest):
    """So-VITS-SVC 推理（翻唱变声）"""
    try:
        from workstation.services.sovits_svc_infer import SoVITSSVCInferer
        from workstation.config import get_settings

        settings = get_settings()
        inferer = SoVITSSVCInferer(
            model_path=request.model_path,
            output_dir=settings.sovits_svc.infer_output_dir,
            models_dir=settings.sovits_svc.models_dir,
            so_vits_svc_dir=settings.sovits_svc.so_vits_svc_dir,
            python_path=settings.sovits_svc.python_path,
        )

        result_path = await inferer.infer(
            audio_path=request.audio_path,
            speaker_id=request.speaker_id,
            transpose=request.transpose,
            model_path=request.model_path,
            cluster_model_path=request.cluster_model_path,
        )

        return {
            "status": "success",
            "output_filename": result_path.name,
            "audio_url": f"/api/audio-files/svc-results/{result_path.name}",
        }
    except Exception as e:
        logger.error(f"So-VITS-SVC infer error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _scan_models(models_dir: Path) -> list[dict]:
    """扫描模型目录，返回与原 trainer.list_models() 相同形状的列表。

    形状契约（保持不变，主前端/模型工作站均按此消费）：
    每个子目录一项 {name, path, created, g_model, d_model}，
    G_*/D_*.pth 取 mtime 最新者；按 created 倒序。
    """
    models: list[dict] = []
    if models_dir.exists():
        for d in models_dir.iterdir():
            if not d.is_dir():
                continue
            g_files = sorted(d.glob("G_*.pth"), key=lambda p: p.stat().st_mtime)
            d_files = sorted(d.glob("D_*.pth"), key=lambda p: p.stat().st_mtime)
            if g_files or d_files:
                models.append({
                    "name": d.name,
                    "path": str(d),
                    "created": d.stat().st_mtime,
                    "g_model": str(g_files[-1]) if g_files else None,
                    "d_model": str(d_files[-1]) if d_files else None,
                })
    models.sort(key=lambda m: m["created"], reverse=True)
    return models


@router.get("/models")
async def list_models():
    """列出可用模型（只读扫描 ModelStation 模型目录）"""
    try:
        from workstation.config import get_settings

        settings = get_settings()
        models = _scan_models(Path(settings.sovits_svc.models_dir))
        return {"status": "success", "models": models}
    except Exception as e:
        logger.error(f"Failed to list So-VITS-SVC models: {e}")
        raise HTTPException(status_code=500, detail=str(e))
