"""tuner.core.scheduler：闲时训练调度与在线 DPO（探索）。

- idle_scheduler.py  IdleScheduler 闲时训练调度（判定 + 触发，时钟可注入）
- online_dpo.py      OnlineDpo 在线 DPO 执行桩（experimental，默认关闭）

本包只导出纯判定函数、调度/桩类与后台运行实例的构造入口；模块导入零副作用，
不独占启动任何后台线程——启停由 main.py 的 lifespan 负责。
"""
from tuner.core.scheduler.idle_scheduler import IdleScheduler, has_completed_today, is_idle_time
from tuner.core.scheduler.online_dpo import OnlineDpo

__all__ = [
    "IdleScheduler",
    "OnlineDpo",
    "has_completed_today",
    "is_idle_time",
]