"""CX-O-Autonomy REST 路由测试：/api/autonomy/* 端点。

覆盖：
① GET  /autonomy/status  manager 注入且启用返回状态形状（jsonschema 校验对齐 state 契约）
② GET  /autonomy/status  manager 为 None / 未启用 返回 {"status": "disabled"}（200 不抛错）
③ POST /autonomy/control enable/disable/emergency_stop 合法 action 生效（spy manager 断言调用）
④ POST /autonomy/control 非法 action 返回 400
⑤ GET  /autonomy/audit  返回 {items, total}（AuditStore 未装配返回空）
⑥ GET  /autonomy/config  返回 UnifiedConfig.autonomy 节（Task 6.2 迁移，未装配也可读）
⑦ PUT  /autonomy/config  局部更新持久化 settings / 非法字段 422 / 同步 manager.config

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
    """构造仅挂载 autonomy 路由的 FastAPI 测试客户端（/api 前缀）。

    C5: control/config 写端点已挂管理员鉴权，测试经依赖覆盖放行
    （本文件聚焦控制/配置逻辑，鉴权行为由 test_admin_router 覆盖）。
    """
    from server.api.routers.admin import verify_admin_api_key

    app = FastAPI()
    app.include_router(autonomy_router.router, prefix="/api")
    app.dependency_overrides[verify_admin_api_key] = lambda: True
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
        # 无装配入口但 app 有 services → enable 走运行时装配（setup_autonomy 成功）并回填。
        # Task 6.2：开关持久化已改写 UnifiedConfig settings——经 CXO_CONFIG 指向 tmp
        # 隔离 Settings 单例，防测试写真实 config.json。
        import server.autonomy.main as autonomy_main
        from server import config as config_module

        monkeypatch.setenv("CXO_CONFIG", str(tmp_path / "config.json"))
        config_module.Settings.reset()
        try:
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

            r = client.post("/api/autonomy/control", json={"action": "enable"})
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok"
            assert body["state"]["status"] == "running"
            assert autonomy_router.get_autonomy_manager() is fake
            # 开关状态已持久化到 UnifiedConfig（settings 节 enabled=True）
            assert config_module.get_settings().config.autonomy.enabled is True
        finally:
            config_module.Settings.reset()


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
# Task 6.2：配置唯一真相源为 UnifiedConfig（settings 单例），不再依赖 manager 装配——
# 未装配也可读（前端一级导航需要）。经 CXO_CONFIG 指向 tmp 隔离 Settings 单例，
# 防测试读写真实 config.json。
@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    from server import config as config_module

    monkeypatch.setenv("CXO_CONFIG", str(tmp_path / "config.json"))
    config_module.Settings.reset()
    yield config_module.get_settings()
    config_module.Settings.reset()


class TestGetConfig:
    def test_config_returns_settings_section(self, client, isolated_settings):
        isolated_settings.config.autonomy.agent_id = "测试人设"
        isolated_settings.config.autonomy.enabled = True
        r = client.get("/api/autonomy/config")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["agent_id"] == "测试人设"
        assert body["loop_interval_minutes"] == 15
        assert body["budget"]["daily_token_limit"] == 2000000

    def test_config_available_without_manager(self, client, isolated_settings):
        # 未装配（manager 为 None）也可读：返回 settings 节默认值（200，不再 404）
        r = client.get("/api/autonomy/config")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["agent_id"] == "default"


# ================================================================ ⑦ PUT /autonomy/config
class TestPutConfig:
    def test_config_put_partial_update(self, client, isolated_settings):
        r = client.put("/api/autonomy/config", json={"budget": {"overspend_mode": "low_cost"}})
        assert r.status_code == 200
        body = r.json()
        assert body["budget"]["overspend_mode"] == "low_cost"
        # 未提交字段保留默认/原值（深度合并 + 自动补齐）
        assert body["budget"]["daily_token_limit"] == 2000000
        assert body["enabled"] is False
        # 已持久化到 UnifiedConfig（settings 内存态 + config.json 磁盘态）
        assert isolated_settings.config.autonomy.budget.overspend_mode == "low_cost"

    def test_config_put_syncs_manager_runtime_config(self, client, isolated_settings, tmp_path):
        # manager 已装配时 PUT 同步 manager.config（映射回 AutonomyConfig，运行时语义）
        from server.autonomy.config import AutonomyConfig

        m = SpyManager()
        m.config = AutonomyConfig(store_path=str(tmp_path), enabled=True)
        autonomy_router.set_autonomy_manager(m)
        r = client.put("/api/autonomy/config", json={"agent_id": "运行时同步"})
        assert r.status_code == 200
        assert r.json()["agent_id"] == "运行时同步"
        assert isinstance(m.config, AutonomyConfig)
        assert m.config.agent_id == "运行时同步"

    def test_config_put_invalid_field_422(self, client, isolated_settings):
        r = client.put("/api/autonomy/config", json={"unknown_field": 1})
        assert r.status_code == 422

    def test_config_put_invalid_enum_422(self, client, isolated_settings):
        r = client.put("/api/autonomy/config", json={"budget": {"overspend_mode": "explode"}})
        assert r.status_code == 422

    def test_config_put_invalid_time_422(self, client, isolated_settings):
        r = client.put("/api/autonomy/config", json={"schedule": {"wake_time": "25:99"}})
        assert r.status_code == 422
