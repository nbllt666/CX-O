"""server.api.routers.cxfc 路由测试。

模块级 set_cxfc_manager/set_cxfc_discovery 注入假 manager + 假 discovery。
覆盖 register/heartbeat/event/discover/skills/connect/disconnect/list/refresh/call 及异常映射。

运行：python -m pytest tests/test_cxfc_router.py -v
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import cxfc as cxfc_router_mod


class FakePlugin:
    def __init__(self, plugin_id="p1"):
        self.plugin_id = plugin_id


class FakeSkillRegistry:
    def get_all_skills(self):
        return [{"id": "s1"}]


class FakeCXFCManager:
    def __init__(self):
        self.calls: dict = {}

    async def register_plugin(self, request):
        self.calls["register"] = request
        return FakePlugin()

    async def update_heartbeat(self, plugin_id, port):
        return plugin_id in ("p1",)

    async def push_event(self, event):
        self.calls["event"] = event

    def get_plugins(self):
        return [{"id": "p1"}]

    def get_skill_registry(self):
        return FakeSkillRegistry()

    async def connect_to_plugin(self, host, port):
        return FakePlugin("p2")

    async def disconnect_plugin(self, plugin_id, remove_persistent=True):
        self.calls["disconnect"] = plugin_id

    async def refresh_plugin(self, plugin_id):
        return FakePlugin(plugin_id) if plugin_id == "p1" else None

    async def call_tool(self, plugin_id, tool, arguments):
        return {"tool": tool}


class FakeDiscovery:
    async def scan_network(self):
        return [{"id": "n1"}]


@pytest.fixture
def client(monkeypatch):
    mm = FakeCXFCManager()
    cxfc_router_mod.set_cxfc_manager(mm)
    cxfc_router_mod.set_cxfc_discovery(FakeDiscovery())
    app = FastAPI()
    app.include_router(cxfc_router_mod.router)
    return TestClient(app, raise_server_exceptions=False), mm


class TestRegister:
    def test_success(self, client):
        c, mm = client
        r = c.post("/cxfc/register", json={"host": "127.0.0.1", "port": 9000, "name": "p"})
        assert r.status_code == 200
        assert r.json()["plugin_id"] == "p1"

    def test_error_500(self, client):
        c, mm = client
        async def _f(req):
            raise ValueError("boom")
        mm.register_plugin = _f
        r = c.post("/cxfc/register", json={"host": "127.0.0.1", "port": 9000})
        assert r.status_code == 500


class TestHeartbeat:
    def test_success(self, client):
        c, mm = client
        r = c.post("/cxfc/heartbeat", json={"plugin_id": "p1", "port": 9000})
        assert r.status_code == 200
        assert r.json()["status"] == "alive"

    def test_not_found_404(self, client):
        c, mm = client
        r = c.post("/cxfc/heartbeat", json={"plugin_id": "nope", "port": 9000})
        assert r.status_code == 404

    def test_error_500(self, client):
        c, mm = client
        async def _f(*a, **k):
            raise RuntimeError("boom")
        mm.update_heartbeat = _f
        r = c.post("/cxfc/heartbeat", json={"plugin_id": "p1", "port": 9000})
        assert r.status_code == 500


class TestEvent:
    def test_push(self, client):
        c, mm = client
        r = c.post("/cxfc/event/push", json={"from_port": 9000, "event_type": "skill_executed", "data": {}})
        assert r.status_code == 200
        assert r.json()["status"] == "received"
        assert mm.calls["event"].event_type == "skill_executed"


class TestDiscover:
    def test_no_scan(self, client):
        c, mm = client
        r = c.get("/cxfc/discover")
        assert r.status_code == 200
        assert r.json()["plugins"][0]["id"] == "p1"
        assert "network_plugins" not in r.json()

    def test_scan(self, client):
        c, mm = client
        r = c.get("/cxfc/discover", params={"scan": "true"})
        assert r.status_code == 200
        assert r.json()["network_plugins"][0]["id"] == "n1"

    def test_scan_no_discovery(self, client, monkeypatch):
        cxfc_router_mod.set_cxfc_discovery(None)
        c, mm = client
        r = c.get("/cxfc/discover", params={"scan": "true"})
        assert r.status_code == 200
        assert r.json()["network_plugins"] == []

    def test_error_500(self, client):
        c, mm = client
        mm.get_plugins = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        r = c.get("/cxfc/discover")
        assert r.status_code == 500


class TestSkills:
    def test_success(self, client):
        c, mm = client
        r = c.get("/cxfc/skills")
        assert r.status_code == 200
        assert r.json()["skills"][0]["id"] == "s1"


class TestConnect:
    def test_success(self, client):
        c, mm = client
        r = c.post("/cxfc/connect", json={"host": "127.0.0.1", "port": 9000})
        assert r.status_code == 200
        assert r.json()["plugin"]["plugin_id"] == "p2"

    def test_unreachable_503(self, client):
        c, mm = client
        async def _f(host, port):
            return None
        mm.connect_to_plugin = _f
        r = c.post("/cxfc/connect", json={"host": "127.0.0.1", "port": 9999})
        assert r.status_code == 503


class TestPlugins:
    def test_disconnect(self, client):
        c, mm = client
        r = c.delete("/cxfc/plugins/p1")
        assert r.status_code == 200
        assert mm.calls["disconnect"] == "p1"

    def test_list(self, client):
        c, mm = client
        r = c.get("/cxfc/plugins")
        assert r.status_code == 200
        assert r.json()["plugins"][0]["id"] == "p1"

    def test_refresh_success(self, client):
        c, mm = client
        r = c.post("/cxfc/plugins/p1/refresh")
        assert r.status_code == 200
        assert r.json()["plugin"]["plugin_id"] == "p1"

    def test_refresh_404(self, client):
        c, mm = client
        r = c.post("/cxfc/plugins/nope/refresh")
        assert r.status_code == 404

    def test_call_tool(self, client):
        c, mm = client
        r = c.post("/cxfc/plugins/p1/call", json={"tool": "t", "arguments": {"a": 1}})
        assert r.status_code == 200
        assert r.json()["result"]["tool"] == "t"

    def test_call_tool_error_500(self, client):
        c, mm = client
        async def _f(*a, **k):
            raise RuntimeError("boom")
        mm.call_tool = _f
        r = c.post("/cxfc/plugins/p1/call", json={"tool": "t"})
        assert r.status_code == 500