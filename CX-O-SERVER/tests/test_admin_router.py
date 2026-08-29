"""server.api.routers.admin 路由测试。

monkeypatch ADMIN_API_KEY + set_service_state 注入假 manager + monkeypatch
server.config.get_settings + monkeypatch.chdir 隔离备份目录。覆盖：
- verify_admin_api_key（未配置 403 / 缺失/错误 key 403 / 正确放行）
- dashboard / stats / health（healthy/degraded）
- get_config / update_config（provider 校验 400 / 成功）
- get_logs（level/lines 收敛）
- create_backup（403 / 数据目录不存在 400 / 成功生成 zip）

运行：python -m pytest tests/test_admin_router.py -v
"""
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.dependencies import ServiceState, set_service_state
from server.api.routers import admin as admin_router_mod
from server.core.tools import registry as registry_mod


class SimpleBox:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeSection:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeSettings:
    def __init__(self):
        self.config = SimpleBox(
            llm=FakeSection(provider="ollama", model="qwen"),
            vector=FakeSection(enabled=True),
            acp=FakeSection(enabled=True, agent_name="alice"),
            system=FakeSection(debug=False),
            # run_io → get_io_executor 会读 config.executor.io_pool_size
            #（模块级单例惰性构造，全量/定向执行时序不同，替身必须完整）
            executor=FakeSection(io_pool_size=2),
        )
        self.saved = False

    def save_config(self):
        self.saved = True


class FakeStats:
    def get_statistics(self):
        return {"total": 1}


class FakeACP:
    async def get_statistics(self):
        return {"total_agents": 1}


@pytest.fixture
def client(monkeypatch):
    state = ServiceState()
    state.memory_manager = FakeStats()
    state.context_manager = FakeStats()
    state.acp_manager = FakeACP()
    set_service_state(state)
    fake_registry = SimpleBox(get_tool_stats=lambda: {"total_tools": 3})
    monkeypatch.setattr(registry_mod, "tool_registry", fake_registry)
    # C7: ADMIN_API_KEY 改为惰性读取 env，测试经 setenv 注入
    monkeypatch.setenv("ADMIN_API_KEY", "secret_key")
    monkeypatch.setattr("server.config.get_settings", lambda: FakeSettings())

    app = FastAPI()
    app.include_router(admin_router_mod.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def no_key_client(monkeypatch):
    # C7: 惰性读取 env——未配置场景经 delenv 模拟
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(admin_router_mod.router)
    return TestClient(app, raise_server_exceptions=False)


class TestVerifyAdminApiKey:
    def test_no_key_configured_403(self, no_key_client):
        c = no_key_client
        r = c.get("/admin/stats", headers={"X-API-Key": "x"})
        assert r.status_code == 403

    def test_missing_header_403(self, client):
        c = client
        r = c.get("/admin/stats")
        assert r.status_code == 403

    def test_wrong_key_403(self, client):
        c = client
        r = c.get("/admin/stats", headers={"X-API-Key": "wrong"})
        assert r.status_code == 403

    def test_correct_key_ok(self, client):
        c = client
        r = c.get("/admin/stats", headers={"X-API-Key": "secret_key"})
        assert r.status_code == 200


class TestDashboard:
    def test_success(self, client):
        c = client
        r = c.get("/admin/dashboard", headers={"X-API-Key": "secret_key"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["dashboard"]["memory"]["total"] == 1
        assert body["dashboard"]["acp"]["total_agents"] == 1

    def test_requires_auth(self, client):
        c = client
        r = c.get("/admin/dashboard")
        assert r.status_code == 403


class TestStats:
    def test_success(self, client):
        c = client
        r = c.get("/admin/stats", headers={"X-API-Key": "secret_key"})
        assert r.status_code == 200
        body = r.json()
        assert body["statistics"]["memory"]["total"] == 1
        assert body["statistics"]["tools"]["total_tools"] == 3


class TestHealth:
    def test_healthy(self, client):
        c = client
        r = c.get("/admin/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert body["components"]["memory"] == "healthy"


class TestGetConfig:
    def test_success(self, client):
        c = client
        r = c.get("/admin/config", headers={"X-API-Key": "secret_key"})
        assert r.status_code == 200
        cfg = r.json()["config"]
        assert cfg["llm"]["provider"] == "ollama"
        assert cfg["vector"]["enabled"] is True
        assert cfg["acp"]["agent_name"] == "alice"
        assert cfg["system"]["debug"] is False


class TestUpdateConfig:
    def test_success(self, client, monkeypatch):
        c = client
        settings = FakeSettings()
        monkeypatch.setattr("server.config.get_settings", lambda: settings)
        r = c.put("/admin/config", headers={"X-API-Key": "secret_key"},
                  json={"llm": {"provider": "vllm", "model": "gpt4"},
                        "vector": {"enabled": False},
                        "acp": {"enabled": False, "agent_name": "bob"},
                        "system": {"debug": True}})
        assert r.status_code == 200
        assert settings.saved is True
        assert settings.config.llm.provider == "vllm"
        assert settings.config.llm.model == "gpt4"
        assert settings.config.vector.enabled is False
        assert settings.config.acp.agent_name == "bob"
        assert settings.config.system.debug is True

    def test_invalid_provider_400(self, client):
        c = client
        r = c.put("/admin/config", headers={"X-API-Key": "secret_key"},
                  json={"llm": {"provider": "weird"}})
        assert r.status_code == 400

    def test_requires_auth(self, client):
        c = client
        r = c.put("/admin/config", json={"llm": {"provider": "ollama"}})
        assert r.status_code == 403


class TestLogs:
    def test_defaults(self, client):
        c = client
        r = c.get("/admin/logs", headers={"X-API-Key": "secret_key"})
        assert r.status_code == 200
        assert r.json()["level"] == "INFO"
        assert r.json()["lines"] == 50

    def test_invalid_level_returns_info(self, client):
        c = client
        r = c.get("/admin/logs", headers={"X-API-Key": "secret_key"}, params={"level": "BOGUS"})
        assert r.json()["level"] == "INFO"

    def test_lines_capped(self, client):
        c = client
        r = c.get("/admin/logs", headers={"X-API-Key": "secret_key"}, params={"lines": 5000})
        assert r.json()["lines"] == 1000


class TestCreateBackup:
    def test_requires_auth(self, client):
        c = client
        r = c.post("/admin/backup")
        assert r.status_code == 403

    def test_data_dir_missing_400(self, client, monkeypatch, tmp_path):
        c = client
        # 显式 patch 绝对路径到不存在的位置（替代原 chdir 相对路径手法）
        monkeypatch.setattr(admin_router_mod, "_DATA_DIR", tmp_path / "data")
        monkeypatch.setattr(admin_router_mod, "_BACKUP_DIR", tmp_path / "data" / "backups")
        r = c.post("/admin/backup", headers={"X-API-Key": "secret_key"})
        assert r.status_code == 400

    def test_success_creates_zip(self, client, monkeypatch, tmp_path):
        c = client
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "a.txt").write_text("hello")
        monkeypatch.setattr(admin_router_mod, "_DATA_DIR", data_dir)
        monkeypatch.setattr(admin_router_mod, "_BACKUP_DIR", data_dir / "backups")
        r = c.post("/admin/backup", headers={"X-API-Key": "secret_key"})
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        # 备份 zip 已生成
        backups = list((data_dir / "backups").glob("*.zip"))
        assert len(backups) == 1


# ===========================================================================
# 第四轮体检修复（20260827）M7/M8 定向：CX-A 管理面运行时端点
# ===========================================================================
from server.core.admin.auth import AdminRateLimitedError  # noqa: E402
from server.core.admin.cluster_bridge import ClusterAdminBridge  # noqa: E402
from server.core.admin.control_plane import AdminControlPlane  # noqa: E402
from server.api.routers import backup as backup_mod  # noqa: E402


class _RecordingAuth:
    """记录 guard 调用顺序的认证替身；rate_limited=True 时 check_rate_limit 抛 429。"""

    def __init__(self, rate_limited=False):
        self.calls = []
        self.rate_limited = rate_limited

    def authenticate(self, token):
        self.calls.append("authenticate")
        return "operator"

    def check_required_level(self, level, required):
        self.calls.append("required")

    def check_rate_limit(self):
        self.calls.append("rate_limit")
        if self.rate_limited:
            raise AdminRateLimitedError("too many requests")

    def check_replay(self, request_id):
        self.calls.append("replay")


class _AsyncClusterManager:
    """state/trigger_failover 均为 async 的假集群管理器（桥接层协程路径）。"""

    def __init__(self):
        self.state_reads = 0
        self.failovers = 0

    async def state(self):
        self.state_reads += 1
        return {"node_id": "n1", "role": "leader", "epoch": 3}

    async def trigger_failover(self, params=None):
        self.failovers += 1
        return {"triggered": True}


def _fake_manifest():
    class M:
        def build(self, cluster_state):
            return {"built": True, "cluster_state": cluster_state}

        def detect_models(self):
            return {"models": 1}

        def detect_capabilities(self):
            return {"caps": 1}

    return M()


@pytest.fixture
def cx_a_client(monkeypatch):
    """注入 CX-A 运行时（真 control_plane + 真桥 + async 假集群管理器）。"""
    auth = _RecordingAuth()
    cluster_manager = _AsyncClusterManager()
    bridge = ClusterAdminBridge(cluster_manager=cluster_manager)
    control_plane = AdminControlPlane(services=None, auth=auth, cluster_bridge=bridge)
    manifest = _fake_manifest()

    admin_router_mod.inject_admin_runtime(
        auth, control_plane, manifest, None, bridge, None
    )
    # 避免写真实 data/admin_audit.jsonl（桥内 _write 也走 audit_now）
    monkeypatch.setattr(
        admin_router_mod, "audit_now", lambda *a, **k: {"id": "noop"}
    )
    monkeypatch.setattr(
        "server.core.admin.cluster_bridge.audit_now", lambda *a, **k: {"id": "noop"}
    )
    app = FastAPI()
    app.include_router(admin_router_mod.router)
    try:
        yield TestClient(app, raise_server_exceptions=False), auth, cluster_manager
    finally:
        # 还原运行时全局（防泄漏到其他用例）
        for name in (
            "_admin_auth", "_control_plane", "_manifest",
            "_instance_registry", "_cluster_bridge", "_services",
        ):
            setattr(admin_router_mod, name, None)


_AUTH_HEADER = {"Authorization": "Bearer super-token"}


class TestGuardOrderAndClusterResolve:
    def test_control_resolves_async_cluster_state(self, cx_a_client):
        """M8 定向(admin_control 路): async 集群方法返回真实数据而非假 pending。"""
        c, auth, cluster_manager = cx_a_client
        r = c.post(
            "/admin/control",
            headers=_AUTH_HEADER,
            json={"action": "state", "target": "cluster", "request_id": "r-1"},
        )
        assert r.status_code == 200
        body = r.json()
        # 层级契约与同步集群路径一致：body.result = dispatch 字典，
        # dispatch.result = _cluster 的 {"result": 桥返回}，桥的协程包装
        # 在最内层被 await 还原为真实状态数据。
        assert body["result"]["result"]["result"] == {
            "node_id": "n1", "role": "leader", "epoch": 3
        }
        assert cluster_manager.state_reads == 1  # 协程确实被执行过

    def test_control_rate_limit_before_replay(self, cx_a_client):
        """M7 定向: check_rate_limit 先于 check_replay 执行。"""
        c, auth, _ = cx_a_client
        c.post(
            "/admin/control",
            headers=_AUTH_HEADER,
            json={"action": "state", "target": "cluster", "request_id": "r-order"},
        )
        assert "replay" in auth.calls and "rate_limit" in auth.calls
        assert auth.calls.index("rate_limit") < auth.calls.index("replay")

    def test_control_rate_limited_429_without_replay_check(self, cx_a_client):
        """M7 定向: 限流被拒时不再消耗 request_id（replay 未执行）。"""
        c, auth, _ = cx_a_client
        auth.rate_limited = True
        r = c.post(
            "/admin/control",
            headers=_AUTH_HEADER,
            json={"action": "state", "target": "cluster", "request_id": "r-x"},
        )
        assert r.status_code == 429
        assert "replay" not in auth.calls

    def test_batch_resolves_async_cluster_paths(self, cx_a_client):
        """M8 定向(admin_batch 路): batch 两步均能解包出真实结果。"""
        c, _, cluster_manager = cx_a_client
        r = c.post(
            "/admin/batch",
            headers=_AUTH_HEADER,
            json={
                "request_id": "b-1",
                "mode": "sequential",
                "steps": [
                    {"target": "cluster", "action": "state"},
                    {"target": "cluster", "action": "trigger_failover",
                     "params": {"from_node": "n0"}},
                ],
            },
        )
        assert r.status_code == 200
        steps = r.json()["steps"]
        assert [s["ok"] for s in steps] == [True, True]
        # step.result = dispatch 字典（最内层桥协程包装已解包为真实数据）
        assert steps[0]["result"] == {
            "action": "state", "target": "cluster", "ok": True,
            "result": {"result": {"node_id": "n1", "role": "leader", "epoch": 3}},
        }
        # 写路结果经 Pending 包装 await 后还原
        assert steps[1]["result"]["result"]["result"] == {"triggered": True}
        assert cluster_manager.failovers == 1

    def test_manifest_and_status_use_real_cluster_data(self, cx_a_client):
        """M8 定向(manifest/status 直读路): read_state 协程包装被解包。"""
        c, _, cluster_manager = cx_a_client
        r = c.get("/admin/manifest", headers=_AUTH_HEADER)
        assert r.status_code == 200
        manifest_body = r.json()
        assert manifest_body["built"] is True
        assert manifest_body["cluster_state"]["node_id"] == "n1"

        r2 = c.get("/admin/status", headers=_AUTH_HEADER)
        snapshot = r2.json()["snapshot"]
        assert snapshot["cluster"]["role"] == "leader"
        assert cluster_manager.state_reads >= 2


# ===========================================================================
# 第四轮体检修复（20260827）L12 定向：备份导入大小上限
# ===========================================================================
class TestImportBackupLimit:
    @staticmethod
    def _backup_client(monkeypatch):
        """独立应用挂载 backup 路由：注入成功 manager + 免鉴权。"""
        from fastapi import FastAPI

        class _OkManager:
            def import_backup(self, path):
                return {
                    "id": "i1", "backup_type": "full", "status": "completed",
                    "created_at": "t", "completed_at": None, "description": None,
                    "size_bytes": 1, "compressed_size": 1, "file_count": 1, "path": "",
                }

        monkeypatch.setattr(backup_mod, "get_backup_manager", lambda: _OkManager())
        app = FastAPI()
        app.include_router(backup_mod.router)
        app.dependency_overrides[admin_router_mod.verify_admin_api_key] = lambda: True
        return TestClient(app, raise_server_exceptions=False)

    def test_oversize_422_and_tmp_cleaned(self, monkeypatch):
        """L12 定向: 超过上限返回 422，且临时文件被清理。"""
        import os
        import tempfile as tempfile_mod

        c = self._backup_client(monkeypatch)

        captured_paths = []
        real_ntf = tempfile_mod.NamedTemporaryFile

        def spy_ntf(*a, **k):
            f = real_ntf(*a, **k)
            captured_paths.append(f.name)
            return f

        # 端点内 import tempfile 绑定同一模块对象 → patch 生效；
        # 上限与分块大小同步压小以驱动多轮 read 循环
        monkeypatch.setattr(tempfile_mod, "NamedTemporaryFile", spy_ntf)
        monkeypatch.setattr(backup_mod, "_MAX_IMPORT_BYTES", 10)
        monkeypatch.setattr(backup_mod, "_IMPORT_CHUNK_SIZE", 8)

        r = c.post(
            "/backups/import",
            files={"file": ("big.zip", b"x" * 30, "application/zip")},
        )
        assert r.status_code == 422
        for p in captured_paths:
            assert not os.path.exists(p)  # tmp 已清理

    def test_within_limit_streams_ok(self, monkeypatch):
        c = self._backup_client(monkeypatch)
        r = c.post(
            "/backups/import",
            files={"file": ("b.zip", b"PK\x03\x04", "application/zip")},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "success"