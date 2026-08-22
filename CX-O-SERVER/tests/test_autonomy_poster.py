"""CX-O-Autonomy 发帖行动 Poster 单元测试（P2-T3）。

覆盖：
① 平台不在白名单 → AutonomyPlatformNotWhitelistedError
② 草稿生成：draft 为空且注入 llm_client 时按人设生成；无 llm_client 且无 draft 抛 ValueError
③ 内容闸门拒绝 → AutonomyContentRejectedError，且后续步骤（限速/执行）不执行
④ 限速拒绝 → AutonomyRateLimitedError
⑤ computer_control 调用成功 → status=executed，且 rate_limiter.hit 被调
⑥ computer_control 为 None → status=prepared（未执行，等待执行器接入）

运行：python -m pytest tests/test_autonomy_poster.py -q
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.autonomy.action.social.poster import (
    AutonomyContentRejectedError,
    AutonomyPlatformNotWhitelistedError,
    AutonomyRateLimitedError,
    Poster,
)

DEFAULT_PLATFORMS = ["weibo", "x"]


def build_poster(
    *,
    llm_client=None,
    content_gate=None,
    rate_limiter=None,
    platforms=None,
    computer_control=None,
    persona=None,
):
    """构造 Poster：平台白名单默认 weibo/x，人设默认 CX-O 自主体。"""
    return Poster(
        llm_client=llm_client,
        content_gate=content_gate,
        rate_limiter=rate_limiter,
        platforms=list(platforms) if platforms is not None else list(DEFAULT_PLATFORMS),
        computer_control=computer_control,
        persona=persona or {"description": "CX-O 自主体"},
    )


def passing_gate():
    """返回 allowed=True 的闸门替身。"""
    gate = AsyncMock()
    gate.check.return_value = {"allowed": True, "reason": "ok", "checks": {"enabled": True}}
    return gate


def passing_limiter():
    """返回 allow 恒真的限流替身（用于验证 hit 被调）。"""
    limiter = MagicMock()
    limiter.allow.return_value = True
    return limiter


# ================================================================ ① 平台不在白名单
@pytest.mark.asyncio
async def test_platform_not_whitelisted_raises():
    poster = build_poster(platforms=["weibo"])
    with pytest.raises(AutonomyPlatformNotWhitelistedError) as ei:
        await poster.post("x", "草稿")
    assert ei.value.error_code == "AUTONOMY_PLATFORM_NOT_WHITELISTED"
    # 白名单校验最先执行：闸门/限速/执行均不应触发
    assert poster.computer_control is None


# ================================================================ ② 草稿生成
@pytest.mark.asyncio
async def test_draft_generated_by_llm_when_empty():
    llm = AsyncMock()
    llm.chat.return_value = SimpleNamespace(content="今天发现了一朵会发光的云。", error=None)
    poster = build_poster(llm_client=llm, content_gate=passing_gate(), rate_limiter=passing_limiter())
    out = await poster.post("weibo", draft="")
    assert out["status"] == "prepared"  # 未注入 computer_control
    assert llm.chat.await_count == 1
    # 生成文本进入发布脚本的键盘输入步骤
    assert out["script"][0]["arguments"]["text"] == "今天发现了一朵会发光的云。"


@pytest.mark.asyncio
async def test_draft_empty_without_llm_raises_valueerror():
    poster = build_poster()
    with pytest.raises(ValueError):
        await poster.post("weibo", draft="")


# ================================================================ ③ 内容闸门拒绝
@pytest.mark.asyncio
async def test_content_gate_rejects_and_blocks_subsequent_steps():
    gate = AsyncMock()
    gate.check.return_value = {
        "allowed": False,
        "reason": "persona_mismatch",
        "checks": {"persona": {"applied": True, "allowed": False}},
    }
    limiter = passing_limiter()
    computer_control = AsyncMock(return_value={"steps": []})
    poster = build_poster(
        content_gate=gate, rate_limiter=limiter, computer_control=computer_control
    )
    with pytest.raises(AutonomyContentRejectedError) as ei:
        await poster.post("weibo", "违规草稿")
    assert ei.value.error_code == "AUTONOMY_CONTENT_REJECTED"
    gate.check.assert_awaited_once_with("违规草稿")
    # 后续步骤（限速检查 / 执行 / 命中）均不执行
    limiter.allow.assert_not_called()
    computer_control.assert_not_called()
    limiter.hit.assert_not_called()


# ================================================================ ④ 限速拒绝
@pytest.mark.asyncio
async def test_rate_limited_raises():
    gate = passing_gate()
    limiter = passing_limiter()
    limiter.allow.return_value = False
    computer_control = AsyncMock()
    poster = build_poster(
        content_gate=gate, rate_limiter=limiter, computer_control=computer_control
    )
    with pytest.raises(AutonomyRateLimitedError) as ei:
        await poster.post("weibo", "草稿")
    assert ei.value.error_code == "AUTONOMY_RATE_LIMITED"
    # 闸门先过（限速在闸门之后），执行不触发
    gate.check.assert_awaited_once_with("草稿")
    computer_control.assert_not_called()
    limiter.hit.assert_not_called()


# ================================================================ ⑤ 电脑控制执行成功
@pytest.mark.asyncio
async def test_computer_control_executes_and_hits_ratelimit():
    limiter = passing_limiter()

    async def fake_control(script):
        return {
            "plugin_id": "cxfc_computer",
            "steps": [{"tool": s["tool"], "result": {"success": True}} for s in script],
            "post_id": "wb-123",
        }

    poster = build_poster(
        content_gate=passing_gate(), rate_limiter=limiter, computer_control=fake_control
    )
    out = await poster.post("weibo", "今天的日落好温柔。")
    assert out["status"] == "executed"
    assert out["platform"] == "weibo"
    assert out["post_id"] == "wb-123"
    # 发布脚本为两步骤：键盘输入 + 提交发布
    assert out["script"][0]["tool"] == "computer_keyboard_control"
    assert out["script"][1]["tool"] == "computer_run_command"
    assert out["gate"]["allowed"] is True
    # 限速：执行前 allow 检查，成功后 hit 命中一次
    limiter.allow.assert_called_once_with("post")
    limiter.hit.assert_called_once_with("post")


# ================================================================ ⑥ 未接入执行器 → prepared
@pytest.mark.asyncio
async def test_no_computer_control_returns_prepared():
    limiter = passing_limiter()
    poster = build_poster(content_gate=passing_gate(), rate_limiter=limiter, computer_control=None)
    out = await poster.post("weibo", "准备好的草稿")
    assert out["status"] == "prepared"
    assert out["platform"] == "weibo"
    assert len(out["script"]) == 2
    assert out["script"][0]["arguments"]["text"] == "准备好的草稿"
    # 未执行：hit 不被调用
    limiter.allow.assert_called_once_with("post")
    limiter.hit.assert_not_called()
