"""CXO-Tuner API 路由。

端点：
  - GET    /api/v1/health
  - POST   /api/v1/feedback
  - GET    /api/v1/dataset/stats
  - POST   /api/v1/train/trigger   （骨架占位）
  - GET    /api/v1/train/status    （骨架占位）
  - GET    /api/v1/adapters
  - DELETE /api/v1/adapters/{id}
  - POST   /api/v1/adapters/{id}/apply（骨架占位）
  - POST   /api/v1/judge/build（历史对话→DPO 自动构建）
"""
from __future__ import annotations

import logging
import threading
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from tuner.config import TunerConfig
from tuner.core.collector import Collector
from tuner.core.adapter_store.store import AdapterStore, AdapterNotFoundError
from tuner.core.collector.cleaner import InvalidFeedbackError
from tuner.core.collector.dataset import DatasetStore
from tuner.core.trainer.qlora_trainer import QLoRATrainer
from tuner.core.trainer.store import TrainerJobStore
from tuner.core.trainer.train_job import TrainJob
from tuner.models import (
    AdapterInfo,
    ApplyAdapterResponse,
    DatasetStats,
    FeedbackIn,
    FeedbackResponse,
    JudgeBuildRequest,
    JudgeBuildResponse,
    TrainStatus,
    TrainTriggerRequest,
)

logger = logging.getLogger("cxo_tuner.api")

router = APIRouter(prefix="/api/v1", tags=["cxo-tuner"])


def _services(request: Request) -> Collector:
    return request.app.state.collector


def _store(request: Request) -> DatasetStore:
    return request.app.state.dataset_store


def _adapters(request: Request) -> AdapterStore:
    return request.app.state.adapter_store


def _trainer(request: Request) -> QLoRATrainer:
    return request.app.state.trainer


def _job_store(request: Request) -> TrainerJobStore:
    return request.app.state.trainer_store


def _config(request: Request) -> TunerConfig:
    return request.app.state.config


def _dpo_builder(request: Request):
    return request.app.state.dpo_builder


def _to_status(job: TrainJob) -> TrainStatus:
    return TrainStatus(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        loss_curve=job.loss_curve,
        memory_usage_mb=job.memory_usage_mb,
        error=job.error,
    )


@router.get("/health", response_model=dict)
def health(request: Request) -> dict:
    """健康检查。"""
    return {"status": "ok", "dataset_size": _store(request).count()}


@router.post("/feedback", response_model=FeedbackResponse, status_code=200)
def submit_feedback(feedback: FeedbackIn, request: Request) -> FeedbackResponse:
    """提交偏好反馈。非法返回 422（不入库）、低质量丢弃、重复幂等。"""
    try:
        return _services(request).submit_feedback(feedback)
    except InvalidFeedbackError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_feedback", "reason": str(exc)},
        )


@router.get("/dataset/stats", response_model=DatasetStats)
def dataset_stats(request: Request):
    return _store(request).get_stats()


@router.post("/train/trigger", response_model=TrainStatus)
def trigger_train(req: TrainTriggerRequest, request: Request) -> TrainStatus:
    """触发训练。

    1. 校验：epochs 1-100（默认 1）、sample_ratio 0-1（默认 1）、
       anchor_ratio 0-1（默认取配置 anchor_ratio）。
    2. 创建 TrainJob（status=idle），后台线程启动训练（running）。
    3. 立即返回 job_id 与初始 status（idle），训练不阻塞请求。
    """
    cfg = _config(request)
    epochs = int(req.epochs if req.epochs is not None else 1)
    if not (1 <= int(epochs) <= 100):
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_request", "reason": "epochs 必须在 [1, 100] 区间（默认 1）"},
        )
    sample_ratio = float(req.sample_ratio if req.sample_ratio is not None else 1.0)
    if not (0.0 <= sample_ratio <= 1.0):
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_request", "reason": "sample_ratio 必须在 [0, 1] 区间（默认 1）"},
        )
    anchor_ratio = float(req.anchor_ratio if req.anchor_ratio is not None else cfg.anchor_ratio)
    if not (0.0 <= anchor_ratio <= 1.0):
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_request", "reason": "anchor_ratio 必须在 [0, 1] 区间（默认取配置）"},
        )

    job_id = str(req.job_id or "").strip() or ""
    base_model = req.base_model or cfg.base_model
    dataset_size = _store(request).count()
    job = TrainJob(
        job_id=job_id,
        status="idle",
        base_model=base_model,
        epochs=epochs,
        sample_ratio=sample_ratio,
        anchor_ratio=anchor_ratio,
    )
    store = _job_store(request)
    store.create(job)
    # 先快照初始 idle 状态，再启动后台线程，保证返回 status 恒为 idle
    initial_status = _to_status(job)
    logger.info(
        "训练触发: job_id=%s base_model=%r epochs=%d sample_ratio=%.2f anchor_ratio=%.2f dataset_size=%d",
        job.job_id, base_model, epochs, sample_ratio, anchor_ratio, dataset_size,
    )

    # 后台线程训练：不阻塞请求
    trainer = _trainer(request)
    thread = threading.Thread(target=trainer.run, args=(job.job_id,), daemon=True, name=f"train-{job.job_id}")
    thread.start()
    logger.info("训练后台线程已启动: job_id=%s thread_name=%s", job.job_id, thread.name)

    return initial_status


@router.get("/train/status", response_model=TrainStatus)
def train_status(
    job_id: Optional[str] = Query(default=None, description="训练任务 ID；缺省返回最新任务"),
    request: Request = None,
) -> TrainStatus:
    """查询训练状态。指定 job_id 返回该任务；缺省返回最新任务。"""
    store = _job_store(request)
    if job_id:
        job = store.get(str(job_id).strip())
        if job is None:
            raise HTTPException(
                status_code=404, detail={"error": "not_found", "reason": f"job '{job_id}' 不存在"}
            )
        return _to_status(job)
    latest = store.latest()
    if latest is None:
        return TrainStatus(job_id="", status="idle")
    return _to_status(latest)


@router.get("/adapters", response_model=List[AdapterInfo])
def list_adapters(request: Request) -> List[AdapterInfo]:
    return _adapters(request).list_adapters()


@router.delete("/adapters/{adapter_id}", response_model=dict)
def delete_adapter(adapter_id: str, request: Request) -> dict:
    try:
        ok = _adapters(request).delete(adapter_id)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": ok}


@router.post("/adapters/{adapter_id}/apply", response_model=ApplyAdapterResponse)
def apply_adapter(adapter_id: str, request: Request) -> ApplyAdapterResponse:
    try:
        return _adapters(request).apply(adapter_id)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/judge/build", response_model=JudgeBuildResponse)
def judge_build(req: JudgeBuildRequest, request: Request) -> JudgeBuildResponse:
    """历史对话→DPO 自动构建。

    输入会话历史样本（同一 prompt 的多个候选回复）+ 可选角色人设提示，触发
    LLM-as-a-Judge 批量比较并产出 source=judge 的 DPO 记录写入数据集。
    返回构建条数、跳过条数与 judge 明细摘要（供审计）。
    """
    samples = [
        {"prompt": s.prompt, "responses": s.responses, "session_id": s.session_id}
        for s in req.samples
    ]
    res = _dpo_builder(request).build(samples, req.character_card_hint)
    return JudgeBuildResponse(
        built=res.built,
        skipped=res.skipped,
        total_samples=res.total,
        audit=res.audit,
    )