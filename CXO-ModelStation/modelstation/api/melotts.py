"""
MeloTTS 训练/数据准备 API

端点形状与 api/sovits_svc.py 同构（spec 冻结）：
- POST /preprocess  数据准备（统一数据集 manifest v2 → MeloTTS filelist）
- POST /train       启动微调训练（跨类型互斥：占用时 409 携带当前训练类型与 task_id）
- POST /stop        停止训练
- GET  /status      训练状态（附带模型列表；列表失败降级为空列表）
- GET  /models      已训练模型列表（形状对齐 sovits /models）

infer 不在本期范围（MeloTTS 试听留待后续，spec Task 3.3）。

注意：本模块使用模块级状态（trainer 单例与 trainer 侧 _train_status）。
部署要求：单 worker（uvicorn --workers 1），跨进程状态不同步。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modelstation.services.melotts_dataset_prep import prepare_filelists
from modelstation.services.melotts_trainer import (
    MelottsEngineNotReadyError,
    TrainingInProgressError,
    get_trainer,
    get_train_status,
)
from modelstation.services.security_utils import validate_training_data_dir

logger = logging.getLogger(__name__)
router = APIRouter()


class MelottsPreprocessRequest(BaseModel):
    dataset_dir: str
    # filelist 说话人名；缺省取 dataset_dir 目录名（清洗语义与 dataset_builder 一致）
    speaker_name: Optional[str] = None
    # 语言代码（filelist 第三列）；缺省取 config.melotts.language
    language: Optional[str] = None


class MelottsTrainRequest(BaseModel):
    # 默认值取 MeloTTS 上游 melo/configs/config.json 实码（epochs=10000/batch=6/lr=3e-4）
    epochs: int = Field(10000, ge=1, le=100000)
    batch_size: int = Field(6, ge=1)
    learning_rate: float = Field(3e-4, gt=0)
    output_name: Optional[str] = None
    language: Optional[str] = None
    # 预训练基础模型（G checkpoint）路径；缺省用 config.melotts.base_checkpoint，
    # 为空时由 MeloTTS 管线走官方默认预训练模型下载
    base_checkpoint: Optional[str] = None


def _conflict_detail(current: Optional[dict]) -> dict:
    """409 响应体：携带当前训练类型与任务标识（spec 冻结语义）。"""
    holder = dict(current or {})
    return {
        "message": "训练任务正在进行中",
        "current_training": {
            "owner_type": holder.get("owner_type"),
            "task_id": holder.get("task_id"),
            "started_at": holder.get("started_at"),
        },
    }


@router.post("/preprocess")
async def preprocess(request: MelottsPreprocessRequest):
    """MeloTTS 数据准备：统一数据集（manifest v2）→ train/val filelist"""
    try:
        # 集中校验 dataset_dir 必须位于 data/training 之下（防目录穿越/任意路径）
        validated_dir = validate_training_data_dir(request.dataset_dir)
        kwargs = {"dataset_dir": str(validated_dir)}
        if request.speaker_name is not None:
            kwargs["speaker_name"] = request.speaker_name
        if request.language is not None:
            kwargs["language"] = request.language
        stats = prepare_filelists(**kwargs)
        return {"status": "success", "stats": stats}
    except ValueError as e:
        logger.warning(f"MeloTTS preprocess invalid request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"MeloTTS preprocess error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/train")
async def start_training(request: MelottsTrainRequest):
    """启动 MeloTTS 微调训练（跨类型互斥：sovits/melotts 共享单一训练槽位）"""
    try:
        trainer = get_trainer()
        kwargs = {
            "epochs": request.epochs,
            "batch_size": request.batch_size,
            "learning_rate": request.learning_rate,
        }
        if request.output_name is not None:
            kwargs["output_name"] = request.output_name
        if request.language is not None:
            kwargs["language"] = request.language
        if request.base_checkpoint is not None:
            kwargs["base_checkpoint"] = request.base_checkpoint
        task_id = await trainer.start_training(**kwargs)
        return {"status": "success", "task_id": task_id, "message": "训练已启动"}
    except TrainingInProgressError as e:
        logger.warning(f"MeloTTS train conflict: {e}")
        raise HTTPException(status_code=409, detail=_conflict_detail(e.current))
    except MelottsEngineNotReadyError as e:
        # 未就绪（引擎缺失/依赖缺失）：明确报错含 setup 指引（spec 冻结）
        logger.error(f"MeloTTS engine not ready: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except (FileNotFoundError, ValueError) as e:
        logger.warning(f"MeloTTS train invalid request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start MeloTTS training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_training():
    """停止训练"""
    try:
        trainer = get_trainer()
        await trainer.stop_training()
        return {"status": "success", "message": "训练已停止"}
    except Exception as e:
        logger.error(f"Failed to stop MeloTTS training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_status():
    """获取训练状态（附带已训练模型列表；models 获取失败时降级为空列表）"""
    try:
        trainer = get_trainer()
        models = trainer.list_models()
    except Exception as e:
        logger.warning(f"Failed to list MeloTTS models for status: {e}")
        models = []
    return {**get_train_status(), "models": models}


@router.get("/models")
async def list_models():
    """列出已训练的模型"""
    try:
        trainer = get_trainer()
        models = trainer.list_models()
        return {"status": "success", "models": models}
    except Exception as e:
        logger.error(f"Failed to list MeloTTS models: {e}")
        raise HTTPException(status_code=500, detail=str(e))
