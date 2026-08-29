"""
server/handlers/chat.py 回归测试
聊天处理器：parse_tool_args 参数解析 / get_tools_for_agent 工具收集 /
_process_tool_calls 工具调用循环 / _build_chat_context 上下文构建 / MESSAGE 与 STREAM 处理器
"""
import pytest

import server.dependencies as deps
from server.core import tools as tools_mod
from server.core.tools import builtin as builtin_mod
from server.handlers import chat as chat_mod
from server.core.tools import parse_tool_args
from server.handlers.chat import (
    _build_chat_context,
    register_chat_handlers,
)
from server.chat_helpers import get_tools_for_agent
from server.protocol.actions import ChatActions


# --------------------------------------------------------------------------- #
# parse_tool_args
# --------------------------------------------------------------------------- #
class TestParseToolArgs:
    def test_dict_passthrough(self):
        assert parse_tool_args({"arguments": {"a": 1}}) == {"a": 1}

    @pytest.mark.parametrize("raw,expected", [
        ('{"a": 1, "b": [2, 3]}', {"a": 1, "b": [2, 3]}),
        ("{'a': 1}", {"a": 1}),           # ast.literal_eval 兜底
        ("not json at all", {}),          # 双失败 → 空 dict
        ("", {}),
    ])
    def test_string_forms(self, raw, expected):
        assert parse_tool_args({"arguments": raw}) == expected

    def test_function_wrapper(self):
        assert parse_tool_args({"function": {"arguments": '{"x": 1}'}}) == {"x": 1}

    def test_non_dict_fallback(self):
        assert parse_tool_args({"arguments": [1, 2]}) == {}

    def test_no_arguments(self):
        assert parse_tool_args({}) == {}


# --------------------------------------------------------------------------- #
# Fake 集合
# --------------------------------------------------------------------------- #
class FakeTool:
    def __init__(self, enabled=True, category="general"):
        self.enabled = enabled
        self.category = category

    def to_openai_function(self):
        return {"name": "main-tool"}


class FakeToolRegistry:
    def __init__(self):
        self.tools = {
            "write_long_term_memory": FakeTool(),
            "set_alarm": FakeTool(),
            "detail_only": FakeTool(category="summary"),  # 被排除分类
        }
        self.calls = []

    def get_tool(self, name):
        self.calls.append(("get", name))
        return self.tools.get(name)

    def call_tool(self, name, args):
        self.calls.append(("call", name, args))
        return {"result": f"{name}:ok"}


class FakeContextMgr:
    def __init__(self):
        self.sessions = {}
        self.messages = []

    def get_session(self, sid):
        return self.sessions.get(sid)

    def create_session(self, **kw):
        self.sessions[kw["session_id"]] = kw

    def ensure_session(self, session_id, workspace_id="default", title="", metadata=None):
        if self.get_session(session_id) is None:
            self.create_session(
                session_id=session_id,
                workspace_id=workspace_id,
                title=title,
                metadata=metadata,
            )
        return session_id

    def add_message(self, **kw):
        self.messages.append(kw)

    async def add_message_async(self, **kw):
        # 伴生C3 适配：chat.py 已改走 add_message_async（core 管理器的
        # run_io 包裹变体），fake 保持同签名同步落内存
        self.add_message(**kw)

    def get_message_count(self, sid):
        return len(self.messages)

    def get_messages(self, sid, limit=10):
        return list(self.messages)[-limit:]


class FakeLLM:
    def __init__(self, content="hi", tool_calls=None, usage=None):
        self.content = content
        self.tool_calls = tool_calls
        self.usage = usage or {"total_tokens": 10}

    async def chat(self, **kw):
        self.calls = kw
        return self

    async def stream_chat(self, **kw):
        self.stream_calls = kw
        for seg in ["你", "好"]:
            yield {"type": "content", "content": seg}


class FakeManager:
    def __init__(self):
        self.handlers = {}
        self.sent = []
        self.broadcasts = []
        self.llm_count = 0

    async def broadcast(self, message, exclude=None):
        self.broadcasts.append(message)

    def register_action_handler(self, action, handler):
        self.handlers[action] = handler

    def increment_llm_count(self):
        self.llm_count += 1

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))


# --------------------------------------------------------------------------- #
# get_tools_for_agent
# --------------------------------------------------------------------------- #
class TestGetToolsForAgent:
    def test_builtin_plus_main(self, monkeypatch):
        reg = FakeToolRegistry()
        # get_tools_for_agent 从 server.core.tools 与 builtin 延迟导入
        monkeypatch.setattr(tools_mod, "tool_registry", reg)
        monkeypatch.setattr(builtin_mod, "get_builtin_tools", lambda: [{"name": "builtin"}])
        tools = get_tools_for_agent()
        names = [t["name"] for t in tools]
        assert "builtin" in names
        assert "main-tool" in names          # write_long_term_memory 等主工具
        assert names.count("main-tool") == 2  # 两个非 summary 主工具
        # summary 分类被排除
        assert all(t.get("name") != "detail_only" for t in tools)


# --------------------------------------------------------------------------- #
# _process_tool_calls
# --------------------------------------------------------------------------- #
class TestProcessToolCalls:
    @pytest.mark.asyncio
    async def test_builtin_and_registry(self, monkeypatch):
        reg = FakeToolRegistry()
        # _process_tool_calls 从 server.core.tools 与 builtin 延迟导入
        monkeypatch.setattr(tools_mod, "tool_registry", reg)
        monkeypatch.setattr(builtin_mod, "call_builtin_tool",
                            lambda name, args: {"result": f"builtin:{name}"})
        llm = FakeLLM(content="done")
        messages = [{"role": "user", "content": "hi"}]
        resp = await chat_mod._process_tool_calls(
            [{"name": "calculator", "arguments": '{"a":1}', "id": "c1"},
             {"name": "set_alarm", "arguments": {"t": 1}, "id": "c2"}],
            messages, llm
        )
        assert resp.content == "done"
        # 两条 tool 消息被追加
        roles = [m["role"] for m in messages]
        assert roles.count("tool") == 2
        # 无 id 的兜底生成
        assert any(m.get("tool_call_id") for m in messages)

    @pytest.mark.asyncio
    async def test_missing_id_generated(self, monkeypatch):
        reg = FakeToolRegistry()
        monkeypatch.setattr(tools_mod, "tool_registry", reg)
        llm = FakeLLM(content="ok")
        messages = []
        await chat_mod._process_tool_calls(
            [{"name": "set_alarm", "arguments": {}}], messages, llm)
        tool_msg = [m for m in messages if m["role"] == "tool"][0]
        assert tool_msg["tool_call_id"].startswith("call_")


# --------------------------------------------------------------------------- #
# _build_chat_context
# --------------------------------------------------------------------------- #
class TestBuildChatContext:
    @pytest.mark.asyncio
    async def test_agent_not_found(self, monkeypatch):
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: None)
        mgr = FakeManager()
        ctx = await _build_chat_context("ghost", "hi", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert ctx is None
        msg = mgr.sent[-1][1]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == "AGENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_success_no_memory(self, monkeypatch):
        agent_config = {"name": "A", "use_memory": False, "id": "a1"}
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: agent_config)
        monkeypatch.setattr(chat_mod, "get_llm_client_for_agent", lambda cfg: FakeLLM())
        monkeypatch.setattr(deps, "get_memory_manager", lambda: None)
        cm = FakeContextMgr()
        monkeypatch.setattr(deps, "get_context_manager", lambda: cm)
        mgr = FakeManager()
        ctx = await _build_chat_context("a1", "hi", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert ctx is not None
        assert ctx.session_id == "agent-a1"
        assert ctx.memory_context is None
        # session 已创建，user 消息已注入
        assert "agent-a1" in cm.sessions
        assert cm.messages[0]["role"] == "user"


# --------------------------------------------------------------------------- #
# S4 显式睡眠语接线（F2-S4 修复）
# --------------------------------------------------------------------------- #
class _FakeSleepSensor:
    def __init__(self, state="AWAKE"):
        self.hits = []
        self.state = state
        self.wake_calls = 0

    def set_sleep_speech(self, hit):
        self.hits.append(hit)

    def snapshot(self):
        return {"state": self.state}

    def wake_up(self, now=None):
        self.wake_calls += 1
        self.state = "AWAKE"
        return {"state": "AWAKE"}


class _FakePhysioRuntime:
    def __init__(self, enabled=True, sensor=None):
        self._enabled = enabled
        self.sleep_sensor = sensor

    def is_enabled(self):
        return self._enabled


class TestSleepSpeechWiring:
    @pytest.mark.asyncio
    async def test_sleep_keyword_injects_s4(self, monkeypatch):
        """聊天文本命中睡眠关键词 → sleep_sensor.set_sleep_speech(True)（agent 缺失也注入）。"""
        from types import SimpleNamespace

        sensor = _FakeSleepSensor()
        runtime = _FakePhysioRuntime(enabled=True, sensor=sensor)
        monkeypatch.setattr(
            deps, "_service_state", SimpleNamespace(physio_runtime=runtime)
        )
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: None)
        mgr = FakeManager()
        await _build_chat_context("a1", "我困了，先去睡了", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert sensor.hits == [True]

    @pytest.mark.asyncio
    async def test_no_keyword_does_not_inject(self, monkeypatch):
        from types import SimpleNamespace

        sensor = _FakeSleepSensor()
        runtime = _FakePhysioRuntime(enabled=True, sensor=sensor)
        monkeypatch.setattr(
            deps, "_service_state", SimpleNamespace(physio_runtime=runtime)
        )
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: None)
        mgr = FakeManager()
        await _build_chat_context("a1", "今天天气不错", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert sensor.hits == []

    @pytest.mark.asyncio
    async def test_disabled_runtime_degrades(self, monkeypatch):
        from types import SimpleNamespace

        sensor = _FakeSleepSensor()
        runtime = _FakePhysioRuntime(enabled=False, sensor=sensor)
        monkeypatch.setattr(
            deps, "_service_state", SimpleNamespace(physio_runtime=runtime)
        )
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: None)
        mgr = FakeManager()
        await _build_chat_context("a1", "我困了", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert sensor.hits == []

    @pytest.mark.asyncio
    async def test_missing_runtime_does_not_break_chat(self, monkeypatch):
        """physio runtime 未装配 → S4 注入静默跳过，聊天主流程不受影响。"""
        monkeypatch.setattr(deps, "_service_state", None)
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: None)
        mgr = FakeManager()
        ctx = await _build_chat_context("a1", "晚安", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert ctx is None  # agent 缺失正常返回 None，S4 注入未抛异常


# --------------------------------------------------------------------------- #
# 用户唤醒意图检测（Task 2：_maybe_wake_from_sleep）
# --------------------------------------------------------------------------- #
class TestWakeFromSleep:
    @pytest.mark.asyncio
    async def test_wake_keyword_returns_sensor_to_awake(self, monkeypatch):
        """ASLEEP 状态命中唤醒关键词 → sleep_sensor 回到 AWAKE 并广播 system.wake。"""
        from types import SimpleNamespace

        sensor = _FakeSleepSensor(state="ASLEEP")
        runtime = _FakePhysioRuntime(enabled=True, sensor=sensor)
        monkeypatch.setattr(
            deps, "_service_state", SimpleNamespace(physio_runtime=runtime)
        )
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: None)
        mgr = FakeManager()
        await _build_chat_context("a1", "在吗？快醒醒", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert sensor.wake_calls == 1
        assert sensor.state == "AWAKE"
        assert len(mgr.broadcasts) == 1
        assert mgr.broadcasts[0]["type"] == "system.wake"
        assert mgr.broadcasts[0]["data"]["previous_state"] == "ASLEEP"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["PENDING_CONFIRMATION", "ENTERING_SLEEP", "ASLEEP", "AWAY", "DROWSY"])
    async def test_sleep_states_plain_text_wakes(self, monkeypatch, state):
        """任一可唤醒态 + 普通用户文本 → 强制回到 AWAKE。"""
        from types import SimpleNamespace

        sensor = _FakeSleepSensor(state=state)
        runtime = _FakePhysioRuntime(enabled=True, sensor=sensor)
        monkeypatch.setattr(
            deps, "_service_state", SimpleNamespace(physio_runtime=runtime)
        )
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: None)
        mgr = FakeManager()
        await _build_chat_context("a1", "今天天气不错", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert sensor.wake_calls == 1
        assert sensor.state == "AWAKE"

    @pytest.mark.asyncio
    async def test_awake_state_no_wake(self, monkeypatch):
        """AWAKE 状态普通文本 → 不触发 wake_up、不广播。"""
        from types import SimpleNamespace

        sensor = _FakeSleepSensor(state="AWAKE")
        runtime = _FakePhysioRuntime(enabled=True, sensor=sensor)
        monkeypatch.setattr(
            deps, "_service_state", SimpleNamespace(physio_runtime=runtime)
        )
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: None)
        mgr = FakeManager()
        await _build_chat_context("a1", "你好", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert sensor.wake_calls == 0
        assert sensor.state == "AWAKE"
        assert mgr.broadcasts == []

    @pytest.mark.asyncio
    async def test_empty_text_does_not_wake_even_in_sleep(self, monkeypatch):
        """空文本（如多模态无图无文）不触发唤醒。"""
        from types import SimpleNamespace

        sensor = _FakeSleepSensor(state="ASLEEP")
        runtime = _FakePhysioRuntime(enabled=True, sensor=sensor)
        monkeypatch.setattr(
            deps, "_service_state", SimpleNamespace(physio_runtime=runtime)
        )
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: None)
        mgr = FakeManager()
        await _build_chat_context("a1", "", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert sensor.wake_calls == 0

    @pytest.mark.asyncio
    async def test_missing_runtime_no_wake_no_crash(self, monkeypatch):
        """physio runtime 未装配 → 唤醒检测静默跳过，不崩溃。"""
        monkeypatch.setattr(deps, "_service_state", None)
        monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: None)
        mgr = FakeManager()
        await _build_chat_context("a1", "在吗", mgr, "c1", "r1", ChatActions.MESSAGE)
        assert mgr.broadcasts == []


# --------------------------------------------------------------------------- #
# MESSAGE / STREAM 处理器
# --------------------------------------------------------------------------- #
@pytest.fixture
def mgr():
    return FakeManager()


@pytest.fixture
def handlers(mgr):
    register_chat_handlers(mgr)
    return mgr.handlers


def _setup_ctx(monkeypatch, agent_config=None, llm=None):
    agent_config = agent_config or {"name": "A", "use_memory": False, "id": "a1"}
    # chat.py 在模块顶层 from server.chat_helpers import get_agent_config, get_llm_client_for_agent
    monkeypatch.setattr(chat_mod, "get_agent_config", lambda aid: agent_config)
    if llm is None:
        llm = FakeLLM()
    monkeypatch.setattr(chat_mod, "get_llm_client_for_agent", lambda cfg: llm)
    monkeypatch.setattr(deps, "get_memory_manager", lambda: None)
    cm = FakeContextMgr()
    monkeypatch.setattr(deps, "get_context_manager", lambda: cm)
    return cm, llm


class TestChatMessageHandler:
    @pytest.mark.asyncio
    async def test_message_success(self, handlers, mgr, monkeypatch):
        cm, llm = _setup_ctx(monkeypatch)
        llm.content = "回复"
        await handlers[ChatActions.MESSAGE](None, {"data": {"agent_id": "a1", "text": "hi"}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["type"] == "response"
        assert msg["action"] == ChatActions.MESSAGE
        assert msg["data"]["content"] == "回复"
        assert msg["data"]["tokens_used"] == 10
        # assistant 消息已记录
        assert cm.messages[-1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_message_with_tool_calls(self, handlers, mgr, monkeypatch):
        cm, llm = _setup_ctx(monkeypatch)
        llm.tool_calls = [{"name": "set_alarm", "arguments": '{"t":1}', "id": "c1"}]
        tool_llm = FakeLLM(content="工具后回复", tool_calls=None)
        monkeypatch.setattr(chat_mod, "get_tools_for_agent", lambda: [])
        # 让 _process_tool_calls 的第 2 次 chat 返回 tool_llm
        monkeypatch.setattr(chat_mod, "_process_tool_calls",
                            lambda calls, msgs, llm: _finish_tool_calls(
                                tool_llm, msgs))
        await handlers[ChatActions.MESSAGE](None, {"data": {"agent_id": "a1", "text": "hi"}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["data"]["content"] == "工具后回复"

    @pytest.mark.asyncio
    async def test_message_error(self, handlers, mgr, monkeypatch):
        _setup_ctx(monkeypatch)
        async def bad_chat(**kw):
            raise RuntimeError("llm down")
        monkeypatch.setattr(chat_mod, "get_llm_client_for_agent",
                            lambda cfg: _BadLLM(bad_chat))
        await handlers[ChatActions.MESSAGE](None, {"data": {"agent_id": "a1", "text": "hi"}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == "CHAT_ERROR"
        assert "llm down" in msg["error"]["message"]


class _BadLLM:
    def __init__(self, chat):
        self._chat = chat

    async def chat(self, **kw):
        return await self._chat(**kw)


async def _finish_tool_calls(tool_llm, msgs):
    msgs.extend([
        {"role": "assistant", "content": None, "tool_calls": [{}]},
        {"role": "tool", "tool_call_id": "c1", "name": "set_alarm", "content": "{}"},
    ])
    return tool_llm


class TestChatStreamHandler:
    @pytest.mark.asyncio
    async def test_stream_success(self, handlers, mgr, monkeypatch):
        cm, llm = _setup_ctx(monkeypatch)
        class StreamLLM:
            async def stream_chat(self, **kw):
                yield {"type": "content", "content": "你"}
                yield {"type": "content", "content": "好"}
                yield {"type": "thinking", "content": "思考"}
        monkeypatch.setattr(chat_mod, "get_llm_client_for_agent", lambda cfg: StreamLLM())
        await handlers[ChatActions.STREAM](None, {"data": {"agent_id": "a1", "text": "hi"}}, "c1")
        # 两个 content chunk + 一个 final（final 的 data 为空 dict 无 content）
        streams = [m[1] for m in mgr.sent if m[1]["type"] == "stream"]
        contents = [m["data"].get("content") for m in streams
                    if not m.get("is_final") and m["data"].get("content")]
        assert contents == ["你", "好"]
        final = [m for m in streams if m.get("is_final")]
        assert len(final) == 1
        assert mgr.llm_count == 1
        # assistant 消息累积记录
        assert cm.messages[-1]["role"] == "assistant"
        assert cm.messages[-1]["content"] == "你好"

    @pytest.mark.asyncio
    async def test_stream_error(self, handlers, mgr, monkeypatch):
        _setup_ctx(monkeypatch)
        class BadStream:
            async def stream_chat(self, **kw):
                raise RuntimeError("stream down")
                yield
        monkeypatch.setattr(chat_mod, "get_llm_client_for_agent", lambda cfg: BadStream())
        await handlers[ChatActions.STREAM](None, {"data": {"agent_id": "a1", "text": "hi"}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == "CHAT_STREAM_ERROR"