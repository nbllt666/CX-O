"""
So-VITS-SVC 训练/推理 API

注意：本模块使用模块级状态 dict 缓存训练状态与 trainer 实例。
在 FastAPI 多 worker 部署下，每个 worker 进程会持有独立的
_train_status 与 _trainer_instance，跨进程不同步。

部署要求：必须以单 worker 启动（uvicorn --workers 1），
否则会出现多进程状态不一致、训练任务被多个进程重复启动的问题。
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class SVCPreprocessRequest(BaseModel):
    training_data_dir: str
    speaker_name: str = "speaker"


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
    cluster_model_path: Optional[str] = None


_train_status: dict = {
    "task_id": None,
    "status": "idle",
    "progress": 0.0,
    "epoch": 0,
    "total_epochs": 0,
    "message": "",
}

_trainer_instance: Optional["SoVITSSVCTrainer"] = None
_trainer_kwargs_hash: Optional[str] = None


def _hash_kwargs(kwargs: dict) -> str:
    """对 kwargs 做稳定 hash，用于检测配置变化决定是否重建 trainer。"""
    payload = json.dumps(kwargs, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_trainer() -> "SoVITSSVCTrainer":
    """
    获取 SoVITSSVCTrainer 稳定单例。

    模块级单例：复用同一个实例，保留 `_preprocessed` 已预处理 speaker 集合
    以及运行中的训练进程状态。workflow.py 等其它模块也通过 get_sovits_trainer()
    复用同一实例，避免跨接口因状态不共享误报 "Preprocessing must be completed"。
    """
    global _trainer_instance, _trainer_kwargs_hash
    from workstation.services.sovits_svc_trainer import SoVITSSVCTrainer
    from workstation.config import get_settings

    settings = get_settings()
    kwargs = {
        "output_dir": settings.sovits_svc.output_dir,
        "training_data_dir": settings.sovits_svc.training_data_dir,
        "so_vits_svc_dir": settings.sovits_svc.so_vits_svc_dir,
        "python_path": settings.sovits_svc.python_path,
    }
    new_hash = _hash_kwargs(kwargs)
    if _trainer_instance is None:
        _trainer_instance = SoVITSSVCTrainer(**kwargs)
        _trainer_kwargs_hash = new_hash
    return _trainer_instance


def get_sovits_trainer() -> "SoVITSSVCTrainer":
    """对外导出的共享单例获取入口，供 workflow 等模块复用同一 trainer 实例。"""
    return _get_trainer()


@router.post("/preprocess")
async def preprocess(request: SVCPreprocessRequest):
    """So-VITS-SVC 数据预处理"""
    try:
        trainer = _get_trainer()
        results = await trainer.preprocess(
            training_data_dir=request.training_data_dir,
            speaker_name=request.speaker_name,
        )
        all_success = all(v.get("success", False) for v in results.values())
        return {
            "status": "success" if all_success else "partial",
            "results": results,
        }
    except Exception as e:
        logger.error(f"So-VITS-SVC preprocess error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/train")
async def start_training(request: SVCTrainRequest):
    """启动 So-VITS-SVC 训练"""
    global _train_status

    if _train_status["status"] == "running":
        return {"status": "error", "message": "训练任务正在进行中"}

    try:
        trainer = _get_trainer()

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
        trainer = _get_trainer()
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
        trainer = _get_trainer()
        models = trainer.list_models()
        return {"status": "success", "models": models}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _update_train_status(**kwargs):
    global _train_status
    for k, v in kwargs.items():
        if k in _train_status:
            _train_status[k] = v
