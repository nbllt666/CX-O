"""CX-O-Dream REST 路由测试：/api/dream/* 端点。

覆盖：
① GET  /dream/status  未装配/未启用返回 {"status":"disabled"}（200 不抛错）；启用返回引擎状态
② POST /dream/trigger 未启用返回 {"status":"disabled"}；启用调用 engine.run_session（默认/自定义 agent）
③ GET  /dream/list    未启用返回空列表；启用分页 + state 过滤
④ POST /dream/{id}/confirm  固化返回 memory_id；候选不存在/未启用 404
⑤ POST /dream/{id}/reject   否定返回 ok（reason 透传）；候选不存在/未启用 404
⑥ DELETE /dream/session/{id} 会话回滚返回 {purged:n}（红线 R5）
⑦ POST /dream/purge  返回 {purged_memories, purged_buffer}
⑧ GET  /dream/config  返回配置（独立配置模块，不依赖引擎）
⑨ PUT  /dream/config  非法 422 / 合法更新持久化 + GET 往返 / enabled 开关通知引擎 start/stop

运行：python -m pytest tests/test_dream_router.py -q
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import dream as dream_router
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
    """构造仅挂载 dream 路由的 FastAPI 测试客户端（/api 前缀）。"""
    app = FastAPI()
    app.include_router(dream_router.router, prefix="/api")
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

    def test_list_pagination(self, client, engine):
        dream_router.set_dream_engine(engine)
        r = client.get("/api/dream/list", params={"limit": 1, "offset": 1})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
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
class TestConfig:
    def test_get_config_returns_defaults(self, client, monkeypatch, tmp_path):
        _patch_config_io(monkeypatch, tmp_path)
        r = client.get("/api/dream/config")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["model"] == "summary"
        assert body["dream_temperature"] == 0.9
        assert body["schedule"]["sleep_time"] == "02:00"

    def test_put_config_invalid_field_422(self, client, monkeypatch, tmp_path):
        _patch_config_io(monkeypatch, tmp_path)
        r = client.put("/api/dream/config", json={"unknown_field": 1})
        assert r.status_code == 422

    def test_put_config_invalid_time_422(self, client, monkeypatch, tmp_path):
        _patch_config_io(monkeypatch, tmp_path)
        r = client.put("/api/dream/config", json={"schedule": {"wake_time": "25:99"}})
        assert r.status_code == 422

    def test_put_config_valid_update_persists_and_roundtrip(self, client, monkeypatch, tmp_path):
        _patch_config_io(monkeypatch, tmp_path)
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
        # 已持久化
        assert (tmp_path / "dream_config.json").exists()
        # GET 往返
        r2 = client.get("/api/dream/config")
        assert r2.status_code == 200
        assert r2.json()["dream_temperature"] == 0.7

    def test_put_config_enabled_false_stops_engine(self, client, monkeypatch, tmp_path, engine):
        _patch_config_io(monkeypatch, tmp_path)
        dream_router.set_dream_engine(engine)
        r = client.put("/api/dream/config", json={"enabled": False})
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        assert "stop" in engine.calls

    def test_put_config_enabled_true_starts_engine(self, client, monkeypatch, tmp_path, engine):
        _patch_config_io(monkeypatch, tmp_path)
        engine.config.enabled = False
        dream_router.set_dream_engine(engine)
        r = client.put("/api/dream/config", json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True
        assert "start" in engine.calls
