"""CX-O-Autonomy 安全层——RateLimiter 滑动窗口限流器。

对自主行动按 key 做滑动窗口限频（默认 key="post"，对应 autonomy_config.safety
的 post_rate_per_hour，每小时最大发帖数）：
- allow(key)     仅检查当前窗口内是否未达上限，不记录命中；
- hit(key)       记录一次命中（消费）；
- window_remaining(key)  返回窗口内剩余可用次数。

支持测试时钟注入：构造传入 clock: Callable（返回秒级时间戳），或逐次传入
now 参数覆盖当前时间，便于验证窗口滑出后的恢复行为。
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional


class RateLimiter:
    """滑动窗口限流器：按 key 统计窗口内命中数，窗口滑出后自动恢复。"""

    def __init__(
        self,
        limit_per_hour: int = 5,
        window_minutes: int = 60,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.limit_per_hour = max(int(limit_per_hour), 0)
        self.window_minutes = max(int(window_minutes), 1)
        self.window_seconds: float = self.window_minutes * 60.0
        # 测试时钟注入：clock() -> 秒级时间戳
        self._clock: Optional[Callable[[], float]] = clock
        # key -> 窗口内命中时间戳列表
        self._hits: Dict[str, List[float]] = {}

    def _now(self, now: Optional[float] = None) -> float:
        """解析当前时间：优先显式 now，其次注入时钟，最后系统时间。"""
        if now is not None:
            return float(now)
        if self._clock is not None:
            return float(self._clock())
        return time.time()

    def _prune(self, key: str, now: float) -> None:
        """清理窗口外（now - window_seconds 之前）的命中记录。"""
        cutoff = now - self.window_seconds
        kept = [t for t in self._hits.get(key, []) if t > cutoff]
        if kept:
            self._hits[key] = kept
        elif key in self._hits:
            del self._hits[key]

    def allow(self, key: str = "post", now: Optional[float] = None) -> bool:
        """检查该 key 当前窗口内是否还可消费（未达上限）。不记录命中。"""
        now_ts = self._now(now)
        self._prune(key, now_ts)
        return len(self._hits.get(key, [])) < self.limit_per_hour

    def hit(self, key: str = "post", now: Optional[float] = None) -> int:
        """记录一次命中（消费），返回窗口内累计命中数。"""
        now_ts = self._now(now)
        self._prune(key, now_ts)
        hits = self._hits.setdefault(key, [])
        hits.append(now_ts)
        return len(hits)

    def window_remaining(self, key: str = "post", now: Optional[float] = None) -> int:
        """返回该 key 当前窗口内剩余可用次数。"""
        now_ts = self._now(now)
        self._prune(key, now_ts)
        return max(self.limit_per_hour - len(self._hits.get(key, [])), 0)
