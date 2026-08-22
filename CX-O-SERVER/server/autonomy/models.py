"""CX-O-Autonomy 数据模型（对齐 public/schema/ 下契约）。

- AutonomyAction      自主行动（autonomy_action.schema.json）
- AutonomyAuditEntry  审计日志条目（autonomy_audit.schema.json）
- AutonomyState       状态快照（autonomy_state.schema.json）

动作枚举 9 项：sleep / wait / read_news / search / write_memory / write_post /
start_live / stop_live / write_diary；motivations 四维（curiosity / social_need /
creative_drive / fatigue）均取值 0-1。
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# 动作枚举 9 项（对齐 autonomy_action.schema.json）
ActionType = Literal[
    "sleep",
    "wait",
    "read_news",
    "search",
    "write_memory",
    "write_post",
    "start_live",
    "stop_live",
    "write_diary",
]

# 审计结果枚举（对齐 autonomy_audit.schema.json）
AuditResult = Literal["success", "failed", "blocked", "skipped"]

# 状态枚举（对齐 autonomy_state.schema.json）
StateStatus = Literal["running", "paused", "sleeping", "budget_limited", "error"]


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Motivations(BaseModel):
    """动机状态：curiosity / social_need / creative_drive / fatigue 各 0-1。"""

    model_config = ConfigDict(extra="forbid")
    curiosity: float = Field(default=0.0, ge=0.0, le=1.0)
    social_need: float = Field(default=0.0, ge=0.0, le=1.0)
    creative_drive: float = Field(default=0.0, ge=0.0, le=1.0)
    fatigue: float = Field(default=0.0, ge=0.0, le=1.0)


class AutonomyAction(BaseModel):
    """LLM 规划器输出的自主行动（对齐 autonomy_action.schema.json，action 必填）。"""

    model_config = ConfigDict(extra="forbid")
    action: ActionType
    target: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    expected_outcome: str = ""


class AutonomyAuditEntry(BaseModel):
    """自主行动审计日志条目（对齐 autonomy_audit.schema.json）。"""

    model_config = ConfigDict(extra="forbid")
    timestamp: str = Field(default_factory=_now_iso)
    motivations: Optional[Motivations] = None
    action: str = ""
    target: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    result: AuditResult = "skipped"
    error: Optional[str] = None
    cost_tokens: int = Field(default=0, ge=0)
    trigger_reason: str = ""
    expected_outcome: str = ""


class AutonomyState(BaseModel):
    """自主系统状态快照（对齐 autonomy_state.schema.json）。"""

    model_config = ConfigDict(extra="forbid")
    motivations: Motivations = Field(default_factory=Motivations)
    status: StateStatus = "paused"
    last_action: Optional[str] = None
    last_cycle_at: Optional[str] = None
    daily_budget_used_tokens: int = Field(default=0, ge=0)
    budget_reset_date: Optional[str] = None
    diary_last_at: Optional[str] = None
