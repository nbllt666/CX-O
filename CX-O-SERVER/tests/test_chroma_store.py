"""server.core.memory.chroma_store (ChromaVectorStore) 单元测试。

注入假 chromadb 模块（sys.modules）隔离外部客户端，覆盖：
未安装降级、初始化与集合就绪、添加/检索/删除/存在检查、
相似检索距离归一化 ``(2-d)/2`` 与 min_score 过滤、同步（全量+增量）、
集合信息/清空/关闭。

运行：python -m pytest tests/test_chroma_store.py -v
"""
import sys
import types
from types import SimpleNamespace

import pytest

from server.core.memory.chroma_store import ChromaVectorStore, SyncResult


# ---------------------------------------------------------------------- 假对象
class FakeCollection:
    """内存版 chroma collection，按 id 存储。"""

    def __init__(self, name):
        self.name = name
        # id -> {embedding, document, metadata}
        self._items = {}

    def add(self, ids, embeddings=None, documents=None, metadatas=None):
        for i, id_ in enumerate(ids):
            self._items[id_] = {
                "embedding": embeddings[i] if embeddings else None,
                "document": documents[i] if documents else "",
                "metadata": metadatas[i] if metadatas else {},
            }

    def query(self, query_embeddings, n_results, where=None, include=None):
        # 简化：按距离假数据不应触发；这里用余弦距离近似计算
        matched = []
        for id_, item in self._items.items():
            meta = item["metadata"]
            if where and meta.get("type") != where.get("type"):
                continue
            matched.append((id_, item))
        ids = [m[0] for m in matched]
        distances = [0.5] * len(matched)  # 固定距离，sim = (2-0.5)/2 = 0.75
        documents = [m[1]["document"] for m in matched]
        metadatas = [m[1]["metadata"] for m in matched]
        n = min(n_results, len(matched))
        return {
            "ids": [ids[:n]],
            "documents": [documents[:n]],
            "metadatas": [metadatas[:n]],
            "distances": [distances[:n]],
        }

    def get(self, ids, include=None):
        got_ids = [id_ for id_ in ids if id_ in self._items]
        return {
            "ids": got_ids,
            "documents": [self._items[i]["document"] for i in got_ids],
            "metadatas": [self._items[i]["metadata"] for i in got_ids],
            "embeddings": [self._items[i]["embedding"] for i in got_ids],
        }

    def delete(self, ids):
        for id_ in ids:
            self._items.pop(id_, None)

    def count(self):
        return len(self._items)


class FakeClient:
    def __init__(self, registry, ephemeral=False):
        self._registry = registry
        self._ephemeral = ephemeral

    def get_or_create_collection(self, name, metadata=None):
        if name not in self._registry:
            self._registry[name] = FakeCollection(name)
        return self._registry[name]

    def delete_collection(self, name):
        self._registry.pop(name, None)


def _install_fake_chromadb(monkeypatch, registry=None):
    """把假 chromadb 模块经 monkeypatch 注入 sys.modules，返回 (fake_mod, registry)。"""
    registry = registry if registry is not None else {}
    mod = types.ModuleType("chromadb")

    def _client_factory(registry, ephemeral):
        def _make(**kw):
            return FakeClient(registry, ephemeral=ephemeral)

        return _make

    mod.PersistentClient = _client_factory(registry, ephemeral=False)
    mod.EphemeralClient = _client_factory(registry, ephemeral=True)
    monkeypatch.setitem(sys.modules, "chromadb", mod)
    return mod, registry


@pytest.fixture
def fake_chromadb(monkeypatch):
    mod, registry = _install_fake_chromadb(monkeypatch)
    return mod, registry


# -------------------------------------------------------------------- 未安装降级
class TestNotInstalled:
    def _block_chromadb(self, monkeypatch):
        real_import = __import__

        def _fake_import(name, *args, **kwargs):
            if name == "chromadb" or name.startswith("chromadb."):
                raise ImportError("No module named 'chromadb'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _fake_import)

    def test_client_none_and_collection_none_when_not_installed(self, monkeypatch):
        sys.modules.pop("chromadb", None)
        self._block_chromadb(monkeypatch)
        store = ChromaVectorStore(db_path=":memory:")
        assert store._client is None
        assert store._collection is None
        assert store.is_available() is False
        assert store.get_collection_info() == {"status": "unavailable"}

    @pytest.mark.asyncio
    async def test_ops_safe_defaults_when_unavailable(self, monkeypatch):
        sys.modules.pop("chromadb", None)
        self._block_chromadb(monkeypatch)
        store = ChromaVectorStore(db_path=":memory:")
        assert await store.add_memory_vector(1, "c", [0.1]) is False
        assert await store.search_similar([0.1]) == []
        assert await store.delete_by_memory_id(1) is False
        assert await store.get_vector_by_id(1) is None
        assert await store.check_exists(1) is False
        assert store.clear_collection() is False
        res = await store.sync_with_sqlite(None)
        assert res.total_checked == 0
        assert res.errors == 0


# ------------------------------------------------------------------ 初始化
class TestInit:
    @pytest.mark.asyncio
    async def test_persistent_initializes_collection(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/chroma_test")
        assert store._client is not None
        assert store._collection is not None
        assert "memory_vectors" in registry
        assert store.is_available() is True

    @pytest.mark.asyncio
    async def test_ephemeral_mode(self, monkeypatch):
        _, registry = _install_fake_chromadb(monkeypatch)
        store = ChromaVectorStore(db_path="data/x", persistent=False)
        assert store._client is not None
        assert store._collection is not None

    @pytest.mark.asyncio
    async def test_custom_collection_name(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x", collection_name="my_col")
        assert store.collection_name == "my_col"
        assert "my_col" in registry


# ------------------------------------------------------------------ 向量读写
class TestVectorIO:
    @pytest.mark.asyncio
    async def test_add_memory_vector(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        ok = await store.add_memory_vector(1, "hello", [0.1, 0.2], {"type": "long_term"})
        assert ok is True
        coll = registry["memory_vectors"]
        assert "1" in coll._items
        assert coll._items["1"]["metadata"]["memory_id"] == 1

    @pytest.mark.asyncio
    async def test_get_vector_by_id(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        await store.add_memory_vector(5, "content", [0.7, 0.8], {"k": "v"})
        got = await store.get_vector_by_id(5)
        assert got["id"] == 5
        assert got["content"] == "content"
        assert got["embedding"] == [0.7, 0.8]

    @pytest.mark.asyncio
    async def test_get_vector_by_id_missing_returns_none(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        assert await store.get_vector_by_id(99) is None

    @pytest.mark.asyncio
    async def test_check_exists(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        await store.add_memory_vector(1, "c", [0.1])
        assert await store.check_exists(1) is True
        assert await store.check_exists(2) is False


# ------------------------------------------------------------------ 相似检索
class TestSearchSimilar:
    @pytest.mark.asyncio
    async def test_normalizes_distance_and_maps_metadata(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        await store.add_memory_vector(7, "content", [0.1] * 3, {"type": "long_term"})
        results = await store.search_similar([0.1] * 3, limit=5, min_score=0.5)
        assert len(results) == 1
        assert results[0]["id"] == 7
        assert results[0]["score"] == pytest.approx(0.75)
        assert results[0]["metadata"]["type"] == "long_term"

    @pytest.mark.asyncio
    async def test_filters_by_min_score(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        await store.add_memory_vector(1, "a", [0.1])
        # 用极高 min_score 把 0.75 相似度过滤掉
        results = await store.search_similar([0.1], limit=5, min_score=0.9)
        assert results == []

    @pytest.mark.asyncio
    async def test_memory_type_where_filter(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        await store.add_memory_vector(1, "a", [0.1], {"type": "long_term"})
        await store.add_memory_vector(2, "b", [0.1], {"type": "short_term"})
        results = await store.search_similar([0.1], memory_type="long_term")
        assert [r["id"] for r in results] == [1]


# ------------------------------------------------------------------ 生命周期与同步
class TestLifecycle:
    @pytest.mark.asyncio
    async def test_delete_by_memory_id(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        await store.add_memory_vector(3, "c", [0.1])
        assert await store.delete_by_memory_id(3) is True
        assert await store.check_exists(3) is False

    @pytest.mark.asyncio
    async def test_get_collection_info_count(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        await store.add_memory_vector(1, "a", [0.1])
        info = store.get_collection_info()
        assert info["status"] == "available"
        assert info["count"] == 1
        assert info["name"] == "memory_vectors"

    @pytest.mark.asyncio
    async def test_clear_collection(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        await store.add_memory_vector(1, "a", [0.1])
        await store.add_memory_vector(2, "b", [0.1])
        assert store.clear_collection() is True
        assert registry["memory_vectors"].count() == 0

    @pytest.mark.asyncio
    async def test_sync_with_sqlite_creates_missing(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")

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
        assert registry["memory_vectors"]._items["1"]["metadata"]["type"] == "long_term"

    @pytest.mark.asyncio
    async def test_sync_incremental_filters_by_updated_at(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")

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
    async def test_close_nulls_connections(self, fake_chromadb):
        _, registry = fake_chromadb
        store = ChromaVectorStore(db_path="data/x")
        store.close()
        assert store._client is None
        assert store._collection is None