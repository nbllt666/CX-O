"""CX-O-Autonomy 安全层（P1-T5）单元测试。

覆盖范围：
① TokenLedger —— add/remaining/超限/usage_ratio cap 1.0/告警一次/新日重置/持久化往返；
② ContentGate —— 防火墙拒绝与放行、persona_check 调用（同步/异步）、未注入时基础检查；
③ RateLimiter —— 达上限 allow=False、窗口滑过后恢复、hit 计数、时钟注入；
④ KillSwitch —— 急停后 is_active False、resume 恢复、pause/sleeping、持久化往返；
⑤ AuditStore —— append/list 分页/缺字段拒绝/非法枚举拒绝/clear。

运行：python -m pytest tests/test_autonomy_safety.py -q
"""
import asyncio
import datetime
from pathlib import Path

import pytest

from server.autonomy.safety import (
    AuditStore,
    ContentGate,
    KillSwitch,
    RateLimiter,
    TokenLedger,
)


def _run(coro):
    """在同步测试内运行 async 协程。"""
    return asyncio.run(coro)


# ================================================================ ① TokenLedger
class TestTokenLedger:
    def test_add_and_remaining(self, tmp_path):
        ledger = TokenLedger(daily_token_limit=2000000, store_path=str(tmp_path / "ledger.json"))
        assert ledger.daily_used() == 0
        assert ledger.remaining() == 2000000

        ledger.add_tokens({"prompt_tokens": 100, "completion_tokens": 50})
        assert ledger.daily_used() == 150
        ledger.add_tokens(30)
        assert ledger.daily_used() == 180
        assert ledger.remaining() == 2000000 - 180
        assert ledger.get_mode() == "normal"

    def test_total_tokens_takes_priority(self, tmp_path):
        ledger = TokenLedger(store_path=str(tmp_path / "ledger.json"))
        # total_tokens 存在时优先使用，忽略 prompt/completion
        ledger.add_tokens({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 160})
        assert ledger.daily_used() == 160

    def test_add_tokens_invalid_type_rejected(self, tmp_path):
        ledger = TokenLedger(store_path=str(tmp_path / "ledger.json"))
        with pytest.raises(TypeError):
            ledger.add_tokens("100")

    def test_unlimited_remaining_is_none(self, tmp_path):
        # daily_token_limit=0 表示不限制：remaining 返回 None（无穷大语义）
        ledger = TokenLedger(daily_token_limit=0, store_path=str(tmp_path / "ledger.json"))
        assert ledger.remaining() is None
        assert ledger.usage_ratio() == 0.0
        assert ledger.is_over_budget() is False
        assert ledger.get_mode() == "normal"

    def test_over_budget_and_ratio_cap(self, tmp_path):
        ledger = TokenLedger(daily_token_limit=100, store_path=str(tmp_path / "ledger.json"))
        ledger.add_tokens(150)
        assert ledger.is_over_budget() is True
        assert ledger.usage_ratio() == 1.0  # 超限 cap 1.0
        assert ledger.get_mode() == "sleep"  # 默认 overspend_mode

    def test_over_budget_with_custom_mode(self, tmp_path):
        ledger = TokenLedger(
            daily_token_limit=100,
            overspend_mode="low_cost",
            store_path=str(tmp_path / "ledger.json"),
        )
        ledger.add_tokens(100)
        assert ledger.is_over_budget() is True
        assert ledger.get_mode() == "low_cost"

    def test_llm_calls_over_budget(self, tmp_path):
        ledger = TokenLedger(
            daily_token_limit=1000000,
            daily_llm_calls_limit=2,
            store_path=str(tmp_path / "ledger.json"),
        )
        ledger.add_llm_call()
        assert ledger.is_over_budget() is False
        ledger.add_llm_call()  # 达到上限即超支（>= 语义，与 token 判定一致）
        assert ledger.is_over_budget() is True
        assert ledger.daily_calls() == 2

    def test_alert_triggered_once_per_day(self, tmp_path):
        ledger = TokenLedger(
            daily_token_limit=100,
            cost_alert_threshold=0.5,
            store_path=str(tmp_path / "ledger.json"),
        )
        ledger.add_tokens(60)  # ratio 0.6 >= 0.5
        assert ledger.is_alert_triggered() is True
        assert ledger.is_alert_triggered() is False  # 当日不重复

    def test_alert_not_triggered_below_threshold(self, tmp_path):
        ledger = TokenLedger(
            daily_token_limit=100,
            cost_alert_threshold=0.9,
            store_path=str(tmp_path / "ledger.json"),
        )
        ledger.add_tokens(50)  # ratio 0.5 < 0.9
        assert ledger.is_alert_triggered() is False

    def test_new_day_reset(self, tmp_path):
        ledger = TokenLedger(store_path=str(tmp_path / "ledger.json"))
        ledger.add_tokens(500)
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        assert ledger.reset_if_new_day(tomorrow) is True  # 跨日 → 重置
        assert ledger.daily_used() == 0
        assert ledger.remaining() == ledger.daily_token_limit
        assert ledger.reset_if_new_day(tomorrow) is False  # 同日不再重置

    def test_persistence_roundtrip(self, tmp_path):
        path = str(tmp_path / "ledger.json")
        ledger = TokenLedger(daily_token_limit=2000000, store_path=path)
        ledger.add_tokens(1234)
        ledger.add_llm_call()
        ledger.save()

        restored = TokenLedger(daily_token_limit=2000000, store_path=path).load()
        assert restored.daily_used() == 1234
        assert restored.daily_calls() == 1
        assert restored.remaining() == 2000000 - 1234


# ================================================================ ② ContentGate
class _FakeFilterResult:
    """模拟 firewall.py 的 FilterResult。"""

    def __init__(self, allowed=True, reason=""):
        self.allowed = allowed
        self.reason = reason


class _FakeFirewall:
    """模拟 FirewallService：记录调用参数并返回可配置结果。"""

    def __init__(self, allowed=True, reason=""):
        self.allowed = allowed
        self.reason = reason
        self.calls = []

    def filter_message(self, content, user_id="", username=""):
        self.calls.append((content, user_id, username))
        return _FakeFilterResult(allowed=self.allowed, reason=self.reason)


class TestContentGate:
    def test_firewall_reject(self):
        fw = _FakeFirewall(allowed=False, reason="Message too long (max: 100)")
        gate = ContentGate(firewall=fw)
        content = "x" * 200
        result = _run(gate.check(content, user_id="u", username="n"))
        assert result["allowed"] is False
        assert "too long" in result["reason"]
        assert result["checks"]["firewall"]["allowed"] is False
        assert fw.calls == [(content, "u", "n")]  # 正确透传 user_id/username

    def test_firewall_allow(self):
        fw = _FakeFirewall(allowed=True)
        gate = ContentGate(firewall=fw)
        result = _run(gate.check("正常内容"))
        assert result["allowed"] is True
        assert result["reason"] == "ok"
        assert result["checks"]["firewall"]["allowed"] is True

    def test_persona_check_called_sync(self):
        calls = []

        def persona(content):
            calls.append(content)
            return True

        gate = ContentGate(firewall=_FakeFirewall(allowed=True), persona_check=persona)
        result = _run(gate.check("hello"))
        assert result["allowed"] is True
        assert calls == ["hello"]
        assert result["checks"]["persona"]["allowed"] is True

    def test_persona_check_reject(self):
        gate = ContentGate(
            firewall=_FakeFirewall(allowed=True),
            persona_check=lambda c: False,
        )
        result = _run(gate.check("不贴合人设"))
        assert result["allowed"] is False
        assert result["reason"] == "persona_mismatch"

    def test_persona_check_async(self):
        async def persona(content):
            return True

        gate = ContentGate(firewall=_FakeFirewall(allowed=True), persona_check=persona)
        assert _run(gate.check("hi"))["allowed"] is True

    def test_no_firewall_empty_content(self):
        gate = ContentGate()  # 未注入防火墙
        result = _run(gate.check("   "))
        assert result["allowed"] is False
        assert result["reason"] == "empty_content"

    def test_no_firewall_too_long(self):
        gate = ContentGate()
        result = _run(gate.check("x" * 20000))
        assert result["allowed"] is False
        assert result["reason"] == "content_too_long"

    def test_no_firewall_normal_pass(self):
        gate = ContentGate()
        result = _run(gate.check("正常内容"))
        assert result["allowed"] is True
        assert result["reason"] == "ok"

    def test_disabled_gate_allows_everything(self):
        gate = ContentGate(firewall=_FakeFirewall(allowed=False), enabled=False)
        result = _run(gate.check("bad"))
        assert result["allowed"] is True
        assert result["reason"] == "gate_disabled"


# ================================================================ ③ RateLimiter
class TestRateLimiter:
    def test_allow_and_hit_count(self):
        limiter = RateLimiter(limit_per_hour=2, window_minutes=60)
        assert limiter.allow("post") is True
        limiter.hit("post")
        assert limiter.allow("post") is True
        limiter.hit("post")
        assert limiter.allow("post") is False  # 达上限
        assert limiter.window_remaining("post") == 0

    def test_window_slides_and_recovers(self):
        limiter = RateLimiter(limit_per_hour=1, window_minutes=60)
        t0 = 1000.0
        limiter.hit("post", now=t0)
        assert limiter.allow("post", now=t0) is False
        assert limiter.allow("post", now=t0 + 3599.0) is False  # 仍在窗口内
        assert limiter.allow("post", now=t0 + 3600.0) is True   # 窗口滑出后恢复
        assert limiter.window_remaining("post", now=t0 + 3600.0) == 1

    def test_clock_injection(self):
        now = [1000.0]
        limiter = RateLimiter(limit_per_hour=1, window_minutes=60, clock=lambda: now[0])
        limiter.hit("post")
        assert limiter.allow("post") is False
        now[0] = 1000.0 + 3600.0  # 推进时钟
        assert limiter.allow("post") is True

    def test_separate_keys_independent(self):
        limiter = RateLimiter(limit_per_hour=1, window_minutes=60)
        limiter.hit("post")
        assert limiter.allow("post") is False
        assert limiter.allow("write_memory") is True  # 不同 key 独立计数

    def test_limit_zero_always_denied(self):
        limiter = RateLimiter(limit_per_hour=0, window_minutes=60)
        assert limiter.allow("post") is False
        assert limiter.window_remaining("post") == 0


# ================================================================ ④ KillSwitch
class TestKillSwitch:
    def test_default_active(self, tmp_path):
        ks = KillSwitch(store_path=str(tmp_path / "killswitch.json"))
        assert ks.enabled is True
        assert ks.is_active() is True

    def test_emergency_stop(self, tmp_path):
        ks = KillSwitch(store_path=str(tmp_path / "killswitch.json"))
        ks.emergency_stop()
        assert ks.enabled is False
        assert ks.is_active() is False

    def test_resume_restores(self, tmp_path):
        ks = KillSwitch(store_path=str(tmp_path / "killswitch.json"))
        ks.emergency_stop()
        ks.pause()
        ks.set_sleeping(True)
        assert ks.is_active() is False
        ks.resume()
        assert ks.is_active() is True
        assert ks.paused is False
        assert ks.sleeping is False
        assert ks.enabled is True

    def test_pause_and_sleeping(self, tmp_path):
        ks = KillSwitch(store_path=str(tmp_path / "killswitch.json"))
        ks.pause()
        assert ks.is_active() is False
        ks.resume()
        assert ks.is_active() is True
        ks.set_sleeping(True)
        assert ks.is_active() is False
        ks.set_sleeping(False)
        assert ks.is_active() is True

    def test_persistence_roundtrip(self, tmp_path):
        path = str(tmp_path / "killswitch.json")
        ks = KillSwitch(store_path=path)
        ks.emergency_stop()
        ks.set_sleeping(True)
        ks.save()

        restored = KillSwitch(store_path=path).load()
        assert restored.enabled is False
        assert restored.sleeping is True
        assert restored.is_active() is False


# ================================================================ ⑤ AuditStore
class TestAuditStore:
    def _entry(self, **overrides):
        entry = {
            "timestamp": "2026-08-22T02:00:00Z",
            "action": "write_memory",
            "result": "success",
        }
        entry.update(overrides)
        return entry

    def test_append_and_list(self, tmp_path):
        store = AuditStore(path=str(tmp_path / "audit.jsonl"))
        store.append(self._entry())
        store.append(self._entry(action="write_post", result="blocked"))
        result = store.list()
        assert result["total"] == 2
        assert [i["action"] for i in result["items"]] == ["write_memory", "write_post"]

    def test_list_pagination(self, tmp_path):
        store = AuditStore(path=str(tmp_path / "audit.jsonl"))
        for i in range(5):
            store.append(self._entry(action=f"a{i}"))
        page = store.list(limit=2, offset=1)
        assert page["total"] == 5
        assert [i["action"] for i in page["items"]] == ["a1", "a2"]

    def test_missing_required_fields_rejected(self, tmp_path):
        store = AuditStore(path=str(tmp_path / "audit.jsonl"))
        with pytest.raises(ValueError):
            store.append({"action": "write_post"})  # 缺 timestamp
        with pytest.raises(ValueError):
            store.append({"timestamp": "2026-08-22T02:00:00Z"})  # 缺 action

    def test_invalid_result_rejected(self, tmp_path):
        store = AuditStore(path=str(tmp_path / "audit.jsonl"))
        with pytest.raises(ValueError):
            store.append(self._entry(result="gone_wrong"))

    def test_clear(self, tmp_path):
        store = AuditStore(path=str(tmp_path / "audit.jsonl"))
        store.append(self._entry())
        store.clear()
        result = store.list()
        assert result["total"] == 0
        assert result["items"] == []

    def test_default_path_is_jsonl(self):
        # 缺省路径基于 __file__ 解析到 server/autonomy/data/audit_logs.jsonl
        store = AuditStore()
        assert store.path.endswith("audit_logs.jsonl")
        assert "server" in Path(store.path).parts
