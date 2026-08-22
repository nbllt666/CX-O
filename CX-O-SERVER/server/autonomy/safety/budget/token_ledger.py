"""CX-O-Autonomy 安全层——TokenLedger 每日 Token/调用预算台账。

对齐 autonomy_config.schema.json 的 budget 配置语义：
- daily_token_limit / daily_llm_calls_limit 为 0 表示"不限制"；
- cost_alert_threshold 取 0-1，使用率达到阈值触发一次告警（当日不重复）；
- overspend_mode 超支降级模式（sleep / low_cost）。

职责：
- 按自然日累计 token 消耗（add_tokens，支持 dict 或 int）与 LLM 调用次数；
- 超支判定（is_over_budget）、预算使用率（usage_ratio，超限 cap 1.0）；
- 当日剩余预算（remaining，不限制时返回 None 表示无穷大）；
- 告警闸门（is_alert_triggered，当日只触发一次）；
- 超支降级模式（get_mode → normal / overspend_mode）；
- 按日期自动重置（reset_if_new_day），并 JSON 持久化到
  server/autonomy/data/token_ledger.json（store_path 缺省基于 __file__ 绝对路径）。
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

# 默认存储路径：本文件位于 server/autonomy/safety/budget/，parents[2] = server/autonomy
DEFAULT_STORE_PATH = str(Path(__file__).resolve().parents[2] / "data" / "token_ledger.json")


def _normalize_date(value: Optional[Union[datetime.date, datetime.datetime, str]]) -> str:
    """把 date / datetime / ISO 字符串统一归一化为 YYYY-MM-DD。"""
    if value is None:
        return datetime.date.today().isoformat()
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, str):
        return value[:10]
    raise TypeError(f"无法识别的日期参数 {value!r}")


class TokenLedger:
    """每日 token/调用预算台账，按自然日自动重置并持久化 JSON。"""

    def __init__(
        self,
        daily_token_limit: int = 2000000,
        daily_llm_calls_limit: int = 0,
        cost_alert_threshold: float = 0.8,
        overspend_mode: str = "sleep",
        store_path: Optional[str] = None,
    ) -> None:
        # 参数缺省值对齐 autonomy_config.schema.json budget 契约
        self.daily_token_limit = max(int(daily_token_limit), 0)
        self.daily_llm_calls_limit = max(int(daily_llm_calls_limit), 0)
        self.cost_alert_threshold = max(min(float(cost_alert_threshold), 1.0), 0.0)
        self.overspend_mode = overspend_mode
        self.store_path = store_path or DEFAULT_STORE_PATH
        self._date: str = _normalize_date(None)
        self._used_tokens: int = 0
        self._llm_calls: int = 0
        self._alerted: bool = False

    # ------------------------------------------------------------ 当日消耗
    def add_tokens(self, usage: Union[Dict[str, Any], int]) -> int:
        """累加当日 token 消耗，返回累加后的当日已用 token 数。

        usage 为 int 时直接累加；为 dict 时优先取 total_tokens，
        否则取 prompt_tokens + completion_tokens；两个键均缺失时按 0 计。
        """
        if isinstance(usage, int):
            tokens = max(usage, 0)
        elif isinstance(usage, dict):
            total = usage.get("total_tokens")
            if total is not None:
                tokens = max(int(total), 0)
            else:
                prompt = int(usage.get("prompt_tokens") or 0)
                completion = int(usage.get("completion_tokens") or 0)
                tokens = max(prompt + completion, 0)
        else:
            raise TypeError(f"usage 必须为 dict 或 int，收到 {type(usage).__name__}")
        self._used_tokens += tokens
        return self._used_tokens

    def add_llm_call(self) -> int:
        """累加当日 LLM 调用次数，返回累计值。"""
        self._llm_calls += 1
        return self._llm_calls

    # ------------------------------------------------------------ 查询
    def daily_used(self) -> int:
        """返回当日已消耗 token 数。"""
        return self._used_tokens

    def daily_calls(self) -> int:
        """返回当日 LLM 调用次数。"""
        return self._llm_calls

    def remaining(self) -> Optional[int]:
        """返回当日剩余可用 token 数。

        注意：daily_token_limit 为 0（不限制）时返回 None，语义为无穷大。
        """
        if self.daily_token_limit <= 0:
            return None
        return max(self.daily_token_limit - self._used_tokens, 0)

    def is_over_budget(self) -> bool:
        """是否超支：token 消耗达到上限 或 LLM 调用次数达到上限。

        对应上限为 0（不限制）时该项不参与判定。
        """
        if self.daily_token_limit > 0 and self._used_tokens >= self.daily_token_limit:
            return True
        if self.daily_llm_calls_limit > 0 and self._llm_calls >= self.daily_llm_calls_limit:
            return True
        return False

    def usage_ratio(self) -> float:
        """预算使用率（0-1，超限 cap 1.0）。不限制时返回 0.0。"""
        if self.daily_token_limit <= 0:
            return 0.0
        return min(self._used_tokens / self.daily_token_limit, 1.0)

    def is_alert_triggered(self) -> bool:
        """使用率达到告警阈值且当日尚未告警过时返回 True，并置当日告警标记。

        当日只触发一次；跨日（reset_if_new_day）后标记重置，可再次触发。
        """
        if self.daily_token_limit <= 0 or self._alerted:
            return False
        if self.usage_ratio() >= self.cost_alert_threshold:
            self._alerted = True
            return True
        return False

    def get_mode(self) -> str:
        """返回运行模式：超支时返回 overspend_mode（sleep/low_cost），否则 normal。"""
        if self.is_over_budget():
            return self.overspend_mode
        return "normal"

    # ------------------------------------------------------------ 日期与持久化
    def reset_if_new_day(
        self,
        now: Optional[Union[datetime.date, datetime.datetime, str]] = None,
    ) -> bool:
        """按日期自动重置当日计数。

        now 缺省取当前日期；与记录的日期不同则清零 token/调用/告警标记并更新日期，
        返回 True 表示发生跨日重置，否则 False。
        """
        today = _normalize_date(now)
        if today == self._date:
            return False
        self._date = today
        self._used_tokens = 0
        self._llm_calls = 0
        self._alerted = False
        return True

    def load(self) -> "TokenLedger":
        """从 store_path 读取持久化状态；文件缺失/损坏时回退默认并重置为当前日期。"""
        self._date = _normalize_date(None)
        self._used_tokens = 0
        self._llm_calls = 0
        self._alerted = False
        path = Path(self.store_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._date = _normalize_date(data.get("date"))
                self._used_tokens = max(int(data.get("used_tokens", 0)), 0)
                self._llm_calls = max(int(data.get("llm_calls", 0)), 0)
                self._alerted = bool(data.get("alerted", False))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                # 损坏文件不致命：回退默认并重置为当前日期
                self._date = _normalize_date(None)
                self._used_tokens = 0
                self._llm_calls = 0
                self._alerted = False
        self.reset_if_new_day()
        return self

    def save(self) -> str:
        """将当前状态持久化为 JSON，返回写入路径。"""
        path = Path(self.store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "date": self._date,
            "used_tokens": self._used_tokens,
            "llm_calls": self._llm_calls,
            "alerted": self._alerted,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(path)
