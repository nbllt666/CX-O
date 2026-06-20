"""
F5-TTS 微调 API

注意：本模块使用模块级状态 dict 缓存训练状态与 service 实例。
在 FastAPI 多 worker 部署下，每个 worker 进程会持有独立的
_train_status 与 _service_instance，跨进程不同步。

部署要求：必须以单 worker 启动（uvicorn --workers 1），
否则会出现多进程状态不一致、训练任务被多个进程重复启动的问题。
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# 训练数据目录允许的根目录，用户输入的 training_data_dir 必须位于其下
_TRAINING_DATA_ROOT = Path("data/training").resolve()


def _validate_training_data_dir(path: str) -> Path:
    """校验 training_data_dir 必须位于 data/training 根目录之下，
    拒绝绝对路径与 .. 目录穿越，防止创建/读取任意目录。"""
    if not path:
        raise ValueError("training_data_dir must not be empty")
    candidate = Path(path)
    if candidate.is_absolute():
        raise ValueError(
            f"training_data_dir must be a relative path under {_TRAINING_DATA_ROOT}, "
            f"got absolute path: {path}"
        )
    resolved = candidate.resolve()
    if not resolved.is_relative_to(_TRAINING_DATA_ROOT):
        raise ValueError(
            f"training_data_dir must be located under {_TRAINING_DATA_ROOT}, got: {resolved}"
        )
    return resolved


class TrainRequest(BaseModel):
    training_data_dir: Optional[str] = None
    base_model: Optional[str] = None
    epochs: int = Field(100, ge=1, le=100000)
    batch_size: int = Field(4, ge=1)
    learning_rate: float = Field(1e-4, gt=0)
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
_service_kwargs_hash: Optional[str] = None


def _hash_kwargs(kwargs: dict) -> str:
    """对 kwargs 做稳定 hash，用于检测配置变化决定是否重建 service。"""
    payload = json.dumps(kwargs, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_service(rebuild: bool = False, **kwargs) -> "F5TTSFinetuneService":
    """
    获取 F5TTSFinetuneService 稳定单例。

    实例一旦创建即被复用，以保留正在运行的训练进程状态。/stop 与 /models
    复用 /train 创建的同一实例（rebuild=False，直接复用，不重建），避免把
    正在训练的实例替换成新的空实例导致 stop 停不掉真实进程。

    仅 /train 传入 rebuild=True：当配置变化时允许按新配置重建，以支持用
    新配置启动训练。
    """
    global _service_instance, _service_kwargs_hash
    from workstation.services.f5tts_finetune import F5TTSFinetuneService

    new_hash = _hash_kwargs(kwargs)
    if _service_instance is None or (rebuild and _service_kwargs_hash != new_hash):
        _service_instance = F5TTSFinetuneService(**kwargs)
        _service_kwargs_hash = new_hash
    return _service_instance


@router.post("/train")
async def start_training(request: TrainRequest):
    """启动 F5-TTS 微调训练"""

    if _train_status["status"] == "running":
        return {"status": "error", "message": "训练任务正在进行中"}

    try:
        from workstation.config import get_settings

        settings = get_settings()
        training_data_dir = _validate_training_data_dir(
            request.training_data_dir or settings.f5tts_finetune.training_data_dir
        )
        service = _get_service(
            rebuild=True,
            base_model=request.base_model or settings.f5tts_finetune.base_model,
            output_dir=settings.f5tts_finetune.output_dir,
            training_data_dir=str(training_data_dir),
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
        logger.error(f"Failed to stop F5-TTS training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        logger.error(f"Failed to list F5-TTS models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _update_train_status(**kwargs):
    for k, v in kwargs.items():
        if k in _train_status:
            _train_status[k] = v
