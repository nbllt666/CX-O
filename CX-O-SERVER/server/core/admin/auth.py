"""CX-A 管理面认证与防护（对齐 cx_admin.pyi AdminAuth 契约）。

[ ] 更新
"""
import logging
import secrets
import time
import threading
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 管理面异常层次（错误码与 public/schema/error_codes / cx_admin.pyi 对齐）
# ---------------------------------------------------------------------------


class AdminError(Exception):
    """管理面基础异常。error_code 为下述 ADMIN_* 之一。"""

    error_code: str = "ADMIN_ERROR"
    message: str = ""

    def __init__(self, message: str = ""):
        self.message = message
        super().__init__(message or self.error_code)


class AdminDisabledError(AdminError):
    error_code = "ADMIN_DISABLED"


class AdminAuthError(AdminError):
    error_code = "ADMIN_AUTH_FAILED"


class AdminForbiddenError(AdminError):
    error_code = "ADMIN_FORBIDDEN"


class AdminReplayError(AdminError):
    error_code = "ADMIN_REPLAYED"


class AdminRateLimitedError(AdminError):
    error_code = "ADMIN_RATE_LIMITED"


class AdminUnknownActionError(AdminError):
    error_code = "ADMIN_UNKNOWN_ACTION"


class AdminServiceError(AdminError):
    error_code = "ADMIN_SERVICE_ERROR"


# 能力分级排序：readonly（仅 GET）< operator（可控制）< superadmin（可重启/故障转移/增删节点）
LEVEL_ORDER: Dict[str, int] = {
    "readonly": 0,
    "operator": 1,
    "superadmin": 2,
}


def _token_value(tok) -> str:
    """兼容 AdminTokenConfig 对象或 dict 两种形态取 token 明文。"""
    if isinstance(tok, dict):
        return tok.get("token", "")
    return getattr(tok, "token", "")


def _token_level(tok) -> str:
    if isinstance(tok, dict):
        return tok.get("level", "readonly")
    return getattr(tok, "level", "readonly")


class AdminAuth:
    """多级 token 认证 + request_id 防重放（TTL 缓存）+ 简单令牌桶限流。

    Args:
        config: ``server.config.AdminConfig`` 对象（鸭子类型，可注入等价物）。
    """

    def __init__(self, config):
        self.config = config
        self._replay: Dict[str, float] = {}
        self._replay_lock = threading.Lock()

        self._rate_capacity = float(getattr(config, "rate_limit_per_sec", None) or 20)
        if self._rate_capacity <= 0:
            self._rate_capacity = 20.0
        self._rate_tokens = self._rate_capacity
        self._rate_last = time.monotonic()
        self._rate_lock = threading.Lock()

        # 安全遥测计数器（ADDITIVE，spec enhance-admin-telemetry 二）：
        # 独立锁，不复用 _rate_lock/_replay_lock（两处递增点位于既有锁内，
        # 独立锁避免锁序耦合）；AdminDisabledError 路径不计数（显式设计声明）。
        self._security_lock = threading.Lock()
        self._auth_fail_count = 0
        self._rate_limited_count = 0
        self._replay_count = 0

    # ---- 认证 ----
    def authenticate(self, bearer_token: str) -> str:
        """按 config.tokens 逐条 compare_digest 匹配，返回 level。

        无任何 token 匹配抛 AdminAuthError；config.tokens 为空抛 AdminDisabledError。
        """
        tokens = list(getattr(self.config, "tokens", None) or [])
        if not tokens:
            # AdminDisabledError 路径不计数（配置未启用≠认证失败）
            raise AdminDisabledError("ADMIN_DISABLED")
        for tok in tokens:
            if not _token_value(tok):
                continue
            if secrets.compare_digest(_token_value(tok), bearer_token):
                level = _token_level(tok)
                return level if level in LEVEL_ORDER else "readonly"
        with self._security_lock:
            self._auth_fail_count += 1
        raise AdminAuthError("ADMIN_AUTH_FAILED")

    # ---- 权限 ----
    def check_required_level(self, token_level: str, required: str) -> None:
        """token level 不足 required 时抛 AdminForbiddenError。"""
        have = LEVEL_ORDER.get(str(token_level), -1)
        need = LEVEL_ORDER.get(str(required), 99)
        if have < need:
            raise AdminForbiddenError("ADMIN_FORBIDDEN")

    # ---- 防重放 ----
    def check_replay(self, request_id: str) -> None:
        """request_id 重复抛 AdminReplayError；同时清理超过 TTL 的旧缓存。"""
        if not request_id:
            return
        now = time.monotonic()
        ttl = float(getattr(self.config, "request_id_ttl_sec", None) or 300) or 300
        with self._replay_lock:
            stale = [rid for rid, ts in self._replay.items() if now - ts > ttl]
            for rid in stale:
                self._replay.pop(rid, None)
            if request_id in self._replay:
                with self._security_lock:
                    self._replay_count += 1
                raise AdminReplayError("ADMIN_REPLAYED")
            self._replay[request_id] = now

    # ---- 限流 ----
    def check_rate_limit(self) -> None:
        """简单令牌桶：超限抛 AdminRateLimitedError。"""
        now = time.monotonic()
        with self._rate_lock:
            elapsed = now - self._rate_last
            self._rate_tokens = min(
                self._rate_capacity, self._rate_tokens + elapsed * self._rate_capacity
            )
            self._rate_last = now
            if self._rate_tokens < 1.0:
                with self._security_lock:
                    self._rate_limited_count += 1
                raise AdminRateLimitedError("ADMIN_RATE_LIMITED")
            self._rate_tokens -= 1.0

    # ---- 安全遥测计数器（ADDITIVE，spec enhance-admin-telemetry 二）----
    def get_security_counters(self) -> Dict[str, int]:
        """返回安全事件只读计数快照（供遥测 security 组采集）。"""
        with self._security_lock:
            return {
                "auth_fail_count": self._auth_fail_count,
                "rate_limited_count": self._rate_limited_count,
                "replay_count": self._replay_count,
            }

    # ---- 测试/reset 辅助 ----
    def reset_replay(self) -> None:
        """清空防重放缓存（测试用）。"""
        with self._replay_lock:
            self._replay.clear()