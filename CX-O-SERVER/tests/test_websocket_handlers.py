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

    @pytest.mark.asyncio
    async def test_config_agent_id_auto_subscribes(self, handler, fake_mgr):
        # W1: config 携带 agent_id → 落 metadata 并自动订阅 agent:{id} alarm 频道
        conn = SimpleNamespace(metadata={})
        fake_mgr.connections["c1"] = conn
        await handler._handle_config("c1", {"agent_id": "ag1", "timeout": 60})
        assert fake_mgr.subscriptions == [("c1", "agent:ag1")]
        assert conn.metadata["agent_id"] == "ag1"

    @pytest.mark.asyncio
    async def test_config_agent_rebind_unsubscribes_old(self, handler, fake_mgr):
        # W1: 换绑 agent → 先退订旧频道再订阅新频道，避免跨 agent 串音
        conn = SimpleNamespace(
            metadata={"agent_id": "ag1"}, is_subscribed=lambda ch: ch == "agent:ag1"
        )
        fake_mgr.connections["c1"] = conn
        await handler._handle_config("c1", {"agent_id": "ag2"})
        assert fake_mgr.unsubscriptions == [("c1", "agent:ag1")]
        assert fake_mgr.subscriptions == [("c1", "agent:ag2")]
        assert conn.metadata["agent_id"] == "ag2"

    @pytest.mark.asyncio
    async def test_config_without_agent_id_no_subscribe(self, handler, fake_mgr):
        # W1: 字段缺失时行为不变（向后兼容），不触发任何订阅
        fake_mgr.connections["c1"] = SimpleNamespace(metadata={})
        await handler._handle_config("c1", {"timeout": 60})
        assert fake_mgr.subscriptions == []


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
        get_session=lambda sid: {"id": sid} if sid == "s1" else None,
        create_session=lambda **kw: kw.get("session_id") or "s1",
        update_session=lambda *a, **kw: True,
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
    async def test_creates_agent_session_when_missing(self, handler, fake_mgr, monkeypatch):
        created = []
        context_mgr = SimpleNamespace(
            get_session=lambda sid: None,
            create_session=lambda **kw: created.append(kw.get("workspace_id"))
            or kw.get("session_id", "new_s1"),
            update_session=lambda *a, **kw: True,
            add_message=lambda session_id, role, content: None,
        )
        _patch_chat_deps(monkeypatch, context_mgr=context_mgr)
        await handler._handle_chat("c1", {"message": "hi"})
        # 未携带 session_id → 默认 agent-{id} 会话（对齐历史读取键）
        assert created == ["agent-chats"]
        assert _last_sent(fake_mgr)["session_id"] == "agent-default"

    @pytest.mark.asyncio
    async def test_agent_session_autocreate_when_provided_but_missing(
        self, handler, fake_mgr, monkeypatch
    ):
        created = []
        context_mgr = SimpleNamespace(
            get_session=lambda sid: None,
            create_session=lambda **kw: created.append(kw.get("session_id"))
            or kw.get("session_id", "new_s1"),
            update_session=lambda *a, **kw: True,
            add_message=lambda session_id, role, content: None,
        )
        _patch_chat_deps(monkeypatch, context_mgr=context_mgr)
        # 携带 agent-default 但会话不存在 → 自动创建而非报错
        await handler._handle_chat("c1", {"message": "hi", "session_id": "agent-default"})
        assert created == ["agent-default"]
        assert _last_sent(fake_mgr)["type"] == "chat_response"
        assert _last_sent(fake_mgr)["session_id"] == "agent-default"

    @pytest.mark.asyncio
    async def test_unknown_session_errors(self, handler, fake_mgr, monkeypatch):
        _patch_chat_deps(monkeypatch)
        # 携带不存在的非 agent-{id} 会话 → 报「会话不存在」
        await handler._handle_chat("c1", {"message": "hi", "session_id": "nope"})
        msg = _last_sent(fake_mgr)
        assert msg["type"] == "error"
        assert "不存在" in msg["error"]

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
    async def test_stream_thinking_frame_forwarded(self, handler, fake_mgr, monkeypatch):
        # W4: stream_chat 产出 dict 分帧时，thinking 帧以 SSE 同款字段（type/content）
        # 转发；content 帧仍以 chat_chunk 外发；thinking 不入对话上下文。
        saved = []
        context_mgr = SimpleNamespace(
            get_session=lambda sid: {"id": sid} if sid == "s1" else None,
            create_session=lambda **kw: kw.get("session_id") or "s1",
            update_session=lambda *a, **kw: True,
            add_message=lambda session_id, role, content: saved.append((role, content)),
        )

        async def stream_chat(messages, temperature=0.7, max_tokens=4096):
            yield {"type": "thinking", "content": "正在思考"}
            yield {"type": "content", "content": "你"}
            yield {"type": "content", "content": "好"}

        llm = SimpleNamespace(chat=None, stream_chat=stream_chat)
        _patch_chat_deps(monkeypatch, llm=llm, context_mgr=context_mgr)
        await handler._handle_chat_stream("c1", {"message": "hi", "session_id": "s1"})
        thinking = [m for _, m in fake_mgr.sent if m["type"] == "thinking"]
        assert thinking == [{"type": "thinking", "content": "正在思考"}]
        chunks = [m["content"] for _, m in fake_mgr.sent if m["type"] == "chat_chunk"]
        assert chunks == ["你", "好"]
        assert _last_sent(fake_mgr)["type"] == "chat_done"
        # thinking 不累积为回复（与 SSE 契约一致：仅 content 入对话上下文）
        assert ("assistant", "你好") in saved

    @pytest.mark.asyncio
    async def test_stream_cancel_interrupts(self, handler, fake_mgr, monkeypatch):
        async def stream_chat(messages, temperature=0.7, max_tokens=4096):
            handler._cancel_flags["c1"] = True  # 首个 chunk 前即收到取消请求
            yield "半句话"

        llm = SimpleNamespace(chat=None, stream_chat=stream_chat)
        _patch_chat_deps(monkeypatch, llm=llm)
        await handler._handle_chat_stream("c1", {"message": "hi", "session_id": "s1"})
        assert _last_sent(fake_mgr)["type"] == "cancelled"

    @pytest.mark.asyncio
    async def test_stream_cancel_saves_partial_response(self, handler, fake_mgr, monkeypatch):
        # E4: 取消时已生成的半截回复以 [已打断] 标记补写入库，避免「用户问了没回答」断层
        saved = []
        context_mgr = SimpleNamespace(
            get_session=lambda sid: {"id": sid} if sid == "s1" else None,
            create_session=lambda **kw: kw.get("session_id") or "s1",
            update_session=lambda *a, **kw: True,
            add_message=lambda session_id, role, content: saved.append((role, content)),
        )

        async def stream_chat(messages, temperature=0.7, max_tokens=4096):
            yield "半句话"
            handler._cancel_flags["c1"] = True  # 第二个 chunk 前收到取消请求
            yield "后续内容"

        llm = SimpleNamespace(chat=None, stream_chat=stream_chat)
        _patch_chat_deps(monkeypatch, llm=llm, context_mgr=context_mgr)
        await handler._handle_chat_stream("c1", {"message": "hi", "session_id": "s1"})
        assert _last_sent(fake_mgr)["type"] == "cancelled"
        assert ("assistant", "半句话\n\n[已打断]") in saved

    @pytest.mark.asyncio
    async def test_stream_error_saves_partial_response(self, handler, fake_mgr, monkeypatch):
        # E4: 流中途异常时已生成的半截回复以 [已中断] 标记补写入库
        saved = []
        context_mgr = SimpleNamespace(
            get_session=lambda sid: {"id": sid} if sid == "s1" else None,
            create_session=lambda **kw: kw.get("session_id") or "s1",
            update_session=lambda *a, **kw: True,
            add_message=lambda session_id, role, content: saved.append((role, content)),
        )

        async def stream_chat(messages, temperature=0.7, max_tokens=4096):
            yield "部分"
            yield "内容"
            raise RuntimeError("llm exploded")

        llm = SimpleNamespace(chat=None, stream_chat=stream_chat)
        _patch_chat_deps(monkeypatch, llm=llm, context_mgr=context_mgr)
        await handler._handle_chat_stream("c1", {"message": "hi", "session_id": "s1"})
        msg = _last_sent(fake_mgr)
        assert msg["type"] == "error"
        assert "llm exploded" in msg["error"]
        assert ("assistant", "部分内容\n\n[已中断]") in saved

    @pytest.mark.asyncio
    async def test_stream_cancel_empty_response_not_saved(self, handler, fake_mgr, monkeypatch):
        # E4: 取消时一个字都未生成（full_response 为空串）则不补写 assistant 消息
        saved = []
        context_mgr = SimpleNamespace(
            get_session=lambda sid: {"id": sid} if sid == "s1" else None,
            create_session=lambda **kw: kw.get("session_id") or "s1",
            update_session=lambda *a, **kw: True,
            add_message=lambda session_id, role, content: saved.append((role, content)),
        )

        async def stream_chat(messages, temperature=0.7, max_tokens=4096):
            handler._cancel_flags["c1"] = True  # 首个 chunk 前即取消，零内容
            yield "半句话"

        llm = SimpleNamespace(chat=None, stream_chat=stream_chat)
        _patch_chat_deps(monkeypatch, llm=llm, context_mgr=context_mgr)
        await handler._handle_chat_stream("c1", {"message": "hi", "session_id": "s1"})
        assert _last_sent(fake_mgr)["type"] == "cancelled"
        assert all(role != "assistant" for role, _ in saved)


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