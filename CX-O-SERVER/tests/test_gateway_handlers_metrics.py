"""
server/handlers/metrics.py 回归测试
监控处理器：memory/acp/mcp/tools/plugins 各服务指标汇总与降级
"""
from types import SimpleNamespace

import pytest

import server.handlers.metrics as metrics_mod
from server.handlers.metrics import register_metrics_handlers
from server.protocol.actions import MetricsActions


class FakeManager:
    def __init__(self):
        self.handlers = {}
        self.sent = []
        self.stats = {"connections": 5}

    def register_handler(self, action, handler):
        self.handlers[action] = handler

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))

    def get_stats(self):
        return self.stats


@pytest.fixture
def mgr():
    return FakeManager()


@pytest.fixture
def handler(mgr):
    register_metrics_handlers(mgr)
    return mgr.handlers[MetricsActions.GET]


def _last_data(mgr):
    return mgr.sent[-1][1]["data"]


def _patch_all_deps(monkeypatch):
    import server.dependencies as deps
    monkeypatch.setattr(deps, "get_memory_manager", lambda: SimpleNamespace(get_statistics=lambda: {"m": 1}))
    monkeypatch.setattr(deps, "get_acp_manager", lambda: SimpleNamespace(**{"get_statistics": _async({"a": 1})}))
    monkeypatch.setattr(deps, "get_mcp_manager", lambda: SimpleNamespace(get_stats=lambda: {"mc": 1}))
    import server.core.tools
    monkeypatch.setattr(server.core.tools, "tool_registry", SimpleNamespace(get_tool_stats=lambda: {"t": 1}))
    import server.core.plugins.manager as pm
    monkeypatch.setattr(pm, "get_plugin_manager", lambda: SimpleNamespace(get_stats=lambda: {"p": 1}))


class TestMetricsGet:
    @pytest.mark.asyncio
    async def test_all_available(self, handler, mgr, monkeypatch):
        _patch_all_deps(monkeypatch)
        await handler(None, {"request_id": "r1"}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["type"] == "response"
        assert msg["action"] == MetricsActions.GET
        assert msg["request_id"] == "r1"
        data = msg["data"]
        assert data["memory"] == {"m": 1}
        assert data["acp"] == {"a": 1}
        assert data["mcp"] == {"mc": 1}
        assert data["tools"] == {"t": 1}
        assert data["plugins"] == {"p": 1}
        assert data["gateway"] == {"connections": 5}

    @pytest.mark.asyncio
    async def test_memory_degrades(self, handler, mgr, monkeypatch):
        import server.dependencies as deps
        def boom():
            raise RuntimeError("no memory")
        monkeypatch.setattr(deps, "get_memory_manager", boom)
        monkeypatch.setattr(deps, "get_acp_manager", lambda: SimpleNamespace(**{"get_statistics": _async({"a": 1})}))
        monkeypatch.setattr(deps, "get_mcp_manager", lambda: SimpleNamespace(get_stats=lambda: {"mc": 1}))
        import server.core.tools
        monkeypatch.setattr(server.core.tools, "tool_registry", SimpleNamespace(get_tool_stats=lambda: {"t": 1}))
        import server.core.plugins.manager as pm
        monkeypatch.setattr(pm, "get_plugin_manager", lambda: SimpleNamespace(get_stats=lambda: {"p": 1}))
        await handler(None, {}, "c1")
        data = _last_data(mgr)
        assert data["memory"] == {"error": "unavailable"}
        assert data["acp"] == {"a": 1}  # 其余正常

    @pytest.mark.asyncio
    async def test_all_unavailable(self, handler, mgr, monkeypatch):
        import server.dependencies as deps
        def boom(*a, **k):
            raise RuntimeError("down")
        monkeypatch.setattr(deps, "get_memory_manager", boom)
        monkeypatch.setattr(deps, "get_acp_manager", boom)
        monkeypatch.setattr(deps, "get_mcp_manager", boom)
        import server.core.tools
        monkeypatch.setattr(server.core.tools, "tool_registry", SimpleNamespace(get_tool_stats=boom))
        import server.core.plugins.manager as pm
        monkeypatch.setattr(pm, "get_plugin_manager", boom)
        await handler(None, {}, "c1")
        data = _last_data(mgr)
        assert all(data[k] == {"error": "unavailable"} for k in ["memory", "acp", "mcp", "tools", "plugins"])
        assert data["gateway"] == {"connections": 5}


def _async(value):
    async def inner():
        return value
    return inner