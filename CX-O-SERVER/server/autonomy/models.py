"""CX-O-Autonomy 数据模型（对齐 public/schema/ 下契约）。

- AutonomyAction      自主行动（autonomy_action.schema.json）
- AutonomyAuditEntry  审计日志条目（autonomy_audit.schema.json）
- AutonomyFocus       焦点对象（autonomy_state.schema.json 的 focus）
- AutonomyState       状态快照（autonomy_state.schema.json）

动作枚举 9 项：sleep / wait / read_news / search / write_memory / write_post /
start_live / stop_live / write_diary；motivations 四维（curiosity / social_need /
creative_drive / fatigue）均取值 0-1；focus 承载 curiosity 的指向性
（topic＝当前最想探索的具体事物，level＝对该对象的兴趣强度 0-1）。
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
StateStatus = Literal["running", "paused", "sleeping"]


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class AutonomyFocus(BaseModel):
    """焦点对象：当前最想探索的"某个事物"及兴趣强度（对齐 autonomy_state.schema.json 的 focus）。

    topic 为空串表示暂无明确焦点；level 为对该对象的兴趣强度 [0,1]。
    与 motivations.curiosity 正交：curiosity 表达"多想探索"，focus 表达"想探索什么"。
    """

    model_config = ConfigDict(extra="forbid")
    topic: str = ""
    level: float = Field(default=0.0, ge=0.0, le=1.0)


class Motivations(BaseModel):
    """动机状态：curiosity / social_need / creative_drive / fatigue 各 0-1。"""

    model_config = ConfigDict(extra="forbid")
    curiosity: float = Field(default=0.0, ge=0.0, le=1.0)
    social_need: float = Field(default=0.0, ge=0.0, le=1.0)
    creative_drive: float = Field(default=0.0, ge=0.0, le=1.0)
    fatigue: float = Field(default=0.0, ge=0.0, le=1.0)


class AutonomyAction(BaseModel):
    """LLM 规划器输出的自主行动（对齐 autonomy_action.schema.json，action 必填）。

    focus 为可选字段（契约 @1.15.0 新增）：LLM 自报的本轮关注对象；缺省＝沿用上次焦点。
    """

    model_config = ConfigDict(extra="forbid")
    action: ActionType
    target: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    expected_outcome: str = ""
    focus: Optional[AutonomyFocus] = None


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
    """自主系统状态快照（对齐 autonomy_state.schema.json）。

    2026-09-27 人类裁决：`daily_budget_used_tokens` / `budget_reset_date` 已随
    「删除预算记账闸门」从契约与模型中移除（纯本地项目不需要预算管控）。
    """

    model_config = ConfigDict(extra="forbid")
    motivations: Motivations = Field(default_factory=Motivations)
    focus: AutonomyFocus = Field(default_factory=AutonomyFocus)
    status: StateStatus = "paused"
    last_action: Optional[str] = None
    last_cycle_at: Optional[str] = None
    diary_last_at: Optional[str] = None
