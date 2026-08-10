"""
server/handlers/system.py 回归测试
系统处理器：健康检查 / 系统状态汇总（各服务可用性与降级）
"""
from types import SimpleNamespace

import pytest

import server.handlers.system as system_mod
from server.handlers.system import register_system_handlers
from server.protocol.actions import SystemActions


class FakeManager:
    def __init__(self):
        self.handlers = {}
        self.sent = []
        self.stats = {"connections": 3}

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
def handlers(mgr):
    register_system_handlers(mgr)
    return mgr.handlers


def _last_sent(mgr):
    return mgr.sent[-1][1]


class TestSystemHealth:
    @pytest.mark.asyncio
    async def test_health_success(self, handlers, mgr, monkeypatch):
        monkeypatch.setattr(
            system_mod, "health_checker",
            SimpleNamespace(get_all_status=lambda: {"asr": "ok", "tts": "ok"}),
        )
        await handlers[SystemActions.HEALTH](None, {"request_id": "r1"}, "c1")
        msg = _last_sent(mgr)
        assert msg["type"] == "response"
        assert msg["action"] == SystemActions.HEALTH
        assert msg["request_id"] == "r1"
        assert msg["data"] == {"asr": "ok", "tts": "ok"}

    @pytest.mark.asyncio
    async def test_health_error_sends_error(self, handlers, mgr, monkeypatch):
        def boom():
            raise RuntimeError("health down")

        monkeypatch.setattr(system_mod, "health_checker", SimpleNamespace(get_all_status=boom))
        await handlers[SystemActions.HEALTH](None, {"request_id": "r1"}, "c1")
        msg = _last_sent(mgr)
        assert msg["type"] == "error"
        assert msg["error"]["code"] == "SYSTEM_ERROR"


class TestSystemStatus:
    def _patch_all_deps(self, monkeypatch):
        import server.dependencies as deps
        monkeypatch.setattr(deps, "get_memory_manager", lambda: SimpleNamespace(get_statistics=lambda: {"m": 1}))
        monkeypatch.setattr(deps, "get_acp_manager", lambda: SimpleNamespace(**{"get_statistics": _async({"a": 1})}))
        monkeypatch.setattr(deps, "get_mcp_manager", lambda: SimpleNamespace(get_stats=lambda: {"mc": 1}))
        monkeypatch.setattr(deps, "get_llm_client", lambda: SimpleNamespace(model_name="intellect"))
        monkeypatch.setattr(deps, "get_model_router", lambda: SimpleNamespace(get_all_models_info=lambda: {"mm": 1}))
        import server.core.tools
        monkeypatch.setattr(server.core.tools, "tool_registry", SimpleNamespace(get_tool_stats=lambda: {"t": 1}))
        import server.core.plugins.manager as pm
        monkeypatch.setattr(pm, "get_plugin_manager", lambda: SimpleNamespace(get_stats=lambda: {"p": 1}))

    @pytest.mark.asyncio
    async def test_status_all_available(self, handlers, mgr, monkeypatch):
        self._patch_all_deps(monkeypatch)
        await handlers[SystemActions.STATUS](None, {"request_id": "r1"}, "c1")
        data = _last_sent(mgr)["data"]
        assert data["gateway"] == {"connections": 3}
        assert data["services"]["memory"]["available"] is True
        assert data["services"]["acp"]["available"] is True
        assert data["services"]["mcp"]["available"] is True
        assert data["services"]["llm"] == {"available": True, "model": "intellect"}
        assert data["services"]["model_router"]["available"] is True
        assert data["services"]["tools"]["available"] is True
        assert data["services"]["plugins"]["available"] is True

    @pytest.mark.asyncio
    async def test_status_memory_unavailable(self, handlers, mgr, monkeypatch):
        import server.dependencies as deps
        monkeypatch.setattr(deps, "get_memory_manager", _raise("no memory"))
        monkeypatch.setattr(deps, "get_acp_manager", lambda: SimpleNamespace(**{"get_statistics": _async({"a": 1})}))
        monkeypatch.setattr(deps, "get_mcp_manager", lambda: SimpleNamespace(get_stats=lambda: {"mc": 1}))
        monkeypatch.setattr(deps, "get_llm_client", lambda: SimpleNamespace(model_name="intellect"))
        monkeypatch.setattr(deps, "get_model_router", lambda: SimpleNamespace(get_all_models_info=lambda: {"mm": 1}))
        import server.core.tools
        monkeypatch.setattr(server.core.tools, "tool_registry", SimpleNamespace(get_tool_stats=lambda: {"t": 1}))
        import server.core.plugins.manager as pm
        monkeypatch.setattr(pm, "get_plugin_manager", lambda: SimpleNamespace(get_stats=lambda: {"p": 1}))
        await handlers[SystemActions.STATUS](None, {}, "c1")
        data = _last_sent(mgr)["data"]
        assert data["services"]["memory"] == {"available": False}
        assert data["services"]["acp"]["available"] is True  # 其余正常

    @pytest.mark.asyncio
    async def test_status_gateway_stats(self, handlers, mgr, monkeypatch):
        self._patch_all_deps(monkeypatch)
        await handlers[SystemActions.STATUS](None, {}, "c1")
        assert _last_sent(mgr)["data"]["gateway"] == {"connections": 3}


def _async(value):
    async def inner():
        return value
    return inner


def _raise(msg):
    def inner(*a, **k):
        raise RuntimeError(msg)
    return inner