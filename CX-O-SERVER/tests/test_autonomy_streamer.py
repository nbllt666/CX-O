"""CX-O-Autonomy 直播行动 Streamer 单元测试（P3-T1）。

覆盖：
① prepare_script 用 mock llm_client 生成含 title/outline/opening/script 的结构化脚本
② llm_client 缺失 → {script: "", reason: "llm_unavailable"}
③ start_live 注入 confirmation_callback → awaiting_confirmation 且不执行开播
④ 无 callback 且 computer_control 可调用 → executed
⑤ 无 computer_control → prepared（未执行，等待执行器接入）
⑥ stop_live 写记忆（tags=#直播回忆）并返回 memory_id
⑦ stop_live memory_actions 缺失 → summary_memory_id None

运行：python -m pytest tests/test_autonomy_streamer.py -q
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.autonomy.action.live.streamer import Streamer


def build_streamer(
    *,
    llm_client=None,
    memory_actions=None,
    computer_control=None,
    confirmation_callback=None,
    persona=None,
):
    """构造 Streamer：人设默认 CX-O 自主体。"""
    return Streamer(
        llm_client=llm_client,
        memory_actions=memory_actions,
        computer_control=computer_control,
        confirmation_callback=confirmation_callback,
        persona=persona or {"description": "CX-O 自主体"},
    )


def fake_script_response():
    """返回带【标题】等标记的 LLM 脚本生成响应内容。"""
    return (
        "【标题】温柔夜话\n"
        "【主题】分享今日见闻\n"
        "【大纲】1. 开场互动 2. 主题分享 3. 观众问答\n"
        "【开场白】大家好，欢迎来到我的直播间～\n"
        "【互动要点】提问+回复，点歌互动"
    )


# ================================================================ ① prepare_script 生成
@pytest.mark.asyncio
async def test_prepare_script_generates_structured_script():
    llm = AsyncMock()
    llm.chat.return_value = SimpleNamespace(content=fake_script_response(), error=None)
    streamer = build_streamer(llm_client=llm)
    out = await streamer.prepare_script()
    assert out["reason"] == "ok"
    assert out["title"] == "温柔夜话"
    assert out["outline"]
    assert out["opening"]
    assert out["script"]  # 完整脚本正文
    llm.chat.assert_awaited_once()


# ================================================================ ② llm_client 缺失
@pytest.mark.asyncio
async def test_prepare_script_without_llm_returns_llm_unavailable():
    streamer = build_streamer(llm_client=None)
    out = await streamer.prepare_script()
    assert out == {"script": "", "reason": "llm_unavailable"}


# ================================================================ ③ 半自动确认门
@pytest.mark.asyncio
async def test_start_live_with_confirmation_callback_waits():
    confirmation = MagicMock(return_value=None)
    computer_control = AsyncMock(return_value={"steps": []})
    streamer = build_streamer(
        computer_control=computer_control, confirmation_callback=confirmation
    )
    out = await streamer.start_live(script={"script": "脚本"})
    assert out["status"] == "awaiting_confirmation"
    assert out["script"] == {"script": "脚本"}
    # 请求了确认且未执行开播
    confirmation.assert_called_once()
    computer_control.assert_not_called()


# ================================================================ ④ 无回调 + 执行器 → executed
@pytest.mark.asyncio
async def test_start_live_executes_via_computer_control():
    async def fake_control(script):
        return {
            "plugin_id": "cxfc_computer",
            "steps": [{"tool": s["tool"], "result": {"success": True}} for s in script],
        }

    streamer = build_streamer(computer_control=fake_control)
    out = await streamer.start_live(script={"title": "温柔夜话"})
    assert out["status"] == "executed"
    assert out["script"] == {"title": "温柔夜话"}
    assert out["result"]["steps"]
    # 开播动作序列：computer_run_command 启动 OBS 推流
    assert out["result"]["steps"][0]["tool"] == "computer_run_command"


# ================================================================ ⑤ 无执行器 → prepared
@pytest.mark.asyncio
async def test_start_live_without_computer_control_returns_prepared():
    streamer = build_streamer(computer_control=None)
    out = await streamer.start_live(script={"script": "脚本"})
    assert out["status"] == "prepared"
    assert out["script"] == {"script": "脚本"}


# ================================================================ ⑥ stop_live 写记忆
@pytest.mark.asyncio
async def test_stop_live_writes_live_memory_and_returns_id():
    memory_actions = AsyncMock()
    memory_actions.write_memory.return_value = "mem-live-1"
    streamer = build_streamer(memory_actions=memory_actions)
    out = await streamer.stop_live()
    assert out["status"] == "stopped"
    assert out["summary_memory_id"] == "mem-live-1"
    memory_actions.write_memory.assert_awaited_once()
    kwargs = memory_actions.write_memory.await_args.kwargs
    assert kwargs["tags"] == ["#直播回忆", "#经历"]
    assert kwargs["type"] == "long_term"
    assert kwargs["permanent"] is False
    assert kwargs["importance"] == 4
    assert kwargs["content"]  # 缺省自动生成下播总结


# ================================================================ ⑦ stop_live 无 memory_actions
@pytest.mark.asyncio
async def test_stop_live_without_memory_actions_returns_none_id():
    streamer = build_streamer(memory_actions=None)
    out = await streamer.stop_live()
    assert out["status"] == "stopped"
    assert out["summary_memory_id"] is None
