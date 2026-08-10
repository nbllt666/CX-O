"""server.core.graph.hybrid_query (HybridQueryManager) 单元测试。

通过 FakeDB + FakeSemantic 隔离外部依赖，覆盖属性过滤/路径语义打分/混合搜索/邻居语义检索。
运行：python -m pytest tests/test_graph_hybrid_query.py -v
"""
from datetime import datetime

import numpy as np
import pytest

from server.core.graph.config import GraphConfig
from server.core.graph.hybrid_query import HybridQueryManager
from server.core.graph.models import GraphNode, PathResult, SemanticSearchResult

AGENT = "default"


def _node(nid, text, ntype="concept", props=None):
    now = datetime.now().isoformat()
    return {
        "id": nid,
        "type": ntype,
        "properties": props or {},
        "text_content": text,
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
            agent, src, tgt, rev_src, rev_tgt = params
            return [
                e
                for e in self.edges
                if e["agent_id"] == agent
                and ((e["source_id"] == src and e["target_id"] == tgt) or (e["source_id"] == rev_src and e["target_id"] == rev_tgt))
            ]
        if q.startswith("SELECT * FROM edges WHERE (source_id"):
            nid, _, agent = params
            return [
                e for e in self.edges
                if e["agent_id"] == agent and (e["source_id"] == nid or e["target_id"] == nid)
            ]
        if q.startswith("SELECT * FROM edges WHERE source_id"):
            nid, agent = params
            return [e for e in self.edges if e["source_id"] == nid and e["agent_id"] == agent]
        if q.startswith("SELECT * FROM edges WHERE target_id"):
            nid, agent = params
            return [e for e in self.edges if e["target_id"] == nid and e["agent_id"] == agent]
        raise NotImplementedError(f"Unexpected query: {q}")


class FakeSemantic:
    def __init__(self):
        self.search_results = []

    def search(self, query, node_type=None, limit=10, node_filter=None, agent_id="default"):
        out = []
        for r in self.search_results:
            if node_filter and not node_filter(r.node.id):
                continue
            if node_type and r.node.type != node_type:
                continue
            out.append(r)
        return out[:limit]

    def encode_batch(self, texts):
        return [np.array([1.0, 0.0]) for _ in texts]

    def compute_similarity(self, v1, v2):
        return 1.0


@pytest.fixture
def db():
    return FakeDB(
        nodes=[_node("A", "hello world"), _node("B", "graph", props={"lang": "en"}), _node("C", "data")],
        edges=[_edge("e1", "A", "B"), _edge("e2", "B", "C")],
    )


@pytest.fixture
def semantic():
    return FakeSemantic()


@pytest.fixture
def mgr(db, semantic):
    return HybridQueryManager(db=db, semantic=semantic, config=GraphConfig())


class TestMatchesFilter:
    def test_all_match(self, mgr):
        node = GraphNode.create(type="x", properties={"a": 1, "b": 2}, text_content="t", agent_id=AGENT)
        assert mgr._matches_filter(node, {"a": 1, "b": 2}) is True

    def test_missing_key(self, mgr):
        node = GraphNode.create(type="x", properties={"a": 1}, text_content="t", agent_id=AGENT)
        assert mgr._matches_filter(node, {"a": 1, "z": 2}) is False

    def test_wrong_value(self, mgr):
        node = GraphNode.create(type="x", properties={"a": 1}, text_content="t", agent_id=AGENT)
        assert mgr._matches_filter(node, {"a": 2}) is False


class TestPathSemanticScore:
    def test_two_or_more_nodes_uses_semantic(self, mgr):
        pr = PathResult(path=["A", "B", "C"], length=2, edges=[])
        score = mgr._calculate_path_semantic_score(pr)
        assert score == pytest.approx(1.0)

    def test_less_than_two_texts_zero(self, mgr):
        pr = PathResult(path=["A"], length=0, edges=[])
        assert mgr._calculate_path_semantic_score(pr) == 0.0

    def test_empty_path_zero(self, mgr):
        pr = PathResult(path=[], length=0, edges=[])
        assert mgr._calculate_path_semantic_score(pr) == 0.0


class TestSemanticPathDiscovery:
    def test_returns_scored_paths_sorted(self, mgr):
        scored = mgr.semantic_path_discovery("A", "C", semantic_weight=0.3)
        assert scored
        cs = [x["combined_score"] for x in scored]
        assert cs == sorted(cs, reverse=True)
        assert all({"path", "length", "semantic_score", "structural_score", "combined_score"} <= set(x) for x in scored)

    def test_no_path(self, mgr):
        assert mgr.semantic_path_discovery("A", "Z") == []


class TestSemanticNeighbors:
    def test_returns_filtered_neighbors(self, mgr, semantic):
        b = GraphNode.create(type="concept", text_content="graph", agent_id=AGENT)
        b.id = "B"
        c = GraphNode.create(type="concept", text_content="data", agent_id=AGENT)
        c.id = "C"
        semantic.search_results = [
            SemanticSearchResult(node=b, score=0.9),
            SemanticSearchResult(node=c, score=0.5),
        ]
        results = mgr.semantic_neighbors("A")
        # depth=1 时 A 的唯一邻居是 B；C 需 2 跳，被 node_filter 过滤
        assert [r.node.id for r in results] == ["B"]

    def test_node_no_text_returns_empty(self, mgr):
        db2 = FakeDB([_node("X", None)], [])
        m = HybridQueryManager(db=db2, semantic=FakeSemantic(), config=GraphConfig())
        assert m.semantic_neighbors("X") == []


class TestFilteredSemanticSearch:
    def test_properties_filter(self, mgr, semantic):
        b = GraphNode.create(type="concept", text_content="graph", agent_id=AGENT)
        b.id = "B"  # db 中 B 属性 lang=en
        c = GraphNode.create(type="concept", text_content="data", agent_id=AGENT)
        c.id = "C"  # db 中 C 无 lang 属性
        semantic.search_results = [
            SemanticSearchResult(node=b, score=0.9),
            SemanticSearchResult(node=c, score=0.5),
        ]
        results = mgr.filtered_semantic_search("q", properties_filter={"lang": "en"})
        assert [r.node.id for r in results] == ["B"]

    def test_no_properties_filter_passthrough(self, mgr, semantic):
        b = GraphNode.create(type="concept", text_content="graph", agent_id=AGENT)
        b.id = "B"
        semantic.search_results = [
            SemanticSearchResult(node=b, score=0.9),
        ]
        results = mgr.filtered_semantic_search("q")
        assert len(results) == 1