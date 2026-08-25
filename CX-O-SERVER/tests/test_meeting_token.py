"""SpeakingToken 发言令牌单元测试（§5）。

覆盖：令牌互斥、用户优先 revoke、pending_queue 接力、持有超时自动释放防霸麦。
运行：python -m pytest tests/test_meeting_token.py -v
"""
import asyncio

import pytest

from server.core.meeting.models import TokenState
from server.core.meeting.token import SpeakingToken


@pytest.mark.asyncio
class TestSpeakingToken:
    async def test_mutual_exclusion(self):
        """同一时刻只有一个 holder；第二人申请失败进队列。"""
        token = SpeakingToken()
        assert await token.acquire("A") is True
        assert token.who_holds() == "A"
        assert token.is_held is True
        # 已被 A 持有，B 申请失败并进入排队队列
        assert await token.acquire("B") is False
        assert token.who_holds() == "A"
        assert list(token.pending_queue) == ["B"]

    async def test_release_grants_to_queue(self):
        """释放后授权给举手队列队首。"""
        token = SpeakingToken()
        await token.acquire("A")
        await token.acquire("B")  # B 排队
        await token.acquire("C")  # C 排 A 后
        # 释放 A → 队列前移 B 拿令牌
        next_holder = await token.release("A")
        assert next_holder == "B"
        assert token.who_holds() == "B"
        assert list(token.pending_queue) == ["C"]

    async def test_user_priority_revoke(self):
        """用户开口强制收回：holder 清空、状态 REVOKED、队列清空。"""
        revoked = []
        token = SpeakingToken(on_revoke=lambda h: revoked.append(h))
        await token.acquire("A")
        await token.acquire("B")
        rv = await token.revoke()
        assert rv == "A"
        assert token.who_holds() is None
        assert token.state == TokenState.REVOKED
        assert revoked == ["A"]
        assert not token.pending_queue

    async def test_acquire_after_revoke_returns_false(self):
        """REVOKED 状态下 acquire 不再放行。"""
        token = SpeakingToken()
        await token.acquire("A")
        await token.revoke()
        assert await token.acquire("B") is False

    async def test_reset_recovers_from_revoked(self):
        """reset 后令牌恢复到 IDLE 可重新授权。"""
        token = SpeakingToken()
        await token.acquire("A")
        await token.revoke()
        await token.reset()
        assert token.state == TokenState.IDLE
        assert await token.acquire("B") is True
        assert token.who_holds() == "B"

    async def test_release_non_holder_ignored(self):
        """非持有者 release 被忽略。"""
        token = SpeakingToken()
        await token.acquire("A")
        await token.release("B")  # 忽略
        assert token.who_holds() == "A"

    async def test_hold_timeout_auto_release(self):
        """持有超时自动释放，防霸麦。"""
        token = SpeakingToken(token_hold_timeout_sec=0.05)
        await token.acquire("A")
        assert token.who_holds() == "A"
        await asyncio.sleep(0.15)
        assert token.who_holds() is None

    async def test_no_timeout_when_le_0(self):
        """token_hold_timeout_sec<=0 时持有不限时。"""
        token = SpeakingToken(token_hold_timeout_sec=0)
        await token.acquire("A")
        await asyncio.sleep(0.05)
        assert token.who_holds() == "A"