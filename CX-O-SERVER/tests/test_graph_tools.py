"""server.core.tools.graph_tools 单元测试。

覆盖图数据库工具：agent_id 上下文切换、实体/关系字典序列化、实体 ID 生成
确定性、库名映射、工厂 `_make_graph_tools` 生成 14 操作闭包，以及 4 个图库
（user/thing/concept/event）暴露函数的创建/查询/路径/记忆增强搜索/实体提取/
合并/摘要/更新/删除/统计/导出。图存储以轻量替身注入，`Settings` 默认值用
monkeypatch 隔离。

运行：python -m pytest tests/test_graph_tools.py -v
"""
import hashlib
from datetime import datetime

import pytest

import server.core.tools.graph_tools as gt
from server.core.memory.graph_store import GraphLibrary, Entity, Relation


class FakeGraphStore:
    def __init__(self):
        self.entities = {}
        self.relations = []
        self.calls = []
        self.find_result = []
        self.paths = []
        self.stats = {"entities": 3, "relations": 2}

    def create_entity(self, entity, library):
        self.calls.append(("create_entity", library))
        self.entities[entity.entity_id] = entity
        return entity

    def create_relation(self, relation, library):
        self.calls.append(("create_relation", library))
        self.relations.append(relation)
        return relation

    def get_entity(self, entity_id, library):
        self.calls.append(("get_entity", library))
        return self.entities.get(entity_id)

    def find_related_entities(self, entity_id, relation_type, library, depth):
        self.calls.append(("find_related_entities", library))
        return self.find_result

    def find_paths(self, start, end, library, max_depth):
        self.calls.append(("find_paths", library))
        return self.paths

    def delete_entity(self, entity_id, library, hard):
        self.calls.append(("delete_entity", library))
        return entity_id in self.entities

    def delete_relation(self, from_entity, to_entity, relation_type, library, hard):
        self.calls.append(("delete_relation", library))
        return True

    def update_entity(self, entity_id, updates, library):
        self.calls.append(("update_entity", library))
        if entity_id not in self.entities:
            return None
        self.entities[entity_id].properties.update(updates)
        if "memory_ids" in updates:
            self.entities[entity_id].memory_ids = updates["memory_ids"]
        return self.entities[entity_id]

    def update_relation(self, from_entity, to_entity, relation_type, updates, library):
        self.calls.append(("update_relation", library))
        return None

    def get_stats(self, library):
        self.calls.append(("get_stats", library))
        return self.stats

    def export(self, library):
        self.calls.append(("export", library))
        return {"entities": [], "relations": []}


@pytest.fixture
def store(monkeypatch):
    fake = FakeGraphStore()
    gt.set_graph_dependencies(fake)
    monkeypatch.setattr(
        "server.core.tools.graph_tools.Settings",
        lambda: type("S", (), {"config": type("C", (),
                                             {"limits": type("L", (),
                                                             {"memory": type("M", (),
                                                                             {"entity_candidates": 10,
                                                                              "search_memories_limit": 5})})})})(),
    )
    yield fake
    gt.set_graph_dependencies(None)


def _make(library=GraphLibrary.USER, label="用户图"):
    return gt._make_graph_tools(library, label)


# ---------------------------------------------------------------- agent 上下文
class TestAgentContext:
    def test_default(self):
        assert gt.get_current_agent_id() == "default"

    def test_set_get(self):
        gt.set_current_agent_id("agentx")
        assert gt.get_current_agent_id() == "agentx"

    def test_set_empty_falls_back_default(self):
        gt.set_current_agent_id("")
        assert gt.get_current_agent_id() == "default"


# ---------------------------------------------------------------- 序列化/映射/ID
class TestHelpers:
    def test_entity_to_dict_none(self):
        assert gt._entity_to_dict(None) == {}

    def test_entity_to_dict_full(self):
        e = Entity(entity_id="e1", name="张三", entity_type="person",
                   properties={"a": 1}, memory_ids=["m1"], created_at=datetime(2026, 1, 1),
                   updated_at=datetime(2026, 1, 2), deleted=False)
        d = gt._entity_to_dict(e)
        assert d["entity_id"] == "e1"
        assert d["created_at"] == "2026-01-01T00:00:00"
        assert d["deleted"] is False

    def test_relation_to_dict_none(self):
        assert gt._relation_to_dict(None) == {}

    def test_relation_to_dict_full(self):
        r = Relation(from_entity="a", to_entity="b", relation_type="knows",
                     strength=0.8, evidence_memory_ids=["m1"], created_at=datetime(2026, 1, 1))
        d = gt._relation_to_dict(r)
        assert d["strength"] == 0.8
        assert d["evidence_memory_ids"] == ["m1"]

    def test_generate_entity_id_deterministic(self):
        a = gt._generate_entity_id("张三", "person")
        b = gt._generate_entity_id("张三", "person")
        assert a == b
        assert len(a) == 16
        assert a == hashlib.md5("张三:person".encode()).hexdigest()[:16]

    def test_get_library_mapping(self):
        assert gt._get_library("USER") == GraphLibrary.USER
        assert gt._get_library("thing") == GraphLibrary.THING
        assert gt._get_library("concept") == GraphLibrary.CONCEPT
        assert gt._get_library("event") == GraphLibrary.EVENT
        assert gt._get_library("unknown") == GraphLibrary.USER

    def test_factory_returns_14_ops(self):
        tools = _make()
        assert set(tools.keys()) == {
            "create_entity", "create_relation", "query_entities", "find_paths",
            "search_related_memories", "extract_entities", "merge_entities",
            "get_entity_summary", "update_entity", "delete_entity",
            "update_relation", "delete_relation", "get_stats", "export",
        }

    def test_exposed_matrix(self):
        for prefix in ("user", "thing", "concept", "event"):
            for op in ("create_entity", "create_relation", "query_entities", "find_paths",
                       "search_related_memories", "extract_entities", "merge_entities",
                       "get_entity_summary", "update_entity", "delete_entity",
                       "update_relation", "delete_relation", "get_stats", "export"):
                assert callable(getattr(gt, f"{prefix}_graph_{op}"))


# ---------------------------------------------------------------- 无存储
@pytest.fixture
def no_store(monkeypatch):
    gt.set_graph_dependencies(None)
    # 阻断按需创建真实图存储的回退路径，避免触发真实 DB 初始化
    monkeypatch.setattr(
        "server.dependencies._get_or_create_graph_store",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no store")),
    )
    yield
    gt.set_graph_dependencies(None)


class TestNoStore:
    def test_create_entity(self, no_store):
        r = _make()["create_entity"]("x", "person")
        assert "图存储未初始化" in r["error"]

    def test_get_stats(self, no_store):
        r = _make()["get_stats"]()
        assert "图存储未初始化" in r["error"]


# ---------------------------------------------------------------- 实体操作
class TestEntityOps:
    def test_create_entity_success(self, store):
        r = _make()["create_entity"]("张三", "person", properties={"age": 18}, memory_ids=["m1"])
        assert r["status"] == "success"
        assert r["entity"]["name"] == "张三"
        assert "entity_id" in r["entity"]

    def test_create_entity_exception(self, store):
        gt.set_graph_dependencies(_Boom())
        r = _make()["create_entity"]("x", "person")
        assert "创建用户图实体失败" in r["error"]

    def test_query_entities(self, store):
        store.find_result = [Entity(entity_id="e1", name="A", entity_type="person")]
        r = _make()["query_entities"]("A", depth=2)
        assert r["status"] == "success"
        assert r["count"] == 1
        assert r["entities"][0]["name"] == "A"

    def test_find_paths(self, store):
        store.paths = [[Entity(entity_id="e1", name="A", entity_type="person"),
                        Entity(entity_id="e2", name="B", entity_type="person")]]
        r = _make()["find_paths"]("A", "B", max_depth=2)
        assert r["status"] == "success"
        assert r["count"] == 1
        assert r["paths"][0][0]["name"] == "A"

    def test_update_entity_success(self, store):
        e = Entity(entity_id="e1", name="A", entity_type="person")
        store.entities["e1"] = e
        r = _make()["update_entity"]("e1", {"age": 30})
        assert r["status"] == "success"
        assert r["entity"]["properties"]["age"] == 30

    def test_update_entity_missing(self, store):
        r = _make()["update_entity"]("nope", {"age": 30})
        assert "不存在" in r["error"]

    def test_delete_entity_success(self, store):
        store.entities["e1"] = Entity(entity_id="e1", name="A", entity_type="person")
        r = _make()["delete_entity"]("e1")
        assert r["status"] == "success"
        assert r["soft_delete"] is True

    def test_delete_entity_failed(self, store):
        r = _make()["delete_entity"]("nope")
        assert r["status"] == "failed"

    def test_get_entity_summary(self, store):
        store.entities["e1"] = Entity(entity_id="e1", name="张三", entity_type="person", memory_ids=["m1"])
        r = _make()["get_entity_summary"]("e1")
        assert r["status"] == "success"
        assert "张三" in r["summary"]

    def test_get_entity_summary_missing(self, store):
        r = _make()["get_entity_summary"]("nope")
        assert "不存在" in r["error"]


# ---------------------------------------------------------------- 关系操作
class TestRelationOps:
    def test_create_relation_success(self, store):
        r = _make()["create_relation"]("A", "B", "knows", strength=0.9, evidence_memory_ids=["m1"])
        assert r["status"] == "success"
        assert r["relation"]["strength"] == 0.9

    def test_update_relation_success(self, store):
        class Ok:
            def update_relation(self, f, t, rt, updates, library):
                return Relation(from_entity=f, to_entity=t, relation_type=rt, strength=updates["strength"])

        old = gt._graph_store
        gt.set_graph_dependencies(Ok())
        try:
            r = _make()["update_relation"]("A", "B", "knows", 0.5)
            assert r["status"] == "success"
            assert r["relation"]["strength"] == 0.5
        finally:
            gt.set_graph_dependencies(old)

    def test_update_relation_missing(self, store):
        r = _make()["update_relation"]("A", "B", "knows", 0.5)
        assert "不存在" in r["error"]

    def test_delete_relation_success(self, store):
        r = _make()["delete_relation"]("A", "B", "knows")
        assert r["status"] == "success"
        assert r["soft_delete"] is True


# ---------------------------------------------------------------- 增强/提取/合并/统计
class TestAdvanced:
    def test_search_related_memories_not_found(self, store):
        r = _make()["search_related_memories"]("nope", "q", limit=5)
        assert r["status"] == "success"
        assert r["memories"] == []
        assert "实体未找到" in r["note"]

    def test_search_related_memories_success(self, store):
        store.entities["e1"] = Entity(entity_id="e1", name="张三", entity_type="person", memory_ids=["mem_2026_01", "mem_2026_02"])
        store.find_result = [Entity(entity_id="e2", name="李四", entity_type="person", memory_ids=["mem_2026_03"])]
        r = _make()["search_related_memories"]("e1", "2026", limit=5)
        assert r["status"] == "success"
        assert r["total_related_memories"] == 3
        assert set(r["matched_memory_ids"]) == {"mem_2026_01", "mem_2026_02", "mem_2026_03"}
        assert len(r["matched_memory_ids"]) == 3

    def test_extract_entities(self, store):
        r = _make()["extract_entities"]("Alice met Bob yesterday and Charlie joined.")
        assert r["status"] == "success"
        names = {e["name"] for e in r["extracted_entities"]}
        assert {"Alice", "Bob", "Charlie"}.issubset(names)
        assert all(e["entity_type"] == "person" for e in r["extracted_entities"])

    def test_merge_entities_success(self, store):
        store.entities["e1"] = Entity(entity_id="e1", name="A", entity_type="person", memory_ids=["m1"], properties={"a": 1})
        store.entities["e2"] = Entity(entity_id="e2", name="B", entity_type="person", memory_ids=["m2"], properties={"b": 2})
        r = _make()["merge_entities"]("e1", "e2")
        assert r["status"] == "success"
        assert r["merged_memory_ids_count"] == 2
        assert set(store.entities["e1"].memory_ids) == {"m1", "m2"}

    def test_merge_entities_e1_missing(self, store):
        r = _make()["merge_entities"]("nope", "e2")
        assert "实体 nope 不存在" in r["error"]

    def test_merge_entities_e2_missing(self, store):
        store.entities["e1"] = Entity(entity_id="e1", name="A", entity_type="person")
        r = _make()["merge_entities"]("e1", "nope")
        assert "实体 nope 不存在" in r["error"]

    def test_get_stats(self, store):
        r = _make()["get_stats"]()
        assert r["status"] == "success"
        assert r["entities"] == 3

    def test_export(self, store):
        r = _make()["export"]("json")
        assert r["status"] == "success"
        assert r["format"] == "json"
        assert r["entity_count"] == 0


class _Boom:
    def create_entity(self, *a, **k):
        raise RuntimeError("boom")