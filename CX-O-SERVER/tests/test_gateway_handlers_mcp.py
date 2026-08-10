"""
server/handlers/mcp.py 回归测试
MCP 处理器：CONNECT 校验与 auto_start / TOOLS 单服务器与聚合 / CALL 调用
"""
import pytest

import server.dependencies as deps
from server.handlers.mcp import register_mcp_handlers
from server.protocol.actions import MCPActions


class FakeMCPMgr:
    def __init__(self):
        self.calls = []
        self.server_info = {"name": "s1", "status": "created"}
        self.tools = [{"name": "t1"}]
        self.call_result = {"result": "ok"}

    async def add_server(self, **kw):
        self.calls.append(("add", kw))
        return self.server_info

    async def start_server(self, name):
        self.calls.append(("start", name))

    async def get_tools(self, server_name):
        self.calls.append(("get_tools", server_name))
        return self.tools

    async def list_servers(self):
        self.calls.append(("list",))
        return [{"name": "s1"}, {"details": "no-name"}]

    async def call_tool(self, **kw):
        self.calls.append(("call", kw))
        return self.call_result


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
    register_mcp_handlers(mgr)
    return mgr.handlers


@pytest.fixture
def mm():
    return FakeMCPMgr()


def _patch(monkeypatch, mm):
    monkeypatch.setattr(deps, "get_mcp_manager", lambda: mm)


def _err(mgr):
    msg = mgr.sent[-1][1]
    assert msg["type"] == "error"
    return msg["error"]["code"], msg["error"]["message"]


class TestMCPHandlers:
    @pytest.mark.asyncio
    async def test_connect_success(self, handlers, mgr, mm, monkeypatch):
        _patch(monkeypatch, mm)
        await handlers[MCPActions.CONNECT](
            None, {"request_id": "r1", "data": {"name": "s1", "command": "cmd", "args": ["a"]}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["action"] == MCPActions.CONNECT
        assert msg["data"] == {"name": "s1", "status": "created"}
        kw = mm.calls[0][1]
        assert kw["name"] == "s1"
        assert kw["command"] == "cmd"
        assert kw["args"] == ["a"]
        assert ("start", "s1") not in mm.calls  # auto_start 缺省不启动

    @pytest.mark.asyncio
    async def test_connect_auto_start(self, handlers, mgr, mm, monkeypatch):
        _patch(monkeypatch, mm)
        await handlers[MCPActions.CONNECT](None, {"data": {"name": "s1", "auto_start": True}}, "c1")
        assert ("start", "s1") in mm.calls

    @pytest.mark.asyncio
    async def test_connect_empty_name(self, handlers, mgr, mm, monkeypatch):
        _patch(monkeypatch, mm)
        await handlers[MCPActions.CONNECT](None, {"data": {"name": ""}}, "c1")
        code, msg = _err(mgr)
        assert code == "INVALID_REQUEST"
        assert "Missing server name" in msg
        assert mm.calls == []  # 未真正 add_server

    @pytest.mark.asyncio
    async def test_connect_error(self, handlers, mgr, mm, monkeypatch):
        async def bad(**kw):
            raise RuntimeError("conn down")
        mm.add_server = bad
        _patch(monkeypatch, mm)
        await handlers[MCPActions.CONNECT](None, {"data": {"name": "s1"}}, "c1")
        code, msg = _err(mgr)
        assert code == "MCP_ERROR"
        assert "conn down" in msg

    @pytest.mark.asyncio
    async def test_tools_specific_server(self, handlers, mgr, mm, monkeypatch):
        _patch(monkeypatch, mm)
        await handlers[MCPActions.TOOLS](None, {"data": {"server_name": "s1"}}, "c1")
        assert ("get_tools", "s1") in mm.calls
        assert mgr.sent[-1][1]["data"] == {"tools": [{"name": "t1"}]}

    @pytest.mark.asyncio
    async def test_tools_aggregate_skips_no_name(self, handlers, mgr, mm, monkeypatch):
        _patch(monkeypatch, mm)
        await handlers[MCPActions.TOOLS](None, {"data": {}}, "c1")
        # 两个 server，其中无 name 的被防御性跳过 → 只 get_tools 一次
        assert ("list",) in mm.calls
        assert mm.calls.count(("get_tools", "s1")) == 1
        tools = mgr.sent[-1][1]["data"]["tools"]
        assert tools == [{"name": "t1"}]

    @pytest.mark.asyncio
    async def test_tools_error(self, handlers, mgr, mm, monkeypatch):
        async def bad(name):
            raise RuntimeError("tools down")
        mm.get_tools = bad
        _patch(monkeypatch, mm)
        await handlers[MCPActions.TOOLS](None, {"data": {"server_name": "s1"}}, "c1")
        code, msg = _err(mgr)
        assert code == "MCP_ERROR"
        assert "tools down" in msg

    @pytest.mark.asyncio
    async def test_call(self, handlers, mgr, mm, monkeypatch):
        _patch(monkeypatch, mm)
        await handlers[MCPActions.CALL](
            None, {"data": {"server_name": "s1", "tool_name": "t1", "arguments": {"a": 1}}}, "c1")
        kw = mm.calls[0][1]
        assert kw == {"server_name": "s1", "tool_name": "t1", "arguments": {"a": 1}}
        assert mgr.sent[-1][1]["data"] == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_call_error(self, handlers, mgr, mm, monkeypatch):
        async def bad(**kw):
            raise RuntimeError("call down")
        mm.call_tool = bad
        _patch(monkeypatch, mm)
        await handlers[MCPActions.CALL](None, {"data": {"server_name": "s1"}}, "c1")
        code, msg = _err(mgr)
        assert code == "MCP_ERROR"
        assert "call down" in msg