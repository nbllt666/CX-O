"""server.core.graph.semantic_search (SemanticSearch) 单元测试。

覆盖本地模式回退搜索、相似度计算、向量增删本地直通与初始化失败路径。
运行：python -m pytest tests/test_graph_semantic_search.py -v
"""
import numpy as np
import pytest

import server.core.graph.database as dbmod
from server.core.graph.config import GraphConfig
from server.core.graph.models import GraphNode
from server.core.graph.semantic_search import SemanticSearch


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params):
        params = list(params)
        ntype = None
        agent = None
        if "type = ?" in sql:
            ntype = params.pop(0)
        if "agent_id = ?" in sql:
            agent = params.pop(0)
        out = []
        for r in self.rows:
            if ntype is not None and r["type"] != ntype:
                continue
            if agent is not None and r["agent_id"] != agent:
                continue
            out.append(r)
        return out


def _row(nid, text, ntype="concept", agent="default"):
    now = "2026-01-01T00:00:00"
    return {
        "id": nid,
        "type": ntype,
        "properties": {},
        "text_content": text,
        "vector_id": None,
        "created_at": now,
        "updated_at": now,
        "agent_id": agent,
    }


@pytest.fixture
def searcher():
    return SemanticSearch(config=GraphConfig())


@pytest.fixture
def fallback_db():
    return FakeDB(
        [
            _row("n1", "hello world graph"),
            _row("n2", "hello world"),
            _row("n3", "hello unrelated", ntype="fact"),
        ]
    )


class TestComputeSimilarity:
    def test_same(self, searcher):
        assert searcher.compute_similarity(np.array([1, 0]), np.array([1, 0])) == pytest.approx(1.0)

    def test_orthogonal(self, searcher):
        assert searcher.compute_similarity(np.array([1, 0]), np.array([0, 1])) == pytest.approx(0.0)

    def test_length_mismatch(self, searcher):
        assert searcher.compute_similarity(np.array([1, 0]), np.array([1])) == 0.0

    def test_zero_vector(self, searcher):
        assert searcher.compute_similarity(np.array([0, 0]), np.array([1, 0])) == 0.0


class TestLocalMode:
    def test_add_vector_returns_node_id(self, searcher):
        # 显式传 vector，避免触发真实模型加载
        assert searcher.add_vector("n1", "text", "concept", vector=np.array([1.0, 0.0])) == "n1"

    def test_delete_vector_false(self, searcher):
        assert searcher.delete_vector("n1") is False

    def test_health_check_false(self, searcher):
        assert searcher.health_check() is False


class TestInitializeFailure:
    def test_import_error_leaves_uninitialized(self, searcher, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "weaviate":
                raise ImportError
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        searcher.initialize()
        assert searcher._client is None
        assert searcher._initialized is False


class TestFallbackSearch:
    def test_scores_by_overlap(self, searcher, fallback_db, monkeypatch):
        monkeypatch.setattr(dbmod, "get_database", lambda config: fallback_db)
        results = searcher._fallback_search("hello world", None, 10, None)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
        assert results[0].node.id == "n1"  # 2/2 命中
        assert results[0].score == 1.0

    def test_node_type_filter(self, searcher, fallback_db, monkeypatch):
        monkeypatch.setattr(dbmod, "get_database", lambda config: fallback_db)
        results = searcher._fallback_search("hello", "fact", 10, None)
        assert [r.node.id for r in results] == ["n3"]

    def test_node_filter_callback(self, searcher, fallback_db, monkeypatch):
        monkeypatch.setattr(dbmod, "get_database", lambda config: fallback_db)
        results = searcher._fallback_search("hello", None, 10, lambda nid: nid == "n2")
        assert [r.node.id for r in results] == ["n2"]

    def test_limit(self, searcher, fallback_db, monkeypatch):
        monkeypatch.setattr(dbmod, "get_database", lambda config: fallback_db)
        results = searcher._fallback_search("hello", None, 1, None)
        assert len(results) == 1

    def test_no_match_empty(self, searcher, fallback_db, monkeypatch):
        monkeypatch.setattr(dbmod, "get_database", lambda config: fallback_db)
        assert searcher._fallback_search("zzz", None, 10, None) == []

    def test_search_falls_back_when_no_client(self, searcher, fallback_db, monkeypatch):
        monkeypatch.setattr(dbmod, "get_database", lambda config: fallback_db)
        searcher._initialized = True  # 跳过 weaviate 连接的 slow initialize
        results = searcher.search("hello world", limit=10)
        assert results  # 无 client 走 fallback
        assert results[0].node.id == "n1"