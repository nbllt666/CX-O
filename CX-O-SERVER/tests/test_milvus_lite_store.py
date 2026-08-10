"""server.core.memory.milvus_lite_store (MilvusLiteVectorStore) 单元测试。

注入假 pymilvus 模块（sys.modules）隔离外部客户端，覆盖：
未安装降级、初始化与集合创建、添加/检索/删除/存在检查、
相似检索距离归一化 ``(2-d)/2`` 与 min_score 过滤、同步（全量+增量）、
集合信息/清空/关闭。

运行：python -m pytest tests/test_milvus_lite_store.py -v
"""
import sys
import types

import pytest

from server.core.memory.milvus_lite_store import MilvusLiteVectorStore, SyncResult


# ---------------------------------------------------------------------- 假对象
class FakeMilvusClient:
    """内存版 pymilvus MilvusClient，按 collection 存储。"""

    def __init__(self, db_path, registry):
        self.db_path = db_path
        self._registry = registry
        self.closed = False

    def list_collections(self):
        return list(self._registry.keys())

    def create_collection(self, collection_name=None, dimension=None, metric_type=None):
        self._registry.setdefault(collection_name, [])

    def insert(self, collection_name=None, data=None):
        self._registry.setdefault(collection_name, [])
        for row in data or []:
            self._registry[collection_name].append(dict(row))

    def search(self, collection_name=None, data=None, limit=None, output_fields=None):
        rows = self._registry.get(collection_name) or []
        results = []
        for row in rows[:limit]:
            # 固定距离 0.5，sim = (2-0.5)/2 = 0.75
            results.append({"distance": 0.5, "id": row["id"], "entity": row})
        return [results]

    def delete(self, collection_name=None, ids=None):
        rows = self._registry.get(collection_name) or []
        del_ids = set(ids or [])
        self._registry[collection_name] = [r for r in rows if r["id"] not in del_ids]

    def query(self, collection_name=None, filter=None, output_fields=None):
        rows = self._registry.get(collection_name) or []
        if filter:
            id_str = filter.split("==")[-1].strip()
            try:
                target = int(id_str)
            except ValueError:
                target = None
            rows = [r for r in rows if r.get("memory_id") == target]
        return rows

    def get_collection_stats(self, collection_name=None):
        return {"row_count": len((self._registry.get(collection_name)) or [])}

    def drop_collection(self, collection_name=None):
        self._registry.pop(collection_name, None)

    def close(self):
        self.closed = True


def _install_fake_pymilvus(monkeypatch, registry=None):
    """把假 pymilvus 模块经 monkeypatch 注入 sys.modules，返回 (fake_mod, registry)。"""
    registry = registry if registry is not None else {}
    mod = types.ModuleType("pymilvus")

    def _client_factory(registry):
        def _make(db_path, **kw):
            return FakeMilvusClient(db_path, registry)

        return _make

    mod.MilvusClient = _client_factory(registry)
    monkeypatch.setitem(sys.modules, "pymilvus", mod)
    return mod, registry


@pytest.fixture
def fake_milvus(monkeypatch):
    mod, registry = _install_fake_pymilvus(monkeypatch)
    return mod, registry


# -------------------------------------------------------------------- 未安装降级
class TestNotInstalled:
    def _block_pymilvus(self, monkeypatch):
        real_import = __import__

        def _fake_import(name, *args, **kwargs):
            if name == "pymilvus" or name.startswith("pymilvus."):
                raise ImportError("No module named 'pymilvus'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _fake_import)

    def test_client_none_when_not_installed(self, monkeypatch):
        sys.modules.pop("pymilvus", None)
        self._block_pymilvus(monkeypatch)
        store = MilvusLiteVectorStore(db_path=":memory:")
        assert store._client is None
        assert store.is_available() is False
        assert store.get_collection_info() == {"error": "Milvus Lite不可用"}

    @pytest.mark.asyncio
    async def test_ops_safe_defaults_when_unavailable(self, monkeypatch):
        sys.modules.pop("pymilvus", None)
        self._block_pymilvus(monkeypatch)
        store = MilvusLiteVectorStore(db_path=":memory:")
        assert await store.add_memory_vector(1, "c", [0.1]) is False
        assert await store.search_similar([0.1]) == []
        assert await store.delete_by_memory_id(1) is False
        assert await store.get_vector_by_id(1) is None
        assert await store.check_exists(1) is False
        assert store.clear_collection() is False
        res = await store.sync_with_sqlite(None)
        assert res.errors == 1
        assert res.details == ["Milvus Lite不可用"]


# ------------------------------------------------------------------ 初始化
class TestInit:
    @pytest.mark.asyncio
    async def test_initializes_collection(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/milvus_test")
        assert store._client is not None
        assert "memory_vectors" in registry
        assert store.is_available() is True

    @pytest.mark.asyncio
    async def test_custom_collection_name(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x", collection_name="my_col")
        assert store.collection_name == "my_col"
        assert "my_col" in registry


# ------------------------------------------------------------------ 向量读写
class TestVectorIO:
    @pytest.mark.asyncio
    async def test_add_memory_vector(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        ok = await store.add_memory_vector(1, "hello", [0.1, 0.2], {"type": "long_term"})
        assert ok is True
        assert registry["memory_vectors"][0]["memory_id"] == 1
        assert registry["memory_vectors"][0]["type"] == "long_term"

    @pytest.mark.asyncio
    async def test_get_vector_by_id(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        await store.add_memory_vector(5, "content", [0.7, 0.8], {"k": "v"})
        got = await store.get_vector_by_id(5)
        assert got["memory_id"] == 5
        assert got["content"] == "content"

    @pytest.mark.asyncio
    async def test_get_vector_by_id_missing_returns_none(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        assert await store.get_vector_by_id(99) is None

    @pytest.mark.asyncio
    async def test_get_vector_by_id_non_int_rejected(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        assert await store.get_vector_by_id("abc") is None

    @pytest.mark.asyncio
    async def test_check_exists(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        await store.add_memory_vector(1, "c", [0.1])
        assert await store.check_exists(1) is True
        assert await store.check_exists(2) is False


# ------------------------------------------------------------------ 相似检索
class TestSearchSimilar:
    @pytest.mark.asyncio
    async def test_normalizes_distance_and_maps_metadata(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        await store.add_memory_vector(7, "content", [0.1] * 3, {"type": "long_term"})
        results = await store.search_similar([0.1] * 3, limit=5, min_score=0.5)
        assert len(results) == 1
        assert results[0]["memory_id"] == 7
        assert results[0]["score"] == pytest.approx(0.75)
        assert results[0]["metadata"]["content"] == "content"

    @pytest.mark.asyncio
    async def test_filters_by_min_score(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        await store.add_memory_vector(1, "a", [0.1])
        results = await store.search_similar([0.1], limit=5, min_score=0.9)
        assert results == []


# ------------------------------------------------------------------ 生命周期与同步
class TestLifecycle:
    @pytest.mark.asyncio
    async def test_delete_by_memory_id(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        await store.add_memory_vector(3, "c", [0.1])
        assert await store.delete_by_memory_id(3) is True
        assert await store.check_exists(3) is False

    @pytest.mark.asyncio
    async def test_get_collection_info_count(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        await store.add_memory_vector(1, "a", [0.1])
        info = store.get_collection_info()
        assert info["status"] == "active"
        assert info["row_count"] == 1
        assert info["collection_name"] == "memory_vectors"

    @pytest.mark.asyncio
    async def test_clear_collection(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        await store.add_memory_vector(1, "a", [0.1])
        await store.add_memory_vector(2, "b", [0.1])
        assert store.clear_collection() is True
        assert registry["memory_vectors"] == []

    @pytest.mark.asyncio
    async def test_sync_with_sqlite_creates_missing(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")

        class FakeEmbedding:
            async def get_embedding(self, text):
                return [0.1]

        store.embedding_model = FakeEmbedding()

        class FakeSQLite:
            def search_memories(self, memory_type=None, limit=10000, include_deleted=False):
                return [{"id": 1, "content": "hello", "type": "long_term"}]

        res = await store.sync_with_sqlite(FakeSQLite())
        assert isinstance(res, SyncResult)
        assert res.total_checked == 1
        assert res.synced == 1
        assert res.errors == 0
        assert registry["memory_vectors"][0]["memory_id"] == 1

    @pytest.mark.asyncio
    async def test_sync_incremental_filters_by_updated_at(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")

        class FakeEmbedding:
            async def get_embedding(self, text):
                return [0.1]

        store.embedding_model = FakeEmbedding()

        class FakeSQLite:
            def search_memories(self, memory_type=None, limit=10000, include_deleted=False):
                return [
                    {"id": 1, "content": "old", "updated_at": "2026-01-01"},
                    {"id": 2, "content": "new", "updated_at": "2026-08-01"},
                ]

        res = await store.sync_with_sqlite(FakeSQLite(), last_sync_time="2026-06-01")
        assert res.total_checked == 1
        assert res.synced == 1

    @pytest.mark.asyncio
    async def test_close_closes_client(self, fake_milvus):
        _, registry = fake_milvus
        store = MilvusLiteVectorStore(db_path="data/x")
        store.close()
        assert store._client.closed is True