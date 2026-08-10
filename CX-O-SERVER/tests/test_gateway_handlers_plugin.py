"""
server/handlers/plugin.py 回归测试
插件处理器：REGISTER 加载与启用 / HEARTBEAT 存活检测 / LIST 列表（enabled_only 分支）
"""
from types import SimpleNamespace

import pytest

import server.core.plugins.manager as pm
from server.handlers.plugin import register_plugin_handlers
from server.protocol.actions import PluginActions


def make_plugin(pid="p1", enabled=True):
    metadata = SimpleNamespace(id=pid, name="Plugin", version="1.0.0", description="desc")
    return SimpleNamespace(metadata=metadata, enabled=enabled)


class FakePluginMgr:
    def __init__(self):
        self.calls = []
        self.plugin = make_plugin()
        self.enabled_plugins = [make_plugin("e1")]
        self.all_plugins = [make_plugin("e1"), make_plugin("d1", enabled=False)]

    def load_plugin(self, plugin_id):
        self.calls.append(("load", plugin_id))
        return self.plugin

    def enable_plugin(self, plugin_id):
        self.calls.append(("enable", plugin_id))

    def get_plugin(self, plugin_id):
        self.calls.append(("get", plugin_id))
        return self.plugin

    def get_enabled_plugins(self):
        self.calls.append(("enabled",))
        return self.enabled_plugins

    def get_all_plugins(self):
        self.calls.append(("all",))
        return self.all_plugins


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
    register_plugin_handlers(mgr)
    return mgr.handlers


@pytest.fixture
def pmgr():
    return FakePluginMgr()


def _patch(monkeypatch, pmgr):
    monkeypatch.setattr(pm, "get_plugin_manager", lambda: pmgr)


def _err(mgr):
    msg = mgr.sent[-1][1]
    assert msg["type"] == "error"
    return msg["error"]["code"], msg["error"]["message"]


class TestPluginHandlers:
    @pytest.mark.asyncio
    async def test_register_success_enables(self, handlers, mgr, pmgr, monkeypatch):
        _patch(monkeypatch, pmgr)
        await handlers[PluginActions.REGISTER](
            None, {"request_id": "r1", "data": {"plugin_id": "p1", "enabled": True}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["action"] == PluginActions.REGISTER
        assert msg["data"] == {"plugin_id": "p1", "registered": True}
        assert ("load", "p1") in pmgr.calls
        assert ("enable", "p1") in pmgr.calls

    @pytest.mark.asyncio
    async def test_register_not_found(self, handlers, mgr, pmgr, monkeypatch):
        pmgr.plugin = None
        _patch(monkeypatch, pmgr)
        await handlers[PluginActions.REGISTER](None, {"data": {"plugin_id": "p1"}}, "c1")
        assert mgr.sent[-1][1]["data"] == {"plugin_id": "p1", "registered": False}
        assert ("enable", "p1") not in pmgr.calls

    @pytest.mark.asyncio
    async def test_register_disabled_skips_enable(self, handlers, mgr, pmgr, monkeypatch):
        _patch(monkeypatch, pmgr)
        await handlers[PluginActions.REGISTER](None, {"data": {"plugin_id": "p1", "enabled": False}}, "c1")
        assert mgr.sent[-1][1]["data"] == {"plugin_id": "p1", "registered": True}
        assert ("enable", "p1") not in pmgr.calls

    @pytest.mark.asyncio
    async def test_register_error(self, handlers, mgr, monkeypatch):
        def boom():
            raise RuntimeError("reg down")
        monkeypatch.setattr(pm, "get_plugin_manager", boom)
        await handlers[PluginActions.REGISTER](None, {}, "c1")
        code, msg = _err(mgr)
        assert code == "PLUGIN_ERROR"
        assert "reg down" in msg

    @pytest.mark.asyncio
    async def test_heartbeat_alive(self, handlers, mgr, pmgr, monkeypatch):
        _patch(monkeypatch, pmgr)
        await handlers[PluginActions.HEARTBEAT](None, {"data": {"plugin_id": "p1"}}, "c1")
        assert mgr.sent[-1][1]["data"] == {"plugin_id": "p1", "alive": True}

    @pytest.mark.asyncio
    async def test_heartbeat_dead(self, handlers, mgr, pmgr, monkeypatch):
        pmgr.plugin = None
        _patch(monkeypatch, pmgr)
        await handlers[PluginActions.HEARTBEAT](None, {"data": {"plugin_id": "p1"}}, "c1")
        assert mgr.sent[-1][1]["data"] == {"plugin_id": "p1", "alive": False}

    @pytest.mark.asyncio
    async def test_list_enabled_only(self, handlers, mgr, pmgr, monkeypatch):
        _patch(monkeypatch, pmgr)
        await handlers[PluginActions.LIST](None, {"data": {"enabled_only": True}}, "c1")
        assert ("enabled",) in pmgr.calls
        plugins = mgr.sent[-1][1]["data"]["plugins"]
        assert plugins == [{
            "id": "e1", "name": "Plugin", "version": "1.0.0",
            "enabled": True, "description": "desc",
        }]

    @pytest.mark.asyncio
    async def test_list_all(self, handlers, mgr, pmgr, monkeypatch):
        _patch(monkeypatch, pmgr)
        await handlers[PluginActions.LIST](None, {"data": {}}, "c1")
        assert ("all",) in pmgr.calls
        assert len(mgr.sent[-1][1]["data"]["plugins"]) == 2

    @pytest.mark.asyncio
    async def test_list_error(self, handlers, mgr, monkeypatch):
        def boom():
            raise RuntimeError("list down")
        monkeypatch.setattr(pm, "get_plugin_manager", boom)
        await handlers[PluginActions.LIST](None, {}, "c1")
        code, msg = _err(mgr)
        assert code == "PLUGIN_ERROR"
        assert "list down" in msg