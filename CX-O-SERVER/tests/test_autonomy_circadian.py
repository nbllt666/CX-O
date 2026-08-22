"""CX-O-Autonomy P1-T2 昼夜节律调度器单测。

覆盖：
1. 默认作息（wake 08:00 / sleep 02:00 / golden 19:00-23:00 / diary 02:00）相位判定：
   02:30 sleep、07:59 sleep、08:00 awake、12:00 active、20:00 golden、
   23:30 active（非 golden）
2. is_diary_time 在 02:00 命中、其他不命中
3. quiet_windows 单窗口与跨午夜窗口
4. 非法 HH:MM 抛 ValueError
5. 跨午夜睡眠窗口（sleep 22:00 / wake 06:00）边界

运行：python -m pytest tests/test_autonomy_circadian.py -q
"""
from datetime import datetime, time

import pytest

from server.autonomy.core.scheduler import CircadianScheduler, in_window, parse_hhmm

# 默认作息（对齐 config.ScheduleConfig 默认值：wake 08:00 / sleep 02:00 /
# golden 19:00-23:00 / diary 02:00 / 无静默档）
DEFAULT_SCHEDULE = {
    "wake_time": "08:00",
    "sleep_time": "02:00",
    "golden_start": "19:00",
    "golden_end": "23:00",
    "diary_time": "02:00",
    "quiet_windows": [],
}


def dt(hour: int, minute: int = 0) -> datetime:
    """构造测试用 datetime（固定日期 2026-08-22，避免依赖当天时间）。"""
    return datetime(2026, 8, 22, hour, minute)


# ================================================================ ① 默认作息相位判定
class TestDefaultPhase:
    def setup_method(self) -> None:
        self.scheduler = CircadianScheduler(dict(DEFAULT_SCHEDULE))

    def test_sleep_window(self):
        # 入睡窗口 [02:00, 08:00)，end（08:00）不含
        assert self.scheduler.is_sleep_time(dt(2, 30)) is True
        assert self.scheduler.is_sleep_time(dt(7, 59)) is True
        assert self.scheduler.is_sleep_time(dt(2, 0)) is True
        assert self.scheduler.is_sleep_time(dt(8, 0)) is False

    def test_awake(self):
        assert self.scheduler.is_awake(dt(8, 0)) is True
        assert self.scheduler.is_awake(dt(12, 0)) is True
        assert self.scheduler.is_awake(dt(2, 30)) is False

    def test_golden(self):
        assert self.scheduler.is_golden(dt(20, 0)) is True
        assert self.scheduler.is_golden(dt(19, 0)) is True
        assert self.scheduler.is_golden(dt(23, 0)) is False  # end 不含
        assert self.scheduler.is_golden(dt(23, 30)) is False  # 黄金档外
        assert self.scheduler.is_golden(dt(12, 0)) is False  # 黄金档外
        assert self.scheduler.is_golden(dt(2, 0)) is False  # 睡眠时段不算黄金档

    def test_current_phase(self):
        assert self.scheduler.current_phase(dt(2, 30)) == "sleep"
        assert self.scheduler.current_phase(dt(7, 59)) == "sleep"
        assert self.scheduler.current_phase(dt(8, 0)) == "active"
        assert self.scheduler.current_phase(dt(12, 0)) == "active"
        assert self.scheduler.current_phase(dt(20, 0)) == "golden"
        assert self.scheduler.current_phase(dt(23, 30)) == "active"


# ================================================================ ② 日记时刻判定
class TestDiaryTime:
    def setup_method(self) -> None:
        self.scheduler = CircadianScheduler(dict(DEFAULT_SCHEDULE))

    def test_diary_time_hit(self):
        assert self.scheduler.is_diary_time(dt(2, 0)) is True

    def test_diary_time_miss(self):
        for hour, minute in [(0, 0), (1, 59), (2, 1), (3, 0), (12, 0), (23, 59)]:
            assert self.scheduler.is_diary_time(dt(hour, minute)) is False, (hour, minute)


# ================================================================ ③ 静默档窗口
class TestQuietWindows:
    def test_single_window(self):
        s = CircadianScheduler({**DEFAULT_SCHEDULE, "quiet_windows": ["12:00-13:00"]})
        assert s.is_quiet(dt(12, 0)) is True
        assert s.is_quiet(dt(12, 30)) is True
        assert s.is_quiet(dt(12, 59)) is True
        assert s.is_quiet(dt(13, 0)) is False  # end 不含
        assert s.is_quiet(dt(11, 59)) is False

    def test_cross_midnight_window(self):
        # 跨午夜静默档 [23:00, 01:00)
        s = CircadianScheduler({**DEFAULT_SCHEDULE, "quiet_windows": ["23:00-01:00"]})
        assert s.is_quiet(dt(23, 0)) is True
        assert s.is_quiet(dt(23, 59)) is True
        assert s.is_quiet(dt(0, 0)) is True
        assert s.is_quiet(dt(0, 59)) is True
        assert s.is_quiet(dt(1, 0)) is False  # end 不含
        assert s.is_quiet(dt(22, 59)) is False

    def test_multiple_windows(self):
        s = CircadianScheduler(
            {**DEFAULT_SCHEDULE, "quiet_windows": ["12:00-13:00", "15:00-16:00"]}
        )
        assert s.is_quiet(dt(15, 30)) is True
        assert s.is_quiet(dt(12, 30)) is True
        assert s.is_quiet(dt(14, 0)) is False


# ================================================================ ④ 非法 HH:MM 校验
class TestParseErrors:
    def test_parse_hhmm_valid(self):
        assert parse_hhmm("08:00") == time(8, 0)
        assert parse_hhmm("8:00") == time(8, 0)  # 契约允许单数字小时
        assert parse_hhmm("00:00") == time(0, 0)
        assert parse_hhmm("23:59") == time(23, 59)

    def test_parse_hhmm_invalid(self):
        for bad in ["25:00", "24:00", "08:60", "08", "08:00:00", "a:b", "", " 08:00", "8:0", "08:6"]:
            with pytest.raises(ValueError):
                parse_hhmm(bad)

    def test_constructor_invalid_time_raises(self):
        with pytest.raises(ValueError):
            CircadianScheduler({**DEFAULT_SCHEDULE, "wake_time": "25:99"})

    def test_constructor_invalid_quiet_window_raises(self):
        with pytest.raises(ValueError):
            CircadianScheduler({**DEFAULT_SCHEDULE, "quiet_windows": ["12:00"]})
        with pytest.raises(ValueError):
            CircadianScheduler({**DEFAULT_SCHEDULE, "quiet_windows": ["12:00-25:00"]})
        with pytest.raises(ValueError):
            CircadianScheduler({**DEFAULT_SCHEDULE, "quiet_windows": ["12:00-13:00-14:00"]})


# ================================================================ in_window 工具函数
class TestInWindow:
    def test_same_day_window(self):
        start, end = parse_hhmm("11:00"), parse_hhmm("13:00")
        assert in_window(dt(11, 0), start, end) is True
        assert in_window(dt(12, 0), start, end) is True
        assert in_window(dt(13, 0), start, end) is False

    def test_cross_midnight_window(self):
        start, end = parse_hhmm("22:00"), parse_hhmm("06:00")
        assert in_window(dt(23, 0), start, end) is True
        assert in_window(dt(5, 0), start, end) is True
        assert in_window(dt(6, 0), start, end) is False
        assert in_window(dt(12, 0), start, end) is False


# ================================================================ ⑤ 跨午夜睡眠窗口边界
class TestCrossMidnightSleep:
    def test_cross_midnight_window(self):
        # sleep 22:00 / wake 06:00：睡眠窗口 [22:00, 06:00) 跨午夜
        s = CircadianScheduler(
            {
                "wake_time": "06:00",
                "sleep_time": "22:00",
                "golden_start": "19:00",
                "golden_end": "23:00",
                "diary_time": "02:00",
                "quiet_windows": [],
            }
        )
        # 22:00 起入睡
        assert s.is_sleep_time(dt(21, 59)) is False
        assert s.is_sleep_time(dt(22, 0)) is True
        assert s.is_sleep_time(dt(23, 30)) is True
        # 跨午夜段
        assert s.is_sleep_time(dt(0, 0)) is True
        assert s.is_sleep_time(dt(2, 0)) is True
        assert s.is_sleep_time(dt(5, 59)) is True
        # 06:00 清醒
        assert s.is_sleep_time(dt(6, 0)) is False
        assert s.is_awake(dt(6, 0)) is True
        assert s.is_awake(dt(12, 0)) is True
        assert s.is_awake(dt(21, 59)) is True
