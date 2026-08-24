"""server.core.admin.auth 测试：token 分级 / 防重放 / 限流 / 空 token 降级。

运行：python -m pytest tests/test_admin_auth.py -v
"""
import pytest
from unittest.mock import MagicMock

from server.core.admin.auth import (
    AdminAuth,
    AdminAuthError,
    AdminDisabledError,
    AdminForbiddenError,
    AdminRateLimitedError,
    AdminReplayError,
)


def _cfg(tokens=None, ttl=300, rps=100.0):
    cfg = MagicMock()
    cfg.tokens = tokens or []
    cfg.request_id_ttl_sec = ttl
    cfg.rate_limit_per_sec = rps
    return cfg


def _tok(token, level="readonly"):
    return MagicMock(token=token, level=level)


class TestAuthenticate:
    def test_match_returns_level(self):
        auth = AdminAuth(_cfg(tokens=[_tok("a", "readonly"), _tok("b", "superadmin")]))
        assert auth.authenticate("a") == "readonly"
        assert auth.authenticate("b") == "superadmin"

    def test_no_token_raises_disabled(self):
        auth = AdminAuth(_cfg(tokens=[]))
        with pytest.raises(AdminDisabledError):
            auth.authenticate("any")

    def test_unknown_raises_auth_failed(self):
        auth = AdminAuth(_cfg(tokens=[_tok("a", "operator")]))
        with pytest.raises(AdminAuthError):
            auth.authenticate("nope")

    def test_dict_tokens_accepted(self):
        auth = AdminAuth(_cfg(tokens=[{"token": "x", "level": "operator"}]))
        assert auth.authenticate("x") == "operator"


class TestCheckRequiredLevel:
    def test_enough_passes(self):
        auth = AdminAuth(_cfg(tokens=[_tok("a", "superadmin")]))
        auth.check_required_level("superadmin", "operator")
        auth.check_required_level("superadmin", "superadmin")

    def test_insufficient_raises(self):
        auth = AdminAuth(_cfg(tokens=[_tok("a", "readonly")]))
        with pytest.raises(AdminForbiddenError):
            auth.check_required_level("readonly", "operator")
        with pytest.raises(AdminForbiddenError):
            auth.check_required_level("operator", "superadmin")


class TestReplay:
    def test_replay_raises(self):
        auth = AdminAuth(_cfg(tokens=[], ttl=300))
        auth.check_replay("rid-1")
        with pytest.raises(AdminReplayError):
            auth.check_replay("rid-1")

    def test_distinct_ok(self):
        auth = AdminAuth(_cfg(tokens=[], ttl=300))
        auth.check_replay("r1")
        auth.check_replay("r2")

    def test_ttl_expiry_clears(self, monkeypatch):
        import time as _time

        auth = AdminAuth(_cfg(tokens=[], ttl=1))
        auth.check_replay("rid")
        with pytest.raises(AdminReplayError):
            auth.check_replay("rid")
        monkeypatch.setattr("server.core.admin.auth.time", _PlainTime)
        # 模拟时间前进 2 秒后应清理
        _PlainTime._offset = 2
        try:
            auth.check_replay("rid")  # 不抛异常
        finally:
            _PlainTime._offset = 0


class _PlainTime:
    _offset = 0.0

    @staticmethod
    def monotonic():
        import time as _t

        return _t.monotonic() + _PlainTime._offset


class TestRateLimit:
    def test_limits_after_capacity(self):
        # capacity 3，第 4 次应触发限流
        auth = AdminAuth(_cfg(tokens=[], rps=3))
        auth.check_rate_limit()
        auth.check_rate_limit()
        auth.check_rate_limit()
        with pytest.raises(AdminRateLimitedError):
            auth.check_rate_limit()

    def test_high_capacity_passes(self):
        auth = AdminAuth(_cfg(tokens=[], rps=100))
        for _ in range(50):
            auth.check_rate_limit()