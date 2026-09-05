"""
工作流 API

注意：本模块使用模块级状态 dict 缓存工作流状态（_workflow_state）
与 SoVITS trainer 实例（_sovits_trainer_instance）。
在 FastAPI 多 worker 部署下，每个 worker 进程会持有独立的工作流状态，
跨进程不同步。

部署要求：必须以单 worker 启动（uvicorn --workers 1），
否则前端的步骤状态、训练进度只能命中其中一个 worker，
可能导致状态显示与实际执行不一致。
"""
from __future__ import annotations

import asyncio
import copy
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter()

_workflow_state: dict = {
    "current_step": 0,
    "steps": [
        {"id": "train_prep", "name": "训练数据准备", "status": "pending", "output": None},
        {"id": "training", "name": "模型训练", "status": "pending", "output": None},
        {"id": "inference", "name": "推理", "status": "pending", "output": None},
    ],
}

# 保护 _workflow_state 中各 step 字段的并发读写。即使在单 worker 下，
# 同一 worker 内也可能存在并发请求同时修改 step 状态（例如前端同时
# 触发多个步骤执行或 reset）。该锁确保 step 状态变更的原子性。
_workflow_lock = asyncio.Lock()


def _get_sovits_trainer():
    """复用 sovits_svc 模块导出的共享单例，确保跨接口共享同一个
    SoVITSSVCTrainer 实例（含 `_preprocessed` 状态与运行中的训练进程），
    避免跨接口触发训练时误报 "Preprocessing must be completed"。"""
    from modelstation.api.sovits_svc import get_sovits_trainer

    return get_sovits_trainer()


def _find_step(step_id: str) -> Optional[dict]:
    for step in _workflow_state["steps"]:
        if step["id"] == step_id:
            return step
    return None


def _step_index(step_id: str) -> int:
    for i, step in enumerate(_workflow_state["steps"]):
        if step["id"] == step_id:
            return i
    return -1


@router.get("/status")
async def get_workflow_status():
    return copy.deepcopy(_workflow_state)


@router.post("/step/{step_id}/execute")
async def execute_step(step_id: str, request: Request):
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}

    async with _workflow_lock:
        step = _find_step(step_id)
        if step is None:
            raise HTTPException(status_code=404, detail=f"Step not found: {step_id}")
        step["status"] = "running"

    try:
        if step_id == "train_prep":
            output = await _execute_train_prep(body)
        elif step_id == "training":
            output = await _execute_training(body)
        elif step_id == "inference":
            output = await _execute_inference(body)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown step: {step_id}")
    except HTTPException:
        # 语义化错误（如训练互斥 409）原样透传，不吞为 500
        logger.error(f"Workflow step {step_id} failed with HTTP error")
        async with _workflow_lock:
            step = _find_step(step_id)
            if step is not None:
                step["status"] = "error"
                step["output"] = {"error": "step failed (see response detail)"}
        raise
    except Exception as e:
        logger.error(f"Workflow step {step_id} failed: {e}")
        async with _workflow_lock:
            step = _find_step(step_id)
            if step is not None:
                step["status"] = "error"
                step["output"] = {"error": str(e)}
        raise HTTPException(status_code=500, detail=str(e))

    async with _workflow_lock:
        step = _find_step(step_id)
        if step is not None:
            step["status"] = "completed"
            step["output"] = output

            if step_id == "training":
                # 训练在后台异步进行：start_training 仅启动监控任务后立即返回 task_id，
                # 训练并未完成。保持 status="running"，前端通过 /api/sovits-svc/status
                # 轮询真实进度，待训练真正结束后再标记为 completed。
                step["status"] = "running"
            else:
                idx = _step_index(step_id)
                if idx >= 0 and _workflow_state["current_step"] <= idx:
                    _workflow_state["current_step"] = idx + 1

        return copy.deepcopy(_workflow_state)


async def _execute_train_prep(body: dict) -> dict:
    trainer = _get_sovits_trainer()

    training_data_dir = body.get("training_data_dir") or str(trainer.training_data_dir)
    speaker_name = body.get("speaker_name", "speaker")

    results = await trainer.preprocess(
        training_data_dir=training_data_dir,
        speaker_name=speaker_name,
    )

    return {"results": results}


async def _execute_training(body: dict) -> dict:
    from modelstation.api.sovits_svc import _training_conflict_detail, _update_train_status
    from modelstation.services.training_mutex import (
        TRAINING_SOVITS_SVC,
        end_training,
        try_begin_training,
        update_training_task,
    )

    trainer = _get_sovits_trainer()

    epochs = body.get("epochs", 10000)
    batch_size = body.get("batch_size", 4)
    learning_rate = body.get("learning_rate", 1e-4)
    output_name = body.get("output_name")
    speaker_name = body.get("speaker_name", "speaker")

    # 跨类型训练互斥：workflow 直调 trainer 的旁路封堵（与 /api/sovits-svc/train
    # 消费同一共享原语）。task_id 先以 None 占位，start_training 返回后回填。
    mutex_ok, mutex_current = try_begin_training(TRAINING_SOVITS_SVC, None)
    if not mutex_ok:
        raise HTTPException(status_code=409, detail=_training_conflict_detail(mutex_current))

    try:
        task_id = await trainer.start_training(
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            output_name=output_name,
            speaker_name=speaker_name,
            # 与 API 路径一致：终态回调释放互斥（completed/failed）并同步共享状态 dict
            progress_callback=lambda **kw: _update_train_status(**kw),
        )
    except Exception:
        end_training(TRAINING_SOVITS_SVC)
        raise

    update_training_task(TRAINING_SOVITS_SVC, task_id)

    return {"task_id": task_id}


async def _execute_inference(body: dict) -> dict:
    from modelstation.services.sovits_svc_infer import SoVITSSVCInferer
    from modelstation.config import get_settings

    settings = get_settings()

    audio_path = body.get("audio_path", "")
    model_path = body.get("model_path")
    speaker_id = body.get("speaker_id", 0)
    transpose = body.get("transpose", 0)
    cluster_model_path = body.get("cluster_model_path")

    inferer = SoVITSSVCInferer(
        model_path=model_path,
        output_dir=settings.sovits_svc.audition_dir,
        so_vits_svc_dir=settings.sovits_svc.so_vits_svc_dir,
        python_path=settings.sovits_svc.python_path,
        models_dir=settings.sovits_svc.models_dir,
        # infer 输入白名单根 = 训练数据目录 ∪ data/input
        allowed_audio_roots=[
            settings.sovits_svc.training_data_dir,
            settings.sovits_svc.input_dir,
        ],
    )

    result_path = await inferer.infer(
        audio_path=audio_path,
        speaker_id=speaker_id,
        transpose=transpose,
        model_path=model_path,
        cluster_model_path=cluster_model_path,
    )

    return {"output_filename": result_path.name}


@router.post("/reset")
async def reset_workflow():
    """
    重置工作流状态。

    若 SoVITS trainer 仍有正在运行的训练子进程，会先显式调用
    `trainer.stop_training()` 终止子进程，再清空所有 step 状态。
    整个流程在 _workflow_lock 内完成，确保与 execute_step 互斥。
    """
    async with _workflow_lock:
        trainer = _get_sovits_trainer()
        try:
            await trainer.stop_training()
        except Exception as e:
            # stop_training 失败不应阻塞 reset，仅记录告警
            logger.warning(f"reset_workflow: trainer.stop_training raised: {e}")
        # 释放跨类型训练互斥（幂等；若终态回调已释放则无害）
        from modelstation.services.training_mutex import TRAINING_SOVITS_SVC, end_training

        end_training(TRAINING_SOVITS_SVC)

        for step in _workflow_state["steps"]:
            step["status"] = "pending"
            step["output"] = None
        _workflow_state["current_step"] = 0
        return copy.deepcopy(_workflow_state)


@router.get("/step/{step_id}/output")
async def get_step_output(step_id: str):
    step = _find_step(step_id)
    if step is None:
        raise HTTPException(status_code=404, detail=f"Step not found: {step_id}")
    return {"step_id": step_id, "output": step["output"], "status": step["status"]}
