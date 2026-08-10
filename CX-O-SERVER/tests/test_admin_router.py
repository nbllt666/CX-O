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
    monkeypatch.setattr(admin_router_mod, "ADMIN_API_KEY", "secret_key")
    monkeypatch.setattr("server.config.get_settings", lambda: FakeSettings())

    app = FastAPI()
    app.include_router(admin_router_mod.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def no_key_client(monkeypatch):
    monkeypatch.setattr(admin_router_mod, "ADMIN_API_KEY", "")
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