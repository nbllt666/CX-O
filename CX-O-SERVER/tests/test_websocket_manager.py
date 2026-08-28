"""server.core.websocket.manager (WebSocketManager) 单元测试。

使用 FakeWebSocket 隔离 FastAPI WebSocket，覆盖：
连接封装订阅、连接/断连、点对点发送、广播（含 exclude）、频道订阅/取消/广播、
type 路由与 action 回退、未知消息/未知 action、离线清理与回调、统计计数。

运行：python -m pytest tests/test_websocket_manager.py -v
"""
import json
from datetime import datetime, timedelta

import pytest

from server.core.websocket.manager import (
    WebSocketConnection,
    WebSocketManager,
    get_websocket_manager,
)


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent = []
        self.to_receive = []
        self.raw_frames = []  # 原生 ASGI 帧队列（优先于 to_receive，供 E3 用例注入畸形帧）
        self.closed = False
        self.close_codes = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        self.sent.append(data)

    async def receive_json(self):
        return self.to_receive.pop(0)

    async def receive(self):
        """E3 适配：模拟 ASGI 原生帧。raw_frames 优先（原始帧队列），
        否则把 to_receive 中的对象包装成 {"text": json.dumps(...)} 帧。"""
        if self.raw_frames:
            return self.raw_frames.pop(0)
        item = self.to_receive.pop(0)
        return {"text": json.dumps(item)}

    async def close(self, code: int = 1000):
        if self.closed:
            raise RuntimeError("already closed")  # 模拟底层二次 close 抛错场景
        self.closed = True
        self.close_codes.append(code)


# ================================================================ WebSocketConnection
class TestConnection:
    def test_subscribe_and_unsubscribe(self):
        c = WebSocketConnection(FakeWebSocket(), "c1", {"k": "v"})
        assert c.metadata == {"k": "v"}
        assert c.is_subscribed("ch") is False
        c.subscribe("ch")
        assert c.is_subscribed("ch") is True
        c.unsubscribe("ch")
        assert c.is_subscribed("ch") is False

    def test_unsubscribe_unknown_safe(self):
        c = WebSocketConnection(FakeWebSocket(), "c1")
        c.unsubscribe("nope")  # 不应抛错

    @pytest.mark.asyncio
    async def test_send_updates_activity(self):
        ws = FakeWebSocket()
        c = WebSocketConnection(ws, "c1")
        before = c.last_activity
        await c.send({"type": "ping"})
        assert ws.sent == [{"type": "ping"}]
        assert c.last_activity >= before

    @pytest.mark.asyncio
    async def test_receive(self):
        ws = FakeWebSocket()
        ws.to_receive = [{"type": "hello"}]
        c = WebSocketConnection(ws, "c1")
        assert await c.receive() == {"type": "hello"}

    @pytest.mark.asyncio
    async def test_receive_skips_malformed_frames(self):
        """E3 回归：畸形 JSON 文本帧/二进制帧不抛异常，跳过后取到有效帧。"""
        ws = FakeWebSocket()
        ws.raw_frames = [
            {"text": "{not-valid-json"},
            {"bytes": b"\xff\xfe\x00broken"},
            {"text": json.dumps({"type": "ok"})},
        ]
        c = WebSocketConnection(ws, "c1")
        assert await c.receive() == {"type": "ok"}

    @pytest.mark.asyncio
    async def test_receive_skips_non_dict_json(self):
        """E3 回归：合法 JSON 但非对象（数组/标量）同样跳过，维持 dict 返回契约。"""
        ws = FakeWebSocket()
        ws.raw_frames = [
            {"text": "[1, 2, 3]"},
            {"text": json.dumps({"type": "hello"})},
        ]
        c = WebSocketConnection(ws, "c1")
        assert await c.receive() == {"type": "hello"}

    @pytest.mark.asyncio
    async def test_receive_propagates_disconnect(self):
        """E3 回归：连接关闭时 WebSocketDisconnect 正常向上传播，不被吞掉。"""
        from fastapi import WebSocketDisconnect

        ws = FakeWebSocket()

        async def raise_disconnect():
            raise WebSocketDisconnect(code=1000)

        ws.receive = raise_disconnect
        c = WebSocketConnection(ws, "c1")
        with pytest.raises(WebSocketDisconnect):
            await c.receive()


# ================================================================ WebSocketManager
@pytest.fixture
def mgr():
    return WebSocketManager()


class TestConnectDisconnect:
    @pytest.mark.asyncio
    async def test_connect_generates_client_id_and_sends_connected(self, mgr):
        ws = FakeWebSocket()
        conn = await mgr.connect(ws)
        assert ws.accepted is True
        assert conn.client_id in mgr.connections
        assert ws.sent[0]["type"] == "connected"

    @pytest.mark.asyncio
    async def test_connect_no_connected_message(self, mgr):
        ws = FakeWebSocket()
        conn = await mgr.connect(ws, client_id="fixed", send_connected=False)
        assert conn.client_id == "fixed"
        assert ws.sent == []

    @pytest.mark.asyncio
    async def test_disconnect_removes_and_cleans_subscriptions(self, mgr):
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a")
        mgr.subscribe_to_channel("a", "room")
        await mgr.disconnect("a")
        assert "a" not in mgr.connections
        assert "room" not in mgr.channels

    @pytest.mark.asyncio
    async def test_disconnect_closes_underlying_websocket(self, mgr):
        """H4 回归：disconnect 必须显式 close 底层 WebSocket（防僵尸 TCP）。"""
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a")
        await mgr.disconnect("a")
        assert ws.closed is True
        assert ws.close_codes == [1000]

    @pytest.mark.asyncio
    async def test_disconnect_close_failure_swallowed(self, mgr):
        """底层二次/异常 close 被吞掉，disconnect 本身不抛错。"""
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a")
        ws.closed = True  # 预置为已关闭 → close() 会抛 RuntimeError
        await mgr.disconnect("a")  # 不应抛错
        assert "a" not in mgr.connections

    @pytest.mark.asyncio
    async def test_cleanup_inactive_also_closes_socket(self, mgr):
        """超时清理路径同样会关闭底层连接。"""
        ws = FakeWebSocket()
        conn = await mgr.connect(ws, client_id="a", send_connected=False)
        conn.last_activity = datetime.now() - timedelta(hours=2)
        await mgr._cleanup_inactive_connections()
        assert ws.closed is True

    @pytest.mark.asyncio
    async def test_disconnect_unknown_is_noop(self, mgr):
        await mgr.disconnect("ghost")  # 不应抛错


class TestSend:
    @pytest.mark.asyncio
    async def test_send_to_client(self, mgr):
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a", send_connected=False)
        await mgr.send_to_client("a", {"type": "x"})
        assert ws.sent == [{"type": "x"}]

    @pytest.mark.asyncio
    async def test_send_to_missing_client_noop(self, mgr):
        await mgr.send_to_client("ghost", {"type": "x"})  # 不应抛错

    @pytest.mark.asyncio
    async def test_send_message_alias(self, mgr):
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a", send_connected=False)
        await mgr.send_message("a", {"type": "y"})
        assert ws.sent[-1]["type"] == "y"


class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_to_all(self, mgr):
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        await mgr.connect(ws1, client_id="a", send_connected=False)
        await mgr.connect(ws2, client_id="b", send_connected=False)
        await mgr.broadcast({"type": "z"}, exclude=None)
        assert ws1.sent == ws2.sent == [{"type": "z"}]

    @pytest.mark.asyncio
    async def test_broadcast_exclude(self, mgr):
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        await mgr.connect(ws1, client_id="a", send_connected=False)
        await mgr.connect(ws2, client_id="b", send_connected=False)
        await mgr.broadcast({"type": "z"}, exclude="b")
        assert ws1.sent == [{"type": "z"}]
        assert ws2.sent == []

    @pytest.mark.asyncio
    async def test_broadcast_external_event(self, mgr):
        ws1 = FakeWebSocket()
        await mgr.connect(ws1, client_id="a", send_connected=False)
        await mgr.broadcast_external_event("sys", "alert", "标题", "正文")
        assert ws1.sent[0]["event"] == "external_event"
        assert ws1.sent[0]["data"]["title"] == "标题"


class TestChannels:
    @pytest.mark.asyncio
    async def test_subscribe_requires_connection(self, mgr):
        mgr.subscribe_to_channel("ghost", "ch")  # 无连接 → 不建频道
        assert "ch" not in mgr.channels

    @pytest.mark.asyncio
    async def test_subscribe_and_unsubscribe(self, mgr):
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a", send_connected=False)
        mgr.subscribe_to_channel("a", "room")
        assert mgr.connections["a"].is_subscribed("room")
        assert mgr.channels["room"] == {"a"}
        mgr.unsubscribe_from_channel("a", "room")
        assert "room" not in mgr.channels

    @pytest.mark.asyncio
    async def test_broadcast_to_channel(self, mgr):
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        await mgr.connect(ws1, client_id="a", send_connected=False)
        await mgr.connect(ws2, client_id="b", send_connected=False)
        mgr.subscribe_to_channel("a", "room")
        await mgr.broadcast_to_channel("room", {"type": "m"})
        assert ws1.sent == [{"type": "m"}]
        assert ws2.sent == []


class TestRouting:
    @pytest.mark.asyncio
    async def test_type_handler_called(self, mgr):
        calls = []

        async def handler(client_id, message):
            calls.append((client_id, message))

        mgr.register_handler("greet", handler)
        await mgr.handle_message("a", {"type": "greet", "data": "hi"})
        assert calls == [("a", {"type": "greet", "data": "hi"})]

    @pytest.mark.asyncio
    async def test_type_handler_error_sends_error(self, mgr):
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a", send_connected=False)

        async def bad_handler(client_id, message):
            raise RuntimeError("boom")

        mgr.register_handler("boom", bad_handler)
        await mgr.handle_message("a", {"type": "boom"})
        assert ws.sent[-1]["type"] == "error"

    @pytest.mark.asyncio
    async def test_action_fallback(self, mgr):
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a", send_connected=False)
        calls = []

        async def action_handler(websocket, message, client_id):
            calls.append((websocket, message, client_id))

        mgr.register_action_handler("chat.message", action_handler)
        await mgr.handle_message("a", {"action": "chat.message", "data": "x"})
        assert calls[0][1]["action"] == "chat.message"
        assert calls[0][2] == "a"
        assert calls[0][0] is ws  # 快照自注册连接，不再是裸 None

    @pytest.mark.asyncio
    async def test_action_without_connection_skips_handler(self, mgr):
        """M 回归：无连接的 action 消息不把 None 传入 handler，直接告警返回。"""
        called = []

        async def action_handler(websocket, message, client_id):
            called.append((websocket, message, client_id))

        mgr.register_action_handler("chat.message", action_handler)
        await mgr.handle_action_message("ghost", {"action": "chat.message"})
        assert called == []  # handler 未被调用，websocket=None 未入参

    @pytest.mark.asyncio
    async def test_unknown_message_type(self, mgr):
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a", send_connected=False)
        await mgr.handle_message("a", {"type": "nope"})
        assert ws.sent[-1]["type"] == "error"

    @pytest.mark.asyncio
    async def test_unknown_action(self, mgr):
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a", send_connected=False)
        await mgr.handle_action_message("a", {"action": "nope"})
        assert ws.sent[-1]["type"] == "error"

    @pytest.mark.asyncio
    async def test_action_handler_error_sends_error_and_keeps_connection(self, mgr):
        """E2a 回归：action handler 抛异常不断连，客户端收到 error 帧。"""
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a", send_connected=False)

        async def bad_handler(websocket, message, client_id):
            raise RuntimeError("action boom")

        mgr.register_action_handler("chat.message", bad_handler)
        await mgr.handle_message("a", {"action": "chat.message"})  # 不应抛
        assert "a" in mgr.connections  # 连接未被断开
        last = ws.sent[-1]
        assert last["type"] == "error"
        assert last["data"]["message"] == "action 处理失败"

    @pytest.mark.asyncio
    async def test_handle_action_get_handler(self, mgr):
        async def h(ws, msg, cid):
            pass

        mgr.register_action_handler("act", h)
        assert mgr.get_handler("act") is h
        assert mgr.get_handler("missing") is None


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_inactive_triggers_offline(self, mgr):
        offline = []
        mgr.set_offline_callback(lambda host_agent_id: offline.append(host_agent_id))
        mgr.set_agent_timeout("agent1", 5)

        ws = FakeWebSocket()
        conn = await mgr.connect(ws, client_id="a", metadata={"agent_id": "agent1"},
                                 send_connected=False)
        conn.last_activity = datetime.now() - timedelta(hours=2)

        await mgr._cleanup_inactive_connections()
        assert "a" not in mgr.connections
        assert offline == ["agent1"]

    @pytest.mark.asyncio
    async def test_cleanup_keeps_active(self, mgr):
        ws = FakeWebSocket()
        await mgr.connect(ws, client_id="a", send_connected=False)
        await mgr._cleanup_inactive_connections()
        assert "a" in mgr.connections

    @pytest.mark.asyncio
    async def test_cleanup_default_timeout(self, mgr):
        ws = FakeWebSocket()
        conn = await mgr.connect(ws, client_id="a", send_connected=False)
        conn.last_activity = datetime.now() - timedelta(hours=2)
        await mgr._cleanup_inactive_connections()
        assert "a" not in mgr.connections

    @pytest.mark.asyncio
    async def test_cleanup_loop_cancellable(self, mgr):
        mgr._running = True
        mgr._track_background_task(__import__("asyncio").create_task(
            mgr._cleanup_loop(interval_seconds=1)))
        await mgr.stop_cleanup_task()
        assert mgr._running is False


class TestStats:
    def test_get_stats_counts(self, mgr):
        mgr.increment_llm_count()
        mgr.increment_llm_count()
        stats = mgr.get_stats()
        assert stats["llm_count"] == 2
        assert stats["total_connections"] == 0
        assert stats["total_channels"] == 0

    def test_get_websocket_manager_singleton(self):
        a = get_websocket_manager()
        b = get_websocket_manager()
        assert a is b