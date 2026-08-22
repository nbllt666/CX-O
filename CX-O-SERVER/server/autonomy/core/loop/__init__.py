"""CX-O-Autonomy 主循环引擎包（P1-T8）。

- autonomy_engine.py   AutonomyEngine：感知→动机→规划→行动→审计五层流水线
  主循环，负责任务调度、动作分发、内容闸门、审计记录、Token 记账、效果评估、
  日记触发与重启续接。

本包不涉及任何文件 IO，禁止相对路径。
"""
