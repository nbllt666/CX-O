"""server.api.routers.memory_chat 路由测试。

set_service_state 注入假 memory_manager（含 conversation_engine）+ monkeypatch
server.core.memory.conversation.MemoryConversationEngine。覆盖：
- chat：成功 / 503（记忆/LLM 不可用）/ 500
- get session：成功 / 503
- clear session：成功 / 404
- commands：列表（排除 unknown）

运行：python -m pytest tests/test_memory_chat_router.py -v
"""
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.dependencies import ServiceState, set_service_state
from server.api.routers import memory_chat as memory_chat_router_mod
import server.core.memory.conversation as memory_conversation_mod


class FakeSession:
    messages = [{"role": "user", "content": "hi"}]
    pending_command = None


class FakeEngine:
    COMMAND_TYPES = {
        "search": "搜索记忆",
        "archive": "归档记忆",
        "unknown": "未知",
    }
    DESTRUCTIVE_COMMANDS = {"delete", "clear"}

    def __init__(self):
        self._sessions = {"default": FakeSession()}
        self.process_calls = []

    async def process_message(self, user_message, session_id="default"):
        self.process_calls.append((user_message, session_id))
        return {
            "status": "success",
            "message": "ok",
            "pending_command": None,
            "extra": "data",
        }

    def get_or_create_session(self, session_id):
        return self._sessions.setdefault(session_id, FakeSession())


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(memory_conversation_mod, "MemoryConversationEngine", FakeEngine)
    engine = FakeEngine()
    mm = SimpleMM(conversation_engine=engine)
    state = ServiceState()
    state.memory_manager = mm
    set_service_state(state)
    app = FastAPI()
    app.include_router(memory_chat_router_mod.router)
    return TestClient(app, raise_server_exceptions=False), mm, engine


class SimpleMM:
    def __init__(self, conversation_engine=None):
        self.conversation_engine = conversation_engine


@pytest.fixture
def no_engine_client(monkeypatch):
    monkeypatch.setattr(memory_conversation_mod, "MemoryConversationEngine", FakeEngine)
    mm = SimpleMM(conversation_engine=None)
    state = ServiceState()
    state.memory_manager = mm
    state.model_router = None  # LLM 不可用
    set_service_state(state)
    app = FastAPI()
    app.include_router(memory_chat_router_mod.router)
    return TestClient(app, raise_server_exceptions=False), mm


class TestChat:
    def test_success(self, client):
        c, mm, engine = client
        r = c.post("/memory-chat", json={"message": "搜索记忆", "session_id": "default"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["session_id"] == "default"
        assert body["data"]["extra"] == "data"
        assert engine.process_calls[0][0] == "搜索记忆"

    def test_llm_unavailable_503(self, no_engine_client):
        c, mm = no_engine_client
        r = c.post("/memory-chat", json={"message": "hi"})
        assert r.status_code == 503

    def test_memory_unavailable_503(self, monkeypatch):
        monkeypatch.setattr(memory_conversation_mod, "MemoryConversationEngine", FakeEngine)
        state = ServiceState()
        state.memory_manager = None
        set_service_state(state)
        app = FastAPI()
        app.include_router(memory_chat_router_mod.router)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/memory-chat", json={"message": "hi"})
        assert r.status_code == 503

    def test_engine_error_500(self, client):
        c, mm, engine = client
        async def _boom(**kw):
            raise RuntimeError("boom")
        engine.process_message = _boom
        r = c.post("/memory-chat", json={"message": "hi"})
        assert r.status_code == 500


class TestGetSession:
    def test_success(self, client):
        c, mm, engine = client
        r = c.get("/memory-chat/sessions/default")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["has_pending_command"] is False
        assert len(body["messages"]) == 1

    def test_503(self, no_engine_client):
        c, mm = no_engine_client
        r = c.get("/memory-chat/sessions/default")
        assert r.status_code == 503


class TestClearSession:
    def test_success(self, client):
        c, mm, engine = client
        r = c.delete("/memory-chat/sessions/default")
        assert r.status_code == 200
        assert "default" not in engine._sessions

    def test_not_found_404(self, client):
        c, mm, engine = client
        r = c.delete("/memory-chat/sessions/nope")
        assert r.status_code == 404


class TestCommands:
    def test_list_excludes_unknown(self, client):
        c, mm, engine = client
        r = c.get("/memory-chat/commands")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert "unknown" not in body["commands"]
        assert body["commands"]["search"] == "搜索记忆"
        assert sorted(body["destructive_commands"]) == ["clear", "delete"]