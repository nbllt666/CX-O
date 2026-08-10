"""
tests/test_chat_stream.py
==========================
流式聊天管线（server.core.chat.stream）单元测试。

覆盖：
  - ChatStreamState 默认值
  - 内容流式累积与 chunk 产出（dict / 裸 str 兼容）
  - thinking 累积
  - 工具调用循环：工具结果追加、二次生成、状态记录
  - 内置工具执行
  - 工具调用后不再注入工具列表
  - 最大工具轮数截断
  - LLM 抛错 → error chunk + done
  - error chunk 透传
  - temperature / max_tokens 透传
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from server.core.chat.stream import (  # noqa: E402
    BUILTIN_TOOL_NAMES,
    MAX_TOOL_ROUNDS,
    ChatStreamState,
    generate_chat_stream,
)

# 模块内同时含同步与异步测试，统一挂 asyncio 标记（同步测试在事件循环内运行无副作用）
pytestmark = pytest.mark.asyncio

_AGENT = {"temperature": 0.3, "max_tokens": 512}


class _FakeStreamLLM:
    """按调用轮次返回 chunk 的假 LLM。

    ``per_round`` 为每轮的 chunk 序列；``raise_on_round`` 指定在某一轮抛错。
    记录 ``rounds`` 以校验参数透传与轮数。
    """

    def __init__(self, per_round, raise_on_round=None):
        self.per_round = list(per_round)
        self.raise_on_round = raise_on_round
        self.rounds = []
        self.calls = 0

    async def stream_chat(self, **kwargs):
        self.calls += 1
        self.rounds.append(kwargs)
        if self.raise_on_round == self.calls:
            raise RuntimeError("boom")
        # 超出预定义轮数则循环复用最后一轮（供 max_tool_rounds 截断测试）
        idx = min(self.calls - 1, len(self.per_round) - 1)
        for chunk in self.per_round[idx]:
            yield chunk


async def _drain(agen):
    return [c async for c in agen]


# ---------------------------------------------------------------------------
# ChatStreamState
# ---------------------------------------------------------------------------

class TestState:
    async def test_defaults(self):
        s = ChatStreamState()
        assert s.accumulated_response == ""
        assert s.thinking == ""
        assert s.tool_calls == []
        assert s.chunk_count == 0
        assert s.llm_rounds == 0
        assert s.done is False


# ---------------------------------------------------------------------------
# 内容流式
# ---------------------------------------------------------------------------

class TestContentStream:
    async def test_content_chunks_accumulate(self):
        llm = _FakeStreamLLM([
            [{"type": "content", "content": "你好"}, {"type": "content", "content": "世界"}],
        ])
        state = ChatStreamState()
        chunks = await _drain(generate_chat_stream(llm, [], _AGENT, state=state))
        assert [c["type"] for c in chunks] == ["content", "content"]
        assert state.accumulated_response == "你好世界"
        assert state.chunk_count == 2
        assert state.done is True
        assert state.llm_rounds == 1

    async def test_legacy_string_chunk(self):
        llm = _FakeStreamLLM([["旧", "格式"]])
        state = ChatStreamState()
        chunks = await _drain(generate_chat_stream(llm, [], _AGENT, state=state))
        assert chunks == [
            {"type": "content", "content": "旧"},
            {"type": "content", "content": "格式"},
        ]
        assert state.accumulated_response == "旧格式"

    async def test_thinking_accumulated_not_yielded(self):
        llm = _FakeStreamLLM([
            [{"type": "thinking", "content": "想一"}, {"type": "content", "content": "答"}],
        ])
        state = ChatStreamState()
        chunks = await _drain(generate_chat_stream(llm, [], _AGENT, state=state))
        assert [c["type"] for c in chunks] == ["content"]
        assert state.thinking == "想一"
        assert state.accumulated_response == "答"

    async def test_temperature_and_max_tokens_passed(self):
        llm = _FakeStreamLLM([[{"type": "content", "content": "x"}]])
        await _drain(generate_chat_stream(llm, [], _AGENT))
        assert llm.rounds[0]["temperature"] == 0.3
        assert llm.rounds[0]["max_tokens"] == 512
        assert llm.rounds[0]["tools"] is None  # 未传 tools 时 None

    async def test_tools_only_on_first_round(self):
        llm = _FakeStreamLLM([
            [{"type": "tool_calls", "tool_calls": [{"name": "datetime", "arguments": {}}]}],
            [{"type": "content", "content": "最终"}],
        ])
        state = ChatStreamState()
        await _drain(generate_chat_stream(llm, [], _AGENT, tools=[{"f": 1}], state=state))
        assert llm.rounds[0]["tools"] == [{"f": 1}]
        assert llm.rounds[1]["tools"] is None  # 二次生成不带工具
        assert state.llm_rounds == 2


# ---------------------------------------------------------------------------
# 工具调用循环
# ---------------------------------------------------------------------------

class TestToolLoop:
    async def test_tool_call_appends_messages_and_records(self, monkeypatch):
        llm = _FakeStreamLLM([
            [{"type": "tool_calls", "tool_calls": [{"name": "datetime", "arguments": {}}]}],
            [{"type": "content", "content": "最终答复"}],
        ])
        messages = []
        state = ChatStreamState()
        await _drain(generate_chat_stream(llm, messages, _AGENT, state=state))
        # 工具调用记录进状态
        assert len(state.tool_calls) == 1
        assert state.tool_calls[0]["name"] == "datetime"
        # assistant + tool 消息追加
        roles = [m["role"] for m in messages]
        assert roles == ["assistant", "tool"]
        assert messages[-1]["name"] == "datetime"
        assert state.accumulated_response == "最终答复"

    async def test_builtin_tool_executed(self, monkeypatch):
        llm = _FakeStreamLLM([
            [{"type": "tool_calls", "tool_calls": [{"name": "datetime", "arguments": {}}]}],
            [{"type": "content", "content": "ok"}],
        ])
        calls = []
        monkeypatch.setattr(
            "server.core.tools.builtin.call_builtin_tool",
            lambda name, args: calls.append((name, args)) or {"v": 1},
        )
        await _drain(generate_chat_stream(llm, [], _AGENT, state=ChatStreamState()))
        assert calls == [("datetime", {})]
        assert "datetime" in BUILTIN_TOOL_NAMES

    async def test_registry_tool_executed(self, monkeypatch):
        llm = _FakeStreamLLM([
            [{"type": "tool_calls", "tool_calls": [{"name": "my_tool", "arguments": {"a": 1}}]}],
            [{"type": "content", "content": "ok"}],
        ])
        calls = []
        fake_registry = type("R", (), {"call_tool": lambda self, n, a: calls.append((n, a)) or "r"})()
        monkeypatch.setattr("server.core.tools.tool_registry", fake_registry)
        await _drain(generate_chat_stream(llm, [], _AGENT, state=ChatStreamState()))
        assert calls == [("my_tool", {"a": 1})]

    async def test_max_tool_rounds_truncated(self):
        # 每轮都返回 tool_calls → 循环被 max_tool_rounds 截断
        llm = _FakeStreamLLM([
            [{"type": "tool_calls", "tool_calls": [{"name": "datetime", "arguments": {}}]}]
        ])
        state = ChatStreamState()
        await _drain(generate_chat_stream(llm, [], _AGENT, state=state))
        assert state.llm_rounds == MAX_TOOL_ROUNDS
        assert state.done is True


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------

class TestErrors:
    async def test_llm_raises_yields_error_and_done(self):
        llm = _FakeStreamLLM([[{"type": "content", "content": "x"}]], raise_on_round=1)
        chunks = await _drain(generate_chat_stream(llm, [], _AGENT))
        assert chunks[-1]["type"] == "error"
        assert "boom" in chunks[-1]["content"]

    async def test_error_chunk_passthrough(self):
        llm = _FakeStreamLLM([[{"type": "error", "content": "上游错误"}]])
        chunks = await _drain(generate_chat_stream(llm, [], _AGENT))
        assert chunks == [{"type": "error", "content": "上游错误"}]

    async def test_empty_chunks_and_no_tools_finish(self):
        llm = _FakeStreamLLM([[]])
        state = ChatStreamState()
        chunks = await _drain(generate_chat_stream(llm, [], _AGENT, state=state))
        assert chunks == []
        assert state.done is True
        assert state.llm_rounds == 1