"""CX-O-Dream REST 路由测试：/api/dream/* 端点。

覆盖：
① GET  /dream/status  未装配/未启用返回 {"status":"disabled"}（200 不抛错）；启用返回引擎状态
② POST /dream/trigger 未启用返回 {"status":"disabled"}；启用调用 engine.run_session（默认/自定义 agent）
③ GET  /dream/list    未启用返回空列表；启用分页 + state 过滤
④ POST /dream/{id}/confirm  固化返回 memory_id；候选不存在/未启用 404
⑤ POST /dream/{id}/reject   否定返回 ok（reason 透传）；候选不存在/未启用 404
⑥ DELETE /dream/session/{id} 会话回滚返回 {purged:n}（红线 R5）
⑦ POST /dream/purge  返回 {purged_memories, purged_buffer}
⑧ GET  /dream/config  返回配置（UnifiedConfig.dream 节，Task 6.2 迁移，不依赖引擎）
⑨ PUT  /dream/config  非法 422 / 合法更新持久化 settings + GET 往返 / enabled 开关通知引擎 start/stop
⑩ GET/PUT /dream/config trigger 触发闸门子节：PUT 合法 trigger 往返（响应/GET/
   settings/config.json 均含该值）/ 非法值 422（越界 probability / 未知字段）/
   旧配置（dream 节无 trigger 数据）GET 自动补默认 trigger

运行：python -m pytest tests/test_dream_router.py -q
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import dream as dream_router
from server.api.routers.admin import verify_admin_api_key
from server.autonomy.dream.config import DreamConfig


# ================================================================ 假引擎
class FakeBuffer:
    def __init__(self):
        self.items = [
            {
                "id": 1, "dream_session_id": "s1", "agent_id": "default",
                "candidate_content": "梦里在森林漫步", "decision": "pending",
                "lucidity_score": 0.6, "created_at": "2026-08-23T01:00:00",
                "expires_at": "2026-08-26T01:00:00",
            },
            {
                "id": 2, "dream_session_id": "s2", "agent_id": "default",
                "candidate_content": "梦见海边的落日", "decision": "rejected",
                "lucidity_score": 0.4, "created_at": "2026-08-23T02:00:00",
                "expires_at": "2026-09-22T02:00:00",
            },
        ]

    def list(self, agent_id="default", decision=None, limit=50, offset=0):
        items = [i for i in self.items if i["agent_id"] == agent_id]
        if decision is not None:
            items = [i for i in items if i["decision"] == decision]
        return items[offset:offset + limit]

    def count(self, agent_id="default", decision=None):
        items = [i for i in self.items if i["agent_id"] == agent_id]
        if decision is not None:
            items = [i for i in items if i["decision"] == decision]
        return len(items)


class FakeMemoryManager:
    def __init__(self, purged=2):
        self.purged = purged

    def purge_dream_session(self, session_id, agent_id="default"):
        return self.purged


class FakeConsolidator:
    def __init__(self, memory_id=42):
        self.memory_id = memory_id
        self.last_reason = None
        self.memory_manager = FakeMemoryManager()

    def consolidate(self, buffer_id, agent_id="default"):
        if buffer_id == 999:
            return None
        return self.memory_id

    def reject(self, buffer_id, agent_id="default", reason=""):
        self.last_reason = reason
        if buffer_id == 999:
            return False
        return True


class FakePurgeJob:
    async def run(self, agent_id="default"):
        return {"purged_memories": 3, "purged_buffer": 1}


class FakeEngine:
    def __init__(self, enabled=True):
        self.config = DreamConfig(enabled=enabled)
        self.buffer = FakeBuffer()
        self.consolidator = FakeConsolidator()
        self.purge_job = FakePurgeJob()
        self.calls = []

    async def run_session(self, agent_id="default"):
        self.calls.append(("run_session", agent_id))
        return {"generated": 3, "approved": 2, "rejected": 1}

    def get_status(self):
        return {
            "status": "idle",
            "enabled": True,
            "last_session_at": "2026-08-23T01:00:00",
            "stats": {"sessions": 1, "generated": 3, "approved": 2, "rejected": 1, "purges": 0},
        }

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")


# ================================================================ fixtures
@pytest.fixture(autouse=True)
def _reset_router_globals():
    """每个测试前后重置路由模块全局注入，避免跨测试污染。"""
    dream_router.set_dream_engine(None)
    yield
    dream_router.set_dream_engine(None)


@pytest.fixture
def client():
    """构造仅挂载 dream 路由的 FastAPI 测试客户端（/api 前缀）。

    写路径（trigger/confirm/reject/purge_session/purge/config PUT）已补挂
    verify_admin_api_key：既有用例经 dependency_overrides 放行，403 场景由
    TestDreamWriteAuthRequired 单独覆盖（读路径 status/list/config GET 保持开放）。
    """
    app = FastAPI()
    app.include_router(dream_router.router, prefix="/api")
    app.dependency_overrides[verify_admin_api_key] = lambda: True
    return TestClient(app)


@pytest.fixture
def engine():
    return FakeEngine()


def _patch_config_io(monkeypatch, tmp_path):
    """将路由的 load_config/save_config 指向临时目录，避免污染真实 data/dream_config.json。"""
    cfg_file = tmp_path / "dream_config.json"

    def fake_load(store_path=""):
        if not cfg_file.exists():
            return DreamConfig()
        return DreamConfig.model_validate(json.loads(cfg_file.read_text(encoding="utf-8")))

    def fake_save(config, store_path=""):
        cfg_file.write_text(
            json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(cfg_file)

    monkeypatch.setattr(dream_router, "load_config", fake_load)
    monkeypatch.setattr(dream_router, "save_config", fake_save)


# ================================================================ ① GET /dream/status
class TestStatus:
    def test_status_disabled_when_no_engine(self, client):
        r = client.get("/api/dream/status")
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}

    def test_status_disabled_when_engine_disabled(self, client, engine):
        engine.config.enabled = False
        dream_router.set_dream_engine(engine)
        r = client.get("/api/dream/status")
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}

    def test_status_returns_engine_status(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.get("/api/dream/status")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "idle"
        assert body["enabled"] is True


# ================================================================ ② POST /dream/trigger
class TestTrigger:
    def test_trigger_disabled_when_no_engine(self, client):
        r = client.post("/api/dream/trigger")
        assert r.status_code == 200
        assert r.json() == {"status": "disabled"}

    def test_trigger_calls_run_session_default_agent(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.post("/api/dream/trigger")
        assert r.status_code == 200
        assert r.json() == {"generated": 3, "approved": 2, "rejected": 1}
        assert ("run_session", "default") in engine.calls

    def test_trigger_with_agent_id(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.post("/api/dream/trigger", params={"agent_id": "agentA"})
        assert r.status_code == 200
        assert ("run_session", "agentA") in engine.calls


# ================================================================ ③ GET /dream/list
class TestList:
    def test_list_empty_when_no_engine(self, client):
        r = client.get("/api/dream/list")
        assert r.status_code == 200
        assert r.json() == {"items": [], "total": 0}

    def test_list_returns_items(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.get("/api/dream/list")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    def test_list_filters_by_state(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.get("/api/dream/list", params={"state": "pending"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["decision"] == "pending"

    def test_list_pagination_total_is_full_match_count(self, client, engine):
        """分页时 total 应为总匹配数（不受 limit/offset 影响），而非当前页条数。"""
        dream_router.set_dream_engine(engine)
        r = client.get("/api/dream/list", params={"limit": 1, "offset": 1})
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 1          # 当前页 1 条
        assert body["total"] == 2               # 总匹配 2 条（修复前误为 len(items)=1）
        assert body["items"][0]["id"] == 2


# ================================================================ ④ POST /dream/{id}/confirm
class TestConfirm:
    def test_confirm_returns_memory_id(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.post("/api/dream/1/confirm")
        assert r.status_code == 200
        assert r.json() == {"memory_id": 42}

    def test_confirm_404_when_candidate_missing(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.post("/api/dream/999/confirm")
        assert r.status_code == 404

    def test_confirm_404_when_no_engine(self, client):
        r = client.post("/api/dream/1/confirm")
        assert r.status_code == 404


# ================================================================ ⑤ POST /dream/{id}/reject
class TestReject:
    def test_reject_returns_ok_and_passes_reason(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.post("/api/dream/1/reject", json={"reason": "与事实不符"})
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "buffer_id": 1}
        assert engine.consolidator.last_reason == "与事实不符"

    def test_reject_without_reason_body(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.post("/api/dream/1/reject")
        assert r.status_code == 200
        assert engine.consolidator.last_reason == ""

    def test_reject_404_when_candidate_missing(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.post("/api/dream/999/reject", json={"reason": "x"})
        assert r.status_code == 404

    def test_reject_404_when_no_engine(self, client):
        r = client.post("/api/dream/1/reject", json={"reason": "x"})
        assert r.status_code == 404


# ================================================================ ⑥ DELETE /dream/session/{id}
class TestSessionRollback:
    def test_session_rollback_returns_purged(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.delete("/api/dream/session/sess_001")
        assert r.status_code == 200
        assert r.json() == {"purged": 2}

    def test_session_404_when_no_engine(self, client):
        r = client.delete("/api/dream/session/sess_001")
        assert r.status_code == 404


# ================================================================ ⑦ POST /dream/purge
class TestPurge:
    def test_purge_returns_counts(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.post("/api/dream/purge")
        assert r.status_code == 200
        assert r.json() == {"purged_memories": 3, "purged_buffer": 1}

    def test_purge_404_when_no_engine(self, client):
        r = client.post("/api/dream/purge")
        assert r.status_code == 404


# ================================================================ ⑧⑨ GET/PUT /dream/config
# Task 6.2：配置唯一真相源为 UnifiedConfig（settings 单例）——经 CXO_CONFIG 指向
# tmp 隔离 Settings 单例，防测试读写真实 config.json。
@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    from server import config as config_module

    monkeypatch.setenv("CXO_CONFIG", str(tmp_path / "config.json"))
    config_module.Settings.reset()
    yield config_module.get_settings(), tmp_path / "config.json"
    config_module.Settings.reset()


class TestConfig:
    def test_get_config_returns_defaults(self, client, isolated_settings):
        settings, cfg_path = isolated_settings
        r = client.get("/api/dream/config")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["model"] == "summary"
        assert body["dream_temperature"] == 0.9
        assert body["schedule"]["sleep_time"] == "02:00"

    def test_put_config_invalid_field_422(self, client, isolated_settings):
        r = client.put("/api/dream/config", json={"unknown_field": 1})
        assert r.status_code == 422

    def test_put_config_invalid_time_422(self, client, isolated_settings):
        r = client.put("/api/dream/config", json={"schedule": {"wake_time": "25:99"}})
        assert r.status_code == 422

    def test_put_config_valid_update_persists_and_roundtrip(self, client, isolated_settings):
        settings, cfg_path = isolated_settings
        r = client.put(
            "/api/dream/config",
            json={"dream_temperature": 0.7, "candidates_per_session": 5, "enabled": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["dream_temperature"] == 0.7
        assert body["candidates_per_session"] == 5
        assert body["enabled"] is True
        # 未提交字段保留默认（深度合并 + 自动补齐）
        assert body["model"] == "summary"
        assert body["schedule"]["wake_time"] == "08:00"
        # 已持久化到 UnifiedConfig（settings 内存态 + config.json 磁盘态）
        assert settings.config.dream.dream_temperature == 0.7
        assert cfg_path.exists()
        persisted = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert persisted["dream"]["dream_temperature"] == 0.7
        # GET 往返
        r2 = client.get("/api/dream/config")
        assert r2.status_code == 200
        assert r2.json()["dream_temperature"] == 0.7

    def test_put_config_enabled_false_stops_engine(self, client, isolated_settings, engine):
        dream_router.set_dream_engine(engine)
        r = client.put("/api/dream/config", json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert "stop" in engine.calls

    def test_put_config_enabled_true_starts_engine(self, client, isolated_settings, engine):
        dream_router.set_dream_engine(engine)
        r = client.put("/api/dream/config", json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        assert "start" in engine.calls
        # 引擎侧 config 映射回 DreamConfig（类型契约保持）
        from server.autonomy.dream.config import DreamConfig

        assert isinstance(engine.config, DreamConfig)


# ================================================================ ⑩ trigger 触发闸门子节
class TestConfigTrigger:
    def test_put_config_trigger_roundtrip(self, client, isolated_settings):
        """PUT 合法 trigger：响应、settings 内存态、config.json 磁盘态、GET 均含该值。"""
        settings, cfg_path = isolated_settings
        r = client.put(
            "/api/dream/config",
            json={
                "trigger": {
                    "emotion_enabled": True,
                    "emotion_threshold": 0.8,
                    "probability": 0.5,
                }
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["trigger"]["emotion_enabled"] is True
        assert body["trigger"]["emotion_threshold"] == 0.8
        assert body["trigger"]["probability"] == 0.5
        # 未提交的 trigger 字段保留默认（深度合并 + 自动补齐）
        assert body["trigger"]["emotion_window_hours"] == 24
        assert body["trigger"]["emotion_min_events"] == 1
        # 已持久化到 UnifiedConfig（settings 内存态 + config.json 磁盘态）
        assert settings.config.dream.trigger.emotion_enabled is True
        persisted = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert persisted["dream"]["trigger"]["probability"] == 0.5
        # GET 往返
        r2 = client.get("/api/dream/config")
        assert r2.status_code == 200
        trigger = r2.json()["trigger"]
        assert trigger["emotion_enabled"] is True
        assert trigger["emotion_threshold"] == 0.8
        assert trigger["probability"] == 0.5

    def test_put_config_trigger_invalid_probability_422(self, client, isolated_settings):
        r = client.put("/api/dream/config", json={"trigger": {"probability": 1.5}})
        assert r.status_code == 422

    def test_put_config_trigger_unknown_field_422(self, client, isolated_settings):
        """trigger 子节 extra="forbid"：未知字段 422。"""
        r = client.put("/api/dream/config", json={"trigger": {"unknown": 1}})
        assert r.status_code == 422

    def test_get_config_legacy_without_trigger_fills_defaults(self, client, isolated_settings):
        """旧配置（dream 节无 trigger 数据）GET 自动补默认 trigger。"""
        settings, cfg_path = isolated_settings
        cfg_path.write_text(
            json.dumps({"dream": {"enabled": True}}, ensure_ascii=False),
            encoding="utf-8",
        )
        settings.reload_config()
        assert settings.config.dream.enabled is True
        r = client.get("/api/dream/config")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["trigger"]["emotion_enabled"] is False
        assert body["trigger"]["emotion_threshold"] == 0.7
        assert body["trigger"]["emotion_window_hours"] == 24
        assert body["trigger"]["emotion_min_events"] == 1
        assert body["trigger"]["probability"] == 1.0


# ================================================================ 写路径鉴权（鉴权漏挂簇修复补充用例）
# verify_admin_api_key 校验失败统一抛 403（项目既有口径，对齐 test_stats_interrupt.py）；
# 本组用例不挂 dependency_overrides，真实走到密钥校验依赖。
class TestDreamWriteAuthRequired:
    @staticmethod
    def _raw_client() -> TestClient:
        app = FastAPI()
        app.include_router(dream_router.router, prefix="/api")
        return TestClient(app, raise_server_exceptions=False)

    def test_trigger_requires_auth(self):
        r = self._raw_client().post("/api/dream/trigger")
        assert r.status_code == 403

    def test_confirm_requires_auth(self):
        r = self._raw_client().post("/api/dream/1/confirm")
        assert r.status_code == 403

    def test_reject_requires_auth(self):
        r = self._raw_client().post("/api/dream/1/reject", json={"reason": "x"})
        assert r.status_code == 403

    def test_purge_session_requires_auth(self):
        r = self._raw_client().delete("/api/dream/session/sess_001")
        assert r.status_code == 403

    def test_purge_requires_auth(self):
        r = self._raw_client().post("/api/dream/purge")
        assert r.status_code == 403

    def test_put_config_requires_auth(self):
        r = self._raw_client().put("/api/dream/config", json={"enabled": True})
        assert r.status_code == 403

    def test_read_paths_stay_open(self):
        # 读路径回归：status / list / config GET 不挂鉴权，无密钥仍 200
        c = self._raw_client()
        assert c.get("/api/dream/status").status_code == 200
        assert c.get("/api/dream/list").status_code == 200
        assert c.get("/api/dream/config").status_code == 200
