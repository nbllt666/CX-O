"""server.api.routers.context 路由测试。

set_service_state 注入假 context/memory manager + model_router。覆盖：
- sessions：list / create / get（404）/ delete（404）/ clear session / clear all
- messages：get / add（非法 role 400）
- summary：成功（解析 JSON）/ 空会话 404 / 摘要模型不可用 503
- stats

运行：python -m pytest tests/test_context_router.py -v
"""
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.dependencies import ServiceState, set_service_state
from server.api.routers import context as context_router_mod
from server.core.utils import run_io


class SimpleBox:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeContextManager:
    def __init__(self):
        self.sessions = {
            "s1": {"session_id": "s1", "workspace_id": "default", "title": "t1", "active": True},
        }
        self.messages = {"s1": [{"role": "user", "content": "hi"}]}

    def get_sessions(self, workspace_id="default", limit=20, active_only=True):
        return [s for s in self.sessions.values() if s["workspace_id"] == workspace_id]

    def create_session(self, workspace_id="default", title="", metadata=None):
        return "s_new"

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    def clear_session_messages(self, session_id):
        if session_id not in self.sessions:
            return False
        self.messages[session_id] = []
        return True

    def delete_session(self, session_id):
        if session_id not in self.sessions:
            return False
        del self.sessions[session_id]
        return True

    def clear_all_sessions(self):
        n = len(self.sessions)
        self.sessions.clear()
        return n

    def get_messages(self, session_id, limit=50, offset=0):
        return self.messages.get(session_id, [])

    def get_recent_messages(self, session_id, limit=50):
        return self.messages.get(session_id, [])[-limit:]

    def add_message(self, session_id, role, content, content_type="text", metadata=None):
        self.messages.setdefault(session_id, []).append(
            {"role": role, "content": content, "content_type": content_type}
        )
        return "m_new"

    def update_session(self, session_id, summary=None, **kwargs):
        if session_id in self.sessions:
            self.sessions[session_id]["summary"] = summary

    def get_statistics(self, workspace_id="default"):
        return {"session_count": len(self.sessions)}

    # ------------------------------------------------------------------
    # 异步变体：对齐真 ContextManager 的 *_async 委托语义（run_io 移入
    # IO 线程池后调同步实现），供路由层 async 热路径调用。
    # ------------------------------------------------------------------

    async def create_session_async(self, *args, **kwargs):
        return await run_io(self.create_session, *args, **kwargs)

    async def get_session_async(self, *args, **kwargs):
        return await run_io(self.get_session, *args, **kwargs)

    async def get_sessions_async(self, *args, **kwargs):
        return await run_io(self.get_sessions, *args, **kwargs)

    async def update_session_async(self, *args, **kwargs):
        return await run_io(self.update_session, *args, **kwargs)

    async def add_message_async(self, *args, **kwargs):
        return await run_io(self.add_message, *args, **kwargs)

    async def get_messages_async(self, *args, **kwargs):
        return await run_io(self.get_messages, *args, **kwargs)

    async def get_recent_messages_async(self, *args, **kwargs):
        return await run_io(self.get_recent_messages, *args, **kwargs)

    async def get_statistics_async(self, *args, **kwargs):
        return await run_io(self.get_statistics, *args, **kwargs)


class FakeSummarizer:
    async def chat(self, messages, stream=False, max_tokens=2048):
        body = (
            '{"key_points": [{"content": "p1", "importance": "high", '
            '"participants": ["user"]}], '
            '"report": {"topic": "主题", "participants": ["user"], '
            '"message_count": 1, "main_discussion": "讨论", '
            '"key_decisions": ["d1"], "action_items": [], "open_questions": [], '
            '"sentiment": "positive", "sentiment_analysis": "ok", '
            '"timeline": [{"time": "开始", "event": "e"}]}}'
        )
        return SimpleBox(content=body)


class FakeModelRouter:
    def __init__(self, client=None):
        self.client = client

    def get_client(self, name):
        return self.client


class FakeMemoryManager:
    async def write_memory(self, content, memory_type, importance, tags=None, metadata=None):
        return 42


@pytest.fixture
def client():
    ctx = FakeContextManager()
    mm = FakeMemoryManager()
    router = FakeModelRouter(client=FakeSummarizer())
    state = ServiceState()
    state.context_manager = ctx
    state.memory_manager = mm
    state.model_router = router
    set_service_state(state)
    app = FastAPI()
    app.include_router(context_router_mod.router)
    return TestClient(app), ctx, router


class TestSessions:
    def test_list(self, client):
        c, ctx, _ = client
        r = c.get("/context/sessions")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_create(self, client):
        c, ctx, _ = client
        r = c.post("/context/sessions", json={"workspace_id": "default", "title": "x"})
        assert r.status_code == 200
        assert r.json()["session_id"] == "s_new"

    def test_get_success(self, client):
        c, ctx, _ = client
        r = c.get("/context/sessions/s1")
        assert r.status_code == 200
        assert r.json()["session"]["title"] == "t1"

    def test_get_404(self, client):
        c, ctx, _ = client
        r = c.get("/context/sessions/nope")
        assert r.status_code == 404

    def test_delete_success(self, client):
        c, ctx, _ = client
        r = c.delete("/context/sessions/s1")
        assert r.status_code == 200
        assert "s1" not in ctx.sessions

    def test_delete_404(self, client):
        c, ctx, _ = client
        r = c.delete("/context/sessions/nope")
        assert r.status_code == 404

    def test_clear_messages_success(self, client):
        c, ctx, _ = client
        r = c.delete("/context/sessions/s1/messages")
        assert r.status_code == 200
        assert ctx.messages["s1"] == []

    def test_clear_messages_404(self, client):
        c, ctx, _ = client
        r = c.delete("/context/sessions/nope/messages")
        assert r.status_code == 404


class TestClearAll:
    def test_success(self, client):
        c, ctx, _ = client
        r = c.delete("/context/sessions/all")
        assert r.status_code == 200
        assert r.json()["deleted_count"] == 1


class TestMessages:
    def test_get(self, client):
        c, ctx, _ = client
        r = c.get("/context/messages/s1")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_add_success(self, client):
        c, ctx, _ = client
        r = c.post("/context/messages", json={"session_id": "s1", "role": "user", "content": "hi"})
        assert r.status_code == 200
        assert r.json()["message_id"] == "m_new"

    def test_add_invalid_role_400(self, client):
        c, ctx, _ = client
        r = c.post("/context/messages", json={"session_id": "s1", "role": "admin", "content": "hi"})
        assert r.status_code == 400


class TestSummary:
    def test_success(self, client):
        c, ctx, _ = client
        r = c.post("/context/summary", params={"session_id": "s1", "max_points": 3})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["summary_memory_id"] == 42
        assert body["report"]["topic"] == "主题"
        assert len(body["key_points"]) == 1

    def test_empty_session_404(self, client):
        c, ctx, _ = client
        r = c.post("/context/summary", params={"session_id": "empty"})
        assert r.status_code == 404

    def test_summary_unavailable_503(self, client):
        c, ctx, router = client
        router.client = None
        r = c.post("/context/summary", params={"session_id": "s1"})
        assert r.status_code == 503


class TestStats:
    def test_success(self, client):
        c, ctx, _ = client
        r = c.get("/context/stats")
        assert r.status_code == 200
        assert r.json()["statistics"]["session_count"] == 1


class TestAsyncParity:
    """异步化后响应结构回归：路由切到 *_async / run_io 后端点返回体必须保持原结构。"""

    def test_sessions_list_structure_unchanged(self, client):
        """GET /context/sessions 走 get_sessions_async 后结构与同步时代一致。"""
        c, _, _ = client
        r = c.get("/context/sessions")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"status", "sessions", "total"}
        assert body["status"] == "success"
        assert body["total"] == len(body["sessions"]) == 1
        # 会话元素字段契约不变
        assert set(body["sessions"][0].keys()) == {
            "session_id", "workspace_id", "title", "active"
        }

    def test_add_message_structure_unchanged(self, client):
        """POST /context/messages 走 add_message_async 后返回体结构不变。"""
        c, _, _ = client
        r = c.post(
            "/context/messages",
            json={"session_id": "s1", "role": "user", "content": "hi"},
        )
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"status", "message_id", "message"}
        assert body["status"] == "success"
        assert body["message_id"] == "m_new"
        assert body["message"] == "消息添加成功"