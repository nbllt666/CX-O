"""CXO-Tuner 裁判引擎与「历史对话→DPO 自动构建」管道。

- JudgeEngine：LLM-as-a-Judge pairwise 裁判（_compare -> JudgeResult）。
- DpoBuilder：对同一 prompt 的多候选回复做 pairwise 比较，产出 source=judge 的
  DPO 记录写入 DatasetStore，并记录审计明细。
"""
from __future__ import annotations

from tuner.core.judge.dpo_builder import BuildDpoResult, DpoBuilder
from tuner.core.judge.judge_engine import (
    DIMENSION_KEYS,
    JudgeCallError,
    JudgeEngine,
    JudgeError,
    JudgeParseError,
    JudgeResult,
)

__all__ = [
    "JudgeEngine",
    "JudgeResult",
    "JudgeError",
    "JudgeCallError",
    "JudgeParseError",
    "DpoBuilder",
    "BuildDpoResult",
    "DIMENSION_KEYS",
]