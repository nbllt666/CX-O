"""
server/handlers/tools.py 回归测试
工具处理器：LIST 过滤透传 / CALL 异步调用 / REGISTER 校验与注册
"""
from types import SimpleNamespace

import pytest

import server.core.tools as tools_mod
from server.handlers.tools import register_tools_handlers
from server.protocol.actions import ToolsActions


class FakeToolRegistry:
    def __init__(self):
        self.calls = []
        self.functions = [{"name": "f1"}]
        self.call_result = {"result": "ok"}
        self.registered = SimpleNamespace(name="t1")

    def list_openai_functions(self, **kw):
        self.calls.append(("list", kw))
        return self.functions

    async def call_tool_async(self, name, arguments):
        self.calls.append(("call", name, arguments))
        return self.call_result

    def register(self, **kw):
        self.calls.append(("register", kw))
        return self.registered


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
    register_tools_handlers(mgr)
    return mgr.handlers


@pytest.fixture
def reg():
    return FakeToolRegistry()


def _patch(monkeypatch, reg):
    monkeypatch.setattr(tools_mod, "tool_registry", reg)


def _err(mgr):
    msg = mgr.sent[-1][1]
    assert msg["type"] == "error"
    return msg["error"]["code"], msg["error"]["message"]


class TestToolsHandlers:
    @pytest.mark.asyncio
    async def test_list(self, handlers, mgr, reg, monkeypatch):
        _patch(monkeypatch, reg)
        await handlers[ToolsActions.LIST](
            None, {"request_id": "r1", "data": {"include_builtin": True, "enabled_only": False, "category": "c"}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["action"] == ToolsActions.LIST
        assert msg["request_id"] == "r1"
        assert msg["data"]["tools"] == [{"name": "f1"}]
        kw = reg.calls[0][1]
        assert kw == {"enabled_only": False, "include_builtin": True, "category": "c"}

    @pytest.mark.asyncio
    async def test_list_error(self, handlers, mgr, reg, monkeypatch):
        def bad(**kw):
            raise RuntimeError("list down")
        reg.list_openai_functions = bad
        _patch(monkeypatch, reg)
        await handlers[ToolsActions.LIST](None, {}, "c1")
        code, msg = _err(mgr)
        assert code == "TOOLS_ERROR"
        assert "list down" in msg

    @pytest.mark.asyncio
    async def test_call(self, handlers, mgr, reg, monkeypatch):
        _patch(monkeypatch, reg)
        await handlers[ToolsActions.CALL](None, {"data": {"name": "t1", "arguments": {"a": 1}}}, "c1")
        assert reg.calls[0][1:] == ("t1", {"a": 1})
        assert mgr.sent[-1][1]["data"] == {"result": "ok"}
        assert mgr.sent[-1][1]["action"] == ToolsActions.CALL

    @pytest.mark.asyncio
    async def test_call_error(self, handlers, mgr, reg, monkeypatch):
        async def bad(name, arguments):
            raise RuntimeError("call down")
        reg.call_tool_async = bad
        _patch(monkeypatch, reg)
        await handlers[ToolsActions.CALL](None, {"data": {"name": "t1"}}, "c1")
        code, msg = _err(mgr)
        assert code == "TOOLS_ERROR"
        assert "call down" in msg

    @pytest.mark.asyncio
    async def test_register_success(self, handlers, mgr, reg, monkeypatch):
        _patch(monkeypatch, reg)
        await handlers[ToolsActions.REGISTER](
            None, {"data": {"name": "t1", "parameters": {"type": "object"}, "enabled": True}}, "c1")
        assert mgr.sent[-1][1]["data"] == {"name": "t1", "registered": True}
        kw = reg.calls[0][1]
        assert kw["name"] == "t1"
        assert kw["parameters"] == {"type": "object"}

    @pytest.mark.asyncio
    async def test_register_empty_name(self, handlers, mgr, reg, monkeypatch):
        _patch(monkeypatch, reg)
        await handlers[ToolsActions.REGISTER](None, {"data": {"name": "", "parameters": {"t": "o"}}}, "c1")
        code, msg = _err(mgr)
        assert code == "INVALID_REQUEST"
        assert "name" in msg
        assert reg.calls == []  # 未真正注册

    @pytest.mark.asyncio
    async def test_register_empty_parameters(self, handlers, mgr, reg, monkeypatch):
        _patch(monkeypatch, reg)
        await handlers[ToolsActions.REGISTER](None, {"data": {"name": "t1", "parameters": {}}}, "c1")
        code, msg = _err(mgr)
        assert code == "INVALID_REQUEST"
        assert "parameters" in msg
        assert reg.calls == []

    @pytest.mark.asyncio
    async def test_register_error(self, handlers, mgr, reg, monkeypatch):
        def bad(**kw):
            raise RuntimeError("reg down")
        reg.register = bad
        _patch(monkeypatch, reg)
        await handlers[ToolsActions.REGISTER](None, {"data": {"name": "t1", "parameters": {"t": "o"}}}, "c1")
        code, msg = _err(mgr)
        assert code == "TOOLS_ERROR"
        assert "reg down" in msg