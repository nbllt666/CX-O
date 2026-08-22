"""CX-O-Autonomy 昼夜节律调度器。

CircadianScheduler 根据日程配置（schedule）在任意时刻判定当前所处相位
（sleep / golden / quiet / active），并支持跨午夜的睡眠窗口、静默档窗口判定。

- parse_hhmm:  将 "HH:MM" 字符串解析为 time 对象，非法格式抛 ValueError
- in_window:   判断时间是否落在 [start, end) 窗口内，支持跨午夜
- CircadianScheduler: 相位判定主类（is_sleep_time / is_awake / is_golden /
  is_quiet / is_diary_time / current_phase）

时间格式与 config.py 完全对齐（契约 pattern ^([01]?[0-9]|2[0-3]):[0-5][0-9]$）。
本模块不涉及任何文件 IO，禁止相对路径。
"""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import List, Tuple

# 时间字段格式（对齐契约 pattern ^([01]?[0-9]|2[0-3]):[0-5][0-9]$）
_HHMM_RE = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
# 静默档窗口格式 HH:MM-HH:MM
_QUIET_WINDOW_RE = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]-([01]?[0-9]|2[0-3]):[0-5][0-9]$")


def parse_hhmm(s: str) -> time:
    """将 "HH:MM" 字符串解析为 time 对象。

    对齐 config.py 的时间格式契约（pattern ^([01]?[0-9]|2[0-3]):[0-5][0-9]$），
    非法格式（含非字符串、越界时分）抛 ValueError。
    """
    if not isinstance(s, str) or not _HHMM_RE.match(s):
        raise ValueError(f"时间必须为 HH:MM 格式，收到 {s!r}")
    hour, minute = s.split(":")
    return time(int(hour), int(minute))


def _parse_quiet_window(s: str) -> Tuple[time, time]:
    """将 "HH:MM-HH:MM" 静默档窗口字符串解析为 (start, end) time 元组，非法抛 ValueError。"""
    if not isinstance(s, str) or not _QUIET_WINDOW_RE.match(s):
        raise ValueError(f"静默档必须为 HH:MM-HH:MM 格式，收到 {s!r}")
    start_s, end_s = s.split("-")
    return parse_hhmm(start_s), parse_hhmm(end_s)


def in_window(now: datetime, start: time, end: time) -> bool:
    """判断 now 是否落在 [start, end) 时间窗口内，支持跨午夜。

    - start < end：同日窗口，start <= t < end
    - start >= end：跨午夜窗口，t >= start 或 t < end
      （即 [start, 24:00) ∪ [00:00, end)）

    边界语义：end 时刻不命中（如睡眠窗口 [02:00, 08:00)，08:00 视为已清醒）。
    """
    t = now.time()
    if start < end:
        return start <= t < end
    return t >= start or t < end


class CircadianScheduler:
    """昼夜节律调度器：按日程配置在任意时刻判定当前相位。

    构造时解析全部 HH:MM 字段为 time 对象并校验，非法格式抛 ValueError。
    睡眠窗口（sleep_time..wake_time）与静默档窗口均支持跨午夜。
    """

    def __init__(self, schedule: dict) -> None:
        """初始化调度器并解析校验日程配置。

        schedule 必须包含 wake_time / sleep_time / golden_start / golden_end /
        diary_time（均为 "HH:MM" 字符串）；quiet_windows（"HH:MM-HH:MM" 列表）
        可缺省，缺省视为空列表。
        """
        self.wake_time: time = parse_hhmm(schedule["wake_time"])
        self.sleep_time: time = parse_hhmm(schedule["sleep_time"])
        self.golden_start: time = parse_hhmm(schedule["golden_start"])
        self.golden_end: time = parse_hhmm(schedule["golden_end"])
        self.diary_time: time = parse_hhmm(schedule["diary_time"])
        self.quiet_windows: List[Tuple[time, time]] = [
            _parse_quiet_window(w) for w in schedule.get("quiet_windows", [])
        ]

    def is_sleep_time(self, now: datetime) -> bool:
        """判断 now 是否处于入睡窗口。

        入睡窗口为 [sleep_time, wake_time)，支持跨午夜。例如 wake 08:00 /
        sleep 02:00 → 睡眠窗口 [02:00, 08:00)，08:00 整点视为已清醒。
        """
        return in_window(now, self.sleep_time, self.wake_time)

    def is_awake(self, now: datetime) -> bool:
        """判断 now 是否处于清醒时段（非入睡窗口）。"""
        return not self.is_sleep_time(now)

    def is_golden(self, now: datetime) -> bool:
        """判断 now 是否处于黄金档。

        同时满足：落在 golden_start..golden_end 窗口内，且处于清醒时段。
        """
        return in_window(now, self.golden_start, self.golden_end) and self.is_awake(now)

    def is_quiet(self, now: datetime) -> bool:
        """判断 now 是否落在任一静默档窗口（HH:MM-HH:MM，可跨午夜）。"""
        return any(in_window(now, start, end) for start, end in self.quiet_windows)

    def is_diary_time(self, now: datetime) -> bool:
        """判断 now 的 HH:MM 是否等于日记时刻 diary_time（用于每日日记触发判定）。

        按分钟粒度比对（now.hour / now.minute），不涉及秒。
        """
        return now.hour == self.diary_time.hour and now.minute == self.diary_time.minute

    def current_phase(self, now: datetime) -> str:
        """返回当前相位，按优先级取首个命中：sleep → golden → quiet → active。

        - sleep：入睡窗口（最高优先级）
        - golden：黄金档（含清醒前提，见 is_golden）
        - quiet：静默档
        - active：其余清醒时段（兜底）

        日记时刻不单独作为相位，由 is_diary_time 单独判定。
        """
        if self.is_sleep_time(now):
            return "sleep"
        if self.is_golden(now):
            return "golden"
        if self.is_quiet(now):
            return "quiet"
        return "active"
