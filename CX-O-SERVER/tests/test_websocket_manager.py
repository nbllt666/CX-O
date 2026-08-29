"""server.core.websocket.manager (WebSocketManager) 单元测试。

使用 FakeWebSocket 隔离 FastAPI WebSocket，覆盖：
连接封装订阅、连接/断连、点对点发送、广播（含 exclude）、频道订阅/取消/广播、
type 路由与 action 回退、未知消息/未知 action、离线清理与回调、统计计数、
E3 畸形帧防护（HEAD 基线已含第七轮 G1 用例）、E2a action 异常隔离，
以及 R9-01 重连串扰防护（第九轮合并并入）：
- 同 client_id 重连：连接代际递增、旧 socket 先被关闭（防串扰）
- 代际校验：旧端点携带旧代际 disconnect 不拆毁新连接/新会话频道成员
- channels 无残留：新代际 disconnect 正常回收频道成员，空频道被删除
- 未携带代际的 disconnect（内部清理路径/外部踢出）保持既有语义
- receive：二进制/畸形帧刷新 last_activity + UNSUPPORTED_FRAME error 帧限频回发

运行：python -m pytest tests/test_websocket_manager.py -v
"""
import asyncio
import json
import time
from datetime import datetime, timedelta

import pytest
from fastapi import WebSocketDisconnect

from server.core.websocket.manager import (
    WebSocketConnection,
    WebSocketManager,
    get_websocket_manager,
)


class FakeWebSocket:
    def __init__(self, frames=None):
        self.accepted = False
        self.sent = []
        self.to_receive = []
        # 原生 ASGI 帧队列（优先于 to_receive，供 E3/R9 用例注入畸形帧）。
        # frames 参数：R9 合并适配——兼容第九轮用例的构造方式 FakeWebSocket(frames=[...])
        self.raw_frames = list(frames or [])
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


@pytest.fixture
def _no_audio_processor(monkeypatch):
    """屏蔽 connect 内 per-client 音频处理器懒创建，隔离重型依赖与全局单例。"""
    import server.services.vad_processor as vp

    monkeypatch.setattr(vp, "get_audio_stream_processor", lambda client_id: None)


async def _drain_until(predicate, tries=200):
    """让出事件循环直至条件满足（后台任务/延迟清理任务执行），超时返回最终判定。"""
    for _ in range(tries):
        if predicate():
            return True
        await asyncio.sleep(0.001)
    return predicate()


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
        ws = FakeWebSocket()

        async def raise_disconnect():
            raise WebSocketDisconnect(code=1000)

        ws.receive = raise_disconnect
        c = WebSocketConnection(ws, "c1")
        with pytest.raises(WebSocketDisconnect):
            await c.receive()


# ================================================================ WebSocketManager
@pytest.fixture
def mgr(_no_audio_processor):
    return WebSocketManager()


# R9 合并：第九轮用例的 manager 夹具（与 mgr 同构，均隔离音频处理器懒创建）
@pytest.fixture
def manager(_no_audio_processor):
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


# ================================================================ 重连代际（R9 合并并入）
class TestReconnectGeneration:
    @pytest.mark.asyncio
    async def test_reconnect_assigns_distinct_generation(self, manager):
        """同 client_id 重连：新旧连接代际不同且单调递增。"""
        c1 = await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        c2 = await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        assert c2.generation > c1.generation
        assert manager.connections.get("c1") is c2

    @pytest.mark.asyncio
    async def test_reconnect_closes_old_socket(self, manager):
        """R9-01：同 client_id 重连先 close 旧 socket，新 socket 不受影响。"""
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        await manager.connect(ws1, client_id="c1", send_connected=False)
        await manager.connect(ws2, client_id="c1", send_connected=False)
        assert ws1.closed is True
        assert ws2.closed is False

    @pytest.mark.asyncio
    async def test_old_disconnect_does_not_destroy_new_connection(self, manager):
        """R9-01 核心回归：重连后旧端点 finally 携带旧代际 disconnect，
        不得拆毁新连接（既不移除登记，也不关闭新 socket）。"""
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        c1 = await manager.connect(ws1, client_id="c1", send_connected=False)
        c2 = await manager.connect(ws2, client_id="c1", send_connected=False)

        await manager.disconnect("c1", generation=c1.generation)

        assert manager.connections.get("c1") is c2
        assert ws2.closed is False

    @pytest.mark.asyncio
    async def test_old_disconnect_does_not_run_session_cleanup(self, manager, monkeypatch):
        """R9-01：旧代际 disconnect 被拦下时，不触发双流会话/音频实例清理
        （那些属于新会话的资源，拆毁即串扰）。"""
        cleaned = []
        import server.handlers.audio as audio_mod

        async def fake_cleanup(client_id):
            cleaned.append(("dual_stream", client_id))

        monkeypatch.setattr(audio_mod, "cleanup_dual_stream_session", fake_cleanup)

        c1 = await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        await manager.disconnect("c1", generation=c1.generation)
        assert cleaned == []

    @pytest.mark.asyncio
    async def test_new_disconnect_cleans_up(self, manager):
        """新代际 disconnect 正常清理：移除登记并关闭 socket。"""
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        c1 = await manager.connect(ws1, client_id="c1", send_connected=False)
        c2 = await manager.connect(ws2, client_id="c1", send_connected=False)
        await manager.disconnect("c1", generation=c1.generation)  # 旧端点 finally，被拦下
        await manager.disconnect("c1", generation=c2.generation)  # 新端点 finally，生效
        assert "c1" not in manager.connections
        assert ws2.closed is True


# ================================================================ channels 残留（R9 合并并入）
class TestChannelsNoResidual:
    @pytest.mark.asyncio
    async def test_old_disconnect_preserves_new_channel_membership(self, manager):
        """R9-01：重连后新旧连接先后订阅同一频道，旧代际 disconnect 被拦下，
        新连接的频道成员不被误删。"""
        await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        manager.subscribe_to_channel("c1", "live")
        c2 = await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        manager.subscribe_to_channel("c1", "live")  # 新连接重新订阅

        await manager.disconnect("c1", generation=1)  # 旧端点 finally（旧代际）

        assert manager.connections.get("c1") is c2
        assert "c1" in manager.channels.get("live", set())

    @pytest.mark.asyncio
    async def test_final_disconnect_leaves_no_channel_residual(self, manager):
        """最终断开（新代际）后 channels 无残留，空频道被回收。"""
        await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        c = await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        manager.subscribe_to_channel("c1", "live")

        await manager.disconnect("c1", generation=c.generation)

        assert "c1" not in manager.channels.get("live", set())
        assert "live" not in manager.channels  # 空频道删除

    @pytest.mark.asyncio
    async def test_broadcast_cleanup_carries_generation(self, manager):
        """R9-01：广播失败触发的延迟清理携带发送时连接代际——清理期间重连
        后，旧代际清理被拦下，不误拆新连接。"""
        class FailingWebSocket(FakeWebSocket):
            async def send_json(self, data):
                raise RuntimeError("connection closed")

        ws1 = FailingWebSocket()
        c1 = await manager.connect(ws1, client_id="c1", send_connected=False)
        # 广播：发送失败 → 生成延迟清理任务（尚未执行）
        await manager.broadcast({"type": "ping"})
        # 清理任务执行前同 id 重连（新连接健康）
        ws2 = FakeWebSocket()
        c2 = await manager.connect(ws2, client_id="c1", send_connected=False)

        done = await _drain_until(lambda: len(manager._background_tasks) == 0)
        assert done is True

        # 旧代际清理被代际校验拦下：新连接存活
        assert manager.connections.get("c1") is c2
        assert ws2.closed is False


# ================================================================ 既有语义保持（R9 合并并入）
class TestLegacyDisconnectSemantics:
    @pytest.mark.asyncio
    async def test_disconnect_without_generation_cleans_current(self, manager):
        """未携带代际（内部清理路径/外部踢出，如 config.py kick）保持既有
        语义：清理当前登记连接与其频道成员。"""
        await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        manager.subscribe_to_channel("c1", "live")

        await manager.disconnect("c1")

        assert "c1" not in manager.connections
        assert "c1" not in manager.channels.get("live", set())

    @pytest.mark.asyncio
    async def test_disconnect_unknown_client_id_is_noop(self, manager):
        """disconnect 对不存在的 client_id 幂等（不抛异常）。"""
        await manager.disconnect("ghost")
        await manager.disconnect("ghost", generation=42)

    @pytest.mark.asyncio
    async def test_generation_not_reused_after_full_cycle(self, manager):
        """代际取自全局单调序列：整轮断开后重连拿到更大代际，历史残留
        disconnect 无法再命中（无 ABA 复用）。"""
        c1 = await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        await manager.disconnect("c1", generation=c1.generation)

        c2 = await manager.connect(FakeWebSocket(), client_id="c1", send_connected=False)
        assert c2.generation > c1.generation
        # 模拟历史残留 disconnect（旧代际迟到到达）
        await manager.disconnect("c1", generation=c1.generation)
        assert manager.connections.get("c1") is c2


# ================================================================ receive 帧处理（R9 合并并入）
class TestReceiveFrameHandling:
    @pytest.mark.asyncio
    async def test_binary_frame_skipped_activity_refreshed_limited_error(self):
        """二进制帧：跳过 + 刷新 last_activity + 限频回发 UNSUPPORTED_FRAME。"""
        conn = WebSocketConnection(
            FakeWebSocket(frames=[{"bytes": b"\x00\x01"}, {"bytes": b"\x02"},
                                  {"text": json.dumps({"type": "ping"})}]),
            "c1",
        )
        before = conn.last_activity
        await asyncio.sleep(0.01)  # 确保时间可比较

        msg = await conn.receive()

        assert msg == {"type": "ping"}
        assert conn.last_activity > before
        # 两次二进制帧仅回发 1 条 error（限频生效）
        errs = [m for m in conn.websocket.sent if m.get("code") == "UNSUPPORTED_FRAME"]
        assert len(errs) == 1
        assert errs[0]["type"] == "error"
        assert errs[0]["message"] == "不支持二进制帧"

    @pytest.mark.asyncio
    async def test_unsupported_frame_error_rate_limited_window(self):
        """限频窗口（5 秒）内不发第二条；窗口过期后允许再发。"""
        conn = WebSocketConnection(
            FakeWebSocket(frames=[{"bytes": b"\x00"}, {"bytes": b"\x01"},
                                  {"text": json.dumps({"ok": 1})}]),
            "c1",
        )
        await conn.receive()
        assert len(conn.websocket.sent) == 1
        # 人为把上次回发时间拨回 6 秒前 → 窗口过期
        conn._last_unsupported_frame_error_ts = time.monotonic() - 6.0
        # 第二条二进制帧经 conn.receive 内部路径不易直达（首帧已是 dict），
        # 直接驱动限频方法验证窗口逻辑
        await conn._send_unsupported_frame_error()
        assert len(conn.websocket.sent) == 2

    @pytest.mark.asyncio
    async def test_malformed_text_frame_no_error_frame(self):
        """畸形 text 帧仅跳过并刷新活跃，不回发 UNSUPPORTED_FRAME（二进制专属）。"""
        conn = WebSocketConnection(
            FakeWebSocket(frames=[{"text": "not-json"}, {"text": json.dumps({"ok": 1})}]),
            "c1",
        )
        msg = await conn.receive()
        assert msg == {"ok": 1}
        assert conn.websocket.sent == []

    @pytest.mark.asyncio
    async def test_non_dict_json_frame_skipped_with_activity(self):
        """合法 JSON 标量/数组同样跳过且计入活跃（保持返回契约 Dict）。

        注：与 HEAD 的 test_receive_skips_non_dict_json 行为相近，但本例额外
        断言跳过路径不回发任何 error 帧，予以保留。"""
        conn = WebSocketConnection(
            FakeWebSocket(frames=[{"text": "[1,2]"}, {"text": json.dumps({"ok": 1})}]),
            "c1",
        )
        msg = await conn.receive()
        assert msg == {"ok": 1}
        assert conn.websocket.sent == []
