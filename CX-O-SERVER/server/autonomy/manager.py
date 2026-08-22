"""CX-O-Autonomy 自主系统管理器（P0 最小骨架，P1-T8 再扩展主循环）。

持有配置、运行状态（running/paused/sleeping/budget_limited）、动机、最近行动与
当日预算消耗。主循环由 P1-T8 扩展；本阶段仅实现 启用/停用/暂停/恢复/紧急停止/
状态快照。

异常契约（对齐 public/interface_stub/cxo_autonomy.pyi，本模块定义 5 类）：
- AutonomyError（基类）/ AutonomyDisabledError（error_code = AUTONOMY_DISABLED）
- AutonomyBudgetExceededError（error_code = AUTONOMY_BUDGET_EXCEEDED）
- AutonomyActionBlockedError（error_code = AUTONOMY_ACTION_BLOCKED）
- AutonomyPersistError（error_code = AUTONOMY_PERSIST_ERROR）
- 其余异常（AutonomyContentRejectedError / AutonomyRateLimitedError /
  AutonomyPlatformNotWhitelistedError）定义于 action/social/poster.py
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from server.autonomy.config import AutonomyConfig
from server.autonomy.models import Motivations


class AutonomyError(Exception):
    """自主系统基础异常（对齐接口契约）。"""

    error_code: str = "AUTONOMY_ERROR"
    message: str = ""

    def __init__(self, message: str = "", error_code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code


class AutonomyDisabledError(AutonomyError):
    """自主系统未启用时调用工具/端点。error_code = AUTONOMY_DISABLED"""

    error_code = "AUTONOMY_DISABLED"


class AutonomyBudgetExceededError(AutonomyError):
    """当日预算超支，降级/拒绝。error_code = AUTONOMY_BUDGET_EXCEEDED"""

    error_code = "AUTONOMY_BUDGET_EXCEEDED"


class AutonomyActionBlockedError(AutonomyError):
    """行动被权限白名单/黑名单拒绝。error_code = AUTONOMY_ACTION_BLOCKED"""

    error_code = "AUTONOMY_ACTION_BLOCKED"


class AutonomyPersistError(AutonomyError):
    """状态/审计/记忆持久化失败。error_code = AUTONOMY_PERSIST_ERROR"""

    error_code = "AUTONOMY_PERSIST_ERROR"


class AutonomyManager:
    """CX-O-Autonomy 自主系统管理器。

    - enabled：总开关（enable / disable / emergency_stop 控制）
    - running：主循环是否在跑（enable / resume 置 True；pause / disable / emergency_stop 置 False）
    - status：running / paused / sleeping / budget_limited / error 状态枚举
    """

    def __init__(self, config: Optional[AutonomyConfig] = None):
        self.config = config or AutonomyConfig()
        self.enabled: bool = False
        self.running: bool = False
        self.status: str = "paused"
        # 动机初始值（P1-T8 起随活动/休息动态更新）
        self.motivations = Motivations(
            curiosity=0.2, social_need=0.2, creative_drive=0.2, fatigue=0.0
        )
        self.last_action: Optional[str] = None
        self.last_cycle_at: Optional[str] = None
        self.daily_budget_used_tokens: int = 0
        self.budget_reset_date: Optional[str] = None
        self.diary_last_at: Optional[str] = None

    def enable(self) -> None:
        """启用自主系统并启动主循环。"""
        self.enabled = True
        self.running = True
        self.status = "running"

    def disable(self) -> None:
        """停用自主系统（主循环停止）。"""
        self.enabled = False
        self.running = False
        self.status = "paused"

    def pause(self) -> None:
        """暂停主循环（不改变总开关）。"""
        self.running = False
        self.status = "paused"

    def resume(self) -> None:
        """恢复主循环。"""
        self.running = True
        self.status = "running"

    def emergency_stop(self) -> None:
        """紧急停止：立即停用并置 error 状态。"""
        self.enabled = False
        self.running = False
        self.status = "error"

    def get_status(self) -> Dict[str, Any]:
        """返回状态快照（对齐 autonomy_state.schema.json）。未启用时抛 AutonomyDisabledError。"""
        if not self.enabled:
            raise AutonomyDisabledError("自主系统未启用")
        return {
            "motivations": self.motivations.model_dump(),
            "status": self.status,
            "last_action": self.last_action,
            "last_cycle_at": self.last_cycle_at,
            "daily_budget_used_tokens": self.daily_budget_used_tokens,
            "budget_reset_date": self.budget_reset_date,
            "diary_last_at": self.diary_last_at,
        }
