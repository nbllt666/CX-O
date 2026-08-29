"""server.api.routers.memory 路由测试。

dependency_overrides 注入假 memory_manager / secondary_router + patch
config_router 的 Settings 模块引用 + patch server.core.memory.emotion.get_emotion_for_decay。
覆盖核心 CRUD、永久记忆、批量、副模型、搜索类端点。

运行：python -m pytest tests/test_memory_router.py -v
"""
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.dependencies import get_memory_manager, get_secondary_router, ServiceState, set_service_state
from server.api.routers import memory as memory_router_mod
from server.core.memory import emotion as emotion_mod
from server.core.memory.router import MemoryRouter, RoutingConfig


class FakeConn:
    def cursor(self):
        return FakeCursor()

    def close(self):
        return None


class FakeCursor:
    def execute(self, *a, **k):
        return self

    def fetchall(self):
        return [("default", "memories", "2026-01-01")]

    def fetchone(self):
        return (1,)


class FakeVectorStore:
    def is_available(self):
        return True

    def get_collection_info(self):
        return {"count": 42}


class FakeMemoryManager:
    def __init__(self):
        self._vector_store = FakeVectorStore()
        self._vector_store_config = {"backend": "chroma"}
        self.calls: Dict[str, list] = {}

    def _get_connection(self):
        return FakeConn()

    def search_memories(self, **kw):
        self.calls.setdefault("search", []).append(kw)
        return [{"id": 1, "content": "x", "metadata": {"date": "2026-08-09"}}]

    def get_permanent_memories(self, **kw):
        return [{"id": 5, "content": "p", "importance_score": 4, "tags": [], "metadata": {}}]

    def get_memory(self, memory_id, agent_id="default"):
        return {"id": memory_id, "content": "m"}

    async def write_memory_async(self, **kw):
        return 10

    async def update_memory_async(self, **kw):
        return True

    async def delete_memory_async(self, memory_id, soft_delete=True, agent_id="default"):
        return True

    def get_statistics(self, workspace_id):
        return {"total": 3}

    def get_decay_statistics(self, workspace_id):
        return {"decayed": 1}

    def is_vector_search_enabled(self):
        return True

    async def hybrid_search(self, **kw):
        return [{"id": 1}]

    async def semantic_search(self, query, limit=10, agent_id="default"):
        return [{"id": 1, "score": 0.9}]

    def write_permanent_memory(self, **kw):
        return 6

    def get_permanent_memory(self, memory_id):
        return {"id": memory_id, "content": "p"}

    def update_permanent_memory(self, **kw):
        return True

    def delete_permanent_memory(self, memory_id, is_from_main=True):
        return True

    def search_memories_3d(self, **kw):
        return [{"id": 1}]

    def recall_memory(self, memory_id, emotion_intensity, agent_id="default"):
        return {"id": memory_id}

    def batch_write_memories(self, memories, raise_on_error):
        return {"success": len(memories)}

    def batch_update_memories(self, updates, agent_id="default"):
        return {"updated": len(updates)}

    def batch_delete_memories(self, ids, soft_delete=False, raise_on_error=False, agent_id="default"):
        return {"deleted": len(ids)}

    def batch_update_tags(self, memory_ids, tags, operation, agent_id="default"):
        return {"updated": len(memory_ids)}

    def batch_archive_memories(self, ids, agent_id="default"):
        return {"archived": len(ids)}

    def restore_memory(self, memory_id, agent_id="default"):
        return True

    def sync_decay_values(self, workspace_id):
        return {"synced": 1}


class FakeSecondaryRouter:
    async def execute_command(self, instruction, is_from_main=False):
        return {"ok": True}

    def get_available_commands(self):
        return ["search", "archive"]

    def get_execution_history(self, limit):
        return [{"command": "search"}]


@pytest.fixture
def client(monkeypatch):
    mm = FakeMemoryManager()
    sr = FakeSecondaryRouter()
    state = ServiceState()
    state.memory_manager = mm
    state.secondary_router = sr
    set_service_state(state)

    async def _fake_emotion(content):
        return 2.5

    monkeypatch.setattr(emotion_mod, "get_emotion_for_decay", _fake_emotion)
    app = FastAPI()
    app.include_router(memory_router_mod.router)
    app.dependency_overrides[get_memory_manager] = lambda: mm
    app.dependency_overrides[get_secondary_router] = lambda: sr
    return TestClient(app, raise_server_exceptions=False), mm, sr


class TestListAgents:
    def test_success(self, client, monkeypatch):
        import server.api.routers.agents as agents_mod

        # 隔离真实 agents.json：固定返回 [default, alpha]
        monkeypatch.setattr(
            agents_mod, "_load_agents", lambda: [{"id": "default"}, {"id": "alpha"}]
        )
        c, mm, sr = client
        r = c.get("/memories/agents")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["agents"][0]["agent_id"] == "default"
        assert {a["agent_id"] for a in body["agents"]} == {"default", "alpha"}
        assert body["total"] == len(body["agents"])

    def test_merges_registered_agents(self, client, monkeypatch):
        """agents.json 中已注册但未建独立记忆表的 agent 也应出现在列表。"""
        import server.api.routers.agents as agents_mod

        monkeypatch.setattr(
            agents_mod,
            "_load_agents",
            lambda: [
                {"id": "default"},
                {"id": "alpha"},
                {"id": "beta"},
                {"id": "gamma"},
            ],
        )
        c, mm, sr = client
        r = c.get("/memories/agents")
        body = r.json()
        ids = [a["agent_id"] for a in body["agents"]]
        assert ids[0] == "default"
        assert {"alpha", "beta", "gamma"} <= set(ids)


class TestListMemories:
    def test_success(self, client):
        c, mm, sr = client
        r = c.get("/memories")
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        assert r.json()["memories"][0]["id"] == 1

    def test_permanent(self, client):
        c, mm, sr = client
        r = c.get("/memories", params={"type": "permanent"})
        assert r.status_code == 200
        body = r.json()
        assert body["memories"][0]["type"] == "permanent"
        assert body["memories"][0]["importance"] == 4


class TestCreateMemory:
    def test_empty_400(self, client):
        c, mm, sr = client
        r = c.post("/memories", json={"content": "   "})
        assert r.status_code == 400

    def test_success(self, client):
        c, mm, sr = client
        r = c.post("/memories", json={"content": "hello"})
        assert r.status_code == 200
        assert r.json()["memory_id"] == 10


class TestStats:
    def test_stats(self, client):
        c, mm, sr = client
        r = c.get("/memories/stats")
        assert r.status_code == 200
        assert r.json()["statistics"]["total"] == 3

    def test_decay_stats(self, client):
        c, mm, sr = client
        r = c.get("/memories/decay-stats")
        assert r.status_code == 200
        assert r.json()["statistics"]["decayed"] == 1


class TestDiary:
    def test_success(self, client):
        c, mm, sr = client
        r = c.get("/memories/diary")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["diary_groups"][0]["date"] == "2026-08-09"


class TestSearchByTag:
    def test_success(self, client):
        c, mm, sr = client
        r = c.get("/memories/search-by-tag", params={"tag": "x"})
        assert r.status_code == 200
        assert r.json()["count"] == 1


class TestMemoryCRUD:
    def test_get_success(self, client):
        c, mm, sr = client
        r = c.get("/memories/1")
        assert r.status_code == 200
        assert r.json()["memory"]["id"] == 1

    def test_get_404(self, client):
        c, mm, sr = client
        mm.get_memory = lambda memory_id, agent_id="default": None
        r = c.get("/memories/1")
        assert r.status_code == 404

    def test_update_success(self, client):
        c, mm, sr = client
        r = c.put("/memories/1", json={"content": "new"})
        assert r.status_code == 200

    def test_update_404(self, client):
        c, mm, sr = client
        async def _f(**kw):
            return False
        mm.update_memory_async = _f
        r = c.put("/memories/1", json={"content": "new"})
        assert r.status_code == 404

    def test_delete_success(self, client):
        c, mm, sr = client
        r = c.delete("/memories/1")
        assert r.status_code == 200


class TestSearch:
    def test_post(self, client):
        c, mm, sr = client
        r = c.post("/memories/search", json={"query": "q"})
        assert r.status_code == 200
        assert r.json()["total"] == 1


class TestRag:
    def test_success(self, client):
        c, mm, sr = client
        r = c.post("/memories/rag", params={"query": "q"})
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_error_400(self, client):
        c, mm, sr = client
        from server.core.exceptions import VectorStoreError
        async def _f(**kw):
            raise VectorStoreError("boom")
        mm.hybrid_search = _f
        r = c.post("/memories/rag", params={"query": "q"})
        assert r.status_code == 400


class TestPermanent:
    def test_create(self, client):
        c, mm, sr = client
        r = c.post("/memories/permanent", params={"content": "c"})
        assert r.status_code == 200
        assert r.json()["memory_id"] == 6

    def test_get_404(self, client):
        c, mm, sr = client
        mm.get_permanent_memory = lambda memory_id: None
        r = c.get("/memories/permanent/1")
        assert r.status_code == 404

    def test_list(self, client):
        c, mm, sr = client
        r = c.get("/memories/permanent")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_update_404(self, client):
        c, mm, sr = client
        mm.update_permanent_memory = lambda **kw: False
        r = c.put("/memories/permanent/1", params={"content": "c"})
        assert r.status_code == 404

    def test_delete_404(self, client):
        c, mm, sr = client
        mm.delete_permanent_memory = lambda memory_id, is_from_main=True: False
        r = c.delete("/memories/permanent/1")
        assert r.status_code == 404


class TestRecover3d:
    def test_3d_bad_weights_400(self, client):
        # 重复 query 参数经 FastAPI 解析不可靠，直接调用 handler 验证 len!=3 -> 400
        import pytest as _pt
        from fastapi import HTTPException
        with _pt.raises(HTTPException) as exc:
            import asyncio
            asyncio.run(memory_router_mod.search_memories_3d(query="q", weights=[0.5, 0.5]))
        assert exc.value.status_code == 400

    def test_3d_success(self, client):
        c, mm, sr = client
        r = c.post("/memories/3d", params={"query": "q"})
        assert r.status_code == 200
        assert r.json()["applied_weights"]["importance"] == 0.35

    def test_recall_404(self, client):
        c, mm, sr = client
        mm.recall_memory = lambda *a, **k: None
        r = c.post("/memories/recall/1")
        assert r.status_code == 404


class TestBatch:
    def test_write(self, client):
        c, mm, sr = client
        r = c.post("/memories/batch/write", json=[{"content": "a"}])
        assert r.status_code == 200
        assert r.json()["result"]["success"] == 1

    def test_update(self, client):
        c, mm, sr = client
        r = c.post("/memories/batch/update", json={"ids": [1, 2], "data": {"content": "c"}})
        assert r.status_code == 200

    def test_delete(self, client):
        c, mm, sr = client
        r = c.post("/memories/batch/delete", json={"ids": [1, 2]})
        assert r.status_code == 200

    def test_tags(self, client):
        c, mm, sr = client
        r = c.post("/memories/batch/tags", json={"ids": [1], "tags": ["a"], "operation": "add"})
        assert r.status_code == 200

    def test_archive(self, client):
        c, mm, sr = client
        r = c.post("/memories/batch/archive", json={"ids": [1]})
        assert r.status_code == 200

    def test_restore(self, client):
        c, mm, sr = client
        r = c.post("/memories/batch/restore", json={"ids": [1, 2]})
        assert r.status_code == 200
        assert r.json()["result"]["restored_count"] == 2

    def test_tag_by_query(self, client):
        c, mm, sr = client
        r = c.post("/memories/batch/tag-by-query", json={"query": "q", "tags": ["a"]})
        assert r.status_code == 200

    def test_delete_by_query(self, client):
        c, mm, sr = client
        r = c.post("/memories/batch/delete-by-query", json={"query": "q"})
        assert r.status_code == 200

    def test_archive_by_query(self, client):
        c, mm, sr = client
        r = c.post("/memories/batch/archive-by-query", json={"query": "q"})
        assert r.status_code == 200


class TestTypeAndSync:
    def test_by_type(self, client):
        c, mm, sr = client
        r = c.get("/memories/type/diary")
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_sync_decay(self, client):
        c, mm, sr = client
        r = c.post("/memories/sync-decay")
        assert r.status_code == 200


class TestSecondary:
    def test_execute(self, client):
        c, mm, sr = client
        r = c.post("/memories/secondary/execute", params={"command": "search"})
        assert r.status_code == 200
        assert r.json()["result"]["ok"] is True

    def test_execute_503(self, client):
        # handler 内直接调用 get_secondary_router()（Depends 默认标记→全局态），
        # 置全局 state.secondary_router=None 触发 503
        from server.dependencies import ServiceState as _SS, set_service_state as _sss
        st = _SS()
        st.memory_manager = client[1]
        st.secondary_router = None
        _sss(st)
        c, mm, sr = client
        r = c.post("/memories/secondary/execute", params={"command": "search"})
        assert r.status_code == 503

    def test_commands(self, client):
        c, mm, sr = client
        r = c.get("/memories/secondary/commands")
        assert r.status_code == 200
        assert r.json()["commands"] == ["search", "archive"]

    def test_history(self, client):
        c, mm, sr = client
        r = c.get("/memories/secondary/history")
        assert r.status_code == 200
        assert r.json()["history"][0]["command"] == "search"


class TestSemanticVector:
    def test_semantic_search(self, client):
        c, mm, sr = client
        r = c.post("/memories/semantic-search", json={"query": "q"})
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_semantic_disabled_503(self, client):
        c, mm, sr = client
        mm.is_vector_search_enabled = lambda: False
        r = c.post("/memories/semantic-search", json={"query": "q"})
        assert r.status_code == 503

    def test_vector_status(self, client):
        c, mm, sr = client
        r = c.get("/memories/vectors/status")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["enabled"] is True
        assert data["backend"] == "chroma"
        assert data["vector_count"] == 42
        assert data["sqlite_count"] == 1


class _RecentFakeMM:
    """search_memories 返回含 tags（session_id 命中与否）的记忆，用于 _get_recent_memories 测试。"""

    def __init__(self):
        self.searches = []

    def search_memories(self, **kw):
        self.searches.append(kw)
        if kw.get("offset", 0) == 0:
            return [
                {"id": 1, "tags": [kw["tags"][0]], "content": "本会话记忆"},
                {"id": 2, "tags": ["other_session"], "content": "其他会话记忆"},
            ]
        return []


class TestGetRecentMemories:
    def _router(self, mm):
        return MemoryRouter(mm, None, None, RoutingConfig(max_memories=10, min_score_threshold=0.1))

    def test_filters_by_session_tag(self):
        mm = _RecentFakeMM()
        router = self._router(mm)
        res = router._get_recent_memories("sess_1")
        # 只有带 sess_1 tag 的记忆被返回
        assert len(res) == 1
        assert res[0]["tags"] == ["sess_1"]

    def test_empty_session_returns_empty(self):
        mm = _RecentFakeMM()
        router = self._router(mm)
        assert router._get_recent_memories("") == []
        assert router._get_recent_memories(None) == []


class TestAsyncParity:
    """异步化后响应结构回归：路由内同步 sqlite 直调改为 run_io 包裹后，
    端点返回体结构必须与包裹前保持一致。"""

    def test_list_memories_structure_unchanged(self, client):
        """GET /memories 走 run_io(search_memories) 后返回体结构不变。"""
        c, mm, sr = client
        r = c.get("/memories")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"status", "memories", "total"}
        assert body["status"] == "success"
        assert body["total"] == len(body["memories"]) == 1
        assert body["memories"][0]["id"] == 1
        # run_io 仅改执行线程，透传参数不变
        assert mm.calls["search"][0]["limit"] == 20

    def test_stats_structure_unchanged(self, client):
        """GET /memories/stats 走 run_io(get_statistics) 后返回体结构不变。"""
        c, mm, sr = client
        r = c.get("/memories/stats")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"status", "statistics"}
        assert body["status"] == "success"
        assert body["statistics"] == {"total": 3}


def _record_run_io(monkeypatch):
    """包一层 run_io 记录器：记录经 run_io 执行的同步函数名，透传原实现。"""
    recorded = []
    orig = memory_router_mod.run_io

    async def _recorder(func, *args, **kwargs):
        recorded.append(getattr(func, "__name__", repr(func)))
        return await orig(func, *args, **kwargs)

    monkeypatch.setattr(memory_router_mod, "run_io", _recorder)
    return recorded


class TestRunIoCoverage:
    """第十轮补全：permanent 写入 / batch 写入 / sync_decay 端点经 run_io 执行，
    响应结构与参数透传保持不变。"""

    def test_permanent_write_via_run_io(self, client, monkeypatch):
        c, mm, sr = client
        recorded = _record_run_io(monkeypatch)
        seen = {}
        orig = mm.write_permanent_memory

        def _rec(**kw):
            seen.update(kw)
            return orig(**kw)

        _rec.__name__ = "write_permanent_memory"  # 保持记录器可识别原方法名
        mm.write_permanent_memory = _rec
        r = c.post("/memories/permanent", params={"content": "c"})
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"status", "memory_id", "message"}
        assert body["memory_id"] == 6
        # 参数透传不变：is_from_main 固定 True，空 tags/metadata 归一
        assert seen["content"] == "c"
        assert seen["is_from_main"] is True
        assert seen["tags"] == []
        assert seen["metadata"] == {}
        assert "write_permanent_memory" in recorded

    def test_batch_write_via_run_io(self, client, monkeypatch):
        c, mm, sr = client
        recorded = _record_run_io(monkeypatch)
        seen = {}
        orig = mm.batch_write_memories

        def _rec(memories, raise_on_error):
            seen["memories"] = memories
            seen["raise_on_error"] = raise_on_error
            return orig(memories, raise_on_error)

        _rec.__name__ = "batch_write_memories"  # 保持记录器可识别原方法名
        mm.batch_write_memories = _rec
        r = c.post("/memories/batch/write", json=[{"content": "a"}])
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"status", "result"}
        assert body["result"] == {"success": 1}
        # raise_on_error 默认值经位置参数显式传递保持
        assert seen["raise_on_error"] is False
        assert seen["memories"] == [{"content": "a"}]
        assert "batch_write_memories" in recorded

    def test_sync_decay_via_run_io(self, client, monkeypatch):
        c, mm, sr = client
        recorded = _record_run_io(monkeypatch)
        seen = []
        orig = mm.sync_decay_values

        def _rec(workspace_id):
            seen.append(workspace_id)
            return orig(workspace_id)

        _rec.__name__ = "sync_decay_values"  # 保持记录器可识别原方法名
        mm.sync_decay_values = _rec
        r = c.post("/memories/sync-decay")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"status", "result"}
        assert body["result"] == {"synced": 1}
        # workspace_id 默认值显式透传
        assert seen == ["default"]
        assert "sync_decay_values" in recorded