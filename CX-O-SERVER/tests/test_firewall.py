"""server.services.firewall 单元测试。

覆盖弹幕防火墙：长度/用户/频率/重复/关键词模式过滤、disabled 跳过、
set_config 动态更新、编译模式、单例与统计。通过 monkeypatch 模块级
Settings 为假对象以隔离配置加载。

运行：python -m pytest tests/test_firewall.py -v
"""
import pytest

from server.services import firewall as firewall_mod
from server.services.firewall import FirewallConfig, FirewallService


class _FakeLimits:
    max_messages_per_second = 5.0
    max_messages_per_minute = 100
    duplicate_threshold = 3
    duplicate_window_seconds = 30
    max_message_length = 500


class _FakeFirewallLimits:
    firewall = _FakeLimits()


class _FakeConfig:
    limits = _FakeFirewallLimits()


class _FakeSettings:
    def __init__(self):
        self.config = _FakeConfig()


@pytest.fixture
def svc(monkeypatch):
    """构造隔离的 FirewallService，避免单例粘滞。"""
    monkeypatch.setattr(firewall_mod, "Settings", _FakeSettings)
    # 每次重置单例，保证测试相互独立
    firewall_mod.FirewallService._instance = None
    return FirewallService()


# ---------------------------------------------------------------- 基础
def test_default_config(svc):
    assert svc.config.enabled is True
    assert svc.config.rate_limit_enabled is True
    assert svc.config.duplicate_filter_enabled is True
    assert svc.config.length_filter_enabled is True
    assert svc.config.max_message_length == 500


def test_disabled_always_allows(svc):
    svc.config.enabled = False
    res = svc.filter_message("x", user_id="blocked_user")
    assert res.allowed is True


def test_allowed_basic(svc):
    res = svc.filter_message("hello world")
    assert res.allowed is True
    assert res.filtered_content == "hello world"
    assert res.original_content == "hello world"


# ---------------------------------------------------------------- 长度
def test_message_too_short(svc):
    svc.config.min_message_length = 5
    res = svc.filter_message("hi")
    assert res.allowed is False
    assert "too short" in res.reason


def test_message_too_long(svc):
    svc.config.max_message_length = 5
    res = svc.filter_message("hello world")
    assert res.allowed is False
    assert "too long" in res.reason


def test_length_filter_disabled(svc):
    svc.config.length_filter_enabled = False
    svc.config.min_message_length = 100
    res = svc.filter_message("hi")
    assert res.allowed is True


# ---------------------------------------------------------------- 用户
def test_blocked_user(svc):
    svc.config.blocked_users = ["bad_user"]
    res = svc.filter_message("hello", user_id="bad_user")
    assert res.allowed is False
    assert "blocked" in res.reason


def test_blocked_user_is_owner_only(svc):
    svc.config.blocked_users = ["bad_user"]
    res = svc.filter_message("hello", user_id="good_user")
    assert res.allowed is True


def test_user_filter_disabled(svc):
    svc.config.user_filter_enabled = False
    svc.config.blocked_users = ["bad_user"]
    res = svc.filter_message("hello", user_id="bad_user")
    assert res.allowed is True


# ---------------------------------------------------------------- 频率
def test_rate_limit_per_second(svc):
    svc.config.max_messages_per_second = 2
    svc.filter_message("a")
    svc.filter_message("b")
    res = svc.filter_message("c")  # 3rd within 1s
    assert res.allowed is False
    assert "per second" in res.reason


def test_rate_limit_per_minute_user(svc):
    svc.config.max_messages_per_minute = 3
    svc.config.max_messages_per_second = 100
    for i in range(3):
        svc.filter_message(f"msg{i}", user_id="u1")
    res = svc.filter_message("msg3", user_id="u1")
    assert res.allowed is False
    assert "rate limit exceeded" in res.reason


def test_rate_limit_only_counts_user(svc):
    svc.config.max_messages_per_minute = 3
    svc.config.max_messages_per_second = 1000
    for i in range(100):
        svc.filter_message(f"msg{i}", user_id="u1")
    # 其他用户不受影响
    res = svc.filter_message("other", user_id="u2")
    assert res.allowed is True


# ---------------------------------------------------------------- 重复
def test_duplicate_filter(svc):
    svc.config.duplicate_threshold = 3
    svc.config.duplicate_window_seconds = 30
    svc.filter_message("same")
    svc.filter_message("same")
    svc.filter_message("same")
    res = svc.filter_message("same")  # 第 4 条，之前已有 3 条命中阈值
    assert res.allowed is False
    assert "Duplicate" in res.reason


def test_duplicate_below_threshold_allowed(svc):
    svc.config.duplicate_threshold = 3
    svc.filter_message("same")
    res = svc.filter_message("same")
    assert res.allowed is True


def test_duplicate_filter_disabled(svc):
    svc.config.duplicate_filter_enabled = False
    svc.config.duplicate_threshold = 3
    for _ in range(5):
        assert svc.filter_message("same").allowed is True


# ---------------------------------------------------------------- 关键词
def test_blocked_pattern(svc):
    svc.config.blocked_patterns = [r"暴力", r"咒骂"]
    svc._compile_patterns()
    res = svc.filter_message("暴力冲突")
    assert res.allowed is False
    assert "pattern" in res.reason


def test_blocked_pattern_regex(svc):
    svc.config.blocked_patterns = [r"bad\s+word"]
    svc._compile_patterns()
    res = svc.filter_message("a bad word here")
    assert res.allowed is False


def test_invalid_pattern_ignored(svc):
    svc.config.blocked_patterns = ["[invalid"]
    svc._compile_patterns()
    res = svc.filter_message("anything")
    assert res.allowed is True


def test_pattern_filter_disabled(svc):
    svc.config.pattern_filter_enabled = False
    svc.config.blocked_patterns = [r"bad"]
    svc._compile_patterns()
    res = svc.filter_message("bad")
    assert res.allowed is True


# ---------------------------------------------------------------- set_config
def test_set_config_updates_values(svc):
    svc.set_config({"enabled": True, "max_messages_per_second": 1.0})
    assert svc.config.max_messages_per_second == 1.0


def test_set_config_compiles_patterns(svc):
    svc.set_config({"blocked_patterns": [r"foo", r"bar"]})
    assert len(svc._compiled_patterns) == 2


def test_set_config_ignores_unknown_keys(svc):
    svc.set_config({"nonexistent_key": 123})
    # 不应抛错


def test_set_config_null_max_length_keeps_old(svc):
    old = svc.config.max_message_length
    svc.set_config({"max_message_length": None})
    assert svc.config.max_message_length == old


def test_set_config_non_int_max_length_keeps_old(svc):
    old = svc.config.max_message_length
    svc.set_config({"max_message_length": "abc"})
    assert svc.config.max_message_length == old


def test_filter_message_null_max_length_allows(svc):
    svc.config.max_message_length = None
    svc.config.min_message_length = 1
    res = svc.filter_message("非常长的消息内容" * 100)
    assert res.allowed is True


# ---------------------------------------------------------------- 统计/单例
def test_get_stats(svc):
    svc.filter_message("hello")
    stats = svc.get_stats()
    assert stats["enabled"] is True
    assert stats["blocked_users_count"] == 0
    assert stats["recent_messages_tracked"] == 1


def test_singleton(monkeypatch):
    monkeypatch.setattr(firewall_mod, "Settings", _FakeSettings)
    firewall_mod.FirewallService._instance = None
    a = firewall_mod.get_firewall_service()
    b = firewall_mod.get_firewall_service()
    assert a is b