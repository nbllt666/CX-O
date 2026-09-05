"""
So-VITS-SVC 训练/试听推理 API

注意：本模块使用模块级状态 dict 缓存训练状态与 trainer 实例。
在 FastAPI 多 worker 部署下，每个 worker 进程会持有独立的
_train_status 与 _trainer_instance，跨进程不同步。

部署要求：必须以单 worker 启动（uvicorn --workers 1），
否则会出现多进程状态不一致、训练任务被多个进程重复启动的问题。

自 CX-O-VoiceWorkStation/workstation/api/sovits_svc.py 迁移
（change-id: split-audio-workstation-cxfc-modelstation）：
- 模型输出目录改用 models_dir；试听推理输出目录改用 audition_dir；
- infer 输入白名单 = 训练数据目录 ∪ data/input；
- audio_url 挂 audition category（/api/audio-files/audition/...）。

跨类型训练互斥接线（change-id: extend-modelstation-standalone-melotts-datasets，
spec「MeloTTS 微调训练」：sovits 侧 train 入口消费共享互斥原语）：
- train 端点在本地 _train_lock 闸门之后消费 try_begin_training("sovits_svc")；
  melotts 占用时 409 返回当前训练类型与 task_id；
- 出口点清单（end_training("sovits_svc")，全部幂等）：
  1) train 端点启动异常路径（except）；
  2) _update_train_status 收到监控终态 completed/failed（trainer 完成/失败回调）；
  3) stop 端点 trainer.stop_training() 成功后。
- sovits 独占场景行为不变（成功路径语义与现状完全兼容）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from modelstation.services.security_utils import validate_training_data_dir
from modelstation.services.training_mutex import (
    TRAINING_SOVITS_SVC,
    end_training,
    try_begin_training,
    update_training_task,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SVCPreprocessRequest(BaseModel):
    training_data_dir: str
    speaker_name: str = "speaker"


class SVCTrainRequest(BaseModel):
    epochs: int = Field(10000, ge=1, le=100000)
    batch_size: int = Field(4, ge=1)
    learning_rate: float = Field(1e-4, gt=0)
    output_name: Optional[str] = None
    # 说话人名称透传；None 时 trainer 走默认 "speaker"（sovits_svc_trainer.start_training）
    speaker_name: Optional[str] = None


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

# 保护 _train_status 判空 + 置忙状态的原子性（防并发双请求都通过闸门）
_train_lock = threading.Lock()

_trainer_instance: Optional["SoVITSSVCTrainer"] = None
_trainer_kwargs_hash: Optional[str] = None


def _hash_kwargs(kwargs: dict) -> str:
    """对 kwargs 做稳定 hash，用于检测配置变化决定是否重建 trainer。"""
    payload = json.dumps(kwargs, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_trainer(rebuild: bool = False) -> "SoVITSSVCTrainer":
    """
    获取 SoVITSSVCTrainer 稳定单例。

    模块级单例：复用同一个实例，保留 `_preprocessed` 已预处理 speaker 集合
    以及运行中的训练进程状态。workflow.py 等其它模块也通过 get_sovits_trainer()
    复用同一实例，避免跨接口因状态不共享误报 "Preprocessing must be completed"。

    仅当 rebuild=True 且配置发生变化时才重建实例，以支持用新配置启动训练。
    """
    global _trainer_instance, _trainer_kwargs_hash
    from modelstation.services.sovits_svc_trainer import SoVITSSVCTrainer
    from modelstation.config import get_settings

    settings = get_settings()
    kwargs = {
        "output_dir": settings.sovits_svc.models_dir,
        "training_data_dir": settings.sovits_svc.training_data_dir,
        "so_vits_svc_dir": settings.sovits_svc.so_vits_svc_dir,
        "python_path": settings.sovits_svc.python_path,
    }
    new_hash = _hash_kwargs(kwargs)
    if _trainer_instance is None or (rebuild and _trainer_kwargs_hash != new_hash):
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
        training_data_dir = validate_training_data_dir(request.training_data_dir)
        results = await trainer.preprocess(
            training_data_dir=str(training_data_dir),
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


def _training_conflict_detail(current: Optional[dict]) -> dict:
    """跨类型互斥 409 响应体：携带当前训练类型与任务标识（spec 冻结语义）。"""
    holder = dict(current or {})
    return {
        "message": "训练任务正在进行中",
        "current_training": {
            "owner_type": holder.get("owner_type"),
            "task_id": holder.get("task_id"),
            "started_at": holder.get("started_at"),
        },
    }


@router.post("/train")
async def start_training(request: SVCTrainRequest):
    """启动 So-VITS-SVC 训练"""

    # 判空与置 busy 在同一临界区内原子完成，防止并发第二个请求在判空与
    # start_training 之间的空档再次进入（双请求都读到 idle 都放行）。
    with _train_lock:
        already_running = _train_status["status"] in ("running", "busy_starting")
        if not already_running:
            _train_status["status"] = "busy_starting"

    if already_running:
        raise HTTPException(status_code=409, detail="训练任务正在进行中")

    # 跨类型训练互斥（change-id: extend-modelstation-standalone-melotts-datasets）：
    # 本地状态闸门之后消费共享原语；melotts 占用时 409 返回当前训练类型与 task_id。
    # task_id 由 trainer 内部生成，此处先以 None 占位，start_training 返回后回填。
    mutex_ok, mutex_current = try_begin_training(TRAINING_SOVITS_SVC, None)
    if not mutex_ok:
        _train_status["status"] = "idle"
        raise HTTPException(status_code=409, detail=_training_conflict_detail(mutex_current))

    try:
        trainer = _get_trainer()

        task_id = await trainer.start_training(
            epochs=request.epochs,
            batch_size=request.batch_size,
            learning_rate=request.learning_rate,
            output_name=request.output_name,
            speaker_name=request.speaker_name,
            progress_callback=lambda **kw: _update_train_status(**kw),
        )

        # 回填真实 task_id（409 冲突响应可追溯；占用期间回填失败则保留占位 None）
        update_training_task(TRAINING_SOVITS_SVC, task_id)

        _train_status["task_id"] = task_id
        _train_status["status"] = "running"

        return {"status": "success", "task_id": task_id, "message": "训练已启动"}

    except Exception as e:
        # 启动失败/异常：复位忙状态 + 释放跨类型互斥（幂等），允许后续重试
        _train_status["status"] = "idle"
        end_training(TRAINING_SOVITS_SVC)
        logger.error(f"Failed to start So-VITS-SVC training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_training_status():
    """获取训练状态（附带已训练模型列表；models 获取失败时降级为空列表，
    不影响训练状态本身的查询）"""
    try:
        trainer = _get_trainer()
        models = trainer.list_models()
    except Exception as e:
        logger.warning(f"Failed to list So-VITS-SVC models for status: {e}")
        models = []
    return {**_train_status, "models": models}


@router.post("/stop")
async def stop_training():
    """停止训练"""
    try:
        trainer = _get_trainer()
        await trainer.stop_training()
        _train_status["status"] = "stopped"
        # stop 出口释放跨类型互斥（幂等：trainer 完成/失败回调已释放时无害）
        end_training(TRAINING_SOVITS_SVC)
        return {"status": "success", "message": "训练已停止"}
    except Exception as e:
        logger.error(f"Failed to stop So-VITS-SVC training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/infer")
async def infer(request: SVCInferRequest):
    """So-VITS-SVC 试听推理（对训练好的模型做推理验证，输出至 audition 受控目录）"""
    try:
        from modelstation.services.sovits_svc_infer import SoVITSSVCInferer
        from modelstation.config import get_settings

        settings = get_settings()
        inferer = SoVITSSVCInferer(
            model_path=request.model_path,
            output_dir=settings.sovits_svc.audition_dir,
            so_vits_svc_dir=settings.sovits_svc.so_vits_svc_dir,
            python_path=settings.sovits_svc.python_path,
            models_dir=settings.sovits_svc.models_dir,
            # infer 输入白名单根 = 训练数据目录 ∪ data/input（spec 冻结）
            allowed_audio_roots=[
                settings.sovits_svc.training_data_dir,
                settings.sovits_svc.input_dir,
            ],
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
            "audio_url": f"/api/audio-files/audition/{result_path.name}",
        }
    except ValueError as e:
        # 参数校验失败（非法路径/非法模型路径等）→ 400
        logger.warning(f"So-VITS-SVC infer invalid request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        logger.warning(f"So-VITS-SVC infer resource not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"So-VITS-SVC infer error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def list_models():
    """列出已训练的模型"""
    try:
        trainer = _get_trainer()
        models = trainer.list_models()
        return {"status": "success", "models": models}
    except Exception as e:
        logger.error(f"Failed to list So-VITS-SVC models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _update_train_status(**kwargs):
    for k, v in kwargs.items():
        if k in _train_status:
            _train_status[k] = v
    # trainer 完成/失败回调出口：监控终态（completed/failed）到达时释放跨类型互斥。
    # 仅该出口需要判断——逐 epoch 进度回调不带 status 键，重复 end_training 幂等无害。
    if kwargs.get("status") in ("completed", "failed"):
        end_training(TRAINING_SOVITS_SVC)
