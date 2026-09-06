"""
双人合唱 API（change-id: enhance-cover-pitch-analysis-duet Task 3）

最终 URL（main.py 注册 prefix="/api/cover"，本 router 内路径以 /duet 开头）：
- POST /api/cover/duet          ：提交双人合唱任务 → 202 {status, task_id}
- GET  /api/cover/duet/{task_id}：任务状态/当前阶段/进度/实际采用 transpose/错误
- GET  /api/cover/duet          ：能力就绪情况（Task 1 骨架保留，无副作用）

守卫：separation 未就绪（enabled=false 或引擎目录缺失）→ 503，
复用 api/cover.py 的 separation_ready / separation_unavailable_detail。
成品播放：/api/audio-files/duet/{task_id}/final.wav（audio_files duet 类别）。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from workstation.api.cover import separation_ready, separation_unavailable_detail
from workstation.config import get_settings
from workstation.services import duet_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()


class DuetCreateRequest(BaseModel):
    """双人合唱任务提交参数（与 duet_pipeline._normalize_params 对齐）。

    model_a/model_b 为空 = 该声部保留原声；transpose_a/transpose_b 显式给值时
    覆盖自动推荐；query_a/query_b 为 AudioSep 文本查询描述。
    """

    audio_path: str
    model_a: Optional[str] = None
    model_b: Optional[str] = None
    transpose_a: Optional[int] = None
    transpose_b: Optional[int] = None
    auto_transpose: bool = True
    query_a: Optional[str] = None
    query_b: Optional[str] = None
    gain_a: float = 1.0
    gain_b: float = 1.0
    accompaniment_gain: float = 0.8


@router.post("/duet", status_code=202)
async def create_duet(request: DuetCreateRequest):
    """提交双人合唱任务（202 Accepted，任务异步执行）。"""
    if not separation_ready():
        raise HTTPException(status_code=503, detail=separation_unavailable_detail())
    try:
        task_id = await duet_pipeline.create_duet_task(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "accepted", "task_id": task_id}


@router.get("/duet/{task_id}")
async def get_duet_task_status(task_id: str):
    """查询双人合唱任务状态/当前阶段/进度/实际采用 transpose/错误。"""
    task = duet_pipeline.get_duet_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return task


@router.get("/duet")
async def duet_capability_status():
    """能力就绪情况端点（GET /api/cover/duet，Task 1 骨架保留，无副作用）。"""
    settings = get_settings()
    ready = separation_ready()
    payload = {
        "status": "success",
        "enabled": bool(settings.separation.enabled),
        "separation_ready": ready,
        "note": "POST /duet 提交任务，GET /duet/{task_id} 查询状态（Task 3 已填充）",
    }
    if not ready:
        payload["hint"] = separation_unavailable_detail()
    return payload
