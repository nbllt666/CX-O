"""server.core.memory.weaviate_store (WeaviateVectorStore) 单元测试。

注入假 weaviate 模块（sys.modules）隔离外部客户端，覆盖：
未安装降级、collection 命名、初始化、相似检索的距离归一化与 min_score 过滤、
向量获取的 named-vector 解包、写入懒建 collection、删除/清空/信息/同步、
default collection 保护与工厂分发。

运行：python -m pytest tests/test_weaviate_store.py -v
"""
import sys
import types
from types import SimpleNamespace

import pytest

from server.core.memory.vector_store import create_vector_store
from server.core.memory.weaviate_store import WeaviateVectorStore


# ---------------------------------------------------------------------- 假对象
class FakeObject:
    def __init__(self, properties=None, vector=None, uuid="u1", distance=0.5):
        self.properties = properties or {}
        self.vector = vector
        self.uuid = uuid
        self.metadata = SimpleNamespace(distance=distance)


class FakeNearVector:
    def __init__(self, objects):
        self._objects = objects

    def with_filters(self, f):
        return self

    @property
    def objects(self):
        return self._objects


class FakeQuery:
    def __init__(self, collection):
        self._c = collection

    def near_vector(self, near_vector=None, limit=None, return_metadata=None):
        return FakeNearVector(self._c.objects)

    def fetch_objects(self, **kwargs):
        objs = list(self._c.objects)
        filters = kwargs.get("filters")
        if isinstance(filters, tuple) and len(filters) == 3 and filters[0] == "memory_id":
            _, _op, val = filters
            objs = [o for o in objs if o.properties.get("memory_id") == val]
        return SimpleNamespace(objects=objs)


class FakeData:
    def __init__(self, collection):
        self._c = collection

    def insert(self, properties=None, vector=None):
        self._c.objects.append(FakeObject(properties=properties, vector=vector))

    def delete_by_id(self, uuid):
        self._c.objects[:] = [o for o in self._c.objects if o.uuid != uuid]


class FakeAggregate:
    def __init__(self, collection):
        self._c = collection

    def over_all(self, total_count=False):
        return SimpleNamespace(total_count=len(self._c.objects))


class FakeCollection:
    def __init__(self, name, objects=None):
        self.name = name
        self.objects = list(objects or [])
        self.data = FakeData(self)
        self.query = FakeQuery(self)
        self.aggregate = FakeAggregate(self)


class FakeCollections:
    def __init__(self, registry):
        self._registry = registry

    def exists(self, name):
        return name in self._registry

    def get(self, name):
        return self._registry[name]

    def create(self, name="", vectorizer_config=None, properties=None):
        self._registry[name] = FakeCollection(name)

    def delete(self, name):
        self._registry.pop(name, None)


class FakeClient:
    def __init__(self, registry=None):
        self.collections = FakeCollections(registry if registry is not None else {})

    def is_ready(self):
        return True

    def close(self):
        pass


def _install_fake_weaviate(monkeypatch, registry=None):
    """把假 weaviate 子模块经 monkeypatch 注入 sys.modules，返回 (fake_weaviate, registry)。"""
    ns_config = SimpleNamespace(
        Configure=SimpleNamespace(Vectorizer=SimpleNamespace(none=lambda: None)),
        Property=lambda **kw: kw,
        DataType=SimpleNamespace(TEXT="text", INT="int", NUMBER="number",
                                 TEXT_ARRAY="text[]", DATE="date", BOOL="bool"),
    )
    ns_query = SimpleNamespace(
        Filter=SimpleNamespace(
            by_property=lambda name: SimpleNamespace(equal=lambda v: (name, "equal", v)),
            all_of=lambda conds: ("all_of", conds),
        )
    )
    ns_init = SimpleNamespace(
        AdditionalConfig=lambda **kw: ("additional", kw),
        Timeout=lambda **kw: ("timeout", kw),
    )

    ns_classes = SimpleNamespace(config=ns_config, query=ns_query, init=ns_init)
    submods = {
        "weaviate.classes.config": ns_config,
        "weaviate.classes.query": ns_query,
        "weaviate.classes.init": ns_init,
        "weaviate.classes": ns_classes,
    }
    for name, ns in submods.items():
        m = types.ModuleType(name)
        for k, v in vars(ns).items():
            setattr(m, k, v)
        monkeypatch.setitem(sys.modules, name, m)

    weaviate_mod = types.ModuleType("weaviate")
    weaviate_mod.classes = sys.modules["weaviate.classes"]
    registry = registry if registry is not None else {}
    weaviate_mod.connect_to_local = lambda **kw: FakeClient(registry)
    weaviate_mod.connect_to_embedded = lambda **kw: FakeClient(registry)
    monkeypatch.setitem(sys.modules, "weaviate", weaviate_mod)
    return weaviate_mod, registry


@pytest.fixture
def fake_weaviate(monkeypatch):
    mod, registry = _install_fake_weaviate(monkeypatch)
    return mod, registry


# ----------------------------------------------------------------- 未安装降级
class TestNotInstalled:
    def _block_weaviate(self, monkeypatch):
        real_import = __import__
        states = {"env": ""}

        def _fake_import(name, *args, **kwargs):
            if name == "weaviate" or name.startswith("weaviate."):
                raise ImportError("No module named 'weaviate'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", _fake_import)

    @pytest.mark.asyncio
    async def test_client_none_when_not_installed(self, monkeypatch):
        # 若真实环境已装 weaviate，先移除再封锁 import
        sys.modules.pop("weaviate", None)
        self._block_weaviate(monkeypatch)
        store = WeaviateVectorStore()
        assert store._client is None
        assert store.is_available() is False

    @pytest.mark.asyncio
    async def test_ops_safe_defaults_when_unavailable(self, monkeypatch):
        sys.modules.pop("weaviate", None)
        self._block_weaviate(monkeypatch)
        store = WeaviateVectorStore()
        assert await store.add_memory_vector(1, "c", [0.1]) is False
        assert await store.search_similar([0.1]) == []
        assert await store.delete_by_memory_id(1) is False
        assert await store.get_vector_by_id(1) is None
        assert await store.check_exists(1) is False
        assert store.get_collection_info() == {"error": "Weaviate 不可用"}
        assert store.clear_collection() is False
        assert store.ensure_agent_collection("x") is False
        assert store.delete_agent_collection("x") is False
        res = await store.sync_with_sqlite(None)
        assert res.errors == 1
        assert res.details == ["Weaviate 不可用"]


# ---------------------------------------------------------------- collection 命名
class TestCollectionName:
    @pytest.mark.asyncio
    async def test_default_returns_schema_class(self, fake_weaviate):
        store = WeaviateVectorStore()
        assert store._collection_name_for_agent("default") == "CXOMemory"

    @pytest.mark.asyncio
    async def test_empty_returns_schema_class(self, fake_weaviate):
        store = WeaviateVectorStore()
        assert store._collection_name_for_agent("") == "CXOMemory"

    @pytest.mark.asyncio
    async def test_agent_prefixed_by_schema(self, fake_weaviate):
        store = WeaviateVectorStore()
        assert store._collection_name_for_agent("abc123") == "CXOMemory_abc123"

    @pytest.mark.asyncio
    async def test_agent_sanitizes_special_chars(self, fake_weaviate):
        store = WeaviateVectorStore()
        assert store._collection_name_for_agent("a-b/c d") == "CXOMemory_a_b_c_d"


# ------------------------------------------------------------------ 初始化
class TestInit:
    @pytest.mark.asyncio
    async def test_initialize_sets_client_and_ensures_default(self, fake_weaviate):
        _, registry = fake_weaviate
        store = WeaviateVectorStore()
        assert store._client is not None
        assert "CXOMemory" in registry  # default collection 被预建

    @pytest.mark.asyncio
    async def test_is_available_when_client_ready(self, fake_weaviate):
        store = WeaviateVectorStore()
        assert store.is_available() is True

    @pytest.mark.asyncio
    async def test_embedded_mode(self, monkeypatch):
        _, registry = _install_fake_weaviate(monkeypatch)
        store = WeaviateVectorStore(embedded=True)
        assert store._client is not None
        assert store.embedded is True


# ------------------------------------------------------------------ 相似检索
class TestSearchSimilar:
    @pytest.mark.asyncio
    async def test_normalizes_distance_and_maps_metadata(self, fake_weaviate):
        _, registry = fake_weaviate
        registry["CXOMemory"] = FakeCollection("CXOMemory", [
            FakeObject(properties={"memory_id": 7, "content": "c", "memory_type": "long_term",
                                   "importance": 0.8, "tags": ["t"], "created_at": "2026",
                                   "workspace_id": "w", "is_archived": False},
                       distance=0.4),  # similarity = (2-0.4)/2 = 0.8
        ])
        store = WeaviateVectorStore()
        results = await store.search_similar([0.1] * 3, limit=5, min_score=0.5)
        assert len(results) == 1
        assert results[0]["memory_id"] == 7
        assert results[0]["score"] == pytest.approx(0.8)
        assert results[0]["metadata"]["type"] == "long_term"
        assert results[0]["metadata"]["agent_id"] == "default"

    @pytest.mark.asyncio
    async def test_filters_by_min_score(self, fake_weaviate):
        _, registry = fake_weaviate
        registry["CXOMemory"] = FakeCollection("CXOMemory", [
            FakeObject(properties={"memory_id": 1, "content": "a"}, distance=1.8),  # sim=0.1
            FakeObject(properties={"memory_id": 2, "content": "b"}, distance=0.2),  # sim=0.9
        ])
        store = WeaviateVectorStore()
        results = await store.search_similar([0.1], limit=5, min_score=0.5)
        assert [r["memory_id"] for r in results] == [2]

    @pytest.mark.asyncio
    async def test_memory_type_filter_uses_with_filters(self, fake_weaviate):
        _, registry = fake_weaviate
        store = WeaviateVectorStore()
        # 不应抛错（构造 Filter 链路）
        assert await store.search_similar([0.1], memory_type="long_term") == []


# ---------------------------------------------------------------- 向量读写
class TestVectorIO:
    @pytest.mark.asyncio
    async def test_add_memory_vector_creates_agent_collection(self, fake_weaviate):
        _, registry = fake_weaviate
        store = WeaviateVectorStore()
        ok = await store.add_memory_vector(1, "hello", [0.1, 0.2],
                                           {"type": "long_term", "agent_id": "wx"}, agent_id="wx")
        assert ok is True
        assert "CXOMemory_wx" in registry
        assert registry["CXOMemory_wx"].objects[0].properties["content"] == "hello"

    @pytest.mark.asyncio
    async def test_get_vector_by_id_unpacks_named_vector(self, fake_weaviate):
        _, registry = fake_weaviate
        registry["CXOMemory"] = FakeCollection("CXOMemory", [
            FakeObject(properties={"memory_id": 5, "content": "c", "memory_type": "long_term"},
                       vector={"default": [0.7, 0.8]}),
        ])
        store = WeaviateVectorStore()
        got = await store.get_vector_by_id(5)
        assert got["memory_id"] == 5
        assert got["vector"] == [0.7, 0.8]

    @pytest.mark.asyncio
    async def test_get_vector_by_id_missing_returns_none(self, fake_weaviate):
        _, registry = fake_weaviate
        registry["CXOMemory"] = FakeCollection("CXOMemory")
        store = WeaviateVectorStore()
        assert await store.get_vector_by_id(99) is None

    @pytest.mark.asyncio
    async def test_check_exists(self, fake_weaviate):
        _, registry = fake_weaviate
        registry["CXOMemory"] = FakeCollection("CXOMemory", [
            FakeObject(properties={"memory_id": 1, "content": "c"}),
        ])
        store = WeaviateVectorStore()
        assert await store.check_exists(1) is True
        assert await store.check_exists(2) is False


# ------------------------------------------------------------------ 生命周期与同步
class TestLifecycle:
    @pytest.mark.asyncio
    async def test_delete_by_memory_id_removes_vector(self, fake_weaviate):
        _, registry = fake_weaviate
        registry["CXOMemory"] = FakeCollection("CXOMemory", [
            FakeObject(properties={"memory_id": 3, "content": "c"}, uuid="abc"),
        ])
        store = WeaviateVectorStore()
        assert await store.delete_by_memory_id(3) is True
        assert registry["CXOMemory"].objects == []

    @pytest.mark.asyncio
    async def test_delete_agent_collection_protects_default(self, fake_weaviate):
        _, registry = fake_weaviate
        store = WeaviateVectorStore()
        assert store.delete_agent_collection("default") is False

    @pytest.mark.asyncio
    async def test_delete_agent_collection_removes_non_default(self, fake_weaviate):
        _, registry = fake_weaviate
        store = WeaviateVectorStore()
        store.ensure_agent_collection("wx")
        assert "CXOMemory_wx" in registry
        assert store.delete_agent_collection("wx") is True
        assert "CXOMemory_wx" not in registry

    @pytest.mark.asyncio
    async def test_get_collection_info_count(self, fake_weaviate):
        _, registry = fake_weaviate
        registry["CXOMemory"] = FakeCollection("CXOMemory", [FakeObject(properties={"memory_id": 1})])
        store = WeaviateVectorStore()
        info = store.get_collection_info()
        assert info["count"] == 1
        assert info["vectors_count"] == 1
        assert info["collection_name"] == "CXOMemory"

    @pytest.mark.asyncio
    async def test_clear_collection(self, fake_weaviate):
        _, registry = fake_weaviate
        registry["CXOMemory"] = FakeCollection("CXOMemory", [
            FakeObject(properties={"memory_id": 1}, uuid="a"),
            FakeObject(properties={"memory_id": 2}, uuid="b"),
        ])
        store = WeaviateVectorStore()
        assert store.clear_collection() is True
        assert registry["CXOMemory"].objects == []

    @pytest.mark.asyncio
    async def test_sync_with_sqlite_creates_missing(self, fake_weaviate):
        _, registry = fake_weaviate
        store = WeaviateVectorStore()

        class FakeEmbedding:
            async def get_embedding(self, text):
                return [0.1]

        store.embedding_model = FakeEmbedding()

        class FakeSQLite:
            def search_memories(self, memory_type=None, limit=10000, include_deleted=False):
                return [{"id": 1, "content": "hello", "agent_id": "default"}]

        res = await store.sync_with_sqlite(FakeSQLite())
        assert res.total_checked == 1
        assert res.synced == 1
        assert res.errors == 0
        assert "CXOMemory" in registry
        assert registry["CXOMemory"].objects[0].properties["memory_id"] == 1

    @pytest.mark.asyncio
    async def test_sync_incremental_filters_by_updated_at(self, fake_weaviate):
        _, registry = fake_weaviate
        store = WeaviateVectorStore()

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


# ------------------------------------------------------------------ 工厂
class TestFactory:
    @pytest.mark.asyncio
    async def test_create_weaviate(self, fake_weaviate):
        store = create_vector_store("weaviate")
        assert isinstance(store, WeaviateVectorStore)
        assert store.embedded is False

    @pytest.mark.asyncio
    async def test_create_weaviate_embedded(self, fake_weaviate):
        store = create_vector_store("weaviate_embedded")
        assert isinstance(store, WeaviateVectorStore)
        assert store.embedded is True

    @pytest.mark.asyncio
    async def test_unknown_backend_raises(self, fake_weaviate):
        with pytest.raises(ValueError, match="Unknown vector store backend"):
            create_vector_store("nope")