"""
F5-TTS 微调 API
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class TrainRequest(BaseModel):
    training_data_dir: Optional[str] = None
    base_model: Optional[str] = None
    epochs: int = 100
    batch_size: int = 4
    learning_rate: float = 1e-4
    output_name: Optional[str] = None


class TrainStatus(BaseModel):
    task_id: Optional[str] = None
    status: str = "idle"
    progress: float = 0.0
    epoch: int = 0
    total_epochs: int = 0
    loss: Optional[float] = None
    message: str = ""


_train_status: dict = {
    "task_id": None,
    "status": "idle",
    "progress": 0.0,
    "epoch": 0,
    "total_epochs": 0,
    "loss": None,
    "message": "",
}

_service_instance: Optional["F5TTSFinetuneService"] = None


def _get_service(**kwargs) -> "F5TTSFinetuneService":
    global _service_instance
    from workstation.services.f5tts_finetune import F5TTSFinetuneService

    if _service_instance is None:
        _service_instance = F5TTSFinetuneService(**kwargs)
    return _service_instance


@router.post("/train")
async def start_training(request: TrainRequest):
    """启动 F5-TTS 微调训练"""
    global _train_status

    if _train_status["status"] == "running":
        return {"status": "error", "message": "训练任务正在进行中"}

    try:
        from workstation.config import get_settings

        settings = get_settings()
        service = _get_service(
            base_model=request.base_model or settings.f5tts_finetune.base_model,
            output_dir=settings.f5tts_finetune.output_dir,
            training_data_dir=request.training_data_dir or settings.f5tts_finetune.training_data_dir,
        )

        task_id = await service.start_training(
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
        logger.error(f"Failed to start F5-TTS training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_training_status():
    """获取训练状态"""
    return _train_status


@router.post("/stop")
async def stop_training():
    """停止训练"""
    try:
        service = _get_service()
        await service.stop_training()
        _train_status["status"] = "stopped"
        return {"status": "success", "message": "训练已停止"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/models")
async def list_models():
    """列出已微调的模型"""
    try:
        from workstation.config import get_settings

        settings = get_settings()
        service = _get_service(output_dir=settings.f5tts_finetune.output_dir)
        models = service.list_models()
        return {"status": "success", "models": models}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _update_train_status(**kwargs):
    global _train_status
    for k, v in kwargs.items():
        if k in _train_status:
            _train_status[k] = v
