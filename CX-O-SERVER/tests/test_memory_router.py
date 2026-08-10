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
    monkeypatch.setattr(emotion_mod, "get_emotion_for_decay", lambda content: 2.5)
    app = FastAPI()
    app.include_router(memory_router_mod.router)
    app.dependency_overrides[get_memory_manager] = lambda: mm
    app.dependency_overrides[get_secondary_router] = lambda: sr
    return TestClient(app, raise_server_exceptions=False), mm, sr


class TestListAgents:
    def test_success(self, client):
        c, mm, sr = client
        r = c.get("/memories/agents")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["agents"][0]["agent_id"] == "default"
        assert body["total"] == 2


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