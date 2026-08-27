"""闲时训练调度（IdleScheduler）。

在每日低峰窗口（默认 02:00-05:00）且数据集规模达到门槛时自动触发一次训练。
训练触发复用 trainer 触发接口（由调用方注入 trigger 闭包，等价于 /train/trigger
的调度侧形态）。时钟可通过 now_fn 注入，便于离线单测用假时间推进。

设计约束：
  - is_idle_time / has_completed_today 为纯函数，便于单独单测；
  - IdleScheduler 实例仅承载判定与触发，自身不启动后台线程，启停由业务层负责；
  - 同一自然日内已触发过一次训练则跳过（进程内存去重 + trainer_store 兜底）。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Callable, Optional

from tuner.config import SchedulerConfig

_DEFAULT_MIN_DATASET_SIZE = 100
_DEFAULT_IDLE_START = "02:00"
_DEFAULT_IDLE_END = "05:00"


def _to_minutes(s: str) -> int:
    """把 "HH:MM" 转成当日分钟数（0-1439）。"""
    h, m = s.split(":", 1)
    return int(h) * 60 + int(m)


def is_idle_time(
    dataset_size: int,
    current_time: datetime,
    *,
    min_dataset_size: int = _DEFAULT_MIN_DATASET_SIZE,
    idle_start: str = _DEFAULT_IDLE_START,
    idle_end: str = _DEFAULT_IDLE_END,
) -> bool:
    """纯函数：当前是否满足「闲时可训练」。

    - 数据集规模达到门槛（dataset_size >= min_dataset_size）；
    - 当前时刻落在 [idle_start, idle_end) 时间窗口（默认 02:00-05:00，左闭右开）。
    """
    if int(dataset_size) < int(min_dataset_size):
        return False
    cur = current_time.hour * 60 + current_time.minute
    return _to_minutes(idle_start) <= cur < _to_minutes(idle_end)


def _created_at_local_date(created_at: str):
    """把 job.created_at（isoformat 字符串）解析为本地时区的 date。

    M 级修复：TrainJob.created_at 以 UTC isoformat 存储，此前直接取其 .date()
    与本地 now.date() 比较——UTC 与本地日期在跨日时段（如东八区 00:00–07:59）
    错位一天，导致「当日已训练」去重永久失效、闲时窗口重复触发训练。
    修复口径：带时区的时间戳 astimezone() 归一到本地时区后取 date；
    naive 时间戳视为本地时间直接取 date。
    """
    created = datetime.fromisoformat(created_at)
    if created.tzinfo is not None:
        created = created.astimezone()
    return created.date()


def has_completed_today(trainer_store: Any, now: datetime) -> bool:
    """当日（按 now 的本地自然日）是否已有 completed 训练任务，用于避免重复触发。"""
    day = now.date().isoformat()
    for job in trainer_store.all():
        if job.status != "completed":
            continue
        try:
            local_date = _created_at_local_date(job.created_at)
        except (ValueError, TypeError):
            continue
        if local_date.isoformat() == day:
            return True
    return False


class IdleScheduler:
    """闲时训练调度器。tick() 每次做惰性判定并尝试触发，不维持自启线程。

    参数：
      - config:        SchedulerConfig（enabled / idle_start / idle_end / min_dataset_size）
      - dataset_store: 数据集存储，需提供 count()（或 get_stats().total）取规模
      - trigger:       零参可调用，调用即触发一次训练（复用训练触发接口）
      - now_fn:        时钟注入，缺省用真实本地时间（datetime.now）
      - trainer_store: 可选，TrainerJobStore，用于判断「当日已完成训练」兜底
    """

    def __init__(
        self,
        config: SchedulerConfig,
        dataset_store: Any,
        trigger: Callable[[], Any],
        now_fn: Optional[Callable[[], datetime]] = None,
        trainer_store: Optional[Any] = None,
    ) -> None:
        self.config = config
        self.dataset_store = dataset_store
        self.trigger = trigger
        self.now_fn = now_fn or datetime.now
        self.trainer_store = trainer_store
        self._trained_dates = set()  # 进程内存去重：已触发过训练的自然日
        self._lock = threading.Lock()

    # -- 规模读取 ---------------------------------------------------------------
    def _dataset_size(self) -> int:
        try:
            return int(self.dataset_store.count())
        except Exception:
            try:
                return int(self.dataset_store.get_stats().total)
            except Exception:
                return 0

    def is_idle_active(self, now: datetime) -> bool:
        """按注入配置判断当前是否处于「可闲时训练」状态（规模 + 时间窗口）。"""
        return is_idle_time(
            self._dataset_size(),
            now,
            min_dataset_size=self.config.min_dataset_size,
            idle_start=self.config.idle_start,
            idle_end=self.config.idle_end,
        )

    def tick(self) -> bool:
        """执行一次闲时判定并尝试触发训练。返回是否实际触发了一次训练。"""
        if not self.config.enabled:
            return False
        now = self.now_fn()
        day = now.date().isoformat()
        with self._lock:
            if day in self._trained_dates:
                return False
        if not self.is_idle_active(now):
            return False
        if self.trainer_store is not None and has_completed_today(self.trainer_store, now):
            # 当日已有 completed 任务，视为该自然日已训练过，不再重复触发
            with self._lock:
                self._trained_dates.add(day)
            return False
        self.trigger()
        with self._lock:
            self._trained_dates.add(day)
        return True