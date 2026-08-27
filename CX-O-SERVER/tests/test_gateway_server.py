"""server.gateway（WebSocket server + config）单元测试。

隔离真实 WebSocket / httpx 网络与全局单例，覆盖：

- handle_ping / handle_system_health：消息处理与响应构造
- websocket_handler：PING / HEALTH / handler 分发 / 未知 action / 非法 JSON 路由

运行：python -m pytest tests/test_gateway_server.py -v
"""
import asyncio
import json

import pytest

from server.gateway import server as gateway_server
from server.protocol.message import MessageType, create_pong


# ================================================================ fake 依赖
class FakeWebSocket:
    """模拟 FastAPI WebSocket：记录发送内容，回放接收序列。"""

    def __init__(self, receive_events=None):
        # receive 返回的 dict 序列（含 type: text / bytes / disconnect）
        self._events = list(receive_events or [])
        self.sent = []

    async def receive_text(self):
        for i, ev in enumerate(self._events):
            if ev.get("type") == "text":
                return self._events.pop(i)["text"]
        raise WebSocketDisconnectLike()

    async def receive(self):
        if not self._events:
            raise WebSocketDisconnectLike()
        return self._events.pop(0)

    async def send_json(self, data):
        self.sent.append(data)

    async def send_text(self, text):
        self.sent.append(text)

    def get_sent_json(self):
        return [json.loads(s) if isinstance(s, str) else s for s in self.sent]


class FakeWebSocketManager:
    """内存版 ws_manager：捕获 send_message / connect / disconnect / handler。"""

    def __init__(self):
        self.sent = []
        self.handlers = {}
        self.connected = []
        self.disconnected = []

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))

    async def connect(self, websocket, client_id, send_connected=False):
        self.connected.append(client_id)

    async def disconnect(self, client_id):
        self.disconnected.append(client_id)

    def get_handler(self, action):
        return self.handlers.get(action)

    async def handle_message(self, client_id, message):
        self.sent.append((client_id, ("fallback", message)))


class WebSocketDisconnectLike(Exception):
    pass


@pytest.fixture(autouse=True)
def _patch_ws_manager(monkeypatch):
    """将全局 ws_manager 替换为 fake，并将 WebSocketDisconnect 映射到本地异常。"""
    fake = FakeWebSocketManager()
    monkeypatch.setattr(gateway_server, "ws_manager", fake)
    return fake


# ================================================================ handle_ping
class TestHandlePing:
    @pytest.mark.asyncio
    async def test_ping_sends_pong(self, _patch_ws_manager):
        ws = FakeWebSocket()
        await gateway_server.handle_ping(ws, {"timestamp": 123.0}, "c1")
        assert _patch_ws_manager.sent[0][0] == "c1"
        msg = _patch_ws_manager.sent[0][1]
        assert msg["type"] == MessageType.PONG.value
        assert msg["timestamp"] == 123.0

    @pytest.mark.asyncio
    async def test_ping_default_timestamp(self, _patch_ws_manager):
        ws = FakeWebSocket()
        await gateway_server.handle_ping(ws, {}, "c1")
        msg = _patch_ws_manager.sent[0][1]
        assert msg["type"] == MessageType.PONG.value


# ================================================================ handle_system_health
class TestHandleSystemHealth:
    @pytest.mark.asyncio
    async def test_health_builds_response(self, _patch_ws_manager, monkeypatch):
        from server.gateway.health import health_checker
        monkeypatch.setattr(
            gateway_server, "health_checker",
            _FakeHealth(services={"asr": {"status": "healthy"}}),
        )
        ws = FakeWebSocket()
        await gateway_server.handle_system_health(ws, {"request_id": "r1"}, "c1")
        client_id, msg = _patch_ws_manager.sent[0]
        assert client_id == "c1"
        assert msg["request_id"] == "r1"
        assert msg["data"]["services"]["asr"]["status"] == "healthy"


class _FakeHealth:
    def __init__(self, services):
        self._services = services

    def get_all_status(self):
        # 与真实 health_checker.get_all_status() 返回结构一致
        return {"services": self._services, "timestamp": 0}


# ================================================================ websocket_handler
class TestWebsocketHandler:
    @pytest.mark.asyncio
    async def test_health_action_routes(self, _patch_ws_manager, monkeypatch):
        monkeypatch.setattr(
            gateway_server, "health_checker",
            _FakeHealth({"services": {}}),
        )
        ws = FakeWebSocket([
            {"type": "text", "text": json.dumps(
                {"type": "request", "action": "system.health", "request_id": "rid"})},
        ])
        await gateway_server.websocket_handler(ws, "c1")
        assert _patch_ws_manager.sent and _patch_ws_manager.sent[0][1]["request_id"] == "rid"

    @pytest.mark.asyncio
    async def test_ping_routes(self, _patch_ws_manager):
        ws = FakeWebSocket([
            {"type": "text", "text": json.dumps(
                {"type": "ping", "timestamp": 5})},
        ])
        await gateway_server.websocket_handler(ws, "c1")
        msg = _patch_ws_manager.sent[0][1]
        assert msg["type"] == MessageType.PONG.value

    @pytest.mark.asyncio
    async def test_registered_handler_route(self, _patch_ws_manager):
        async def my_handler(websocket, message, client_id):
            await _patch_ws_manager.send_message(client_id, {"type": "custom", "ok": True})

        _patch_ws_manager.handlers["custom.action"] = my_handler
        ws = FakeWebSocket([
            {"type": "text", "text": json.dumps(
                {"type": "request", "action": "custom.action", "request_id": "r"})},
        ])
        await gateway_server.websocket_handler(ws, "c1")
        assert _patch_ws_manager.sent[0][1]["ok"] is True

    @pytest.mark.asyncio
    async def test_handler_error_sends_generic_error(self, _patch_ws_manager):
        async def bad_handler(websocket, message, client_id):
            raise RuntimeError("boom")

        _patch_ws_manager.handlers["bad.action"] = bad_handler
        ws = FakeWebSocket([
            {"type": "text", "text": json.dumps(
                {"type": "request", "action": "bad.action", "request_id": "r"})},
        ])
        await gateway_server.websocket_handler(ws, "c1")
        msg = _patch_ws_manager.sent[0][1]
        assert msg["type"] == MessageType.ERROR.value
        assert "内部错误" in msg["error"]["message"]

    @pytest.mark.asyncio
    async def test_invalid_json_sends_error(self, _patch_ws_manager):
        ws = FakeWebSocket([{"type": "text", "text": "{not json"}])
        await gateway_server.websocket_handler(ws, "c1")
        msg = _patch_ws_manager.sent[0][1]
        assert msg["type"] == MessageType.ERROR.value
        assert msg["error"]["code"] == "INVALID_JSON"

    @pytest.mark.asyncio
    async def test_unknown_action_sends_unified_error(self, _patch_ws_manager):
        # 无 type 且 action 未注册 → 命中 else 分支，经 ws_manager 发送统一错误结构（B2 修复）
        ws = FakeWebSocket([{"type": "text", "text": json.dumps(
            {"action": "no.such.action"})}])
        await gateway_server.websocket_handler(ws, "c1")
        assert _patch_ws_manager.sent, "应通过 ws_manager.send_message 下发统一错误"
        msg = _patch_ws_manager.sent[0][1]
        assert msg["type"] == MessageType.ERROR.value
        assert msg["error"]["code"] == "UNKNOWN_ACTION"
        assert "未知操作" in msg["error"]["message"]

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self, _patch_ws_manager):
        # 无 text 事件 → 直接抛 disconnect → 触发 disconnect 清理
        ws = FakeWebSocket([])
        await gateway_server.websocket_handler(ws, "c1")
        assert "c1" in _patch_ws_manager.disconnected