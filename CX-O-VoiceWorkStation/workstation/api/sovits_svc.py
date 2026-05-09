"""
So-VITS-SVC 训练/推理 API
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class SVCTrainRequest(BaseModel):
    training_data_dir: Optional[str] = None
    epochs: int = 10000
    batch_size: int = 4
    learning_rate: float = 1e-4
    output_name: Optional[str] = None


class SVCInferRequest(BaseModel):
    audio_path: str
    model_path: Optional[str] = None
    speaker_id: int = 0
    transpose: int = 0


_train_status: dict = {
    "task_id": None,
    "status": "idle",
    "progress": 0.0,
    "epoch": 0,
    "total_epochs": 0,
    "message": "",
}


@router.post("/train")
async def start_training(request: SVCTrainRequest):
    """启动 So-VITS-SVC 训练"""
    global _train_status

    if _train_status["status"] == "running":
        return {"status": "error", "message": "训练任务正在进行中"}

    try:
        from workstation.services.sovits_svc_trainer import SoVITSSVCTrainer
        from workstation.config import get_settings

        settings = get_settings()
        trainer = SoVITSSVCTrainer(
            output_dir=settings.sovits_svc.output_dir,
            training_data_dir=request.training_data_dir or settings.sovits_svc.training_data_dir,
        )

        task_id = await trainer.start_training(
            epochs=request.epochs,
            batch_size=request.batch_size,
            learning_rate=request.learning_rate,
            output_name=request.output_name,
            progress_callback=lambda **kw: _update_train_status(**kw),
        )

        _train_status["task_id"] = task_id
        _train_status["status"] = "running"

        return {"status": "success", "task_id": task_id, "message": "训练已启动"}

    except Exception as e:
        logger.error(f"Failed to start So-VITS-SVC training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_training_status():
    """获取训练状态"""
    return _train_status


@router.post("/stop")
async def stop_training():
    """停止训练"""
    try:
        from workstation.services.sovits_svc_trainer import SoVITSSVCTrainer
        trainer = SoVITSSVCTrainer()
        await trainer.stop_training()
        _train_status["status"] = "stopped"
        return {"status": "success", "message": "训练已停止"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/infer")
async def infer(request: SVCInferRequest):
    """So-VITS-SVC 推理"""
    try:
        from workstation.services.sovits_svc_infer import SoVITSSVCInferer
        from workstation.config import get_settings

        settings = get_settings()
        inferer = SoVITSSVCInferer(
            model_path=request.model_path,
            output_dir=settings.sovits_svc.output_dir,
        )

        result_path = await inferer.infer(
            audio_path=request.audio_path,
            speaker_id=request.speaker_id,
            transpose=request.transpose,
        )

        import base64
        with open(result_path, "rb") as f:
            audio_data = f.read()

        return {
            "status": "success",
            "audio_data": base64.b64encode(audio_data).decode("utf-8"),
            "format": "wav",
            "output_path": str(result_path),
        }
    except Exception as e:
        logger.error(f"So-VITS-SVC infer error: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/models")
async def list_models():
    """列出已训练的模型"""
    try:
        from workstation.services.sovits_svc_trainer import SoVITSSVCTrainer
        from workstation.config import get_settings

        settings = get_settings()
        trainer = SoVITSSVCTrainer(output_dir=settings.sovits_svc.output_dir)
        models = trainer.list_models()
        return {"status": "success", "models": models}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _update_train_status(**kwargs):
    global _train_status
    for k, v in kwargs.items():
        if k in _train_status:
            _train_status[k] = v
