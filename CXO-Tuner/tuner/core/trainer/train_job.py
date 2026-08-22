"""TrainJob：训练任务状态机与线程安全状态容器。

状态机（单向推进）：
    idle -> running -> completed
                     -> failed      （running/cidle 均可直接 failed）
    completed / failed 为终态。

线程安全：所有可变字段访问经由 self._lock 串行化。后端训练线程负责写入进度/损失/
显存消耗（update / complete / fail），API 线程通过 store 读取快照，互不撕裂。
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

# 状态机允许的迁移：源状态 -> {目标状态们}
_TRANSITIONS = {
    "idle": {"running", "failed"},
    "running": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
}


def new_job_id() -> str:
    """生成唯一任务 ID。"""
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InvalidTransitionError(ValueError):
    """对终态做非法状态迁移时抛出。"""


@dataclass
class TrainJob:
    """训练任务。job_id 缺省时自动生成。"""

    job_id: str = ""
    status: str = "idle"
    progress: float = 0.0  # 0-1
    loss_curve: List[float] = field(default_factory=list)
    memory_usage_mb: int = 0
    error: Optional[str] = None
    base_model: str = ""
    epochs: int = 1
    sample_ratio: float = 1.0
    anchor_ratio: float = 0.2
    created_at: str = field(default_factory=_now_iso)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.job_id:
            self.job_id = new_job_id()
        if self.status not in _TRANSITIONS:
            self.status = "idle"

    # -- 状态迁移 ------------------------------------------------------------
    def _transition(self, target: str) -> None:
        with self._lock:
            if target not in _TRANSITIONS.get(self.status, set()):
                raise InvalidTransitionError(
                    f"非法状态迁移: {self.status} -> {target}"
                )
            self.status = target

    def start(self) -> None:
        """idle -> running。"""
        self._transition("running")

    def complete(self, loss: Optional[List[float]] = None) -> None:
        """running -> completed；可选追加最终 loss 曲线。"""
        with self._lock:
            if loss:
                self.loss_curve = list(loss)
            self.progress = 1.0
            if "completed" not in _TRANSITIONS.get(self.status, set()):
                raise InvalidTransitionError(
                    f"非法状态迁移: {self.status} -> completed"
                )
            self.status = "completed"

    def fail(self, message: str) -> None:
        """idle/running -> failed。"""
        with self._lock:
            self.error = message
            if "failed" not in _TRANSITIONS.get(self.status, set()):
                raise InvalidTransitionError(f"非法状态迁移: {self.status} -> failed")
            self.status = "failed"

    # -- 训练过程更新 ---------------------------------------------------------
    def update(self, progress: float, loss: Optional[float] = None,
               memory_usage_mb: Optional[int] = None) -> None:
        """running 过程中更新进度/损失/显存。仅 running 态允许写。"""
        with self._lock:
            if self.status != "running":
                raise InvalidTransitionError(
                    f"仅 running 态可更新过程指标，当前 status={self.status}"
                )
            self.progress = min(1.0, max(0.0, float(progress)))
            if loss is not None:
                self.loss_curve.append(float(loss))
            if memory_usage_mb is not None:
                self.memory_usage_mb = int(memory_usage_mb)

    # -- 视图 / 序列化 -------------------------------------------------------
    def to_dict(self) -> dict:
        with self._lock:
            return {
                "job_id": self.job_id,
                "status": self.status,
                "progress": self.progress,
                "loss_curve": list(self.loss_curve),
                "memory_usage_mb": self.memory_usage_mb,
                "error": self.error,
                "base_model": self.base_model,
                "epochs": self.epochs,
                "sample_ratio": self.sample_ratio,
                "anchor_ratio": self.anchor_ratio,
                "created_at": self.created_at,
            }

    @classmethod
    def from_dict(cls, data: dict) -> "TrainJob":
        return cls(
            job_id=data.get("job_id", ""),
            status=data.get("status", "idle"),
            progress=float(data.get("progress", 0.0)),
            loss_curve=list(data.get("loss_curve", [])),
            memory_usage_mb=int(data.get("memory_usage_mb", 0)),
            error=data.get("error"),
            base_model=data.get("base_model", ""),
            epochs=int(data.get("epochs", 1)),
            sample_ratio=float(data.get("sample_ratio", 1.0)),
            anchor_ratio=float(data.get("anchor_ratio", 0.2)),
            created_at=data.get("created_at", _now_iso()),
        )