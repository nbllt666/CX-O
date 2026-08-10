"""
server.core.distillation.api 路由测试（routes.py + batch_routes.py）
用 FastAPI TestClient + 注入假 DistillationService 到 app.state，隔离真实蒸馏服务。
覆盖：4 个 REST 端点（start/advance/finalize/get）与 5 个批量角色卡端点。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.core.distillation.api.routes import router as dist_router
from server.core.distillation.api.batch_routes import router as batch_router
import server.core.distillation.character_card_parser as cc_parser_mod


# --------------------------------------------------------------------------- #
# 假服务 —— 记录调用 + 可配置异常
# --------------------------------------------------------------------------- #
class FakeDistillationService:
    def __init__(self, result):
        self.calls = []
        self.result = result
        self.errors = {}

    async def _run(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        err = self.errors.get(name)
        if err:
            raise err
        return self.result.get(name, {"ok": True})

    async def start_distillation(self, *args, **kwargs):
        return await self._run("start_distillation", *args, **kwargs)

    async def advance_distillation(self, *args, **kwargs):
        return await self._run("advance_distillation", *args, **kwargs)

    async def finalize_distillation(self, *args, **kwargs):
        return await self._run("finalize_distillation", *args, **kwargs)

    async def get_session_status(self, *args, **kwargs):
        return await self._run("get_session_status", *args, **kwargs)

    async def start_batch_distillation(self, *args, **kwargs):
        return await self._run("start_batch_distillation", *args, **kwargs)

    async def get_group_status(self, *args, **kwargs):
        return await self._run("get_group_status", *args, **kwargs)

    async def finalize_with_agent_creation(self, *args, **kwargs):
        return await self._run("finalize_with_agent_creation", *args, **kwargs)


VALID_RESULTS = {
    "start_distillation": {
        "session_id": "s1", "initial_state": "S_PREREAD", "preread_summary": None},
    "advance_distillation": {
        "session_id": "s1", "current_state": "S_REFLECT",
        "agent_action": "ask_user", "next_needed": True},
    "finalize_distillation": {
        "stored": True, "location": "memories", "memory_id": 1,
        "metadata": {"k": "v"}, "reason": "ok"},
    "get_session_status": {
        "session_id": "s1", "source_type": "text", "state": "S_PREREAD",
        "template_id": "t1", "max_turns": 4, "ask_user_on_ambiguity": True,
        "turns": [], "preread_summary": None, "ambiguity_questions": [],
        "extracted_content": None, "quality_score": None,
        "created_at": "2026-08-09T00:00:00", "updated_at": None,
        "finalized_at": None, "is_finalized": False, "error_message": None},
}


@pytest.fixture
def client(monkeypatch):
    # character_card_to_source_ref 在 batch_routes 函数体内从 character_card_parser 导入
    # 因此需在源模块 patch
    monkeypatch.setattr(
        cc_parser_mod, "character_card_to_source_ref",
        lambda card: f"姓名：{card.get('name', '')}")

    app = FastAPI()
    app.include_router(dist_router)
    app.include_router(batch_router)
    svc = FakeDistillationService(result=VALID_RESULTS)
    app.state.distillation_service = svc
    return TestClient(app), svc


@pytest.fixture
def client_no_service():
    app = FastAPI()
    app.include_router(dist_router)
    app.include_router(batch_router)
    return TestClient(app)


# --------------------------------------------------------------------------- #
# _get_service 未初始化
# --------------------------------------------------------------------------- #
class TestGetServiceUninitialized:
    def test_dist_routes_500(self, client_no_service):
        r = client_no_service.post("/api/v1/distillation/start", json={
            "source_type": "text", "source_ref": "x", "template_id": "t1"})
        assert r.status_code == 500
        assert "未初始化" in r.json()["detail"]

    def test_batch_routes_503(self, client_no_service):
        r = client_no_service.get("/api/v1/distillation/group/g1")
        assert r.status_code == 503
        assert "未初始化" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# routes.py —— 4 个 REST 端点
# --------------------------------------------------------------------------- #
class TestStartDistillation:
    def test_success(self, client):
        c, svc = client
        r = c.post("/api/v1/distillation/start", json={
            "source_type": "text", "source_ref": "sr", "template_id": "t1",
            "max_turns": 4, "ask_user_on_ambiguity": True})
        assert r.status_code == 200
        assert r.json()["session_id"] == "s1"
        name, args, kwargs = svc.calls[0]
        assert name == "start_distillation"
        assert kwargs["source_type"] == "text"
        assert kwargs["source_ref"] == "sr"
        assert kwargs["template_id"] == "t1"

    def test_value_error_422(self, client):
        c, svc = client
        svc.errors["start_distillation"] = ValueError("bad source_type")
        r = c.post("/api/v1/distillation/start", json={
            "source_type": "bad", "source_ref": "x", "template_id": "t1"})
        assert r.status_code == 422

    def test_runtime_error_422(self, client):
        c, svc = client
        svc.errors["start_distillation"] = RuntimeError("pipeline fail")
        r = c.post("/api/v1/distillation/start", json={
            "source_type": "text", "source_ref": "x", "template_id": "t1"})
        assert r.status_code == 422

    def test_connection_error_500(self, client):
        c, svc = client
        svc.errors["start_distillation"] = ConnectionError("no pipeline")
        r = c.post("/api/v1/distillation/start", json={
            "source_type": "text", "source_ref": "x", "template_id": "t1"})
        assert r.status_code == 500


class TestAdvanceDistillation:
    def test_success(self, client):
        c, svc = client
        r = c.post("/api/v1/distillation/s1/advance", json={"user_response": "嗯"})
        assert r.status_code == 200
        name, args, kwargs = svc.calls[0]
        assert name == "advance_distillation"
        assert kwargs["session_id"] == "s1"
        assert kwargs["user_response"] == "嗯"

    def test_key_error_404(self, client):
        c, svc = client
        svc.errors["advance_distillation"] = KeyError("s1")
        r = c.post("/api/v1/distillation/s1/advance", json={"user_response": "嗯"})
        assert r.status_code == 404

    def test_value_error_409(self, client):
        c, svc = client
        svc.errors["advance_distillation"] = ValueError("已终结")
        r = c.post("/api/v1/distillation/s1/advance", json={"user_response": "嗯"})
        assert r.status_code == 409

    def test_runtime_error_500(self, client):
        c, svc = client
        svc.errors["advance_distillation"] = RuntimeError("llm down")
        r = c.post("/api/v1/distillation/s1/advance", json={"user_response": "嗯"})
        assert r.status_code == 500


class TestFinalizeDistillation:
    def test_success(self, client):
        c, svc = client
        r = c.post("/api/v1/distillation/s1/finalize", json={"override_decision": "store"})
        assert r.status_code == 200
        name, args, kwargs = svc.calls[0]
        assert name == "finalize_distillation"
        assert kwargs["override_decision"] == "store"

    def test_value_error_409(self, client):
        c, svc = client
        svc.errors["finalize_distillation"] = ValueError("已终结")
        r = c.post("/api/v1/distillation/s1/finalize", json={})
        assert r.status_code == 409

    def test_runtime_error_500(self, client):
        c, svc = client
        svc.errors["finalize_distillation"] = RuntimeError("decision fail")
        r = c.post("/api/v1/distillation/s1/finalize", json={})
        assert r.status_code == 500


class TestGetSessionStatus:
    def test_success(self, client):
        c, svc = client
        r = c.get("/api/v1/distillation/s1")
        assert r.status_code == 200
        name, args, kwargs = svc.calls[0]
        assert name == "get_session_status"
        assert kwargs["session_id"] == "s1"
    def test_key_error_404(self, client):
        c, svc = client
        svc.errors["get_session_status"] = KeyError("s1")
        r = c.get("/api/v1/distillation/s1")
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# batch_routes.py —— 批量切分 + 角色卡端点
# --------------------------------------------------------------------------- #
class TestBatchStart:
    def test_success(self, client):
        c, svc = client
        r = c.post("/api/v1/distillation/start-batch", json={
            "source_type": "text", "source_ref": "long...", "template_id": "t1"})
        assert r.status_code == 200
        name, args, kwargs = svc.calls[0]
        assert name == "start_batch_distillation"
        assert kwargs["source_type"] == "text"
        assert kwargs["template_id"] == "t1"

    def test_value_error_422(self, client):
        c, svc = client
        svc.errors["start_batch_distillation"] = ValueError("bad")
        r = c.post("/api/v1/distillation/start-batch", json={
            "source_type": "text", "source_ref": "x", "template_id": "t1"})
        assert r.status_code == 422

    def test_exception_500(self, client):
        c, svc = client
        svc.errors["start_batch_distillation"] = RuntimeError("boom")
        r = c.post("/api/v1/distillation/start-batch", json={
            "source_type": "text", "source_ref": "x", "template_id": "t1"})
        assert r.status_code == 500


class TestGroupStatus:
    def test_success(self, client):
        c, svc = client
        r = c.get("/api/v1/distillation/group/g1")
        assert r.status_code == 200
        name, args, kwargs = svc.calls[0]
        assert name == "get_group_status"
        assert args[0] == "g1"

    def test_key_error_404(self, client):
        c, svc = client
        svc.errors["get_group_status"] = KeyError("g1")
        r = c.get("/api/v1/distillation/group/g1")
        assert r.status_code == 404


class TestFinalizeAgent:
    def test_success(self, client):
        c, svc = client
        r = c.post("/api/v1/distillation/s1/finalize-agent", json={
            "override_decision": "agent"})
        assert r.status_code == 200
        name, args, kwargs = svc.calls[0]
        assert name == "finalize_with_agent_creation"
        assert kwargs["session_id"] == "s1"
        assert kwargs["override_decision"] == "agent"

    def test_key_error_404(self, client):
        c, svc = client
        svc.errors["finalize_with_agent_creation"] = KeyError("s1")
        r = c.post("/api/v1/distillation/s1/finalize-agent", json={})
        assert r.status_code == 404

    def test_value_error_409(self, client):
        c, svc = client
        svc.errors["finalize_with_agent_creation"] = ValueError("已终结")
        r = c.post("/api/v1/distillation/s1/finalize-agent", json={})
        assert r.status_code == 409

    def test_exception_500(self, client):
        c, svc = client
        svc.errors["finalize_with_agent_creation"] = RuntimeError("fail")
        r = c.post("/api/v1/distillation/s1/finalize-agent", json={})
        assert r.status_code == 500


class TestParseCharacterCard:
    def test_json_content_success(self, client, monkeypatch):
        c, svc = client

        def fake_parse(json_str):
            data = json.loads(json_str)
            return {"name": data["name"], "description": "desc"}

        monkeypatch.setattr(cc_parser_mod, "parse_character_card_from_json_str", fake_parse)
        r = c.post("/api/v1/distillation/parse-character-card", json={
            "json_content": {"name": "小美"}})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["character_card_data"]["name"] == "小美"
        assert body["source_ref"] == "姓名：小美"

    def test_no_file_no_json_422(self, client):
        c, svc = client
        r = c.post("/api/v1/distillation/parse-character-card", content=b"",
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 422

    def test_json_value_error_400(self, client, monkeypatch):
        c, svc = client

        def fake_parse(json_str):
            raise ValueError("bad card")

        monkeypatch.setattr(cc_parser_mod, "parse_character_card_from_json_str", fake_parse)
        r = c.post("/api/v1/distillation/parse-character-card", json={
            "json_content": {"name": "x"}})
        assert r.status_code == 400
        assert "bad card" in r.json()["detail"]


class TestStartFromCharacterCard:
    def test_success(self, client):
        c, svc = client
        r = c.post("/api/v1/distillation/start-from-character-card", json={
            "character_card_data": {"name": "小美", "description": "d"},
            "template_id": "t1"})
        assert r.status_code == 200
        name, args, kwargs = svc.calls[0]
        assert name == "start_batch_distillation"
        assert kwargs["source_type"] == "character_card"
        assert kwargs["source_ref"] == "姓名：小美"

    def test_missing_name_400(self, client):
        c, svc = client
        r = c.post("/api/v1/distillation/start-from-character-card", json={
            "character_card_data": {"description": "no name"}})
        assert r.status_code == 400
        assert "name" in r.json()["detail"]

    def test_empty_source_ref_400(self, client, monkeypatch):
        c, svc = client
        monkeypatch.setattr(cc_parser_mod, "character_card_to_source_ref", lambda card: "   ")
        r = c.post("/api/v1/distillation/start-from-character-card", json={
            "character_card_data": {"name": "x"}})
        assert r.status_code == 400
        assert "为空" in r.json()["detail"]

    def test_value_error_422(self, client):
        c, svc = client
        svc.errors["start_batch_distillation"] = ValueError("bad")
        r = c.post("/api/v1/distillation/start-from-character-card", json={
            "character_card_data": {"name": "小美"}})
        assert r.status_code == 422

    def test_exception_500(self, client):
        c, svc = client
        svc.errors["start_batch_distillation"] = RuntimeError("boom")
        r = c.post("/api/v1/distillation/start-from-character-card", json={
            "character_card_data": {"name": "小美"}})
        assert r.status_code == 500