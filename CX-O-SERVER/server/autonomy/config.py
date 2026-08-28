"""CX-O-Autonomy 自主系统配置模型与加载/保存（对齐 public/schema/autonomy_config.schema.json）。

- 字段默认值 / 枚举 / 时间格式与契约完全一致（additionalProperties=false → extra="forbid"）
- 缺失字段在加载时自动补齐默认值（pydantic v2 model_validate 的 auto_fill 语义）
- 非法枚举值 / 非法 HH:MM 时间格式抛 ValueError
- store_path 为空时基于 __file__ 绝对路径解析到 server/autonomy/data/，禁止相对路径/../../
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.autonomy._atomic_io import atomic_write_json, quarantine_corrupt_file

logger = logging.getLogger(__name__)

# 动作枚举（autonomy_action.schema.json，9 项）
ACTION_ENUM: List[str] = [
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

# 时间字段格式（对齐契约 pattern ^([01]?[0-9]|2[0-3]):[0-5][0-9]$）
_HHMM_RE = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
# 静默档窗口格式 HH:MM-HH:MM
_QUIET_WINDOW_RE = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]-([01]?[0-9]|2[0-3]):[0-5][0-9]$")


class SearchConfig(BaseModel):
    """搜索配置（契约 search）。"""

    model_config = ConfigDict(extra="forbid")
    mcp_server_name: str = "free-search-mcp"
    fallback_rss: bool = True


class ScheduleConfig(BaseModel):
    """日程配置（契约 schedule）。"""

    model_config = ConfigDict(extra="forbid")
    wake_time: str = "08:00"
    sleep_time: str = "02:00"
    golden_start: str = "19:00"
    golden_end: str = "23:00"
    diary_time: str = "02:00"
    quiet_windows: List[str] = Field(default_factory=list)

    @field_validator("wake_time", "sleep_time", "golden_start", "golden_end", "diary_time")
    @classmethod
    def _check_hhmm(cls, v: str) -> str:
        if not _HHMM_RE.match(v):
            raise ValueError(f"时间字段必须为 HH:MM 格式，收到 {v!r}")
        return v

    @field_validator("quiet_windows")
    @classmethod
    def _check_quiet_windows(cls, v: List[str]) -> List[str]:
        for window in v:
            if not _QUIET_WINDOW_RE.match(window):
                raise ValueError(f"静默档必须为 HH:MM-HH:MM 格式，收到 {window!r}")
        return v


class BudgetConfig(BaseModel):
    """预算配置（契约 budget）。"""

    model_config = ConfigDict(extra="forbid")
    daily_token_limit: int = 2000000
    daily_llm_calls_limit: int = 0
    cost_alert_threshold: float = 0.8
    overspend_mode: str = "sleep"

    @field_validator("overspend_mode")
    @classmethod
    def _check_overspend_mode(cls, v: str) -> str:
        if v not in ("sleep", "low_cost"):
            raise ValueError(f"overspend_mode 非法值 {v!r}，可选 sleep/low_cost")
        return v


class PermissionsConfig(BaseModel):
    """权限配置（契约 permissions）。"""

    model_config = ConfigDict(extra="forbid")
    allowed_actions: List[str] = Field(default_factory=lambda: list(ACTION_ENUM))
    blocked_actions: List[str] = Field(default_factory=list)

    @field_validator("allowed_actions")
    @classmethod
    def _check_allowed_actions(cls, v: List[str]) -> List[str]:
        for action in v:
            if action not in ACTION_ENUM:
                raise ValueError(f"allowed_actions 含非法 action {action!r}")
        return v


class SafetyConfig(BaseModel):
    """安全配置（契约 safety）。"""

    model_config = ConfigDict(extra="forbid")
    content_gate_enabled: bool = True
    persona_check_enabled: bool = True
    post_rate_per_hour: int = 5
    user_online_sleep: bool = True
    leave_mode_authorize: bool = True


class AutonomyConfig(BaseModel):
    """CX-O-Autonomy 自主系统配置（对齐 autonomy_config.schema.json）。

    契约无必填字段：加载时缺失字段自动补齐默认值（auto_fill 语义）。
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    auto_start: bool = False
    agent_id: str = "default"
    loop_interval_minutes: int = 15
    rss_sources: List[str] = Field(default_factory=list)
    search: SearchConfig = Field(default_factory=SearchConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    platforms: List[str] = Field(default_factory=list)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    store_path: str = ""


def resolve_store_dir() -> str:
    """解析默认存储目录：server/autonomy/data/（基于 __file__ 绝对路径，禁止相对路径）。"""
    return str(Path(__file__).resolve().parent / "data")


def _resolve_store(store_path: str) -> str:
    """store_path 为空则回退到默认解析目录。"""
    return store_path or resolve_store_dir()


def load_config(store_path: str = "") -> AutonomyConfig:
    """从 store_path/autonomy_config.json 读取配置。

    缺失字段自动补齐默认值；文件不存在时返回全默认实例；文件损坏
    （OSError / JSON 解析失败）时告警、坏档改名 .corrupt 留痕并回退全默认
    实例（R2：写盘中断不再导致装配失败需人工删档）。
    store_path 为空表示使用默认解析目录（server/autonomy/data/）。
    """
    store = _resolve_store(store_path)
    cfg_path = Path(store) / "autonomy_config.json"
    defaults = AutonomyConfig(store_path=store_path)
    if not cfg_path.exists():
        return defaults
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        corrupt_path = quarantine_corrupt_file(cfg_path)
        logger.warning(
            "自主系统配置损坏，回退默认配置 %s: %s（坏档改名: %s）",
            cfg_path,
            e,
            corrupt_path or "失败",
        )
        return defaults
    raw.setdefault("store_path", store_path)
    return AutonomyConfig.model_validate(raw)


def save_config(config: AutonomyConfig) -> str:
    """将配置原子写入 store_path/autonomy_config.json，返回写入路径。"""
    store = _resolve_store(config.store_path)
    cfg_path = Path(store) / "autonomy_config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cfg_path, config.model_dump())
    return str(cfg_path)
