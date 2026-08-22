"""CX-O-Autonomy 反思层包（P1-T7）。

反思层是自主系统主循环之外的后处理能力，包含三类组件：
- DiaryGenerator      基于当日活动日志生成第一人称日记并写入长期记忆
- Consolidator        对多条自主经历做整合/蒸馏（P3-T2 接入真实蒸馏服务）
- FeedbackEvaluator   对单次行动结果做简单效果评估并提交偏好信号

包内模块：
- diary/generator.py      DiaryGenerator 日记生成器
- consolidator.py         Consolidator 经历整合器
- feedback/evaluator.py   FeedbackEvaluator 效果评估器

对外导出：DiaryGenerator / Consolidator / FeedbackEvaluator。
"""

from server.autonomy.reflection.consolidator import Consolidator
from server.autonomy.reflection.diary.generator import DiaryGenerator
from server.autonomy.reflection.feedback.evaluator import FeedbackEvaluator

__all__ = ["DiaryGenerator", "Consolidator", "FeedbackEvaluator"]
