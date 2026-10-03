"""CX-O-Autonomy 安全层（P1-T5）。

为自主系统提供运行时安全护栏，对外统一导出三大组件：
- ContentGate  对外输出内容闸门（复用主服务防火墙 + 人设校验 + 基础检查）
- RateLimiter  滑动窗口限流器（如每小时最大发帖数）
- AuditStore   审计日志存储（JSONL，对齐 autonomy_audit.schema.json）

2026-09-27 人类裁决：`TokenLedger`（每日 token/调用预算台账）与 `KillSwitch`
（暂停/睡眠状态开关）已随「删除预算记账 / manager 门控 / killswitch 三道路径」
整体移除（纯本地项目不需要这些管控设施）。「用户在线休眠」行为保留，落点改为
`AutonomyEngine._user_online_sleeping` 引擎内标志。

各组件均为无外部副作用依赖的独立实现，store 路径缺省基于 __file__ 绝对路径
解析到 server/autonomy/data/，禁止相对路径。
"""

from server.autonomy.safety.audit import AuditStore
from server.autonomy.safety.gate.content_gate import ContentGate
from server.autonomy.safety.ratelimit.limiter import RateLimiter

__all__ = ["ContentGate", "RateLimiter", "AuditStore"]
