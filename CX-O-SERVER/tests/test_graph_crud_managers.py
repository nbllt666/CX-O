"""
server/core/graph CRUD 管理器回归测试
节点管理器（nodes.NodeManager）与边管理器（edges.EdgeManager），真实 SQLite 临时库
"""
import pytest

from server.core.graph.config import GraphConfig
from server.core.graph.database import Database
from server.core.graph.edges import EdgeManager
from server.core.graph.models import NodeCreate, NodeUpdate, EdgeCreate, EdgeUpdate
from server.core.graph.nodes import NodeManager


@pytest.fixture
def db(tmp_path):
    d = Database(GraphConfig(database_path=str(tmp_path / "crud.db"), timeout=5))
    d.initialize()
    yield d
    d.close()


@pytest.fixture
def node_mgr(db):
    return NodeManager(db, GraphConfig())


@pytest.fixture
def edge_mgr(db):
    return EdgeManager(db, GraphConfig())


def _seed_two_nodes(node_mgr):
    a = node_mgr.create(NodeCreate(type="person", properties={"name": "A"}, text_content="a"), agent_id="default")
    b = node_mgr.create(NodeCreate(type="person", properties={"name": "B"}, text_content="b"), agent_id="default")
    return a, b


# ================================================================ NodeManager
class TestNodeManager:
    def test_create_returns_node_and_persists(self, node_mgr):
        n = node_mgr.create(NodeCreate(type="concept", properties={"k": 1}), agent_id="default")
        got = node_mgr.get(n.id, "default")
        assert got is not None
        assert got.type == "concept"
        assert got.properties == {"k": 1}

    def test_get_missing_returns_none(self, node_mgr):
        assert node_mgr.get("nope", "default") is None

    def test_update_partial(self, node_mgr):
        n = node_mgr.create(NodeCreate(type="t", properties={"a": 1}), agent_id="default")
        updated = node_mgr.update(n.id, NodeUpdate(properties={"b": 2}), "default")
        assert updated.properties == {"a": 1, "b": 2}  # merge 而非覆盖
        assert updated.type == "t"

    def test_update_missing_returns_none(self, node_mgr):
        assert node_mgr.update("nope", NodeUpdate(type="x"), "default") is None

    def test_delete_cascade_removes_edges(self, db, node_mgr, edge_mgr):
        a, b = _seed_two_nodes(node_mgr)
        edge_mgr.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="knows"), "default")
        assert edge_mgr.count(agent_id="default") == 1
        assert node_mgr.delete(a.id, cascade=True, agent_id="default") is True
        assert edge_mgr.count(agent_id="default") == 0  # 级联删除边
        assert node_mgr.get(a.id, "default") is None

    def test_delete_non_cascade_with_edges_rejected(self, db, node_mgr, edge_mgr):
        """第四轮 §6.3 第12条新契约：cascade=False 且有边 → ValueError 拒绝（不产生悬挂边）。"""
        a, b = _seed_two_nodes(node_mgr)
        edge_mgr.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="knows"), "default")
        with pytest.raises(ValueError, match="cascade=True"):
            node_mgr.delete(a.id, cascade=False, agent_id="default")
        assert node_mgr.get(a.id, "default") is not None
        assert edge_mgr.count(agent_id="default") == 1

    def test_delete_non_cascade_without_edges_ok(self, db, node_mgr, edge_mgr):
        """cascade=False 且无关联边 → 直接删除成功。"""
        a, _ = _seed_two_nodes(node_mgr)
        assert node_mgr.delete(a.id, cascade=False, agent_id="default") is True
        assert node_mgr.get(a.id, "default") is None

    def test_list_with_type_and_pagination(self, node_mgr):
        for i in range(5):
            node_mgr.create(NodeCreate(type="t", properties={"i": i}), "default")
        all_nodes = node_mgr.list(agent_id="default")
        assert all_nodes.total == 5
        page = node_mgr.list(node_type="t", limit=2, offset=1, agent_id="default")
        assert len(page.items) == 2
        assert page.total == 5

    def test_batch_create_and_delete(self, node_mgr):
        nodes = node_mgr.batch_create(
            [NodeCreate(type="t", properties={"i": i}) for i in range(4)],
            agent_id="default",
        )
        assert len(nodes) == 4
        assert node_mgr.count(agent_id="default") == 4
        n = node_mgr.batch_delete([x.id for x in nodes[:2]], agent_id="default")
        assert n == 2
        assert node_mgr.count(agent_id="default") == 2

    def test_search_by_type(self, node_mgr):
        node_mgr.create(NodeCreate(type="person"), "default")
        node_mgr.create(NodeCreate(type="place"), "default")
        r = node_mgr.search(node_type="person", agent_id="default")
        assert r.total == 1
        assert r.items[0].type == "person"

    def test_search_by_properties_filter(self, node_mgr):
        node_mgr.create(NodeCreate(type="t", properties={"name": "alice"}), "default")
        node_mgr.create(NodeCreate(type="t", properties={"name": "bob"}), "default")
        r = node_mgr.search(properties_filter={"name": "alice"}, agent_id="default")
        assert r.total == 1
        assert r.items[0].properties["name"] == "alice"

    def test_search_ignores_invalid_property_key(self, node_mgr):
        node_mgr.create(NodeCreate(type="t", properties={"a": 1}), "default")
        # 非法 key 被跳过，不注入 SQL
        r = node_mgr.search(properties_filter={"bad key": 1}, agent_id="default")
        assert r.total == 1

    def test_exists_and_count(self, node_mgr):
        n = node_mgr.create(NodeCreate(type="t"), "default")
        assert node_mgr.exists(n.id, "default") is True
        assert node_mgr.exists("nope", "default") is False
        assert node_mgr.count(agent_id="default") == 1
        assert node_mgr.count(node_type="t", agent_id="default") == 1
        assert node_mgr.count(node_type="other", agent_id="default") == 0

    def test_agent_scope_isolation(self, node_mgr):
        node_mgr.create(NodeCreate(type="t"), agent_id="alice")
        assert node_mgr.count(agent_id="bob") == 0
        assert node_mgr.list(agent_id="bob").total == 0


# ================================================================ EdgeManager
class TestEdgeManager:
    def test_create_requires_source_and_target(self, node_mgr, edge_mgr):
        a, b = _seed_two_nodes(node_mgr)
        e = edge_mgr.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="knows"), "default")
        assert e.source_id == a.id
        assert e.target_id == b.id
        # 源节点不存在 → 报错
        with pytest.raises(ValueError):
            edge_mgr.create(EdgeCreate(source_id="zzz", target_id=b.id, relation_type="r"), "default")
        # 目标节点不存在 → 报错
        with pytest.raises(ValueError):
            edge_mgr.create(EdgeCreate(source_id=a.id, target_id="zzz", relation_type="r"), "default")

    def test_get_and_missing(self, node_mgr, edge_mgr):
        a, b = _seed_two_nodes(node_mgr)
        e = edge_mgr.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="knows"), "default")
        assert edge_mgr.get(e.id, "default").relation_type == "knows"
        assert edge_mgr.get("nope", "default") is None

    def test_update(self, node_mgr, edge_mgr):
        a, b = _seed_two_nodes(node_mgr)
        e = edge_mgr.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="knows"), "default")
        updated = edge_mgr.update(e.id, EdgeUpdate(relation_type="likes", properties={"w": 5}), "default")
        assert updated.relation_type == "likes"
        assert updated.properties == {"w": 5}
        assert edge_mgr.update("nope", EdgeUpdate(), "default") is None

    def test_delete(self, node_mgr, edge_mgr):
        a, b = _seed_two_nodes(node_mgr)
        e = edge_mgr.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="knows"), "default")
        assert edge_mgr.delete(e.id, "default") is True
        assert edge_mgr.delete(e.id, "default") is False  # 已删除

    def test_list_filters(self, node_mgr, edge_mgr):
        a, b = _seed_two_nodes(node_mgr)
        edge_mgr.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="knows"), "default")
        edge_mgr.create(EdgeCreate(source_id=b.id, target_id=a.id, relation_type="likes"), "default")
        assert edge_mgr.list(agent_id="default").total == 2
        assert edge_mgr.list(relation_type="knows", agent_id="default").total == 1
        assert edge_mgr.list(source_id=a.id, agent_id="default").total >= 1

    def test_get_outgoing_incoming(self, node_mgr, edge_mgr):
        a, b = _seed_two_nodes(node_mgr)
        edge_mgr.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="knows"), "default")
        edge_mgr.create(EdgeCreate(source_id=b.id, target_id=a.id, relation_type="likes"), "default")
        out = edge_mgr.get_outgoing(a.id, agent_id="default")
        assert [e.relation_type for e in out] == ["knows"]
        inc = edge_mgr.get_incoming(a.id, agent_id="default")
        assert [e.relation_type for e in inc] == ["likes"]
        # 带 relation_type 过滤
        assert edge_mgr.get_outgoing(a.id, relation_type="knows", agent_id="default")
        assert edge_mgr.get_outgoing(a.id, relation_type="nope", agent_id="default") == []

    def test_search_properties_filter(self, node_mgr, edge_mgr):
        a, b = _seed_two_nodes(node_mgr)
        edge_mgr.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="knows", properties={"level": 3}), "default")
        r = edge_mgr.search(properties_filter={"level": 3}, agent_id="default")
        assert r.total == 1
        r2 = edge_mgr.search(properties_filter={"level": 9}, agent_id="default")
        assert r2.total == 0

    def test_count(self, node_mgr, edge_mgr):
        a, b = _seed_two_nodes(node_mgr)
        edge_mgr.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="knows"), "default")
        assert edge_mgr.count(agent_id="default") == 1
        assert edge_mgr.count(relation_type="knows", agent_id="default") == 1
        assert edge_mgr.count(relation_type="other", agent_id="default") == 0