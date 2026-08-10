"""
server/core/websocket/handlers.py 回归测试
ChatWebSocketHandler 消息分发：聊天/流式聊天/订阅/心跳/取消/配置，及提醒推送
"""
from types import SimpleNamespace

import pytest

import server.core.websocket.handlers as handlers_mod
from server.core.websocket.handlers import (
    ChatWebSocketHandler,
    get_chat_handler,
    push_alarm_to_agent,
)


class FakeWSManager:
    """记录注册的处理器与发送的消息，隔离真实 WebSocket 网络。"""

    def __init__(self):
        self.message_handlers = {}
        self.connections = {}
        self.sent = []
        self.subscriptions = []
        self.unsubscriptions = []
        self.broadcasted = []

    def register_handler(self, msg_type, handler):
        self.message_handlers[msg_type] = handler

    async def send_to_client(self, client_id, message):
        self.sent.append((client_id, message))

    def subscribe_to_channel(self, client_id, channel):
        self.subscriptions.append((client_id, channel))

    def unsubscribe_from_channel(self, client_id, channel):
        self.unsubscriptions.append((client_id, channel))

    async def broadcast_to_channel(self, channel, message):
        self.broadcasted.append((channel, message))


@pytest.fixture
def fake_mgr(monkeypatch):
    mgr = FakeWSManager()
    monkeypatch.setattr(handlers_mod, "get_websocket_manager", lambda: mgr)
    return mgr


@pytest.fixture
def handler(fake_mgr):
    h = ChatWebSocketHandler()
    return h


def _last_sent(fake_mgr):
    return fake_mgr.sent[-1][1]


class TestRegistration:
    def test_registers_all_handlers(self, handler):
        assert set(handler.ws_manager.message_handlers) == {
            "chat", "chat_stream", "subscribe", "unsubscribe", "ping", "cancel", "config",
        }

    def test_get_chat_handler_singleton(self, monkeypatch):
        monkeypatch.setattr(handlers_mod, "_chat_handler", None)
        h = get_chat_handler()
        assert h is get_chat_handler()


class TestSimpleHandlers:
    @pytest.mark.asyncio
    async def test_subscribe(self, handler, fake_mgr):
        await handler._handle_subscribe("c1", {"channel": "room1"})
        assert fake_mgr.subscriptions == [("c1", "room1")]
        assert _last_sent(fake_mgr)["type"] == "subscribed"

    @pytest.mark.asyncio
    async def test_subscribe_without_channel_noop(self, handler, fake_mgr):
        await handler._handle_subscribe("c1", {})
        assert fake_mgr.subscriptions == []

    @pytest.mark.asyncio
    async def test_unsubscribe(self, handler, fake_mgr):
        await handler._handle_unsubscribe("c1", {"channel": "room1"})
        assert fake_mgr.unsubscriptions == [("c1", "room1")]
        assert _last_sent(fake_mgr)["type"] == "unsubscribed"

    @pytest.mark.asyncio
    async def test_ping(self, handler, fake_mgr):
        await handler._handle_ping("c1", {})
        assert _last_sent(fake_mgr)["type"] == "pong"

    @pytest.mark.asyncio
    async def test_cancel(self, handler, fake_mgr):
        await handler._handle_cancel("c1", {})
        assert handler._cancel_flags["c1"] is True
        assert _last_sent(fake_mgr)["type"] == "cancelled"

    @pytest.mark.asyncio
    async def test_config_updates_metadata(self, handler, fake_mgr):
        fake_mgr.connections["c1"] = SimpleNamespace(metadata={})
        await handler._handle_config("c1", {"timeout": 120})
        assert fake_mgr.connections["c1"].metadata["timeout"] == 120
        assert _last_sent(fake_mgr)["type"] == "config_updated"

    @pytest.mark.asyncio
    async def test_config_without_timeout_noop(self, handler, fake_mgr):
        await handler._handle_config("c1", {"other": 1})
        assert fake_mgr.sent == []


_NO_AGENT = object()  # 哨兵：显式表示 agent 不存在


def _patch_chat_deps(monkeypatch, agent_config=None, llm=None, context_mgr=None,
                     build_messages=None, memory_mgr=None):
    import server.dependencies as deps
    import server.prompt_builder as prompt_builder_mod
    import server.chat_helpers as chat_helpers

    async def _async_chat(messages, stream=False):
        return SimpleNamespace(content="你好", usage={"total_tokens": 8})

    agent_config = agent_config or {"id": "default", "name": "Agent", "use_memory": False}
    if agent_config is _NO_AGENT:
        agent_config = None
    llm = llm or SimpleNamespace(
        chat=_async_chat,
        stream_chat=None,
    )
    context_mgr = context_mgr or SimpleNamespace(
        get_session=lambda sid: None,
        create_session=lambda workspace_id, title: "s1",
        add_message=lambda session_id, role, content: None,
    )
    build_messages = build_messages or (lambda **kw: [{"role": "user", "content": "hi"}])

    monkeypatch.setattr(chat_helpers, "get_agent_config", lambda agent_id: agent_config)
    monkeypatch.setattr(chat_helpers, "get_llm_client_for_agent", lambda cfg: llm)
    monkeypatch.setattr(prompt_builder_mod, "build_messages", build_messages)
    monkeypatch.setattr(deps, "get_context_manager", lambda: context_mgr)
    monkeypatch.setattr(deps, "get_memory_manager", lambda: memory_mgr)
    return llm, context_mgr


class TestHandleChat:
    @pytest.mark.asyncio
    async def test_empty_message_error(self, handler, fake_mgr, monkeypatch):
        _patch_chat_deps(monkeypatch)
        await handler._handle_chat("c1", {"message": ""})
        assert _last_sent(fake_mgr)["type"] == "error"

    @pytest.mark.asyncio
    async def test_agent_not_found_error(self, handler, fake_mgr, monkeypatch):
        _patch_chat_deps(monkeypatch, agent_config=_NO_AGENT)
        await handler._handle_chat("c1", {"message": "hi"})
        assert _last_sent(fake_mgr)["type"] == "error"

    @pytest.mark.asyncio
    async def test_success_path(self, handler, fake_mgr, monkeypatch):
        _patch_chat_deps(monkeypatch)
        await handler._handle_chat("c1", {"message": "你好", "session_id": "s1"})
        msg = _last_sent(fake_mgr)
        assert msg["type"] == "chat_response"
        assert msg["content"] == "你好"
        assert msg["session_id"] == "s1"
        assert msg["tokens_used"] == 8

    @pytest.mark.asyncio
    async def test_creates_session_when_missing(self, handler, fake_mgr, monkeypatch):
        created = []
        context_mgr = SimpleNamespace(
            get_session=lambda sid: None,
            create_session=lambda workspace_id, title: created.append(workspace_id) or "new_s1",
            add_message=lambda session_id, role, content: None,
        )
        _patch_chat_deps(monkeypatch, context_mgr=context_mgr)
        await handler._handle_chat("c1", {"message": "hi"})
        assert created == ["default"]  # 未携带 session_id → 自动创建
        assert _last_sent(fake_mgr)["session_id"] == "new_s1"

    @pytest.mark.asyncio
    async def test_exception_sends_error(self, handler, fake_mgr, monkeypatch):
        def boom(**kw):
            raise RuntimeError("llm down")

        _patch_chat_deps(monkeypatch, build_messages=boom)
        await handler._handle_chat("c1", {"message": "hi", "session_id": "s1"})
        msg = _last_sent(fake_mgr)
        assert msg["type"] == "error"
        assert "llm down" in msg["error"]
        assert handler._cancel_flags.get("c1") is None  # finally 清理


class TestHandleChatStream:
    @pytest.mark.asyncio
    async def test_stream_chunks_and_done(self, handler, fake_mgr, monkeypatch):
        async def stream_chat(messages, temperature=0.7, max_tokens=4096):
            for c in ["你", "好"]:
                yield c

        llm = SimpleNamespace(chat=None, stream_chat=stream_chat)
        _patch_chat_deps(monkeypatch, llm=llm)
        await handler._handle_chat_stream("c1", {"message": "hi", "session_id": "s1"})
        types = [m["type"] for _, m in fake_mgr.sent]
        assert "session_info" in types
        assert "chat_chunk" in types
        assert _last_sent(fake_mgr)["type"] == "chat_done"

    @pytest.mark.asyncio
    async def test_stream_cancel_interrupts(self, handler, fake_mgr, monkeypatch):
        async def stream_chat(messages, temperature=0.7, max_tokens=4096):
            handler._cancel_flags["c1"] = True  # 首个 chunk 前即收到取消请求
            yield "半句话"

        llm = SimpleNamespace(chat=None, stream_chat=stream_chat)
        _patch_chat_deps(monkeypatch, llm=llm)
        await handler._handle_chat_stream("c1", {"message": "hi", "session_id": "s1"})
        assert _last_sent(fake_mgr)["type"] == "cancelled"


class TestPushAlarm:
    @pytest.mark.asyncio
    async def test_push_alarm_broadcasts(self, monkeypatch):
        import server.core.websocket.manager as mgr_mod
        fake = FakeWSManager()
        monkeypatch.setattr(mgr_mod, "get_websocket_manager", lambda: fake)
        await push_alarm_to_agent("ag1", "提醒内容")
        assert fake.broadcasted[0][0] == "agent:ag1"
        assert fake.broadcasted[0][1]["type"] == "alarm"
        assert fake.broadcasted[0][1]["message"] == "提醒内容"