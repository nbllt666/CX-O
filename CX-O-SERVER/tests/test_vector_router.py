"""server.api.routers.vector 路由测试。

通过 set_service_state 注入假 MemoryManager（含假 VectorStore / EmbeddingModel），
monkeypatch server.config.get_settings，隔离真实向量库。覆盖：
- config / status / health / stats
- vectors 列表 / 单个 / 删除 / 同步 / 重建 / 搜索
- 未启用向量库时 503

运行：python -m pytest tests/test_vector_router.py -v
"""
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.dependencies import ServiceState, set_service_state
from server.api.routers import vector as vector_mod
from server.api.routers.admin import verify_admin_api_key


# --------------------------------------------------------------------------- #
# 假对象
# --------------------------------------------------------------------------- #
class FakeVectorStore:
    def __init__(self, available=True, count=3):
        self._available = available
        self._count = count
        self.vectors = {1: {"vector": [0.1] * 3, "metadata": {"k": "v"}}}
        self.clear_calls = 0
        self.sync_calls = 0

    def is_available(self):
        return self._available

    def get_collection_info(self):
        return {"count": self._count}

    async def list_vectors(self, limit=50, offset=0, memory_type=None):
        return [{"memory_id": 1, "vector": [0.1] * 3}]

    async def check_exists(self, memory_id):
        return memory_id in self.vectors

    async def get_vector_by_id(self, memory_id):
        return self.vectors.get(memory_id)

    async def delete_by_memory_id(self, memory_id):
        if memory_id in self.vectors:
            del self.vectors[memory_id]
            return True
        return False

    async def sync_with_sqlite(self, mm, last_sync_time=None):
        self.sync_calls += 1
        class R:
            total_checked = 10
            synced = 5
            removed = 1
            errors = 0
        return R()

    def clear_collection(self):
        self.clear_calls += 1

    async def search_similar(self, query_embedding, limit=10, memory_type=None, min_score=0.5):
        return [{"memory_id": 1, "score": 0.9}]


class FakeEmbeddingModel:
    async def get_embedding(self, query):
        return [0.1] * 3


class FakeMemoryManager:
    def __init__(self, vector_store=None, embedding_model=None):
        self._vector_store = vector_store
        self._vector_store_config = {"backend": "chroma"} if vector_store else {}
        self._embedding_model = embedding_model
        self.memories = {1: {"id": 1, "content": "hello", "type": "chat", "importance": 0.8}}

    def get_memory(self, memory_id):
        return self.memories.get(memory_id)

    def read_memories(self, limit=50, offset=0, memory_type=None):
        return list(self.memories.values())

    def search_memories(self, limit=10000):
        return list(self.memories.values())


class FakeSettings:
    def __init__(self, memory=None):
        self.config = type("Cfg", (), {"memory": memory or FakeMemoryConfig()})()


class FakeMemoryConfig:
    def __init__(self):
        self.vector_enabled = True
        self.vector_backend = "chroma"
        self.chroma = type("C", (), {"db_path": "data/chroma_db", "collection_name": "mem", "vector_size": 768})()


@pytest.fixture
def client(monkeypatch):
    store = FakeVectorStore()
    mm = FakeMemoryManager(vector_store=store, embedding_model=FakeEmbeddingModel())
    state = ServiceState()
    state.memory_manager = mm
    set_service_state(state)
    monkeypatch.setattr("server.config.get_settings", lambda: FakeSettings())

    app = FastAPI()
    app.include_router(vector_mod.router)
    # 写路径（delete/sync/rebuild）已补挂 verify_admin_api_key：
    # 既有用例经 dependency_overrides 放行，403 场景由 TestVectorAuthRequired 单独覆盖
    app.dependency_overrides[verify_admin_api_key] = lambda: True
    return TestClient(app), mm, store


@pytest.fixture
def disabled_client(monkeypatch):
    store = FakeVectorStore(available=False)
    mm = FakeMemoryManager(vector_store=None, embedding_model=None)
    state = ServiceState()
    state.memory_manager = mm
    set_service_state(state)
    monkeypatch.setattr("server.config.get_settings", lambda: FakeSettings())

    app = FastAPI()
    app.include_router(vector_mod.router)
    # 同上：鉴权 override 放行，保证 disabled 场景仍能走到 503 分支
    app.dependency_overrides[verify_admin_api_key] = lambda: True
    return TestClient(app), mm, store


# --------------------------------------------------------------------------- #
# 配置 / 状态 / 健康 / 统计
# --------------------------------------------------------------------------- #
class TestConfig:
    def test_chroma_config(self, client):
        c, _, _ = client
        r = c.get("/vector/config")
        assert r.status_code == 200
        cfg = r.json()["config"]
        assert cfg["vector_backend"] == "chroma"
        assert cfg["db_path"] == "data/chroma_db"
        assert cfg["collection_name"] == "mem"


class TestStatus:
    def test_enabled(self, client):
        c, _, _ = client
        r = c.get("/vector/status")
        assert r.status_code == 200
        st = r.json()["vector_status"]
        assert st["vector_enabled"] is True
        assert st["connected"] is True

    def test_disabled(self, disabled_client):
        c, _, _ = disabled_client
        r = c.get("/vector/status")
        assert r.status_code == 200
        assert r.json()["vector_status"]["vector_enabled"] is False


class TestHealth:
    def test_healthy(self, client):
        c, _, _ = client
        r = c.get("/vector/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_disabled(self, disabled_client):
        c, _, _ = disabled_client
        r = c.get("/vector/health")
        assert r.status_code == 200
        assert r.json()["status"] == "disabled"


class TestStats:
    def test_enabled(self, client):
        c, _, _ = client
        r = c.get("/vector/stats")
        assert r.status_code == 200
        st = r.json()["stats"]
        assert st["vector_enabled"] is True
        assert st["total_vectors"] == 3
        assert st["total_memories"] == 1
        assert st["indexed_ratio"] == 3.0


# --------------------------------------------------------------------------- #
# 向量数据管理
# --------------------------------------------------------------------------- #
class TestListVectors:
    def test_enabled(self, client):
        c, mm, store = client
        r = c.get("/vector/vectors")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["total"] == 3

    def test_disabled_503(self, disabled_client):
        c, _, _ = disabled_client
        r = c.get("/vector/vectors")
        assert r.status_code == 503


class TestGetVector:
    def test_success(self, client):
        c, _, _ = client
        r = c.get("/vector/vectors/1")
        assert r.status_code == 200
        assert r.json()["vector"]["vector_size"] == 3
        assert "memory" in r.json()["vector"]

    def test_not_found_404(self, client):
        c, _, _ = client
        r = c.get("/vector/vectors/999")
        assert r.status_code == 404

    def test_disabled_503(self, disabled_client):
        c, _, _ = disabled_client
        r = c.get("/vector/vectors/1")
        assert r.status_code == 503


class TestDeleteVector:
    def test_success(self, client):
        c, _, _ = client
        r = c.delete("/vector/vectors/1")
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_not_found_404(self, client):
        c, _, _ = client
        r = c.delete("/vector/vectors/999")
        assert r.status_code == 404

    def test_disabled_503(self, disabled_client):
        c, _, _ = disabled_client
        r = c.delete("/vector/vectors/1")
        assert r.status_code == 503


class TestSyncVectors:
    def test_success(self, client):
        c, _, store = client
        r = c.post("/vector/sync")
        assert r.status_code == 200
        result = r.json()["result"]
        assert result["synced"] == 5
        assert store.sync_calls == 1

    def test_disabled_503(self, disabled_client):
        c, _, _ = disabled_client
        r = c.post("/vector/sync")
        assert r.status_code == 503


class TestRebuildVectors:
    def test_success(self, client):
        c, _, store = client
        r = c.post("/vector/rebuild")
        assert r.status_code == 200
        assert store.clear_calls == 1
        assert r.json()["result"]["synced"] == 5

    def test_disabled_503(self, disabled_client):
        c, _, _ = disabled_client
        r = c.post("/vector/rebuild")
        assert r.status_code == 503


class TestSearchVectors:
    def test_success(self, client):
        c, _, _ = client
        r = c.post("/vector/search", params={"query": "hello"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["total"] == 1
        assert body["results"][0]["memory"]["id"] == 1

    def test_disabled_503(self, disabled_client):
        c, _, _ = disabled_client
        r = c.post("/vector/search", params={"query": "hello"})
        assert r.status_code == 503


# --------------------------------------------------------------------------- #
# 写路径鉴权（鉴权漏挂簇修复补充用例）
# verify_admin_api_key 校验失败统一抛 403（项目既有口径，对齐 test_stats_interrupt.py）；
# 本组用例不挂 dependency_overrides，真实走到密钥校验依赖。
# --------------------------------------------------------------------------- #
class TestVectorAuthRequired:
    @staticmethod
    def _raw_client(monkeypatch) -> TestClient:
        mm = FakeMemoryManager(vector_store=FakeVectorStore(), embedding_model=FakeEmbeddingModel())
        state = ServiceState()
        state.memory_manager = mm
        set_service_state(state)
        monkeypatch.setattr("server.config.get_settings", lambda: FakeSettings())

        app = FastAPI()
        app.include_router(vector_mod.router)
        return TestClient(app, raise_server_exceptions=False)

    def test_rebuild_requires_auth(self, monkeypatch):
        c = self._raw_client(monkeypatch)
        r = c.post("/vector/rebuild")
        assert r.status_code == 403

    def test_delete_requires_auth(self, monkeypatch):
        c = self._raw_client(monkeypatch)
        r = c.delete("/vector/vectors/1")
        assert r.status_code == 403

    def test_sync_requires_auth(self, monkeypatch):
        c = self._raw_client(monkeypatch)
        r = c.post("/vector/sync")
        assert r.status_code == 403