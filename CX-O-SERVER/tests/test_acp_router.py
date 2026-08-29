"""server.api.routers.acp 路由测试。

set_service_state 注入假 acp_manager + monkeypatch server.core.acp.discover.ACPLanDiscovery /
server.core.acp.group.ACPGroupManager。覆盖：
- discover / agents（list/register/patch/delete） / connect（connect/disconnect/list）
- groups（create/list/join/leave） / send / receive / send-group / messages / stats
- v3.1.0：cleanup resources / update port

运行：python -m pytest tests/test_acp_router.py -v
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.dependencies import ServiceState, set_service_state
from server.api.routers import acp as acp_router_mod
from server.api.routers.admin import verify_admin_api_key
from server.core.acp import discover as acp_discover_mod
from server.core.acp import group as acp_group_mod


class FakeAgentInfo:
    def to_dict(self):
        return {"id": "a1", "name": "A", "status": "offline"}


class FakeConnInfo:
    def to_dict(self):
        return {"id": "c1", "status": "connecting"}


class FakeGroup:
    def to_dict(self):
        return {"id": "g1", "name": "G"}


class FakeMessage:
    def __init__(self, mid="m1"):
        self.id = mid

    def to_dict(self):
        return {"id": self.id, "content": {"text": "hi"}}


class FakeACPManager:
    def __init__(self):
        self._local_agent_id = "local"
        self._local_agent_name = "Local"
        self.agents = {"a1": {"id": "a1"}}
        self.calls: dict = {}

    async def list_agents(self, online_only=False):
        return [{"id": "a1"}]

    async def register_agent(self, agent):
        self.calls["register"] = agent.to_dict()

    async def update_agent(self, *a, **k):
        return True

    async def remove_agent(self, agent_id):
        return True

    async def create_connection(self, conn):
        return None

    async def delete_connection(self, cid):
        return True

    async def list_connections(self, local_only=True):
        return [{"id": "c1"}]

    async def send_message(self, msg):
        self.calls["send"] = msg.id

    async def receive_external_message(self, msg):
        return FakeMessage("rx")

    async def get_messages(self, **kw):
        return [{"id": "m1"}]

    async def get_statistics(self):
        return {"connections": 1}

    async def cleanup_agent_resources(self, agent_id):
        return True

    async def update_agent_port(self, agent_id, port):
        return True


class FakeDiscovery:
    def __init__(self, acp_manager=None):
        self.acp_manager = acp_manager

    async def discover_once(self, timeout):
        return [{"id": "discovered"}]


class FakeGroupManager:
    def __init__(self, acp_manager=None):
        self.acp_manager = acp_manager

    async def create_group(self, **kw):
        return FakeGroup()

    async def list_groups(self):
        return [{"id": "g1"}]

    async def join_group(self, **kw):
        return True

    async def leave_group(self, **kw):
        return True

    async def broadcast_to_group(self, **kw):
        return FakeMessage("gm")


@pytest.fixture
def client(monkeypatch):
    mm = FakeACPManager()
    state = ServiceState()
    state.acp_manager = mm
    set_service_state(state)
    monkeypatch.setattr(acp_discover_mod, "ACPLanDiscovery", FakeDiscovery)
    monkeypatch.setattr(acp_group_mod, "ACPGroupManager", FakeGroupManager)
    app = FastAPI()
    app.include_router(acp_router_mod.router)
    # 写路径（send / cleanup resources）已补挂 verify_admin_api_key：
    # 既有用例经 dependency_overrides 放行，403 场景由 TestAcpWriteAuthRequired 单独覆盖
    app.dependency_overrides[verify_admin_api_key] = lambda: True
    return TestClient(app, raise_server_exceptions=False), mm


class TestDiscover:
    def test_success(self, client):
        c, mm = client
        r = c.post("/acp/discover")
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        assert r.json()["agents"][0]["id"] == "discovered"


class TestAgents:
    def test_list(self, client):
        c, mm = client
        r = c.get("/acp/agents")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_register(self, client):
        c, mm = client
        r = c.post("/acp/agents", json={"id": "agent-1", "name": "Test", "host": "127.0.0.1", "port": 9001})
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        assert mm.calls["register"]["id"] == "agent-1"

    def test_patch_404(self, client):
        c, mm = client
        async def _f(*a, **k):
            return False
        mm.update_agent = _f
        r = c.patch("/acp/agents/nope", json={})
        assert r.status_code == 404

    def test_delete_404(self, client):
        c, mm = client
        async def _f(agent_id):
            return False
        mm.remove_agent = _f
        r = c.delete("/acp/agents/nope")
        assert r.status_code == 404


class TestConnect:
    def test_connect(self, client):
        c, mm = client
        r = c.post("/acp/connect", json={"agent_id": "a1", "host": "127.0.0.1", "port": 9001})
        assert r.status_code == 200
        assert r.json()["connection"]["status"] == "connecting"

    def test_disconnect_404(self, client):
        c, mm = client
        async def _f(cid):
            return False
        mm.delete_connection = _f
        r = c.delete("/acp/connect/nope")
        assert r.status_code == 404

    def test_list_connections(self, client):
        c, mm = client
        r = c.get("/acp/connections")
        assert r.status_code == 200
        assert r.json()["total"] == 1


class TestGroups:
    def test_create(self, client):
        c, mm = client
        r = c.post("/acp/groups", json={"name": "G"})
        assert r.status_code == 200
        assert r.json()["group"]["id"] == "g1"

    def test_list(self, client):
        c, mm = client
        r = c.get("/acp/groups")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_join(self, client):
        c, mm = client
        r = c.post("/acp/groups/g1/join")
        assert r.status_code == 200

    def test_join_fail_400(self, client, monkeypatch):
        class G2(FakeGroupManager):
            async def join_group(self, **kw):
                return False
        monkeypatch.setattr(acp_group_mod, "ACPGroupManager", G2)
        c, mm = client
        r = c.post("/acp/groups/g1/join")
        assert r.status_code == 400

    def test_leave(self, client):
        c, mm = client
        r = c.post("/acp/groups/g1/leave")
        assert r.status_code == 200


class TestSendReceive:
    def test_send(self, client):
        c, mm = client
        r = c.post("/acp/send", json={"to_agent_id": "a1", "content": {"t": 1}})
        assert r.status_code == 200
        assert r.json()["message_id"] in mm.calls["send"]

    def test_receive(self, client):
        c, mm = client
        r = c.post("/acp/receive", json={
            "id": "x", "msg_type": "chat", "from_agent_id": "a", "from_agent_name": "A",
            "content": {"t": 1}, "timestamp": "2026-08-09T00:00:00", "is_sent": True,
        })
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "rx"

    def test_send_group(self, client):
        c, mm = client
        r = c.post("/acp/send/group", params={"group_id": "g1"}, json={"t": 1})
        assert r.status_code == 200
        assert r.json()["message_id"] == "gm"

    def test_messages(self, client):
        c, mm = client
        r = c.get("/acp/messages")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_stats(self, client):
        c, mm = client
        r = c.get("/acp/stats")
        assert r.status_code == 200
        assert r.json()["statistics"]["connections"] == 1


class TestV310:
    def test_cleanup_resources_404(self, client):
        c, mm = client
        r = c.delete("/acp/agents/nope/resources")
        assert r.status_code == 404

    def test_cleanup_resources_success(self, client):
        c, mm = client
        r = c.delete("/acp/agents/a1/resources")
        assert r.status_code == 200
        assert r.json()["agent_id"] == "a1"

    def test_update_port(self, client):
        c, mm = client
        r = c.put("/acp/agents/a1/port", json={"port": 9002})
        assert r.status_code == 200
        assert r.json()["port"] == 9002

    def test_update_port_404(self, client):
        c, mm = client
        async def _f(aid, port):
            return False
        mm.update_agent_port = _f
        r = c.put("/acp/agents/nope/port", json={"port": 9002})
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# 写路径鉴权（鉴权漏挂簇修复补充用例）
# verify_admin_api_key 校验失败统一抛 403（项目既有口径，对齐 test_stats_interrupt.py）；
# 本组用例不挂 dependency_overrides，真实走到密钥校验依赖。
# /acp/receive 为开放协议入口（鉴权属 SEC 簇登记项），保持无鉴权不在本组覆盖范围。
# --------------------------------------------------------------------------- #
class TestAcpWriteAuthRequired:
    @staticmethod
    def _raw_client(monkeypatch) -> TestClient:
        mm = FakeACPManager()
        state = ServiceState()
        state.acp_manager = mm
        set_service_state(state)
        monkeypatch.setattr(acp_discover_mod, "ACPLanDiscovery", FakeDiscovery)
        monkeypatch.setattr(acp_group_mod, "ACPGroupManager", FakeGroupManager)
        app = FastAPI()
        app.include_router(acp_router_mod.router)
        return TestClient(app, raise_server_exceptions=False), mm

    def test_send_requires_auth(self, monkeypatch):
        c, _ = self._raw_client(monkeypatch)
        r = c.post("/acp/send", json={"to_agent_id": "a1", "content": {"t": 1}})
        assert r.status_code == 403

    def test_cleanup_resources_requires_auth(self, monkeypatch):
        c, _ = self._raw_client(monkeypatch)
        r = c.delete("/acp/agents/a1/resources")
        assert r.status_code == 403

    def test_receive_stays_open(self, monkeypatch):
        # 开放协议入口回归：/acp/receive 不受鉴权补挂影响（无密钥仍可投递）
        c, _ = self._raw_client(monkeypatch)
        r = c.post("/acp/receive", json={
            "id": "x", "msg_type": "chat", "from_agent_id": "a", "from_agent_name": "A",
            "content": {"t": 1}, "timestamp": "2026-08-09T00:00:00", "is_sent": True,
        })
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "rx"


# --------------------------------------------------------------------------- #
# ACP 开放协议 token（第11轮第22项）：acp.auth_token 缺省空=不校验（兼容旧行为）；
# 配置后要求同值 X-ACP-Key 头，否则 403。独立于 admin key。
# --------------------------------------------------------------------------- #
class _Box:
    def __init__(self, **kw):
        self.__dict__.update(kw)


_RECEIVE_PAYLOAD = {
    "id": "x", "msg_type": "chat", "from_agent_id": "a", "from_agent_name": "A",
    "content": {"t": 1}, "timestamp": "2026-08-09T00:00:00", "is_sent": True,
}


class TestAcpProtocolToken:
    @staticmethod
    def _client_with_token(monkeypatch, token: str):
        monkeypatch.setattr(
            "server.config.get_settings",
            lambda: _Box(config=_Box(acp=_Box(auth_token=token))),
        )
        return TestAcpWriteAuthRequired._raw_client(monkeypatch)

    def test_empty_token_stays_open(self, monkeypatch):
        c, _ = self._client_with_token(monkeypatch, "")
        r = c.post("/acp/receive", json=_RECEIVE_PAYLOAD)
        assert r.status_code == 200

    def test_configured_token_missing_header_403(self, monkeypatch):
        c, _ = self._client_with_token(monkeypatch, "s3cret")
        r = c.post("/acp/receive", json=_RECEIVE_PAYLOAD)
        assert r.status_code == 403

    def test_configured_token_wrong_403(self, monkeypatch):
        c, _ = self._client_with_token(monkeypatch, "s3cret")
        r = c.post("/acp/receive", json=_RECEIVE_PAYLOAD, headers={"X-ACP-Key": "bad"})
        assert r.status_code == 403

    def test_configured_token_ok(self, monkeypatch):
        c, _ = self._client_with_token(monkeypatch, "s3cret")
        r = c.post(
            "/acp/receive", json=_RECEIVE_PAYLOAD, headers={"X-ACP-Key": "s3cret"}
        )
        assert r.status_code == 200
        assert r.json()["data"]["id"] == "rx"

    def test_send_group_token_missing_403(self, monkeypatch):
        c, _ = self._client_with_token(monkeypatch, "s3cret")
        r = c.post("/acp/send/group", params={"group_id": "g1"}, json={"t": 1})
        assert r.status_code == 403

    def test_send_group_token_ok(self, monkeypatch):
        c, _ = self._client_with_token(monkeypatch, "s3cret")
        r = c.post(
            "/acp/send/group",
            params={"group_id": "g1"},
            json={"t": 1},
            headers={"X-ACP-Key": "s3cret"},
        )
        assert r.status_code == 200