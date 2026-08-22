"""昼夜节律调度器子包（CX-O-Autonomy P1-T2）。

对外导出：
- CircadianScheduler  按日程配置判定当前相位的主类
- parse_hhmm          "HH:MM" 字符串 → time 对象（非法抛 ValueError）
- in_window           时间窗口判定（支持跨午夜）

使用示例：
    from server.autonomy.core.scheduler import CircadianScheduler

    scheduler = CircadianScheduler(schedule={
        "wake_time": "08:00", "sleep_time": "02:00",
        "golden_start": "19:00", "golden_end": "23:00",
        "diary_time": "02:00", "quiet_windows": ["12:00-13:00"],
    })
    scheduler.current_phase(now)  # "sleep" / "golden" / "quiet" / "active"
"""

from server.autonomy.core.scheduler.circadian import (
    CircadianScheduler,
    in_window,
    parse_hhmm,
)

__all__ = ["CircadianScheduler", "parse_hhmm", "in_window"]
