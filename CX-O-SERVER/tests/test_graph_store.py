"""server.core.memory.graph_store (SQLiteGraphStore) 单元测试。

用真实内存 SQLite + 真实 NodeManager/EdgeManager/TraversalManager 包一层轻量容器，
隔离 semantic/vectorizer 的重模型加载，覆盖实体/关系 CRUD、名称解析、
关联查询、路径、统计、导出与删除策略。

运行：python -m pytest tests/test_graph_store.py -v
"""
from dataclasses import dataclass

import pytest

from server.core.graph.config import GraphConfig
from server.core.graph.database import Database
from server.core.graph.edges import EdgeManager
from server.core.graph.nodes import NodeManager
from server.core.graph.traversal import TraversalManager
from server.core.memory.graph_store import (
    ENTITY_TYPE_TO_LIBRARY,
    ConceptEntityType,
    Entity,
    GraphLibrary,
    GraphStoreBase,
    Relation,
    SQLiteGraphStore,
)


@dataclass
class _GraphContainer:
    """SQLiteGraphStore 所需接口的最小真实容器（仅试 graph 逻辑，不启 semantic）。"""

    agent_id: str
    db: Database
    nodes: NodeManager
    edges: EdgeManager
    traversal: TraversalManager


@pytest.fixture
def store():
    config = GraphConfig(database_path=":memory:")
    db = Database(config)
    db.initialize()
    container = _GraphContainer(
        agent_id="default",
        db=db,
        nodes=NodeManager(db, config),
        edges=EdgeManager(db, config),
        traversal=TraversalManager(db, config),
    )
    yield SQLiteGraphStore(container)
    db.close()


@pytest.fixture
def seeded(store):
    a = store.create_entity(Entity(entity_id="a", name="Alice", entity_type="person"), GraphLibrary.USER)
    b = store.create_entity(Entity(entity_id="b", name="Bob", entity_type="person"), GraphLibrary.USER)
    c = store.create_entity(Entity(entity_id="c", name="Python", entity_type="concept"), GraphLibrary.CONCEPT)
    r1 = store.create_relation(Relation(from_entity="Alice", to_entity="Bob", relation_type="knows"), GraphLibrary.USER)
    return {"a": a, "b": b, "c": c, "r1": r1}


# ---------------------------------------------------------------- 枚举与映射
class TestEnums:
    def test_graph_library_values(self):
        assert GraphLibrary.USER.value == "user"
        assert GraphLibrary.THING.value == "thing"
        assert GraphLibrary.CONCEPT.value == "concept"
        assert GraphLibrary.EVENT.value == "event"

    def test_entity_type_to_library(self):
        assert ENTITY_TYPE_TO_LIBRARY["person"] == GraphLibrary.USER
        assert ENTITY_TYPE_TO_LIBRARY["product"] == GraphLibrary.THING
        assert ENTITY_TYPE_TO_LIBRARY["idea"] == GraphLibrary.CONCEPT
        assert ENTITY_TYPE_TO_LIBRARY["event"] == GraphLibrary.EVENT

    def test_abstract_base(self):
        with pytest.raises(TypeError):
            GraphStoreBase()

    def test_accessor_helpers(self, store):
        assert store._node_type(GraphLibrary.USER, "person") == "user_person"
        assert store._edge_type(GraphLibrary.CONCEPT, "related_to") == "concept_related_to"


class TestEntityCrud:
    def test_create_and_get_roundtrip(self, store):
        e = store.create_entity(
            Entity(entity_id="e1", name="Alpha", entity_type="concept", properties={"weight": 3.0}),
            GraphLibrary.CONCEPT,
        )
        assert e.entity_id  # 有 ID
        got = store.get_entity(e.entity_id, GraphLibrary.CONCEPT)
        assert got.name == "Alpha"
        assert got.entity_type == "concept"
        assert got.properties == {"weight": 3.0}

    def test_entity_from_node_strips_internal_props(self, seeded):
        e = seeded["a"]
        assert "name" not in e.properties
        assert "entity_type" not in e.properties
        assert "library" not in e.properties
        assert "memory_ids" not in e.properties

    def test_get_entity_by_name_resolution(self, store, seeded):
        got = store.get_entity("Alice", GraphLibrary.USER)
        assert got is not None
        assert got.name == "Alice"

    def test_get_entity_name_across_library_isolated(self, store, seeded):
        # 同名实体在不同 library 下互不干扰（类型前缀不同）
        otro = seeded["c"]
        assert store.get_entity("Python", GraphLibrary.USER) is None
        assert store.get_entity("Python", GraphLibrary.CONCEPT) is not None

    def test_get_entity_missing_returns_none(self, store):
        assert store.get_entity("nope", GraphLibrary.USER) is None

    def test_update_entity(self, store):
        e = store.create_entity(Entity(entity_id="x", name="X", entity_type="concept"), GraphLibrary.CONCEPT)
        updated = store.update_entity(e.entity_id, {"weight": 9}, GraphLibrary.CONCEPT)
        assert updated.properties["weight"] == 9
        assert updated.name == "X"

    def test_update_entity_missing_returns_none(self, store):
        assert store.update_entity("nope", {"a": 1}, GraphLibrary.USER) is None

    def test_delete_entity_soft(self, store):
        e = store.create_entity(Entity(entity_id="d", name="D", entity_type="person"), GraphLibrary.USER)
        assert store.delete_entity(e.entity_id, GraphLibrary.USER, hard=False) is True
        # 软删后节点仍存在但 properties.deleted=True
        node = store._db.nodes.get(e.entity_id)
        assert node.properties.get("deleted") is True

    def test_delete_entity_hard(self, store):
        e = store.create_entity(Entity(entity_id="h", name="H", entity_type="person"), GraphLibrary.USER)
        assert store.delete_entity(e.entity_id, GraphLibrary.USER, hard=True) is True
        assert store._db.nodes.get(e.entity_id) is None

    def test_delete_entity_missing_returns_false(self, store):
        assert store.delete_entity("nope", GraphLibrary.USER) is False


class TestRelationCrud:
    def test_create_relation_resolves_names(self, seeded):
        r = seeded["r1"]
        assert r.from_entity and r.to_entity  # 已解析为实体 ID
        assert r.relation_type == "knows"
        assert r.strength == 1.0

    def test_create_relation_missing_source_raises(self, store):
        store.create_entity(Entity(entity_id="a", name="Alice", entity_type="person"), GraphLibrary.USER)
        with pytest.raises(ValueError, match="源实体不存在"):
            store.create_relation(
                Relation(from_entity="nobody", to_entity="Alice", relation_type="knows"), GraphLibrary.USER
            )

    def test_create_relation_missing_target_raises(self, store):
        store.create_entity(Entity(entity_id="a", name="Alice", entity_type="person"), GraphLibrary.USER)
        with pytest.raises(ValueError, match="目标实体不存在"):
            store.create_relation(
                Relation(from_entity="Alice", to_entity="nobody", relation_type="knows"), GraphLibrary.USER
            )

    def test_update_relation(self, store, seeded):
        r = seeded["r1"]
        updated = store.update_relation(
            r.from_entity, r.to_entity, "knows", {"strength": 0.5}, GraphLibrary.USER
        )
        assert updated is not None
        assert updated.strength == 0.5

    def test_update_relation_not_found_returns_none(self, store, seeded):
        assert store.update_relation("x", "y", "knows", {"strength": 1}, GraphLibrary.USER) is None

    def test_delete_relation_soft(self, store, seeded):
        r = seeded["r1"]
        assert store.delete_relation(r.from_entity, r.to_entity, "knows", GraphLibrary.USER, hard=False) is True
        edge = store._db.edges.search(source_id=r.from_entity, relation_type="user_knows").items[0]
        assert edge.properties.get("deleted") is True

    def test_delete_relation_hard(self, store, seeded):
        r = seeded["r1"]
        assert store.delete_relation(r.from_entity, r.to_entity, "knows", GraphLibrary.USER, hard=True) is True
        assert store._db.edges.search(source_id=r.from_entity).items == []

    def test_delete_relation_missing_returns_false(self, store):
        assert store.delete_relation("a", "b", "knows", GraphLibrary.USER) is False


class TestTraversal:
    def test_find_related_entities(self, store, seeded):
        related = store.find_related_entities("Alice", None, GraphLibrary.USER)
        names = {e.name for e in related}
        assert "Bob" in names

    def test_find_related_filtered_by_type(self, store, seeded):
        related = store.find_related_entities("Alice", "knows", GraphLibrary.USER)
        assert {e.name for e in related} == {"Bob"}
        none_rel = store.find_related_entities("Alice", "friend", GraphLibrary.USER)
        assert none_rel == []

    def test_find_related_missing_returns_empty(self, store):
        assert store.find_related_entities("nope", None, GraphLibrary.USER) == []

    def test_find_paths(self, store, seeded):
        # Alice -> Bob -> (间接) 无，仅一条直接路径
        paths = store.find_paths("Alice", "Bob", GraphLibrary.USER, max_depth=3)
        assert any(p[0].name == "Alice" and p[-1].name == "Bob" for p in paths)

    def test_find_paths_missing_returns_empty(self, store):
        assert store.find_paths("a", "b", GraphLibrary.USER) == []


class TestStatsExport:
    def test_get_stats(self, store, seeded):
        stats = store.get_stats(GraphLibrary.USER)
        assert stats["library"] == "user"
        assert stats["entity_count"] == 2  # 仅 user 库
        assert stats["relation_count"] == 1

    def test_export(self, store, seeded):
        data = store.export(GraphLibrary.USER)
        assert data["library"] == "user"
        assert len(data["entities"]) == 2
        assert len(data["relations"]) == 1
        assert data["entities"][0]["name"]

    def test_cross_library_stats_isolated(self, store, seeded):
        stats_user = store.get_stats(GraphLibrary.USER)
        stats_concept = store.get_stats(GraphLibrary.CONCEPT)
        assert stats_concept["entity_count"] == 1
        assert stats_user["entity_count"] == 2