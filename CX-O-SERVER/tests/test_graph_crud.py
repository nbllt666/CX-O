"""server.core.graph.nodes (NodeManager) 与 edges (EdgeManager) 单元测试。

通过真实内存 SQLite（:memory:）+ 真实 schema，覆盖节点/边 CRUD、批量操作、
搜索过滤、存在性/计数、级联删除等。运行：python -m pytest tests/test_graph_crud.py -v
"""
import pytest

from server.core.graph.config import GraphConfig
from server.core.graph.database import Database
from server.core.graph.nodes import NodeManager
from server.core.graph.edges import EdgeManager
from server.core.graph.models import NodeCreate, NodeUpdate, EdgeCreate, EdgeUpdate

AGENT = "default"
OTHER_AGENT = "other"


@pytest.fixture
def db():
    config = GraphConfig(database_path=":memory:")
    database = Database(config)
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def nodes(db):
    return NodeManager(db, db.config)


@pytest.fixture
def edges(db):
    return EdgeManager(db, db.config)


def _mk_node(ntype="concept", props=None, text=None, agent=AGENT):
    return NodeCreate(type=ntype, properties=props or {}, text_content=text, agent_id=agent)


@pytest.fixture
def seeded(nodes, edges):
    """预置 A/B/C 三个节点与 A-B、B-C 两条边。"""
    a = nodes.create(_mk_node("concept", {"lang": "en"}, "alpha"))
    b = nodes.create(_mk_node("concept", {"lang": "zh"}, "beta"))
    c = nodes.create(_mk_node("person", {"age": 30}, "gamma"))
    e1 = edges.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="related"))
    e2 = edges.create(EdgeCreate(source_id=b.id, target_id=c.id, relation_type="knows"))
    return {"a": a, "b": b, "c": c, "e1": e1, "e2": e2}


class TestNodeCreate:
    def test_create_returns_node(self, nodes):
        node = nodes.create(_mk_node(text="hello"))
        assert node.id and node.type == "concept"
        assert node.text_content == "hello"
        assert node.agent_id == AGENT

    def test_create_persists(self, nodes):
        node = nodes.create(_mk_node("person", {"age": 1}, "x"))
        assert nodes.get(node.id) is not None

    def test_create_agent_isolation(self, nodes):
        n1 = nodes.create(_mk_node(agent=AGENT))
        n2 = nodes.create(_mk_node(agent=OTHER_AGENT))
        assert nodes.get(n2.id, agent_id=OTHER_AGENT) is not None
        assert nodes.get(n2.id, agent_id=AGENT) is None
        assert nodes.get(n1.id, agent_id=AGENT) is not None


class TestNodeGetUpdate:
    def test_get_missing(self, nodes):
        assert nodes.get("nope") is None

    def test_update_type_properties_text(self, nodes):
        node = nodes.create(_mk_node("concept", {"a": 1}, "t"))
        updated = nodes.update(node.id, NodeUpdate(type="person", properties={"b": 2}, text_content="new"))
        assert updated.type == "person"
        assert updated.properties == {"a": 1, "b": 2}
        assert updated.text_content == "new"
        # 数据库中已持久化
        fetched = nodes.get(node.id)
        assert fetched.type == "person"
        assert fetched.text_content == "new"

    def test_update_missing_returns_none(self, nodes):
        assert nodes.update("nope", NodeUpdate(text_content="x")) is None

    def test_update_partial(self, nodes):
        node = nodes.create(_mk_node("concept", {"a": 1}, "t"))
        updated = nodes.update(node.id, NodeUpdate(text_content="only"))
        assert updated.type == "concept"
        assert updated.properties == {"a": 1}
        assert updated.text_content == "only"


class TestNodeDelete:
    def test_delete_cascade_removes_edges(self, nodes, edges, seeded):
        a = seeded["a"]
        assert nodes.delete(a.id, cascade=True)
        assert nodes.get(a.id) is None
        # 关联边 A-B 被级联删除
        assert edges.get(seeded["e1"].id) is None

    def test_delete_no_cascade_with_edges_rejected(self, nodes, edges, seeded):
        """第四轮 §6.3 第12条新契约：cascade=False 且存在关联边 → 明确拒绝，不产生悬挂边。"""
        a = seeded["a"]
        with pytest.raises(ValueError, match="cascade=True"):
            nodes.delete(a.id, cascade=False)
        # 节点未被删除、关联边完整保留
        assert nodes.get(a.id) is not None
        assert len(edges.get_outgoing(a.id)) == 1

    def test_delete_no_cascade_without_edges_ok(self, nodes):
        """cascade=False 且无关联边 → 允许直接删除。"""
        d = nodes.create(_mk_node("concept", {"tag": "isolated"}, "delta"))
        assert nodes.delete(d.id, cascade=False)
        assert nodes.get(d.id) is None

    def test_delete_missing(self, nodes):
        assert nodes.delete("nope") is False


class TestNodeList:
    def test_list_all(self, nodes, seeded):
        result = nodes.list()
        assert result.total == 3
        assert len(result.items) == 3

    def test_list_by_type(self, nodes, seeded):
        result = nodes.list(node_type="concept")
        assert result.total == 2
        assert all(n.type == "concept" for n in result.items)

    def test_list_pagination(self, nodes, seeded):
        result = nodes.list(limit=1, offset=0)
        assert len(result.items) == 1
        assert result.total == 3
        assert result.has_more is True


class TestNodeBatch:
    def test_batch_create(self, nodes):
        created = nodes.batch_create([_mk_node("a"), _mk_node("b", props={"x": 1})])
        assert len(created) == 2
        assert nodes.count() == 2

    def test_batch_create_agent(self, nodes):
        created = nodes.batch_create([NodeCreate(type="a", agent_id=OTHER_AGENT)])
        assert created[0].agent_id == OTHER_AGENT

    def test_batch_delete(self, nodes, edges, seeded):
        a = seeded["a"]
        b = seeded["b"]
        assert nodes.batch_delete([a.id, b.id]) == 2
        assert nodes.get(a.id) is None
        assert nodes.get(b.id) is None


class TestNodeSearch:
    def test_search_by_type(self, nodes, seeded):
        result = nodes.search(node_type="person")
        assert result.total == 1
        assert result.items[0].type == "person"

    def test_search_by_properties(self, nodes, seeded):
        result = nodes.search(properties_filter={"lang": "zh"})
        assert result.total == 1
        assert result.items[0].text_content == "beta"

    def test_search_invalid_property_key_ignored(self, nodes, seeded):
        # 非法键名被跳过，退回全量过滤
        result = nodes.search(properties_filter={"bad key!": "x"})
        assert result.total == 3

    def test_search_agent_scope(self, nodes, seeded):
        other = nodes.create(_mk_node(agent=OTHER_AGENT))
        result = nodes.search(agent_id=OTHER_AGENT)
        assert result.total == 1
        assert result.items[0].id == other.id


class TestNodeExistsCount:
    def test_exists(self, nodes, seeded):
        assert nodes.exists(seeded["a"].id) is True
        assert nodes.exists("nope") is False

    def test_count_all(self, nodes, seeded):
        assert nodes.count() == 3

    def test_count_by_type(self, nodes, seeded):
        assert nodes.count(node_type="person") == 1


class TestEdgeCreate:
    def test_create_edge(self, nodes, edges, seeded):
        e = edges.create(EdgeCreate(source_id=seeded["a"].id, target_id=seeded["b"].id, relation_type="knows"))
        assert e.source_id == seeded["a"].id
        assert e.target_id == seeded["b"].id

    def test_create_missing_source_raises(self, nodes, edges, seeded):
        with pytest.raises(ValueError):
            edges.create(EdgeCreate(source_id="no", target_id=seeded["a"].id, relation_type="r"))

    def test_create_missing_target_raises(self, nodes, edges, seeded):
        with pytest.raises(ValueError):
            edges.create(EdgeCreate(source_id=seeded["a"].id, target_id="no", relation_type="r"))

    def test_create_persists(self, nodes, edges, seeded):
        e = edges.create(EdgeCreate(source_id=seeded["a"].id, target_id=seeded["b"].id, relation_type="r"))
        assert edges.get(e.id) is not None


class TestEdgeGetUpdate:
    def test_get_missing(self, edges):
        assert edges.get("nope") is None

    def test_update(self, nodes, edges, seeded):
        e = edges.update(
            seeded["e1"].id,
            EdgeUpdate(relation_type="likes", properties={"k": 1}, text_content="note"),
        )
        assert e.relation_type == "likes"
        assert e.properties == {"k": 1}
        assert e.text_content == "note"
        assert edges.get(seeded["e1"].id).relation_type == "likes"

    def test_update_missing(self, edges):
        assert edges.update("nope", EdgeUpdate(relation_type="x")) is None


class TestEdgeDelete:
    def test_delete(self, nodes, edges, seeded):
        assert edges.delete(seeded["e1"].id) is True
        assert edges.get(seeded["e1"].id) is None

    def test_delete_missing(self, edges):
        assert edges.delete("nope") is False


class TestEdgeList:
    def test_list_all(self, nodes, edges, seeded):
        result = edges.list()
        assert result.total == 2

    def test_list_by_relation(self, nodes, edges, seeded):
        result = edges.list(relation_type="knows")
        assert result.total == 1
        assert result.items[0].id == seeded["e2"].id

    def test_list_by_source(self, nodes, edges, seeded):
        result = edges.list(source_id=seeded["a"].id)
        assert result.total == 1
        assert result.items[0].id == seeded["e1"].id

    def test_list_by_target(self, nodes, edges, seeded):
        result = edges.list(target_id=seeded["c"].id)
        assert result.total == 1
        assert result.items[0].id == seeded["e2"].id


class TestEdgeOutgoingIncoming:
    def test_get_outgoing_all(self, nodes, edges, seeded):
        out = edges.get_outgoing(seeded["b"].id)
        assert len(out) == 1
        assert out[0].id == seeded["e2"].id

    def test_get_outgoing_by_relation(self, nodes, edges, seeded):
        assert len(edges.get_outgoing(seeded["b"].id, relation_type="knows")) == 1
        assert len(edges.get_outgoing(seeded["b"].id, relation_type="none")) == 0

    def test_get_incoming(self, nodes, edges, seeded):
        inc = edges.get_incoming(seeded["b"].id)
        assert len(inc) == 1
        assert inc[0].id == seeded["e1"].id


class TestEdgeSearchCount:
    def test_search_combined_filters(self, nodes, edges, seeded):
        edges.update(seeded["e1"].id, EdgeUpdate(properties={"trust": 5}))
        result = edges.search(relation_type="related", properties_filter={"trust": 5})
        assert result.total == 1
        assert result.items[0].id == seeded["e1"].id

    def test_search_invalid_key_ignored(self, nodes, edges, seeded):
        result = edges.search(properties_filter={"bad key!": "x"})
        assert result.total == 2

    def test_count_all(self, nodes, edges, seeded):
        assert edges.count() == 2

    def test_count_by_relation(self, nodes, edges, seeded):
        assert edges.count(relation_type="related") == 1