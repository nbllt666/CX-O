"""CX-O-Autonomy 自主系统包。

CX-O-Autonomy 是 CX-O 的"自主生活"子系统：按人设动机（curiosity / social_need /
creative_drive / fatigue）、日程（起床/入睡/黄金档/日记时刻/静默档）与预算
（token/调用次数/超支降级）驱动的自主行动循环，覆盖 读新闻 → 搜索 → 写记忆 →
发帖 → 直播 → 写日记 等 9 种行动，并以审计日志记录每次行动的决策理由与结果。

包内模块：
- config.py    AutonomyConfig 配置模型（对齐 public/schema/autonomy_config.schema.json）
               与加载/保存/存储目录解析
- models.py    AutonomyAction / AutonomyAuditEntry / AutonomyState 数据模型
- manager.py   AutonomyManager 管理器（P0 最小骨架，P1-T8 扩展主循环）
- main.py      embedded CXFC 插件装配入口（TOOL_SPECS / SKILL_SPECS / setup_autonomy）

对外导出：setup_autonomy / get_autonomy_manager（见 main.py）。
"""

from server.autonomy.main import get_autonomy_manager, setup_autonomy

__all__ = ["setup_autonomy", "get_autonomy_manager"]
