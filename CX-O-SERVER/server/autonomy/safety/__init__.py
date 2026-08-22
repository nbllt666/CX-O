"""CX-O-Autonomy 安全层（P1-T5）。

为自主系统提供运行时安全护栏，对外统一导出五大组件：
- TokenLedger  每日 token/调用预算台账（对齐 autonomy_config.budget）
- ContentGate  对外输出内容闸门（复用主服务防火墙 + 人设校验 + 基础检查）
- RateLimiter  滑动窗口限流器（如每小时最大发帖数）
- KillSwitch   急停/暂停/睡眠状态开关
- AuditStore   审计日志存储（JSONL，对齐 autonomy_audit.schema.json）

各组件均为无外部副作用依赖的独立实现，store 路径缺省基于 __file__ 绝对路径
解析到 server/autonomy/data/，禁止相对路径。
"""

from server.autonomy.safety.audit import AuditStore
from server.autonomy.safety.budget.token_ledger import TokenLedger
from server.autonomy.safety.gate.content_gate import ContentGate
from server.autonomy.safety.killswitch import KillSwitch
from server.autonomy.safety.ratelimit.limiter import RateLimiter

__all__ = ["TokenLedger", "ContentGate", "RateLimiter", "KillSwitch", "AuditStore"]
