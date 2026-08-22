"""CXO-Tuner 接口数据模型。

命名与字段严格对齐 public/interface_stub/cxo_tuner.pyi。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class FeedbackIn(BaseModel):
    """单条偏好反馈输入（对齐 cxo_tuner_feedback.schema.json）。"""

    prompt: str
    response_chosen: str
    response_rejected: str
    source: str  # enum: live_danmaku / judge / distillation
    timestamp: str  # ISO 8601 date-time
    session_id: Optional[str] = None
    quality_score: Optional[float] = None  # 0-1
    metadata: Optional[Dict[str, Any]] = None


class FeedbackResponse(BaseModel):
    """提交反馈后的服务响应。"""

    feedback_id: str
    accepted: bool
    reason: str


class DatasetStats(BaseModel):
    """DPO 数据集统计视图。"""

    total: int
    source_breakdown: Dict[str, int]  # key=live_danmaku/judge/distillation
    positive_ratio: float  # 0-1，正样本（chosen）占比
    negative_ratio: float  # 0-1，负样本（rejected）占比
    anchor_count: int  # anchor=True 的记录数


class TrainTriggerRequest(BaseModel):
    """触发训练请求。base_model 为空时回退配置 base_model。

    阈值默认值：epochs 默认 1（范围 1-100）、sample_ratio 默认 1.0；anchor_ratio
    缺省时由路由层回退到配置 anchor_ratio；job_id 缺省时由 TrainJob 生成。
    """

    base_model: Optional[str] = None
    epochs: int = 1
    sample_ratio: float = 1.0  # 0-1
    anchor_ratio: Optional[float] = None  # 0-1；None 表示取配置默认
    job_id: str = ""


class TrainStatus(BaseModel):
    """训练任务状态。"""

    job_id: str
    status: str  # enum: idle / running / completed / failed
    progress: float = 0.0  # 0-1
    loss_curve: List[float] = []
    memory_usage_mb: int = 0
    error: Optional[str] = None


class AdapterInfo(BaseModel):
    """训练产物（LoRA 适配器）元信息。"""

    id: str
    name: str
    created_at: str  # ISO 8601 date-time
    base_model: str
    epochs: int
    size_bytes: int


class ApplyAdapterResponse(BaseModel):
    """路由应用适配器到在线模型的响应。"""

    adapter_id: str
    applied: bool
    detail: Optional[str] = None


class JudgeBuildSample(BaseModel):
    """单条会话历史样本：同一 prompt 的多个候选回复。"""

    prompt: str
    responses: List[str] = []
    session_id: Optional[str] = None


class JudgeBuildRequest(BaseModel):
    """触发 judge 批量构建 DPO 的请求。"""

    samples: List[JudgeBuildSample]
    character_card_hint: Optional[str] = None


class JudgeBuildResponse(BaseModel):
    """judge 批量构建的结果摘要。audit 为 judge 明细列表（供日志/审计）。"""

    built: int
    skipped: int
    total_samples: int
    audit: List[Dict[str, Any]]