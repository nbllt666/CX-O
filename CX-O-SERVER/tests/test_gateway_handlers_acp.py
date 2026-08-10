"""
server/handlers/acp.py 回归测试
ACP 处理器：CONNECT 注册 agent + 建连 / DISCONNECT 语义一致性与 CONNECTION_NOT_FOUND / CONNECTIONS 列表
"""
import pytest

import server.dependencies as deps
from server.handlers.acp import register_acp_handlers
from server.protocol.actions import ACPActions


class FakeACPMgr:
    def __init__(self):
        self._local_agent_id = "local-1"
        self.calls = []
        self.connections = [{"id": "conn-1", "status": "connected"}]

    async def register_agent(self, agent):
        self.calls.append(("register", agent))
        return agent

    async def create_connection(self, connection):
        self.calls.append(("create", connection))
        return connection

    async def delete_connection(self, connection_id):
        self.calls.append(("delete", connection_id))
        return connection_id in ("conn-1",)

    async def list_connections(self, local_only=True):
        self.calls.append(("list", local_only))
        return self.connections


class FakeManager:
    def __init__(self):
        self.handlers = {}
        self.sent = []

    def register_handler(self, action, handler):
        self.handlers[action] = handler

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))


@pytest.fixture
def mgr():
    return FakeManager()


@pytest.fixture
def handlers(mgr):
    register_acp_handlers(mgr)
    return mgr.handlers


@pytest.fixture
def am():
    return FakeACPMgr()


def _patch(monkeypatch, am):
    monkeypatch.setattr(deps, "get_acp_manager", lambda: am)


def _err(mgr):
    msg = mgr.sent[-1][1]
    assert msg["type"] == "error"
    return msg["error"]["code"], msg["error"]["message"]


class TestACPHendlers:
    @pytest.mark.asyncio
    async def test_connect_success(self, handlers, mgr, am, monkeypatch):
        _patch(monkeypatch, am)
        await handlers[ACPActions.CONNECT](
            None, {"request_id": "r1", "data": {"agent_id": "a1", "agent_name": "AgentA", "host": "127.0.0.1", "port": 9001}}, "c1")
        assert ("register",) in [c[:1] for c in am.calls]
        reg_agent = am.calls[0][1]
        assert reg_agent.id == "a1"
        assert reg_agent.host == "127.0.0.1"
        assert reg_agent.port == 9001
        conn = am.calls[1][1]
        assert conn.local_agent_id == "local-1"
        assert conn.remote_agent_id == "a1"
        assert conn.remote_agent_name == "AgentA"
        assert conn.status == "connected"
        msg = mgr.sent[-1][1]
        assert msg["action"] == ACPActions.CONNECT
        assert msg["data"]["connection_id"] == conn.id
        assert msg["data"]["status"] == "connected"

    @pytest.mark.asyncio
    async def test_connect_defaults(self, handlers, mgr, am, monkeypatch):
        _patch(monkeypatch, am)
        await handlers[ACPActions.CONNECT](None, {"data": {"agent_id": "a2"}}, "c1")
        reg_agent = am.calls[0][1]
        assert reg_agent.port == 0          # 缺省 port=0
        assert reg_agent.capabilities == []  # 缺省 capabilities=[]
        conn = am.calls[1][1]
        assert conn.port == 0

    @pytest.mark.asyncio
    async def test_connect_error(self, handlers, mgr, am, monkeypatch):
        async def bad(agent):
            raise RuntimeError("acp down")
        am.register_agent = bad
        _patch(monkeypatch, am)
        await handlers[ACPActions.CONNECT](None, {"data": {"agent_id": "a1"}}, "c1")
        code, msg = _err(mgr)
        assert code == "ACP_ERROR"
        assert "acp down" in msg

    @pytest.mark.asyncio
    async def test_disconnect_success(self, handlers, mgr, am, monkeypatch):
        _patch(monkeypatch, am)
        await handlers[ACPActions.DISCONNECT](None, {"data": {"connection_id": "conn-1"}}, "c1")
        assert ("delete", "conn-1") in am.calls
        msg = mgr.sent[-1][1]
        assert msg["type"] == "response"
        assert msg["action"] == ACPActions.DISCONNECT
        assert msg["data"] == {"success": True}

    @pytest.mark.asyncio
    async def test_disconnect_not_found(self, handlers, mgr, am, monkeypatch):
        _patch(monkeypatch, am)
        await handlers[ACPActions.DISCONNECT](None, {"data": {"connection_id": "nope"}}, "c1")
        code, msg = _err(mgr)
        assert code == "CONNECTION_NOT_FOUND"
        assert "nope" in msg

    @pytest.mark.asyncio
    async def test_disconnect_error(self, handlers, mgr, am, monkeypatch):
        async def bad(cid):
            raise RuntimeError("del down")
        am.delete_connection = bad
        _patch(monkeypatch, am)
        await handlers[ACPActions.DISCONNECT](None, {"data": {"connection_id": "conn-1"}}, "c1")
        code, msg = _err(mgr)
        assert code == "ACP_ERROR"
        assert "del down" in msg

    @pytest.mark.asyncio
    async def test_connections_local_only_default(self, handlers, mgr, am, monkeypatch):
        _patch(monkeypatch, am)
        await handlers[ACPActions.CONNECTIONS](None, {"data": {}}, "c1")
        # 缺省 local_only 默认 True
        assert ("list", True) in am.calls
        assert mgr.sent[-1][1]["data"] == {"connections": am.connections}

    @pytest.mark.asyncio
    async def test_connections_all(self, handlers, mgr, am, monkeypatch):
        _patch(monkeypatch, am)
        await handlers[ACPActions.CONNECTIONS](None, {"data": {"local_only": False}}, "c1")
        assert ("list", False) in am.calls

    @pytest.mark.asyncio
    async def test_connections_error(self, handlers, mgr, am, monkeypatch):
        async def bad(local_only=True):
            raise RuntimeError("list down")
        am.list_connections = bad
        _patch(monkeypatch, am)
        await handlers[ACPActions.CONNECTIONS](None, {"data": {}}, "c1")
        code, msg = _err(mgr)
        assert code == "ACP_ERROR"
        assert "list down" in msg