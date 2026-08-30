"""
server/api/routers/chat.py 路由回归测试
覆盖非流式 POST /chat（JSON/multipart、内存路由、工具调用、错误降级）与 GET /chat/history/{session_id}。
用假 LLM / 假上下文 / 假记忆管理 / monkeypatch build_messages 与 tool_registry 隔离外部依赖。
（流式端点 /chat/stream、/memory-agent/chat/stream、/summary-agent/chat/stream 依赖 SSE 与重型模型，另测。）
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers.chat import router as chat_router


# --------------------------------------------------------------------------- #
# 假依赖
# --------------------------------------------------------------------------- #
class FakeContextManager:
    def __init__(self):
        self.sessions = {}
        self.messages = {}
        self.calls = []

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    def create_session(self, workspace_id=None, title=None, session_id=None, metadata=None):
        self.calls.append(("create", session_id))
        self.sessions[session_id] = {"id": session_id, "title": title, "metadata": metadata or {}}

    def ensure_session(self, session_id, workspace_id="default", title="", metadata=None):
        self.calls.append(("ensure", session_id))
        if session_id not in self.sessions:
            self.sessions[session_id] = {"id": session_id, "title": title, "metadata": metadata or {}}
        return session_id

    def update_session(self, session_id, metadata=None):
        self.calls.append(("update", session_id))
        if session_id in self.sessions:
            self.sessions[session_id]["metadata"] = metadata

    def add_message(self, session_id, role, content):
        self.calls.append(("add", session_id, role, content))
        self.messages.setdefault(session_id, []).append({"role": role, "content": content})

    def get_messages(self, session_id, limit=50):
        return self.messages.get(session_id, [])[:limit]

    def get_recent_messages(self, session_id, limit=50):
        return self.messages.get(session_id, [])[-limit:]


class FakeMemoryManager:
    def __init__(self):
        self.routed = []


class FakeModelRouter:
    """按模型名返回 LLM 客户端的模型路由替身。"""

    def __init__(self):
        self.clients = {}
        self.get_calls = []

    def get_client(self, model):
        self.get_calls.append(model)
        return self.clients.get(model)


class FakeAgentContextManager:
    def __init__(self):
        self.loaded_agents = []
        self.appended = []

    def load_context(self, agent_id, limit=20):
        self.loaded_agents.append(agent_id)
        return []

    def append_message(self, agent_id, role, content):
        self.appended.append((agent_id, role, content))


class FakeResponse:
    def __init__(self, content, tool_calls=None, usage=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage = usage or {"total_tokens": 7}


class FakeLLM:
    """按轮次返回预设响应。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.chat_calls = []

    async def chat(self, messages, stream=False, tools=None):
        self.chat_calls.append((messages, stream, tools))
        return self.responses.pop(0)


class ChatHarness:
    """承载可逐测试配置的外部依赖替身。"""

    def __init__(self, monkeypatch):
        self.agent_config = None
        self.llm = None
        self.ctx = FakeContextManager()
        self.memory_mgr = FakeMemoryManager()
        self.model_router = FakeModelRouter()
        self.agent_context = FakeAgentContextManager()
        self.current_agent_ids = []
        self.called_build_messages = []
        self.tool_list = []

        class _Tool:
            def __init__(self, category):
                self.category = category

        self._tool_cls = _Tool

        # chat.py 在模块顶层 `from server.chat_helpers import ...` 绑定引用，
        # 因此必须 patch 模块级名字，而非源模块。
        # 路由已切换为 get_agent_config_async（异步变体），patch 点同步迁移；
        # fake 以协程返回以匹配 await 调用语义。
        async def _fake_agent_config(aid):
            return self.agent_config

        monkeypatch.setattr("server.api.routers.chat.get_agent_config_async",
                            _fake_agent_config)
        monkeypatch.setattr("server.api.routers.chat.get_llm_client_for_agent",
                            lambda cfg: self.llm)
        # 函数体内 `from server.dependencies import ...` 在调用时解析，直接 patch 源模块
        monkeypatch.setattr("server.dependencies.get_context_manager",
                            lambda: self.ctx)
        monkeypatch.setattr("server.dependencies.get_memory_manager",
                            lambda: self.memory_mgr)
        monkeypatch.setattr("server.dependencies.get_model_router",
                            lambda: self.model_router)
        monkeypatch.setattr("server.core.context.agent_context_manager.get_agent_context_manager",
                            lambda: self.agent_context)
        monkeypatch.setattr("server.core.tools.graph_tools.set_current_agent_id",
                            lambda aid: self.current_agent_ids.append(aid))

        def _build_messages(**kwargs):
            self.called_build_messages.append(kwargs)
            return [{"role": "user", "content": kwargs.get("user_message", "")}]

        # build_messages 也在 chat.py 模块顶层绑定，patch 模块级名字
        monkeypatch.setattr("server.api.routers.chat.build_messages", _build_messages)

        def _list_tools(include_builtin=True, category=None):
            return self.tool_list

        monkeypatch.setattr("server.core.tools.tool_registry.list_openai_functions", _list_tools)

        def _get_tool(name):
            for t in self.tool_list:
                if t.get("function", {}).get("name") == name:
                    return self._tool_cls("builtin")
            return None

        monkeypatch.setattr("server.core.tools.tool_registry.get_tool", _get_tool)
        monkeypatch.setattr("server.core.tools.tool_registry.call_tool",
                            lambda name, args: {"called": name, "args": args})
        monkeypatch.setattr("server.core.tools.builtin.call_builtin_tool",
                            lambda name, args: {"builtin": name, "args": args})
        monkeypatch.setattr("server.core.tools.builtin.get_builtin_tools", lambda: [])

        app = FastAPI()
        app.include_router(chat_router)
        self.client = TestClient(app)


def _simple_config(**overrides):
    cfg = {
        "id": "default", "name": "默认助手", "model": "main",
        "system_prompt": "p", "use_memory": False, "memory_scene": "chat",
        "temperature": 0.7, "max_tokens": 0,
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def harness(monkeypatch):
    return ChatHarness(monkeypatch)


# --------------------------------------------------------------------------- #
# POST /chat —— JSON
# --------------------------------------------------------------------------- #
class TestChatJson:
    def test_success(self, harness):
        harness.agent_config = _simple_config()
        harness.llm = FakeLLM([FakeResponse("你好！")])

        r = harness.client.post("/chat", json={
            "message": "hi", "agent_id": "default", "stream": False})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["response"] == "你好！"
        assert body["session_id"] == "agent-default"
        assert body["tokens_used"] == 7
        # 会话自动创建 + 用户/助手消息落库
        assert "agent-default" in harness.ctx.sessions
        roles = [c[2] for c in harness.ctx.calls if c[0] == "add"]
        assert roles == ["user", "assistant"]

    def test_agent_not_found_404(self, harness):
        harness.agent_config = None
        r = harness.client.post("/chat", json={"message": "hi", "agent_id": "nope"})
        assert r.status_code == 404
        assert "不存在" in r.json()["detail"]

    def test_error_500(self, harness):
        harness.agent_config = _simple_config()

        class BoomLLM:
            async def chat(self, messages, stream=False, tools=None):
                raise RuntimeError("llm down")

        harness.llm = BoomLLM()
        r = harness.client.post("/chat", json={"message": "hi"})
        assert r.status_code == 500
        assert r.json()["detail"] == "聊天处理失败"

    def test_builtin_tool_called(self, harness):
        harness.agent_config = _simple_config()
        harness.tool_list = [{"function": {"name": "calculator"}}]
        harness.llm = FakeLLM([
            FakeResponse("", tool_calls=[{"name": "calculator", "arguments": "{}", "id": "c1"}]),
            FakeResponse("计算结果", usage={"total_tokens": 3}),
        ])

        r = harness.client.post("/chat", json={"message": "2+2"})
        assert r.status_code == 200
        assert r.json()["response"] == "计算结果"
        # LLM 被调用两次（首次触发工具，二次出最终答案）
        assert len(harness.llm.chat_calls) == 2
        # 工具消息已追加
        tool_msgs = [m for m in harness.llm.chat_calls[1][0] if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["name"] == "calculator"

    def test_tool_invalid_args_fallback(self, harness):
        harness.agent_config = _simple_config()
        harness.tool_list = [{"function": {"name": "calculator"}}]
        # 非法 JSON 参数 → 降级为空 dict，不抛异常
        harness.llm = FakeLLM([
            FakeResponse("", tool_calls=[{"name": "calculator", "arguments": "{bad", "id": "c1"}]),
            FakeResponse("ok"),
        ])
        r = harness.client.post("/chat", json={"message": "x"})
        assert r.status_code == 200
        assert r.json()["response"] == "ok"

    def test_memory_routing_injected(self, harness):
        harness.agent_config = _simple_config(use_memory=True)
        harness.memory_mgr = _MemoryRoutingManager()
        harness.llm = FakeLLM([FakeResponse("已联想记忆")])

        r = harness.client.post("/chat", json={"message": "回忆一下"})
        assert r.status_code == 200
        # 内存路由触发记忆检索（MemoryRouter 内部多次调用 search_memories，含 query 与最近记忆）
        assert any(q == "回忆一下" for q in harness.memory_mgr.search_queries)
        # build_messages 收到 memory_context
        assert any("memory_context" in c for c in harness.called_build_messages)


class _MemoryRoutingManager:
    """带 search_memories 的记忆管理替身，返回一条记忆。"""

    def __init__(self):
        self.search_queries = []

    def search_memories(self, query, limit=10, **kwargs):
        self.search_queries.append(query)
        return [{"content": "相关记忆", "id": 1, "score": 0.9}]


# --------------------------------------------------------------------------- #
# POST /chat —— multipart/form-data
# --------------------------------------------------------------------------- #
class TestChatMultipart:
    def test_success(self, harness):
        harness.agent_config = _simple_config()
        harness.llm = FakeLLM([FakeResponse("收到")])

        r = harness.client.post(
            "/chat",
            files={"text": (None, "hello"), "agent_id": (None, "default")},
        )
        assert r.status_code == 200
        assert r.json()["response"] == "收到"
        # 用户消息为表单 text
        assert harness.ctx.messages["agent-default"][0]["content"] == "hello"


# --------------------------------------------------------------------------- #
# GET /chat/history/{session_id}
# --------------------------------------------------------------------------- #
class TestChatHistory:
    def test_existing_session(self, harness):
        harness.ctx.create_session(session_id="agent-default", title="t")
        harness.ctx.add_message("agent-default", "user", "hi")
        harness.ctx.add_message("agent-default", "assistant", "yo")

        r = harness.client.get("/chat/history/agent-default")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["session_id"] == "agent-default"
        assert len(body["messages"]) == 2

    def test_unknown_session_returns_empty(self, harness):
        r = harness.client.get("/chat/history/unknown-xyz")
        assert r.status_code == 200
        body = r.json()
        assert body["session"] is None
        assert body["messages"] == []

    def test_agent_session_not_auto_created(self, harness):
        # C9: 读路径不再自动创建会话——session 不存在时返回空历史且不产生写路径
        # （旧断言"GET 自动创建 agent 会话"对应的行为即本次修复的缺陷）
        r = harness.client.get("/chat/history/agent-default")
        assert r.status_code == 200
        body = r.json()
        assert body["session"] is None
        assert body["messages"] == []
        assert "agent-default" not in harness.ctx.sessions

    def test_agent_not_configured_returns_empty(self, harness):
        harness.agent_config = None
        r = harness.client.get("/chat/history/agent-default")
        assert r.status_code == 200
        assert r.json()["messages"] == []

    def test_error_500(self, harness, monkeypatch):
        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("server.dependencies.get_context_manager", boom)
        r = harness.client.get("/chat/history/agent-default")
        assert r.status_code == 500
        assert r.json()["detail"] == "获取聊天历史失败"

    def test_history_limit_clamped_to_max(self, harness):
        # T-07: 超大 limit 钳制到上限 200，防恶意拖库
        harness.ctx.create_session(session_id="agent-default", title="t")
        for i in range(250):
            harness.ctx.add_message("agent-default", "user", f"m{i}")
        r = harness.client.get("/chat/history/agent-default", params={"limit": 99999})
        assert r.status_code == 200
        body = r.json()
        assert len(body["messages"]) == 200
        # 保留最近 200 条语义（尾部截断）
        assert body["messages"][0]["content"] == "m50"
        assert body["messages"][-1]["content"] == "m249"

    def test_history_non_positive_limit_clamped_to_one(self, harness):
        # T-07: 非正数 limit 钳制到 1（未钳制时 [-0:] 会返回全量，属真实缺陷）
        harness.ctx.create_session(session_id="agent-default", title="t")
        for i in range(3):
            harness.ctx.add_message("agent-default", "user", f"m{i}")
        r = harness.client.get("/chat/history/agent-default", params={"limit": 0})
        assert r.status_code == 200
        body = r.json()
        assert len(body["messages"]) == 1
        assert body["messages"][0]["content"] == "m2"


# --------------------------------------------------------------------------- #
# POST /chat/stream —— SSE 流式
# --------------------------------------------------------------------------- #
class FakeStreamLLM:
    """带 stream_chat 异步生成器的假 LLM，按调用轮次返回 chunk 列表。"""

    def __init__(self, calls):
        self.calls = list(calls)  # 每次 stream_chat 返回的 chunk 迭代
        self.stream_calls = []

    async def stream_chat(self, messages, temperature=0.7, max_tokens=4096, tools=None):
        idx = len(self.stream_calls)
        self.stream_calls.append((messages, temperature, max_tokens, tools))
        source = self.calls[idx] if idx < len(self.calls) else []
        for c in source:
            yield c


def _parse_sse(r):
    events = []
    for line in r.iter_lines():
        line = line.decode("utf-8") if isinstance(line, bytes) else line
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


class TestChatStream:
    def test_success_content(self, harness):
        harness.agent_config = _simple_config()
        harness.llm = FakeStreamLLM([
            [
                {"type": "thinking", "content": "想一"},
                {"type": "content", "content": "你好"},
                {"type": "content", "content": "世界"},
            ]
        ])
        r = harness.client.post("/chat/stream", json={"message": "hi", "agent_id": "default"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(r)

        types = [e["type"] for e in events]
        assert types[0] == "session"
        assert events[0]["session_id"] == "agent-default"
        assert "thinking" in types
        assert "done" in types
        # 会话被保存，助手消息落库
        assert "agent-default" in harness.ctx.sessions
        assert harness.ctx.messages["agent-default"][-1]["role"] == "assistant"

    def test_string_chunk_compat(self, harness):
        harness.agent_config = _simple_config()
        harness.llm = FakeStreamLLM([["旧格式文本"]])
        r = harness.client.post("/chat/stream", json={"message": "hi"})
        events = _parse_sse(r)
        content_events = [e for e in events if e["type"] == "content"]
        assert any(e["content"] == "旧格式文本" for e in content_events)

    def test_tool_call_then_final(self, harness):
        harness.agent_config = _simple_config()
        harness.tool_list = [{"function": {"name": "calculator"}}]
        harness.llm = FakeStreamLLM([
            [
                {"type": "tool_calls", "tool_calls": [
                    {"name": "calculator", "arguments": "{}", "id": "c1"}]},
            ],
            [{"type": "content", "content": "最终答案"}],
        ])
        r = harness.client.post("/chat/stream", json={"message": "2+2"})
        events = _parse_sse(r)
        types = [e["type"] for e in events]
        assert "tool_call" in types
        assert "tool_start" in types
        assert "tool_result" in types
        assert "done" in types
        # 触发两次 stream_chat（首次触发工具，二次出答案）
        assert len(harness.llm.stream_calls) == 2

    def test_stream_error_yields_error_event(self, harness):
        harness.agent_config = _simple_config()

        class BoomStreamLLM:
            async def stream_chat(self, messages, temperature=0.7, max_tokens=4096, tools=None):
                raise RuntimeError("llm down")
                yield  # pragma: no cover

        harness.llm = BoomStreamLLM()
        r = harness.client.post("/chat/stream", json={"message": "hi"})
        assert r.status_code == 200
        events = _parse_sse(r)
        last = events[-1]
        assert last["type"] == "error"
        assert "处理失败" in last["message"]

    def test_agent_not_found_404(self, harness):
        harness.agent_config = None
        r = harness.client.post("/chat/stream", json={"message": "hi", "agent_id": "nope"})
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# POST /memory-agent/chat/stream —— 记忆管理模型流式
# --------------------------------------------------------------------------- #
class TestMemoryAgentChatStream:
    def test_success(self, harness):
        harness.agent_config = _simple_config(id="memory-agent", name="记忆管理助手")
        harness.model_router.clients["memory"] = FakeStreamLLM([
            [{"type": "content", "content": "记忆管理回复"}],
        ])

        r = harness.client.post("/memory-agent/chat/stream", json={"message": "hi"})
        assert r.status_code == 200
        events = _parse_sse(r)
        types = [e["type"] for e in events]
        assert types[0] == "session"
        assert events[0]["session_id"] == "memory-agent-default"
        assert "done" in types
        # 固定会话被创建，历史上下文被加载，消息被追加
        assert "memory-agent-default" in harness.ctx.sessions
        assert harness.agent_context.loaded_agents == ["memory-agent"]
        assert any(a[0] == "memory-agent" for a in harness.agent_context.appended)

    def test_agent_not_configured_404(self, harness):
        harness.agent_config = None
        r = harness.client.post("/memory-agent/chat/stream", json={"message": "hi"})
        assert r.status_code == 404
        assert "未配置" in r.json()["detail"]

    def test_model_unavailable_503(self, harness):
        harness.agent_config = _simple_config(id="memory-agent", name="记忆管理助手")
        # model_router.clients 为空 → get_client("memory") 返回 None
        r = harness.client.post("/memory-agent/chat/stream", json={"message": "hi"})
        assert r.status_code == 503
        assert "记忆管理模型不可用" in r.json()["detail"]

    def test_stream_error_yields_error_event(self, harness):
        harness.agent_config = _simple_config(id="memory-agent", name="记忆管理助手")

        class BoomStreamLLM:
            async def stream_chat(self, messages, temperature=0.3, max_tokens=4096, tools=None):
                raise RuntimeError("down")
                yield  # pragma: no cover

        harness.model_router.clients["memory"] = BoomStreamLLM()
        r = harness.client.post("/memory-agent/chat/stream", json={"message": "hi"})
        assert r.status_code == 200
        last = _parse_sse(r)[-1]
        assert last["type"] == "error"


# --------------------------------------------------------------------------- #
# POST /summary-agent/chat/stream —— 摘要助手流式
# --------------------------------------------------------------------------- #
class TestSummaryAgentChatStream:
    def test_success(self, harness):
        harness.model_router.clients["summary"] = FakeStreamLLM([
            [{"type": "content", "content": "日记已保存"}],
        ])

        r = harness.client.post("/summary-agent/chat/stream", json={"message": "记录今天"})
        assert r.status_code == 200
        events = _parse_sse(r)
        types = [e["type"] for e in events]
        assert types[0] == "session"
        assert events[0]["session_id"] == "summary-agent-default"
        assert "done" in types
        # 固定会话被创建，当前 agent_id 被设置
        assert "summary-agent-default" in harness.ctx.sessions
        assert harness.current_agent_ids == ["summary-agent"]

    def test_target_session_agent_id(self, harness):
        # 目标会话存在且 metadata.agent_id = "role1" → set_current_agent_id("role1")
        harness.ctx.create_session(session_id="target-1", title="t",
                                   metadata={"agent_id": "role1"})
        harness.model_router.clients["summary"] = FakeStreamLLM([[{"type": "content", "content": "ok"}]])
        r = harness.client.post("/summary-agent/chat/stream",
                                json={"message": "x", "target_session_id": "target-1"})
        assert r.status_code == 200
        assert harness.current_agent_ids == ["role1"]

    def test_target_session_missing_falls_back(self, harness):
        harness.model_router.clients["summary"] = FakeStreamLLM([[{"type": "content", "content": "ok"}]])
        r = harness.client.post("/summary-agent/chat/stream",
                                json={"message": "x", "target_session_id": "nope"})
        assert r.status_code == 200
        assert harness.current_agent_ids == ["summary-agent"]

    def test_both_models_unavailable_503(self, harness):
        # summary 与 main 均不可用 → 503
        r = harness.client.post("/summary-agent/chat/stream", json={"message": "x"})
        assert r.status_code == 503
        # 回退到 main 也被尝试
        assert harness.model_router.get_calls == ["summary", "main"]

    def test_stream_error_yields_error_event(self, harness):
        class BoomStreamLLM:
            async def stream_chat(self, messages, temperature=0.3, max_tokens=4096, tools=None):
                raise RuntimeError("down")
                yield  # pragma: no cover

        harness.model_router.clients["summary"] = BoomStreamLLM()
        r = harness.client.post("/summary-agent/chat/stream", json={"message": "x"})
        assert r.status_code == 200
        last = _parse_sse(r)[-1]
        assert last["type"] == "error"