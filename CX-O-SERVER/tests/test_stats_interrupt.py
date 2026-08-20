"""server.api.routers.stats 的 AI 插话打断端点单测。

monkeypatch server.api.routers.admin.ADMIN_API_KEY + X-API-Key header，覆盖：
- GET /api/stats/interrupt：鉴权（未配置 key 403 / 缺失 key 403 / 有效 key 200 且返回 get_stats 结构）
- POST /api/stats/interrupt/enable：鉴权（缺失 key 403）与热更新生效（模块单例 enabled/speech_end_fallback 被改）

运行：python -m pytest tests/test_stats_interrupt.py -v
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import stats as stats_router_mod
from server.api.routers import admin as admin_router_mod
from server.services.agent_interrupt_user import get_agent_interrupt_module


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(admin_router_mod, "ADMIN_API_KEY", "secret_key")
    app = FastAPI()
    app.include_router(stats_router_mod.router, prefix="/api")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def no_key_client(monkeypatch):
    monkeypatch.setattr(admin_router_mod, "ADMIN_API_KEY", "")
    app = FastAPI()
    app.include_router(stats_router_mod.router, prefix="/api")
    return TestClient(app, raise_server_exceptions=False)


class TestGetInterruptStats:
    def test_no_key_configured_403(self, no_key_client):
        r = no_key_client.get("/api/stats/interrupt", headers={"X-API-Key": "x"})
        assert r.status_code == 403

    def test_missing_header_403(self, client):
        r = client.get("/api/stats/interrupt")
        assert r.status_code == 403

    def test_valid_key_returns_stats(self, client):
        r = client.get("/api/stats/interrupt", headers={"X-API-Key": "secret_key"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        data = body["data"]
        assert "total_judgments" in data
        assert "decisions" in data
        assert "interrupts_triggered" in data


class TestUpdateInterruptEnable:
    def test_requires_auth(self, client):
        r = client.post("/api/stats/interrupt/enable", json={"enabled": False})
        assert r.status_code == 403

    def test_hot_update_enabled_and_fallback(self, client):
        module = get_agent_interrupt_module()
        orig = (module.enabled, module.speech_end_fallback)
        try:
            r = client.post(
                "/api/stats/interrupt/enable",
                headers={"X-API-Key": "secret_key"},
                json={"enabled": False, "speech_end_fallback": True},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "success"
            assert body["data"]["enabled"] is False
            assert body["data"]["speech_end_fallback"] is True
            # 热更新真实生效在模块单例上
            assert module.enabled is False
            assert module.speech_end_fallback is True
        finally:
            # 恢复原状态，避免污染其他测试
            module.enabled = orig[0]
            module.speech_end_fallback = orig[1]

    def test_hot_update_partial_fields_keeps_others(self, client):
        # 仅传 speech_end_fallback：enabled 保持原值不变
        module = get_agent_interrupt_module()
        orig = (module.enabled, module.speech_end_fallback)
        try:
            r = client.post(
                "/api/stats/interrupt/enable",
                headers={"X-API-Key": "secret_key"},
                json={"speech_end_fallback": False},
            )
            assert r.status_code == 200
            body = r.json()["data"]
            assert module.enabled == orig[0]  # enabled 未被改动
            assert module.speech_end_fallback is False
            assert body["enabled"] == module.enabled
            assert body["speech_end_fallback"] is False
        finally:
            module.enabled = orig[0]
            module.speech_end_fallback = orig[1]
