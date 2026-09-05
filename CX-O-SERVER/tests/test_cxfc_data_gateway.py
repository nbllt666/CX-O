"""CXFC 数据网关测试（spec: enhance-cxfc-admin-and-integrate-dream Task 1）。

参照 tests/test_admin_router.py 的 TestClient + monkeypatch 模式：
- FakeGatewayCXFCManager 注入 cxfc 路由（令牌代持/校验最小接口）；
- FakeMemoryManager 经 app.dependency_overrides[get_memory_manager] 注入；
- FakePhysioRuntime 经 physio_router.set_physio_runtime 注入（含植入的原始 HR
  键，用于证明网关响应剥离隐私数据）；
- 真实 CXFCManager + 临时 SQLite 验证"注册签发令牌且库中仅存哈希"。

覆盖用例：
① 无令牌 401 ② 错令牌 403 ③ admin X-API-Key 旁路可用 ④ search 命中
⑤ write 契约违约 422 ⑥ physio status 响应不含原始 HR 列表
⑦ 注册响应含 plugin_access_token 且库中仅存哈希

运行：python -m pytest tests/test_cxfc_data_gateway.py -v
"""
import asyncio
import hashlib
import sqlite3
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import cxfc as cxfc_router_mod
from server.api.routers import physio as physio_router_mod
from server.core.cxfc.manager import CXFCManager
from server.core.cxfc.models import CXFCRegisterRequest
from server.dependencies import get_memory_manager


# ---------------------------------------------------------------------------
# 替身定义
# ---------------------------------------------------------------------------

class FakeMemoryManager:
    """记忆管理器替身：记录调用参数并返回可断言的固定数据。"""

    def __init__(self):
        self.search_calls: List[Dict[str, Any]] = []
        self.write_calls: List[Dict[str, Any]] = []
        self.stats_calls: List[Any] = []
        self.get_calls: List[Dict[str, Any]] = []

    def search_memories(
        self,
        query: Optional[str] = None,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        time_range: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
        include_deleted: bool = False,
        workspace_id: str = "default",
        agent_id: str = "default",
    ):
        self.search_calls.append({"query": query, "limit": limit, "agent_id": agent_id})
        return [{"id": 1, "content": f"命中:{query}", "memory_type": "long_term"}]

    def write_memory(self, **kwargs):
        self.write_calls.append(kwargs)
        return 42

    def get_statistics(self, workspace_id: str = "default"):
        self.stats_calls.append(workspace_id)
        return {"total": 3, "workspace_id": workspace_id}

    def get_memory(self, memory_id: int, include_deleted: bool = False, agent_id: Optional[str] = None):
        self.get_calls.append({"memory_id": memory_id, "agent_id": agent_id})
        if memory_id == 1:
            return {"id": 1, "content": "m1"}
        return None


class FakeGatewayCXFCManager:
    """CXFC 管理器替身：实现令牌代持/校验与注册所需的最小接口。"""

    def __init__(self):
        # 明文令牌 -> plugin_id 的映射（模拟库中哈希比对的最终效果）
        self._tokens = {"tok-issued": "plug-1"}

    async def register_plugin(self, request):
        return SimpleNamespace(plugin_id="plug-1")

    async def register_relay_plugin(self, **kwargs):
        return SimpleNamespace(plugin_id=f"relay_{kwargs.get('plugin_id', 'x')}")

    async def register_embedded_plugin(self, **kwargs):
        return SimpleNamespace(plugin_id=f"embedded_{kwargs.get('plugin_id', 'x')}")

    def get_plugin_access_token(self, plugin_id: str) -> Optional[str]:
        if plugin_id in ("plug-1", "relay_plug-1", "embedded_plug-1"):
            return "tok-issued"
        return None

    def verify_plugin_access_token(self, token: str) -> Optional[str]:
        return self._tokens.get(token)


class FakeSettings:
    """run_io → get_io_executor 读取 config.executor.io_pool_size 的替身配置。"""

    def __init__(self):
        self.config = SimpleNamespace(executor=SimpleNamespace(io_pool_size=2))


def _fake_physio_runtime():
    """生理 runtime 替身：估计器状态中**故意植入原始 HR 序列键**，
    用于证明网关响应经 _strip_raw_hr 清洗后不含任何原始心率数据。"""
    estimator = SimpleNamespace(
        get_state=lambda: {
            "base_hr": 60.0,
            "hr_sleep_confidence": 0.55,
            "window_size": 4,
            "updated_at": None,
            # 植入的原始 HR 序列（真实实现中估计器本就不返回；此处验证防御纵深）
            "samples": [72, 75, 80, 71],
        }
    )
    config = SimpleNamespace(
        backend="noble",
        device_fingerprint="fingerprint-abc",
        device_name_hint="Test Band",
    )
    sleep_sensor = SimpleNamespace(
        snapshot=lambda: {
            "state": "ASLEEP",
            "confidence": 0.8,
            "signals": [{"name": "S2", "weight": 0.3, "value": 0.7, "available": True}],
            "updated_at": "2026-09-04T00:00:00",
            # 植入的原始 HR 序列
            "raw_hr": [71, 72],
        }
    )
    return SimpleNamespace(
        is_enabled=lambda: True,
        get_config=lambda: config,
        estimator=estimator,
        sleep_sensor=sleep_sensor,
    )


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gw_env(monkeypatch):
    """通用环境：假 CXFC 管理器 + 假配置 + ADMIN_API_KEY 注入。"""
    manager = FakeGatewayCXFCManager()
    cxfc_router_mod.set_cxfc_manager(manager)
    monkeypatch.setenv("ADMIN_API_KEY", "gw-admin-key")
    monkeypatch.setattr("server.config.get_settings", lambda: FakeSettings())
    yield manager
    # 清理模块级全局，防泄漏到其他用例
    cxfc_router_mod.set_cxfc_manager(None)


@pytest.fixture
def gw_client(gw_env):
    """挂载 cxfc 路由 + 覆盖记忆管理器依赖的测试客户端。"""
    app = FastAPI()
    app.include_router(cxfc_router_mod.router)
    app.dependency_overrides[get_memory_manager] = lambda: FakeMemoryManager()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def gw_client_with_memory(gw_env):
    """同 gw_client，但返回客户端与记忆替身实例（供调用断言）。"""
    memory = FakeMemoryManager()
    app = FastAPI()
    app.include_router(cxfc_router_mod.router)
    app.dependency_overrides[get_memory_manager] = lambda: memory
    return TestClient(app, raise_server_exceptions=False), memory


@pytest.fixture
def fake_physio_runtime():
    """注入假生理 runtime，用例结束后还原为 None。"""
    runtime = _fake_physio_runtime()
    physio_router_mod.set_physio_runtime(runtime)
    yield runtime
    physio_router_mod.set_physio_runtime(None)


_AUTH = {"Authorization": "Bearer tok-issued"}


# ===========================================================================
# ① 无令牌 401
# ===========================================================================
class TestAuthRequired:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/cxfc/memory/stats"),
            ("get", "/cxfc/memory/1"),
            ("get", "/cxfc/physio/status"),
            ("get", "/cxfc/physio/sleep"),
        ],
    )
    def test_missing_token_401(self, gw_client, method, path):
        r = getattr(gw_client, method)(path)
        assert r.status_code == 401

    def test_missing_token_search_401(self, gw_client):
        r = gw_client.post("/cxfc/memory/search", json={"query": "x"})
        assert r.status_code == 401

    def test_missing_token_write_401(self, gw_client):
        r = gw_client.post("/cxfc/memory/write", json={})
        assert r.status_code == 401

    def test_missing_token_report_401(self, gw_client):
        r = gw_client.post("/cxfc/physio/report", json={"bpm": 70})
        assert r.status_code == 401

    def test_malformed_authorization_401(self, gw_client):
        r = gw_client.get("/cxfc/memory/stats", headers={"Authorization": "Token abc"})
        assert r.status_code == 401


# ===========================================================================
# ② 错令牌 403
# ===========================================================================
class TestInvalidToken:
    def test_wrong_token_403(self, gw_client):
        r = gw_client.get("/cxfc/memory/stats", headers={"Authorization": "Bearer tok-wrong"})
        assert r.status_code == 403

    def test_wrong_token_search_403(self, gw_client):
        r = gw_client.post(
            "/cxfc/memory/search",
            json={"query": "x"},
            headers={"Authorization": "Bearer tok-wrong"},
        )
        assert r.status_code == 403

    def test_wrong_admin_key_not_bypass_401(self, gw_client):
        """X-API-Key 错误且无 Bearer → 不放行也不旁路，按无令牌 401 处理。"""
        r = gw_client.get("/cxfc/memory/stats", headers={"X-API-Key": "bad-key"})
        assert r.status_code == 401


# ===========================================================================
# ③ admin X-API-Key 旁路可用
# ===========================================================================
class TestAdminBypass:
    def test_admin_key_bypass_stats(self, gw_client_with_memory):
        c, _ = gw_client_with_memory
        r = c.get("/cxfc/memory/stats", headers={"X-API-Key": "gw-admin-key"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["statistics"]["total"] == 3
        assert body["plugin_id"] == "admin"

    def test_admin_key_bypass_search(self, gw_client_with_memory):
        c, memory = gw_client_with_memory
        r = c.post(
            "/cxfc/memory/search",
            json={"query": "旁路"},
            headers={"X-API-Key": "gw-admin-key"},
        )
        assert r.status_code == 200
        assert r.json()["plugin_id"] == "admin"
        assert memory.search_calls[0]["query"] == "旁路"


# ===========================================================================
# ④ search 命中（fake memory manager）
# ===========================================================================
class TestMemorySearch:
    def test_search_hit(self, gw_client_with_memory):
        c, memory = gw_client_with_memory
        r = c.post(
            "/cxfc/memory/search",
            json={"query": "会议纪要", "limit": 5, "agent_id": "default"},
            headers=_AUTH,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["total"] == 1
        assert body["memories"][0]["content"] == "命中:会议纪要"
        assert body["plugin_id"] == "plug-1"
        # 参数确实透传到 memory manager
        assert memory.search_calls == [{"query": "会议纪要", "limit": 5, "agent_id": "default"}]

    def test_search_default_params(self, gw_client_with_memory):
        c, memory = gw_client_with_memory
        r = c.post("/cxfc/memory/search", json={"query": "abc"}, headers=_AUTH)
        assert r.status_code == 200
        assert memory.search_calls[0]["limit"] == 10
        assert memory.search_calls[0]["agent_id"] == "default"

    def test_search_limit_out_of_range_422(self, gw_client):
        r = c = gw_client
        r = c.post("/cxfc/memory/search", json={"query": "x", "limit": 500}, headers=_AUTH)
        assert r.status_code == 422


# ===========================================================================
# ⑤ write 契约违约 422（校验依据 public/schema/memory.schema.json）
# ===========================================================================
def _valid_memory_record() -> Dict[str, Any]:
    """构造符合 memory.schema.json 全部 required 字段的合法写入体。"""
    ts = "2026-09-04T00:00:00"
    return {
        "id": 0,
        "content": "网关写入测试",
        "memory_type": "long_term",
        "importance": 3,
        "tags": ["gw"],
        "metadata": {"src": "cxfc"},
        "permanent": False,
        "emotion_score": 0.1,
        "workspace_id": "default",
        "agent_id": "default",
        "created_at": ts,
        "updated_at": ts,
        "accessed_at": ts,
        "access_count": 0,
        "decay_score": 0.0,
        "is_deleted": False,
    }


class TestMemoryWrite:
    def test_write_valid_record(self, gw_client_with_memory):
        c, memory = gw_client_with_memory
        r = c.post("/cxfc/memory/write", json=_valid_memory_record(), headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["memory_id"] == 42
        # 仅可写字段透传给 write_memory（id/created_at 等只读列被剥除）
        assert memory.write_calls[0]["content"] == "网关写入测试"
        assert memory.write_calls[0]["agent_id"] == "default"
        assert "id" not in memory.write_calls[0]
        assert "created_at" not in memory.write_calls[0]

    def test_write_missing_required_422(self, gw_client):
        """缺 required 字段（id/content/... 全家）→ 契约违约 422。"""
        r = gw_client.post("/cxfc/memory/write", json={"content": "只有内容"}, headers=_AUTH)
        assert r.status_code == 422

    def test_write_empty_content_422(self, gw_client):
        """content 违反 minLength=1 → 契约违约 422。"""
        body = _valid_memory_record()
        body["content"] = ""
        r = gw_client.post("/cxfc/memory/write", json=body, headers=_AUTH)
        assert r.status_code == 422

    def test_write_bad_importance_type_422(self, gw_client):
        """importance 传字符串（契约要求 integer）→ 422。"""
        body = _valid_memory_record()
        body["importance"] = "high"
        r = gw_client.post("/cxfc/memory/write", json=body, headers=_AUTH)
        assert r.status_code == 422


# ===========================================================================
# stats / get 端点（复用 memory router 数据来源）
# ===========================================================================
class TestMemoryStatsAndGet:
    def test_stats_reuses_get_statistics(self, gw_client_with_memory):
        c, memory = gw_client_with_memory
        r = c.get("/cxfc/memory/stats", params={"workspace_id": "ws-1"}, headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["statistics"] == {"total": 3, "workspace_id": "ws-1"}
        assert memory.stats_calls == ["ws-1"]

    def test_get_memory_hit(self, gw_client_with_memory):
        c, memory = gw_client_with_memory
        r = c.get("/cxfc/memory/1", headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["memory"]["content"] == "m1"

    def test_get_memory_miss_404(self, gw_client):
        r = gw_client.get("/cxfc/memory/999", headers=_AUTH)
        assert r.status_code == 404


# ===========================================================================
# ⑥ physio 端点：仅衍生指标，绝不返回原始 HR 序列
# ===========================================================================
class TestPhysioGatewayPrivacy:
    def test_status_strips_raw_hr_and_keeps_derived(self, gw_client, fake_physio_runtime):
        r = gw_client.get("/cxfc/physio/status", headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        # 衍生指标保留
        assert body["status"] == "active"
        assert body["enabled"] is True
        assert body["estimator"]["base_hr"] == 60.0
        assert body["estimator"]["hr_sleep_confidence"] == 0.55
        # 植入的原始 HR 序列被剥离（隐私红线 store_raw_hr=false）
        assert "samples" not in body["estimator"]
        assert "raw_hr" not in r.text
        assert "[72" not in r.text

    def test_sleep_strips_raw_hr(self, gw_client, fake_physio_runtime):
        r = gw_client.get("/cxfc/physio/sleep", headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "ASLEEP"
        assert body["confidence"] == 0.8
        assert body["signals"][0]["name"] == "S2"
        # 植入的原始 HR 序列被剥离
        assert "raw_hr" not in body
        assert "raw_hr" not in r.text

    def test_report_disabled_runtime(self, gw_client):
        """runtime 未装配 → 复用 /physio/hr 的 disabled 口径（200 不抛错）。"""
        r = gw_client.post("/cxfc/physio/report", json={"bpm": 70}, headers=_AUTH)
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}

    def test_report_uses_runtime_estimator(self, gw_client, fake_physio_runtime):
        """启用时复用 physio 估计器管道：ingest 结果（置信度）原样返回。"""
        fake_physio_runtime.estimator.ingest = lambda bpm, ts: 0.9
        r = gw_client.post(
            "/cxfc/physio/report",
            json={"bpm": 70, "ts": "2026-09-04T00:00:00"},
            headers=_AUTH,
        )
        assert r.status_code == 200
        assert r.json() == {"hr_sleep_confidence": 0.9}

    def test_disabled_runtime_status(self, gw_client):
        """runtime 未装配 → disabled 口径。"""
        r = gw_client.get("/cxfc/physio/status", headers=_AUTH)
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}


# ===========================================================================
# ⑦ 注册响应含 plugin_access_token 且库中仅存哈希（真实 manager + 临时 SQLite）
# ===========================================================================
class TestRegisterIssuesAccessToken:
    def test_router_response_contains_token(self, gw_client):
        """路由层：三类注册端点响应均含一次性下发的 plugin_access_token。"""
        # direct
        r = gw_client.post("/cxfc/register", json={"host": "127.0.0.1", "port": 9101, "name": "gw"})
        assert r.status_code == 200
        assert r.json()["plugin_access_token"] == "tok-issued"
        # relay
        r2 = gw_client.post("/cxfc/relay/register", json={"plugin_id": "plug-1", "name": "gw"})
        assert r2.status_code == 200
        assert r2.json()["plugin_id"] == "relay_plug-1"
        assert r2.json()["plugin_access_token"] == "tok-issued"
        # embedded
        r3 = gw_client.post("/cxfc/embedded", json={"plugin_id": "plug-1", "name": "gw"})
        assert r3.status_code == 200
        assert r3.json()["plugin_access_token"] == "tok-issued"

    def test_real_manager_register_stores_hash_only(self, tmp_path):
        """真实 CXFCManager + 临时 SQLite：明文仅进内存代持与注册响应，库中仅存哈希。"""
        db_path = tmp_path / "cxfc_plugins.db"

        async def _scenario():
            manager = CXFCManager(storage_path=str(db_path))
            await manager._storage.init_db()
            plugin = await manager.register_plugin(
                CXFCRegisterRequest(host="127.0.0.1", port=9101, name="gw")
            )
            token = manager.get_plugin_access_token(plugin.plugin_id)
            # 校验接口：明文命中返回 plugin_id，错令牌返回 None
            verified = manager.verify_plugin_access_token(token)
            verified_wrong = manager.verify_plugin_access_token("not-a-token")
            # 直读库行（绕过模型层，验证物理存储内容）
            cursor = await manager._storage._db.execute(
                "SELECT plugin_id, token, plugin_access_token_hash FROM cxfc_plugins WHERE plugin_id = ?",
                (plugin.plugin_id,),
            )
            row = await cursor.fetchone()
            await manager._storage.close()
            return token, verified, verified_wrong, tuple(row)

        token, verified, verified_wrong, row = asyncio.run(_scenario())

        # 令牌形态：64 字符十六进制（secrets.token_hex(32)）
        assert token and len(token) == 64
        int(token, 16)  # 合法十六进制
        # 校验行为
        assert verified == "cxfc_127.0.0.1_9101"
        assert verified_wrong is None
        # 库中仅存哈希：hash 列 = sha256(明文)；旧 token 列为 NULL（插件→后端方向令牌是新增能力）
        plugin_id, legacy_token, stored_hash = row
        assert plugin_id == "cxfc_127.0.0.1_9101"
        assert stored_hash == hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert legacy_token is None
        # 明文不出现在库中任何列
        assert all(token != (v or "") for v in row)

    def test_real_manager_embedded_and_relay_hold_plaintext(self, tmp_path):
        """relay/embedded 注册后由后端内存代持明文；verify 可用该明文命中。"""
        db_path = tmp_path / "cxfc_plugins.db"

        async def _scenario():
            manager = CXFCManager(storage_path=str(db_path))
            await manager._storage.init_db()
            relay = await manager.register_relay_plugin(plugin_id="r1", name="relay插件")
            embedded = await manager.register_embedded_plugin(plugin_id="e1", name="嵌入式插件")
            relay_token = manager.get_plugin_access_token(relay.plugin_id)
            embedded_token = manager.get_plugin_access_token(embedded.plugin_id)
            relay_ok = manager.verify_plugin_access_token(relay_token) == relay.plugin_id
            embedded_ok = manager.verify_plugin_access_token(embedded_token) == embedded.plugin_id
            # 哈希确实写入模型（随后随 save_plugin 落库）
            hashes_set = bool(relay.plugin_access_token_hash) and bool(embedded.plugin_access_token_hash)
            await manager._storage.close()
            return relay_token, embedded_token, relay_ok, embedded_ok, hashes_set

        relay_token, embedded_token, relay_ok, embedded_ok, hashes_set = asyncio.run(_scenario())
        assert relay_token and embedded_token and relay_token != embedded_token
        assert relay_ok and embedded_ok and hashes_set

    def test_issued_token_grants_gateway_access(self, gw_client_with_memory):
        """端到端：注册下发令牌 → 用该令牌访问网关 → 放行并绑定 plugin_id。"""
        c, memory = gw_client_with_memory
        r = c.post("/cxfc/register", json={"host": "127.0.0.1", "port": 9101, "name": "gw"})
        token = r.json()["plugin_access_token"]
        r2 = c.get("/cxfc/memory/stats", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        assert r2.json()["plugin_id"] == "plug-1"
        assert memory.stats_calls == ["default"]

    def test_plugins_listing_leaks_no_token(self, gw_env):
        """GET /cxfc/plugins 不得泄露令牌哈希（plugin_access_token_hash 已 exclude）。"""
        from server.core.cxfc.models import CXFCPluginInfo, PluginStatus

        manager = gw_env

        class _ListingManager(FakeGatewayCXFCManager):
            def get_plugins(self):
                return [
                    CXFCPluginInfo(
                        plugin_id="plug-1",
                        status=PluginStatus.CONNECTED,
                        plugin_access_token_hash="a" * 64,
                    )
                ]

        manager.__class__ = _ListingManager  # 注入 get_plugins
        app = FastAPI()
        app.include_router(cxfc_router_mod.router)
        app.dependency_overrides[get_memory_manager] = lambda: FakeMemoryManager()
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/cxfc/plugins")
        assert r.status_code == 200
        assert "plugin_access_token_hash" not in r.text
        assert "tok-issued" not in r.text
