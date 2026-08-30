"""server.api.routers.decision 路由测试。

用 FastAPI TestClient + 注入假 DecisionCore（monkeypatch _get_decision_core），
隔离真实 DecisionCore。覆盖 6 决策点端点 + rejected_content 管理端点 + 异常映射。

运行：python -m pytest tests/test_decision_router.py -v
"""
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import decision as decision_router_mod
from server.core.decision.decision_core import RubricSnapshot


# --------------------------------------------------------------------------- #
# 假 DecisionCore —— 记录调用 + 可配置异常
# --------------------------------------------------------------------------- #
class SimpleDecision:
    """模拟 StorageDecision/FinalDecision 的 model_dump。"""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def model_dump(self) -> Dict[str, Any]:
        return self._data


class FakeDecisionCore:
    def __init__(self):
        self.calls = []
        self.errors: Dict[str, Exception] = {}
        self.results: Dict[str, Any] = {}

    def _run(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if name in self.errors:
            raise self.errors[name]
        return self.results.get(name, SimpleDecision({"ok": True}))

    def _load_rubric(self, agent_id: str) -> RubricSnapshot:
        return RubricSnapshot(
            importance_threshold_permanent=0.7,
            quality_reject_threshold=0.3,
            max_redistill_turns=2,
            ask_user_confidence_threshold=0.5,
            cross_validate_sources=[],
        )

    def decide_location(self, **kwargs):
        return self._run("decide_location", **kwargs)

    def decide_metadata(self, **kwargs):
        return self._run("decide_metadata", **kwargs)

    def decide_ask_user(self, **kwargs):
        return self._run("decide_ask_user", **kwargs)

    def decide_redistill(self, **kwargs):
        return self._run("decide_redistill", **kwargs)

    def decide_cross_validate(self, **kwargs):
        return self._run("decide_cross_validate", **kwargs)

    def decide_reject(self, **kwargs):
        return self._run("decide_reject", **kwargs)


class FakeMemoryManager:
    def __init__(self):
        self.write_calls = []
        self.get_rejected_calls = []
        self.cleanup_calls = []

    def write_with_decision(self, content, decision, metadata=None, source=None):
        self.write_calls.append((content, decision, metadata))
        # 返回形状对齐实现（decision_mixin.py write_with_decision）：
        # {"location", "memory_id", "rejected_id"}
        return {"location": "memories", "memory_id": 1, "rejected_id": None}

    def get_rejected_content(self, session_id, limit=50):
        self.get_rejected_calls.append((session_id, limit))
        return [{"session_id": session_id, "content": "x"}]

    def cleanup_expired_rejected_content(self, retention_days=30):
        self.cleanup_calls.append(retention_days)
        return 3


class FakeServiceState:
    def __init__(self):
        self.memory_manager = FakeMemoryManager()


RUBRIC = {
    "importance_threshold_permanent": 0.7,
    "quality_reject_threshold": 0.3,
    "max_redistill_turns": 2,
    "ask_user_confidence_threshold": 0.5,
    "cross_validate_sources": [],
}


@pytest.fixture
def client(monkeypatch):
    core = FakeDecisionCore()
    monkeypatch.setattr(decision_router_mod, "_get_decision_core", lambda: core)

    app = FastAPI()
    app.include_router(decision_router_mod.router)
    state = FakeServiceState()
    app.state.services = state
    return TestClient(app), core, state


# --------------------------------------------------------------------------- #
# 6 决策点端点
# --------------------------------------------------------------------------- #
class TestDecideLocation:
    def test_success_with_rubric(self, client):
        c, core, state = client
        core.results["decide_location"] = SimpleDecision({
            "decision_id": "d1", "session_id": "s1", "decision_point": "D1_LOCATION",
            "location": "memories", "memory_id": 1, "metadata": {},
            "reason": "ok", "quality_score": 0.8,
        })
        r = c.post("/decision/D1_LOCATION", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_FINALIZE"},
            "rubric": RUBRIC,
        })
        assert r.status_code == 200
        assert r.json()["location"] == "memories"
        name, args, kwargs = core.calls[0]
        assert name == "decide_location"
        assert kwargs["session_id"] == "s1"

    def test_success_with_agent_id(self, client):
        c, core, state = client
        core.results["decide_location"] = SimpleDecision({"location": "permanent_memories"})
        r = c.post("/decision/D1_LOCATION", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_FINALIZE"},
            "agent_id": "agent1",
        })
        assert r.status_code == 200

    def test_with_content_writes_memory(self, client):
        c, core, state = client
        core.results["decide_location"] = SimpleDecision({"location": "memories"})
        r = c.post("/decision/D1_LOCATION", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_FINALIZE"},
            "rubric": RUBRIC,
            "content": "记忆内容",
            "metadata": {"k": "v"},
        })
        assert r.status_code == 200
        assert "write_result" in r.json()
        assert len(state.memory_manager.write_calls) == 1

    def test_missing_rubric_value_error_422(self, client):
        c, core, state = client
        r = c.post("/decision/D1_LOCATION", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_FINALIZE"},
        })
        assert r.status_code == 422

    def test_key_error_404(self, client):
        c, core, state = client
        core.errors["decide_location"] = KeyError("rubric not found")
        r = c.post("/decision/D1_LOCATION", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_FINALIZE"},
            "rubric": RUBRIC,
        })
        assert r.status_code == 404

    def test_value_error_422(self, client):
        c, core, state = client
        core.errors["decide_location"] = ValueError("bad input")
        r = c.post("/decision/D1_LOCATION", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_FINALIZE"},
            "rubric": RUBRIC,
        })
        assert r.status_code == 422

    def test_runtime_error_500(self, client):
        c, core, state = client
        core.errors["decide_location"] = RuntimeError("boom")
        r = c.post("/decision/D1_LOCATION", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_FINALIZE"},
            "rubric": RUBRIC,
        })
        assert r.status_code == 500

    def test_connection_error_503(self, client):
        c, core, state = client
        core.errors["decide_location"] = ConnectionError("no llm")
        r = c.post("/decision/D1_LOCATION", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_FINALIZE"},
            "rubric": RUBRIC,
        })
        assert r.status_code == 503


class TestDecideMetadata:
    def test_success(self, client):
        c, core, state = client
        core.results["decide_metadata"] = SimpleDecision({"importance": 0.8, "tags": ["a"]})
        r = c.post("/decision/D2_METADATA", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_FINALIZE"},
        })
        assert r.status_code == 200
        assert "metadata" in r.json()
        name, args, kwargs = core.calls[0]
        assert name == "decide_metadata"

    def test_value_error_422(self, client):
        c, core, state = client
        core.errors["decide_metadata"] = ValueError("bad")
        r = c.post("/decision/D2_METADATA", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_FINALIZE"},
        })
        assert r.status_code == 422


class TestDecideAskUser:
    def test_success(self, client):
        c, core, state = client
        core.results["decide_ask_user"] = True
        r = c.post("/decision/D3_ASK_USER", json={
            "session_id": "s1", "llm_confidence": 0.2, "rubric": RUBRIC,
        })
        assert r.status_code == 200
        assert r.json()["should_ask_user"] is True
        name, args, kwargs = core.calls[0]
        assert name == "decide_ask_user"
        assert kwargs["llm_confidence"] == 0.2

    def test_missing_rubric_422(self, client):
        c, core, state = client
        r = c.post("/decision/D3_ASK_USER", json={
            "session_id": "s1", "llm_confidence": 0.2,
        })
        assert r.status_code == 422


class TestDecideRedistill:
    def test_success(self, client):
        c, core, state = client
        core.results["decide_redistill"] = False
        r = c.post("/decision/D4_REDISTILL", json={
            "session_id": "s1", "current_turn": 2, "rubric": RUBRIC,
        })
        assert r.status_code == 200
        assert r.json()["should_redistill"] is False
        name, args, kwargs = core.calls[0]
        assert name == "decide_redistill"
        assert kwargs["current_turn"] == 2


class TestDecideCrossValidate:
    def test_success(self, client):
        c, core, state = client
        core.results["decide_cross_validate"] = True
        r = c.post("/decision/D5_CROSS_VALIDATE", json={
            "session_id": "s1",
            "decision_input": {"session_state": "S_CROSSVALIDATE"},
            "rubric": RUBRIC,
        })
        assert r.status_code == 200
        assert r.json()["should_cross_validate"] is True


class TestDecideReject:
    def test_success(self, client):
        c, core, state = client
        core.results["decide_reject"] = SimpleDecision({"action": "reject", "location": "rejected"})
        r = c.post("/decision/D6_REJECT", json={
            "session_id": "s1", "quality_score": 0.1, "rubric": RUBRIC,
        })
        assert r.status_code == 200
        assert r.json()["action"] == "reject"

    def test_with_content_writes_rejected(self, client):
        c, core, state = client
        core.results["decide_reject"] = SimpleDecision({"action": "reject"})
        r = c.post("/decision/D6_REJECT", json={
            "session_id": "s1", "quality_score": 0.1, "rubric": RUBRIC,
            "content": "低质内容",
        })
        assert r.status_code == 200
        assert "write_result" in r.json()
        assert len(state.memory_manager.write_calls) == 1

    def test_runtime_error_500(self, client):
        c, core, state = client
        core.errors["decide_reject"] = RuntimeError("fail")
        r = c.post("/decision/D6_REJECT", json={
            "session_id": "s1", "quality_score": 0.1, "rubric": RUBRIC,
        })
        assert r.status_code == 500


# --------------------------------------------------------------------------- #
# rejected_content 管理端点
# --------------------------------------------------------------------------- #
class TestRejectedContent:
    def test_get_rejected_success(self, client):
        c, core, state = client
        r = c.get("/decision/rejected/s1")
        assert r.status_code == 200
        assert r.json()["count"] == 1
        assert r.json()["session_id"] == "s1"

    def test_get_rejected_no_memory_503(self, client):
        c, core, state = client
        state.memory_manager = None
        r = c.get("/decision/rejected/s1")
        assert r.status_code == 503

    def test_cleanup_success(self, client):
        c, core, state = client
        r = c.post("/decision/cleanup", json={"retention_days": 7})
        assert r.status_code == 200
        assert r.json()["purged_count"] == 3
        assert state.memory_manager.cleanup_calls == [7]

    def test_cleanup_no_memory_503(self, client):
        c, core, state = client
        state.memory_manager = None
        r = c.post("/decision/cleanup", json={})
        assert r.status_code == 503