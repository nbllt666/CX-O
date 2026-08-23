"""休眠前 LLM 确认仲裁器（server/autonomy/dream/confirmation.py）单测。

覆盖：
1. enabled=False → approve_sleep 直接 True 且不调用 LLM
2. 准予：LLM 判定"允许入睡" → True
3. 否决：LLM 判定"拒绝入睡" → False
4. 降级：LLM 缺席 / 异常 / 超时 → fail-open True（异常隔离不抛出）
5. 冷却：cooldown_seconds 内不重复打扰 → True（不调用 LLM）

运行：python -m pytest tests/test_sleep_confirmation.py -q
"""
from datetime import datetime, timedelta

import pytest

from server.autonomy.dream.config import SleepConfirmationConfig
from server.autonomy.dream.confirmation import SleepConfirmationArbiter

_BASE_NOW = datetime(2026, 8, 23, 3, 0, 0)

# ---------------------------------------------------------------- Fake LLM
class _FakeLLM:
    """带 async chat(...) 形态的 LLM（对齐生成器调用口径）。"""

    def __init__(self, content="true"):
        self.content = content
        self.calls = []

    async def chat(self, **kw):
        self.calls.append(kw)
        return self


def _arbiter(
    llm=None,
    enabled=True,
    cooldown_seconds=1800,
    now=_BASE_NOW,
    prompt_template="",
):
    cfg = SleepConfirmationConfig(
        enabled=enabled,
        cooldown_seconds=cooldown_seconds,
        prompt_template=prompt_template,
    )
    return SleepConfirmationArbiter(llm_client=llm, config=cfg, now_fn=lambda: now)


# ================================================================ enabled=False
class TestDisabled:
    @pytest.mark.asyncio
    async def test_disabled_returns_true_without_calling_llm(self):
        llm = _FakeLLM(content="false")
        arb = _arbiter(llm=llm, enabled=False)
        assert await arb.approve_sleep("用户说很困") is True
        assert llm.calls == []  # 未调用 LLM

    @pytest.mark.asyncio
    async def test_disabled_without_llm_returns_true(self):
        arb = _arbiter(llm=None, enabled=False)
        assert await arb.approve_sleep("上下文") is True


# ================================================================ 准予 / 否决
class TestDecision:
    @pytest.mark.asyncio
    async def test_approve_true(self):
        llm = _FakeLLM(content="true")
        arb = _arbiter(llm=llm)
        assert await arb.approve_sleep("最近连续工作，犯困") is True

    @pytest.mark.asyncio
    async def test_approve_text_token(self):
        llm = _FakeLLM(content="确认")
        arb = _arbiter(llm=llm)
        assert await arb.approve_sleep("困了想去睡") is True

    @pytest.mark.asyncio
    async def test_deny_false(self):
        llm = _FakeLLM(content="false")
        arb = _arbiter(llm=llm)
        assert await arb.approve_sleep("只是在发呆，还能继续") is False

    @pytest.mark.asyncio
    async def test_deny_should_sleep_key_value(self):
        llm = _FakeLLM(content="should_sleep: no")
        arb = _arbiter(llm=llm)
        assert await arb.approve_sleep("尚不需要入睡") is False

    @pytest.mark.asyncio
    async def test_deprecated_cleanup_json_inline(self):
        """内嵌 JSON 对象字符串也能解析判定。"""
        llm = _FakeLLM(content='{"should_sleep": true}')
        arb = _arbiter(llm=llm)
        assert await arb.approve_sleep("需要休息") is True

    @pytest.mark.asyncio
    async def test_prompt_includes_context_and_recent(self):
        recent = ["近期内容"]
        llm = _FakeLLM(content="true")

        def recent_fn():
            return recent[0]

        cfg = SleepConfirmationConfig(prompt_template="【模板】判断:{ctx}")
        arb = SleepConfirmationArbiter(
            llm_client=llm, recent_context_fn=recent_fn, config=cfg, now_fn=lambda: _BASE_NOW
        )
        assert await arb.approve_sleep("当前上下文XYZ") is True
        assert len(llm.calls) == 1
        user_prompt = llm.calls[0]["messages"][1]["content"]
        assert "当前上下文XYZ" in user_prompt
        assert "近期内容" in user_prompt
        assert "【模板】" in user_prompt


# ================================================================ 降级（fail-open）
class TestFallback:
    @pytest.mark.asyncio
    async def test_no_llm_fail_open(self):
        arb = _arbiter(llm=None)
        assert await arb.approve_sleep("任意") is True

    @pytest.mark.asyncio
    async def test_unparseable_fail_open(self):
        llm = _FakeLLM(content="抱歉，我无法判断")
        arb = _arbiter(llm=llm)
        assert await arb.approve_sleep("任意") is True

    @pytest.mark.asyncio
    async def test_llm_raise_isolated_fail_open(self):
        class Boom:
            async def chat(self, **kw):
                raise RuntimeError("llm down")

        arb = _arbiter(llm=Boom())
        assert await arb.approve_sleep("任意") is True

    @pytest.mark.asyncio
    async def test_timeout_fail_open(self):
        class Slow:
            async def chat(self, **kw):
                import asyncio

                await asyncio.sleep(2)

        cfg = SleepConfirmationConfig(enabled=True, timeout_sec=0.05)
        arb = SleepConfirmationArbiter(llm_client=Slow(), config=cfg, now_fn=lambda: _BASE_NOW)
        assert await arb.approve_sleep("任意") is True


# ================================================================ 冷却
class TestCooldown:
    def test_should_skip_within_cooldown(self):
        arb = _arbiter(cooldown_seconds=1800)
        assert arb.should_skip(_BASE_NOW, None) is False  # 从未确认 → 不跳过
        past = _BASE_NOW - timedelta(seconds=100)
        assert arb.should_skip(_BASE_NOW, past) is True  # 100s < 1800s → 跳过

    def test_should_skip_after_cooldown(self):
        arb = _arbiter(cooldown_seconds=1800)
        past = _BASE_NOW - timedelta(seconds=3600)
        assert arb.should_skip(_BASE_NOW, past) is False  # 超冷却 → 不跳过

    @pytest.mark.asyncio
    async def test_approve_within_cooldown_skips_llm(self):
        llm = _FakeLLM(content="true")
        clock = [_BASE_NOW]
        arb = SleepConfirmationArbiter(
            llm_client=llm,
            config=SleepConfirmationConfig(enabled=True, cooldown_seconds=1800),
            now_fn=lambda: clock[0],
        )
        assert await arb.approve_sleep("第一次确认") is True
        assert len(llm.calls) == 1  # 首次调用 LLM
        clock[0] += timedelta(seconds=100)  # 仍在冷却期
        assert await arb.approve_sleep("冷却期内再次确认") is True
        assert len(llm.calls) == 1  # 冷却期内不再调用 LLM

    @pytest.mark.asyncio
    async def test_approve_after_cooldown_calls_llm_again(self):
        llm = _FakeLLM(content="true")
        clock = [_BASE_NOW]
        arb = SleepConfirmationArbiter(
            llm_client=llm,
            config=SleepConfirmationConfig(enabled=True, cooldown_seconds=30),
            now_fn=lambda: clock[0],
        )
        assert await arb.approve_sleep("第一次") is True
        clock[0] += timedelta(seconds=60)  # 超过 30s 冷却
        assert await arb.approve_sleep("再次确认") is True
        assert len(llm.calls) == 2  # 冷却过后重新调用 LLM