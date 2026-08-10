"""server.core.graph.semantic_query (SemanticQueryManager) 单元测试。

通过 FakeDB 模拟 SQLite 行 + 覆写嵌入方法去向量化，覆盖多跳查询/路径约束搜索/可达性/余弦/最短路/全路径/边还原。
运行：python -m pytest tests/test_graph_semantic_query.py -v
"""
from datetime import datetime

import pytest

from server.core.graph.models import GraphEdge, GraphNode
from server.core.graph.semantic_query import SemanticQueryManager

AGENT = "default"


def _node(nid):
    now = datetime.now().isoformat()
    return {
        "id": nid,
        "type": None,
        "properties": {},
        "text_content": nid,
        "vector_id": None,
        "created_at": now,
        "updated_at": now,
        "agent_id": AGENT,
    }


def _edge(eid, src, tgt):
    now = datetime.now().isoformat()
    return {
        "id": eid,
        "source_id": src,
        "target_id": tgt,
        "relation_type": "related",
        "properties": {},
        "text_content": None,
        "vector_id": None,
        "created_at": now,
        "agent_id": AGENT,
    }


class FakeDB:
    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges

    def execute_one(self, query, params):
        rows = self.execute(query, params)
        return rows[0] if rows else None

    def execute(self, query, params):
        q = " ".join(query.strip().split())
        if q.startswith("SELECT * FROM nodes WHERE id"):
            nid, agent = params
            row = next((r for r in self.nodes if r["id"] == nid and r["agent_id"] == agent), None)
            return [row] if row else []
        if q.startswith("SELECT target_id FROM edges WHERE source_id"):
            nid, agent = params
            return [{"target_id": e["target_id"]} for e in self.edges if e["source_id"] == nid and e["agent_id"] == agent]
        if q.startswith("SELECT source_id FROM edges WHERE target_id"):
            nid, agent = params
            return [{"source_id": e["source_id"]} for e in self.edges if e["target_id"] == nid and e["agent_id"] == agent]
        if q.startswith("SELECT target_id as neighbor_id"):
            nid, _, nid2, agent = params
            return [{"neighbor_id": e["target_id"]} for e in self.edges if e["source_id"] == nid and e["agent_id"] == agent] + [
                {"neighbor_id": e["source_id"]} for e in self.edges if e["target_id"] == nid2 and e["agent_id"] == agent
            ]
        if q.startswith("SELECT * FROM edges WHERE agent_id"):
            # _get_edge_between: ((source_id=? AND target_id=?) OR ...)
            agent, src, tgt, rev_src, rev_tgt = params
            return [
                e
                for e in self.edges
                if e["agent_id"] == agent
                and ((e["source_id"] == src and e["target_id"] == tgt) or (e["source_id"] == rev_src and e["target_id"] == rev_tgt))
            ]
        raise NotImplementedError(f"Unexpected query: {q}")


class FakeSQM(SemanticQueryManager):
    """去除向量化依赖：固定嵌入。"""

    def __init__(self, db, embeddings):
        super().__init__(db)
        self.embeddings = embeddings

    def _get_query_embedding(self, query):
        return [1.0, 0.0]

    def _get_text_embedding(self, text):
        key = text.strip()
        return self.embeddings.get(key, [0.0, 0.0])


@pytest.fixture
def db():
    return FakeDB(
        nodes=[_node("A"), _node("B"), _node("C")],
        edges=[_edge("e1", "A", "B"), _edge("e2", "B", "C")],
    )


@pytest.fixture
def mgr(db):
    return FakeSQM(
        db,
        {"A": [1.0, 0.0], "B": [0.9, 0.1], "C": [0.0, 1.0]},
    )


class TestReachableNodes:
    def test_one_hop(self, mgr):
        assert mgr._get_reachable_nodes("A", 1) == {"A", "B"}

    def test_two_hops(self, mgr):
        assert mgr._get_reachable_nodes("A", 2) == {"A", "B", "C"}

    def test_zero_hops(self, mgr):
        assert mgr._get_reachable_nodes("A", 0) == {"A"}


class TestCosine:
    def test_same(self, mgr):
        assert mgr._cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)

    def test_orthogonal(self, mgr):
        assert mgr._cosine_similarity([1, 0], [0, 1]) == 0.0

    def test_length_mismatch(self, mgr):
        assert mgr._cosine_similarity([1, 0], [1]) == 0.0

    def test_zero_vector(self, mgr):
        assert mgr._cosine_similarity([0, 0], [1, 0]) == 0.0


class TestExtractNodeText:
    def test_joins_fields(self, mgr):
        node = GraphNode.create(
            type="concept",
            properties={"k": "v", "list": [1, 2], "num": 3},
            text_content="hi",
            agent_id=AGENT,
        )
        text = mgr._extract_node_text(node)
        assert "hi" in text
        assert "concept" in text
        assert "v" in text
        assert "1" in text
        assert "3" in text


class TestShortestPath:
    def test_same(self, mgr):
        assert mgr._get_shortest_path("A", "A") == ["A"]

    def test_direct(self, mgr):
        assert mgr._get_shortest_path("A", "B") == ["A", "B"]

    def test_via(self, mgr):
        assert mgr._get_shortest_path("A", "C") == ["A", "B", "C"]

    def test_no_path(self, mgr, db):
        db.edges = []
        assert mgr._get_shortest_path("A", "C") is None


class TestAllPaths:
    def test_finds_path(self, mgr):
        paths = mgr._find_all_paths("A", "C", 5)
        assert ["A", "B", "C"] in paths

    def test_max_length(self, mgr):
        assert mgr._find_all_paths("A", "C", 1) == []


class TestPathEdges:
    def test_returns_edges(self, mgr):
        edges = mgr._get_path_edges(["A", "B", "C"])
        assert len(edges) == 2
        assert [e.source_id for e in edges] == ["A", "B"]

    def test_short_path(self, mgr):
        assert mgr._get_path_edges(["A"]) == []

    def test_edge_between(self, mgr):
        e = mgr._get_edge_between("A", "B")
        assert e is not None
        assert e.source_id == "A"
        assert e.target_id == "B"

    def test_edge_between_reverse(self, mgr):
        e = mgr._get_edge_between("B", "A")
        assert e is not None


class TestSemanticQuery:
    def test_multi_hop_sorted_and_limited(self, mgr):
        results = mgr.semantic_query_with_hops("A", "q", hops=2, limit=2)
        assert len(results) == 2
        sims = [r["similarity"] for r in results]
        assert sims == sorted(sims, reverse=True)
        assert all("node" in r and "path" in r and "path_edges" in r for r in results)

    def test_zero_hops_returns_start(self, mgr):
        # 起点自身始终可达
        results = mgr.semantic_query_with_hops("A", "q", hops=0)
        assert [r["node"].id for r in results] == ["A"]

    def test_unknown_start(self, db):
        m = FakeSQM(db, {"A": [1, 0]})
        assert m.semantic_query_with_hops("Z", "q") == []

    def test_path_constrained_returns_intermediary(self, mgr):
        # A->C 路径经过 B，B 为唯一中间节点
        results = mgr.path_constrained_semantic_search("A", "C", "q")
        ids = [r["node"].id for r in results]
        assert "B" in ids
        assert "A" not in ids
        assert "C" not in ids

    def test_path_constrained_no_path(self, mgr):
        assert mgr.path_constrained_semantic_search("A", "Z", "q") == []