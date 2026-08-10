"""server.core.graph.traversal (TraversalManager) 单元测试。

通过 FakeDB 模拟 SQLite 行，覆盖 BFS/DFS/邻居/最短路/全路径/PageRank/社区检测。
运行：python -m pytest tests/test_graph_traversal.py -v
"""
from datetime import datetime

import pytest

from server.core.graph.config import GraphConfig
from server.core.graph.models import GraphEdge, GraphNode
from server.core.graph.traversal import TraversalManager

AGENT = "default"


def _node(nid, ntype="concept"):
    now = datetime.now().isoformat()
    return {
        "id": nid,
        "type": ntype,
        "properties": {},
        "text_content": None,
        "vector_id": None,
        "created_at": now,
        "updated_at": now,
        "agent_id": AGENT,
    }


def _edge(eid, src, tgt, rtype="related"):
    now = datetime.now().isoformat()
    return {
        "id": eid,
        "source_id": src,
        "target_id": tgt,
        "relation_type": rtype,
        "properties": {},
        "text_content": None,
        "vector_id": None,
        "created_at": now,
        "agent_id": AGENT,
    }


class FakeDB:
    """解释 traversal/repository 用到的 SQL 子查询，返回内存图行。"""

    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges

    def execute(self, query, params):
        q = " ".join(query.strip().split())
        if q.startswith("SELECT * FROM nodes WHERE id"):
            nid, agent = params
            row = next((r for r in self.nodes if r["id"] == nid and r["agent_id"] == agent), None)
            return [row] if row else []
        if q.startswith("SELECT id FROM nodes"):
            return [{"id": r["id"]} for r in self.nodes if r["agent_id"] == params[0]]
        if q.startswith("SELECT * FROM edges WHERE source_id"):
            nid, agent = params
            return [e for e in self.edges if e["source_id"] == nid and e["agent_id"] == agent]
        if q.startswith("SELECT * FROM edges WHERE target_id"):
            nid, agent = params
            return [e for e in self.edges if e["target_id"] == nid and e["agent_id"] == agent]
        if q.startswith("SELECT * FROM edges WHERE (source_id"):
            nid, _, agent = params
            return [
                e
                for e in self.edges
                if e["agent_id"] == agent and (e["source_id"] == nid or e["target_id"] == nid)
            ]
        if q.startswith("SELECT * FROM edges WHERE id"):
            eid, agent = params
            row = next((e for e in self.edges if e["id"] == eid and e["agent_id"] == agent), None)
            return [row] if row else []
        if q.startswith("SELECT target_id FROM edges WHERE source_id"):
            nid, agent = params
            return [
                {"target_id": e["target_id"]}
                for e in self.edges
                if e["source_id"] == nid and e["agent_id"] == agent
            ]
        if q.startswith("SELECT source_id FROM edges WHERE target_id"):
            nid, agent = params
            return [
                {"source_id": e["source_id"]}
                for e in self.edges
                if e["target_id"] == nid and e["agent_id"] == agent
            ]
        if q.startswith("SELECT target_id as neighbor_id"):
            nid, _, nid2, agent = params
            return [
                {"neighbor_id": e["target_id"]} for e in self.edges if e["source_id"] == nid and e["agent_id"] == agent
            ] + [
                {"neighbor_id": e["source_id"]} for e in self.edges if e["target_id"] == nid2 and e["agent_id"] == agent
            ]
        if q.startswith("SELECT source_id, target_id FROM edges"):
            return [
                {"source_id": e["source_id"], "target_id": e["target_id"]}
                for e in self.edges
                if e["agent_id"] == params[0]
            ]
        raise NotImplementedError(f"Unexpected query: {q}")

    def execute_one(self, query, params):
        rows = self.execute(query, params)
        return rows[0] if rows else None


@pytest.fixture
def graph():
    nodes = [_node("A"), _node("B"), _node("C", "fact"), _node("D")]
    edges = [
        _edge("e1", "A", "B"),
        _edge("e2", "B", "C"),
        _edge("e3", "A", "C"),
    ]
    return FakeDB(nodes, edges)


@pytest.fixture
def mgr(graph):
    return TraversalManager(db=graph, config=GraphConfig())


class TestGetNeighbors:
    def test_depth1_both(self, mgr):
        result = mgr.get_neighbors("A", max_depth=1)
        ids = sorted(n.id for n, _ in result)
        assert ids == ["B", "C"]

    def test_depth0_returns_empty(self, mgr):
        assert mgr.get_neighbors("A", max_depth=0) == []


class TestBfs:
    def test_visits_reachable(self, mgr):
        result = mgr.bfs_traverse("A")
        ids = [n.id for n in result]
        assert "A" in ids
        assert "B" in ids
        assert "C" in ids
        assert "D" not in ids

    def test_type_filter(self, mgr):
        result = mgr.bfs_traverse("A", node_type_filter="fact")
        assert [n.id for n in result] == ["C"]


class TestDfs:
    def test_visits_all(self, mgr):
        result = mgr.dfs_traverse("A")
        ids = [n.id for n in result]
        assert {"A", "B", "C"}.issubset(ids)

    def test_no_duplicates(self, mgr):
        result = mgr.dfs_traverse("A")
        assert len(result) == len(set(n.id for n in result))


class TestShortestPath:
    def test_same_node(self, mgr):
        p = mgr.shortest_path("A", "A")
        assert p.path == ["A"]
        assert p.length == 0

    def test_direct(self, mgr):
        p = mgr.shortest_path("A", "C")
        assert p.path[0] == "A"
        assert p.path[-1] == "C"
        assert p.length == 1

    def test_via(self, mgr):
        p = mgr.shortest_path("A", "C")
        # A->C 直接 1 步，A->B->C 2 步
        assert p.length == 1

    def test_no_path(self, mgr):
        assert mgr.shortest_path("A", "D") is None


class TestAllPaths:
    def test_multiple_paths(self, mgr):
        results = mgr.all_paths("A", "C")
        assert len(results) == 2  # A->C 与 A->B->C
        assert all(r.path[0] == "A" and r.path[-1] == "C" for r in results)

    def test_max_length_cuts_off(self, mgr):
        results = mgr.all_paths("A", "C", max_length=1)
        assert len(results) == 1
        assert results[0].length == 1


class TestPageRank:
    def test_single_node(self):
        db = FakeDB([_node("A")], [])
        m = TraversalManager(db=db, config=GraphConfig())
        # 无入链孤立节点：PageRank = (1-damping)/n = 0.15
        assert m.pagerank()["A"] == pytest.approx(0.15)

    def test_empty(self):
        db = FakeDB([], [])
        m = TraversalManager(db=db, config=GraphConfig())
        assert m.pagerank() == {}

    def test_two_nodes(self, graph):
        m = TraversalManager(db=graph, config=GraphConfig())
        scores = m.pagerank()
        assert set(scores.keys()) == {"A", "B", "C", "D"}
        assert scores["D"] > 0  # 悬挂节点仍获基础分

    def test_important_nodes_sorted(self, mgr):
        important = mgr.get_important_nodes()
        scores = [r["pagerank"] for r in important]
        assert scores == sorted(scores, reverse=True)


class TestCommunity:
    def test_empty(self):
        db = FakeDB([], [])
        m = TraversalManager(db=db, config=GraphConfig())
        assert m.community_detection() == {}

    def test_lpa_covers_all_nodes(self, mgr):
        communities = mgr.community_detection(method="lpa")
        all_ids = [nid for members in communities.values() for nid in members]
        assert set(all_ids) == {"A", "B", "C", "D"}

    def test_unknown_method_falls_back(self, mgr):
        communities = mgr.community_detection(method="bogus")
        assert communities  # 不抛错，回退到 LPA

    def test_community_stats_empty(self):
        db = FakeDB([], [])
        m = TraversalManager(db=db, config=GraphConfig())
        stats = m.get_community_stats()
        assert stats["num_communities"] == 0
        assert stats["avg_community_size"] == 0.0

    def test_community_stats(self, mgr):
        stats = mgr.get_community_stats()
        assert stats["num_communities"] >= 1
        assert stats["largest_community_size"] >= 1


class TestModels:
    def test_graph_node_roundtrip(self):
        n = GraphNode.create("concept", {"a": 1}, agent_id=AGENT)
        d = n.to_dict()
        n2 = GraphNode.from_dict(d)
        assert n2.id == n.id
        assert n2.type == "concept"
        assert n2.properties == {"a": 1}

    def test_graph_edge_roundtrip(self):
        e = GraphEdge.create("A", "B", "related", agent_id=AGENT)
        d = e.to_dict()
        e2 = GraphEdge.from_dict(d)
        assert e2.source_id == "A"
        assert e2.target_id == "B"

    def test_path_result(self):
        from server.core.graph.models import PathResult

        p = PathResult(path=["A", "B"], edges=[], length=1)
        assert p.length == 1