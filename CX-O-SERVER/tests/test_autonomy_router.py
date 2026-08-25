"""CX-O-Autonomy REST 路由测试：/api/autonomy/* 端点。

覆盖：
① GET  /autonomy/status  manager 注入且启用返回状态形状（jsonschema 校验对齐 state 契约）
② GET  /autonomy/status  manager 为 None / 未启用 返回 {"status": "disabled"}（200 不抛错）
③ POST /autonomy/control enable/disable/emergency_stop 合法 action 生效（spy manager 断言调用）
④ POST /autonomy/control 非法 action 返回 400
⑤ GET  /autonomy/audit  返回 {items, total}（AuditStore 未装配返回空）
⑥ GET  /autonomy/config  返回配置；未装配 404
⑦ PUT  /autonomy/config  局部更新成功 / 非法字段 422 / 未装配 404

运行：python -m pytest tests/test_autonomy_router.py -q
"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import validate

from server.api.routers import autonomy as autonomy_router
from server.autonomy.config import AutonomyConfig
from server.autonomy.manager import AutonomyManager
from server.autonomy.safety.audit import AuditStore

# 公共契约目录（public/）：c:\CX-O\public\
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"
STATE_SCHEMA = json.loads(
    (PUBLIC_DIR / "schema" / "autonomy_state.schema.json").read_text(encoding="utf-8")
)


class SpyManager(AutonomyManager):
    """记录控制方法调用的真实 AutonomyManager（对齐真实行为 + 调用断言）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    def enable(self):
        self.calls.append("enable")
        super().enable()

    def disable(self):
        self.calls.append("disable")
        super().disable()

    def pause(self):
        self.calls.append("pause")
        super().pause()

    def resume(self):
        self.calls.append("resume")
        super().resume()

    def emergency_stop(self):
        self.calls.append("emergency_stop")
        super().emergency_stop()


@pytest.fixture(autouse=True)
def _reset_router_globals():
    """每个测试前后重置路由模块全局注入，避免跨测试污染。"""
    autonomy_router.set_autonomy_manager(None)
    autonomy_router.set_audit_store(None)
    yield
    autonomy_router.set_autonomy_manager(None)
    autonomy_router.set_audit_store(None)


@pytest.fixture
def client():
    """构造仅挂载 autonomy 路由的 FastAPI 测试客户端（/api 前缀）。"""
    app = FastAPI()
    app.include_router(autonomy_router.router, prefix="/api")
    return TestClient(app)


def _manager_with_config(tmp_path, **kwargs) -> SpyManager:
    """构造带临时存储目录配置的 SpyManager。"""
    m = SpyManager()
    m.config = AutonomyConfig(store_path=str(tmp_path), **kwargs)
    return m


# ================================================================ ① GET /autonomy/status
class TestStatus:
    def test_status_shape_with_manager(self, client):
        m = SpyManager()
        m.enable()
        autonomy_router.set_autonomy_manager(m)
        r = client.get("/api/autonomy/status")
        assert r.status_code == 200
        body = r.json()
        validate(instance=body, schema=STATE_SCHEMA)
        assert body["status"] == "running"
        assert body["motivations"] == {
            "curiosity": 0.2, "social_need": 0.2, "creative_drive": 0.2, "fatigue": 0.0,
        }
        assert body["daily_budget_used_tokens"] == 0

    # ================================================================ ② 未装配/未启用 → disabled
    def test_status_disabled_when_no_manager(self, client):
        r = client.get("/api/autonomy/status")
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}

    def test_status_disabled_when_manager_not_enabled(self, client):
        autonomy_router.set_autonomy_manager(SpyManager())
        r = client.get("/api/autonomy/status")
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}


# ================================================================ ③④ POST /autonomy/control
class TestControl:
    @pytest.mark.parametrize(
        "action,expected_status",
        [
            ("enable", "running"),
            ("disable", "paused"),
            ("emergency_stop", "error"),
        ],
    )
    def test_control_valid_action_effect_and_calls(self, client, action, expected_status):
        m = SpyManager()
        autonomy_router.set_autonomy_manager(m)
        r = client.post("/api/autonomy/control", json={"action": action})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["state"]["status"] == expected_status
        assert m.calls == [action]

    def test_control_invalid_action_400(self, client):
        autonomy_router.set_autonomy_manager(SpyManager())
        r = client.post("/api/autonomy/control", json={"action": "destroy"})
        assert r.status_code == 400

    def test_control_enable_no_manager_400(self, client, monkeypatch):
        # 无装配入口（get_autonomy_manager 返回 None）→ 400
        import server.autonomy.main as autonomy_main

        monkeypatch.setattr(autonomy_main, "_autonomy_manager", None)
        r = client.post("/api/autonomy/control", json={"action": "enable"})
        assert r.status_code == 400

    def test_control_enable_bootstraps_when_assembled(self, client, monkeypatch):
        # manager 为 None 但装配入口已有单例 → enable 生效并回填模块级引用
        import server.autonomy.main as autonomy_main

        fake = SpyManager()
        monkeypatch.setattr(autonomy_main, "get_autonomy_manager", lambda: fake)
        r = client.post("/api/autonomy/control", json={"action": "enable"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["state"]["status"] == "running"
        assert autonomy_router.get_autonomy_manager() is fake

    def test_control_enable_runtime_assembles_with_services(self, client, tmp_path, monkeypatch):
        # 无装配入口但 app 有 services → enable 走运行时装配（setup_autonomy 成功）并回填
        import server.autonomy.main as autonomy_main

        fake_services = object()
        client.app.state.services = fake_services

        fake = SpyManager()
        fake.config = AutonomyConfig(enabled=True, store_path=str(tmp_path))

        async def _fake_setup(services):
            assert services is fake_services
            autonomy_main._autonomy_manager = fake
            return fake

        monkeypatch.setattr(autonomy_main, "_autonomy_manager", None)
        monkeypatch.setattr(autonomy_main, "setup_autonomy", _fake_setup)
        # 拦截配置读写，避免真实落盘默认存储目录
        monkeypatch.setattr(autonomy_router, "save_config", lambda cfg: str(tmp_path / "cfg.json"))
        monkeypatch.setattr(
            "server.autonomy.config.load_config",
            lambda store_path="": AutonomyConfig(enabled=False, store_path=str(tmp_path)),
        )

        r = client.post("/api/autonomy/control", json={"action": "enable"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["state"]["status"] == "running"
        assert autonomy_router.get_autonomy_manager() is fake


# ================================================================ ⑤ GET /autonomy/audit
class TestAudit:
    def test_audit_returns_items_and_total(self, client, tmp_path):
        store = AuditStore(path=str(tmp_path / "audit_logs.jsonl"))
        store.append({"timestamp": "2026-08-22T10:00:00Z", "action": "write_memory"})
        store.append(
            {"timestamp": "2026-08-22T10:01:00Z", "action": "search", "result": "success"}
        )
        autonomy_router.set_audit_store(store)
        r = client.get("/api/autonomy/audit")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        assert body["items"][0]["action"] == "write_memory"

    def test_audit_empty_when_no_store(self, client):
        r = client.get("/api/autonomy/audit")
        assert r.status_code == 200
        assert r.json() == {"items": [], "total": 0}


# ================================================================ ⑥ GET /autonomy/config
class TestGetConfig:
    def test_config_returns_config(self, client, tmp_path):
        m = _manager_with_config(tmp_path, enabled=True, agent_id="测试人设")
        autonomy_router.set_autonomy_manager(m)
        r = client.get("/api/autonomy/config")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["agent_id"] == "测试人设"
        assert body["loop_interval_minutes"] == 15
        assert body["budget"]["daily_token_limit"] == 2000000

    def test_config_404_when_no_manager(self, client):
        r = client.get("/api/autonomy/config")
        assert r.status_code == 404


# ================================================================ ⑦ PUT /autonomy/config
class TestPutConfig:
    def test_config_put_partial_update(self, client, tmp_path):
        m = _manager_with_config(tmp_path, enabled=True)
        autonomy_router.set_autonomy_manager(m)
        r = client.put("/api/autonomy/config", json={"budget": {"overspend_mode": "low_cost"}})
        assert r.status_code == 200
        body = r.json()
        assert body["budget"]["overspend_mode"] == "low_cost"
        # 未提交字段保留默认/原值（深度合并 + 自动补齐）
        assert body["budget"]["daily_token_limit"] == 2000000
        assert body["enabled"] is True
        # 已持久化到 store_path
        assert (tmp_path / "autonomy_config.json").exists()

    def test_config_put_invalid_field_422(self, client, tmp_path):
        autonomy_router.set_autonomy_manager(_manager_with_config(tmp_path))
        r = client.put("/api/autonomy/config", json={"unknown_field": 1})
        assert r.status_code == 422

    def test_config_put_invalid_enum_422(self, client, tmp_path):
        autonomy_router.set_autonomy_manager(_manager_with_config(tmp_path))
        r = client.put("/api/autonomy/config", json={"budget": {"overspend_mode": "explode"}})
        assert r.status_code == 422

    def test_config_put_invalid_time_422(self, client, tmp_path):
        autonomy_router.set_autonomy_manager(_manager_with_config(tmp_path))
        r = client.put("/api/autonomy/config", json={"schedule": {"wake_time": "25:99"}})
        assert r.status_code == 422

    def test_config_put_404_when_no_manager(self, client):
        r = client.put("/api/autonomy/config", json={"enabled": True})
        assert r.status_code == 404
