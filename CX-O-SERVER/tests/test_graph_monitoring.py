"""server.core.graph 监控/基类/可视化单元测试。

覆盖 QueryMetrics 统计、GraphMonitor 健康检查与图统计、LatencyTracker 延迟跟踪、
BaseGraphRepository 通用查询、GraphExporter 三种导出格式。
运行：python -m pytest tests/test_graph_monitoring.py -v
"""
import json
import time

import pytest

from server.core.graph.config import GraphConfig
from server.core.graph.database import Database
from server.core.graph.monitoring import QueryMetrics, GraphMonitor, LatencyTracker, get_metrics
from server.core.graph.repository import BaseGraphRepository
from server.core.graph.nodes import NodeManager
from server.core.graph.edges import EdgeManager
from server.core.graph.visualization import GraphExporter
from server.core.graph.models import NodeCreate, EdgeCreate

AGENT = "default"


@pytest.fixture
def mon():
    return QueryMetrics()


@pytest.fixture
def db():
    config = GraphConfig(database_path=":memory:")
    database = Database(config)
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def repo(db):
    return BaseGraphRepository(db)


@pytest.fixture
def exporter(db):
    return GraphExporter(db)


@pytest.fixture
def seeded(db):
    nm = NodeManager(db, db.config)
    em = EdgeManager(db, db.config)
    a = nm.create(NodeCreate(type="concept", properties={"lang": "en"}, text_content="alpha"))
    b = nm.create(NodeCreate(type="concept", properties={}, text_content="beta"))
    c = nm.create(NodeCreate(type="person", properties={}, text_content="gamma"))
    e1 = em.create(EdgeCreate(source_id=a.id, target_id=b.id, relation_type="related"))
    e2 = em.create(EdgeCreate(source_id=b.id, target_id=c.id, relation_type="knows"))
    return {"a": a, "b": b, "c": c, "e1": e1, "e2": e2}


class TestQueryMetrics:
    def test_add_query_latency(self, mon):
        mon.add_query_latency(0.1)
        assert mon.total_queries == 1
        assert list(mon.query_latencies) == [0.1]

    def test_add_search_latency(self, mon):
        mon.add_search_latency(0.2)
        assert mon.total_searches == 1

    def test_cache_hit_rate(self, mon):
        assert mon.cache_hit_rate == 0.0
        mon.add_cache_hit()
        mon.add_cache_miss()
        assert mon.cache_hit_rate == 0.5

    def test_latency_p95_empty(self, mon):
        assert mon.get_latency_p95() == 0.0
        assert mon.get_search_latency_p95() == 0.0

    def test_latency_p95_value(self, mon):
        for i in range(20):
            mon.add_query_latency(float(i))
        # 95% 分位取 sorted[int(20*0.95)=19] = 19.0
        assert mon.get_latency_p95() == 19.0

    def test_search_p95(self, mon):
        vals = [1.0, 2.0]
        for v in vals:
            mon.add_search_latency(v)
        assert mon.get_search_latency_p95() == sorted(vals)[int(len(vals) * 0.95)]


class TestGraphMonitorHealth:
    def test_healthy_with_data(self, db, seeded):
        result = GraphMonitor(db).health_check()
        assert result["status"] == "healthy"
        assert result["database"]["status"] == "ok"
        assert result["node_count"] == 3
        assert result["edge_count"] == 2

    def test_degraded_empty_db(self, db):
        result = GraphMonitor(db).health_check()
        assert result["status"] == "degraded"
        assert result["node_count"] == 0
        assert result["edge_count"] == 0

    def test_vector_store_degraded_fallback(self, db, seeded):
        result = GraphMonitor(db).health_check()
        # 本地模式（无 Weaviate）向量存储为 degraded，但节点存在故整体 healthy
        assert result["vector_store"]["status"] == "degraded"


class TestGraphMonitorVectorWiring:
    """M-D8: 健康检查只检查构造注入的 semantic 实例引用，不再每次 new
    SemanticSearch(GraphConfig())；未注入时如实上报 degraded。"""

    def test_not_wired_reports_degraded_with_reason(self, db):
        result = GraphMonitor(db).health_check()
        assert result["vector_store"]["status"] == "degraded"
        assert "not wired" in result["vector_store"]["reason"]

    def test_injected_initialized_semantic_reports_ok(self, db):
        class _FakeSemantic:
            _initialized = True

        monitor = GraphMonitor(db, semantic_search=_FakeSemantic())
        result = monitor.health_check()
        assert result["vector_store"] == {"status": "ok", "backend": "weaviate"}

    def test_injected_uninitialized_semantic_reports_degraded(self, db):
        class _FakeSemantic:
            _initialized = False

        monitor = GraphMonitor(db, semantic_search=_FakeSemantic())
        v = monitor._check_vector_store()
        assert v["status"] == "degraded"
        assert "fallback" in v["reason"]

    def test_no_semantic_search_import_side_effect(self, db, monkeypatch):
        """_check_vector_store 被传入 sentinel 时不得新建真实 SemanticSearch
        （通过拦截 GraphConfig 构造验证无隐式构建路径）。"""
        import server.core.graph.config as gconfig

        def _boom(*a, **k):  # pragma: no cover - 若被调用即失败
            raise AssertionError("health_check 不应构造新的 GraphConfig/SemanticSearch")

        monkeypatch.setattr(gconfig, "GraphConfig", _boom)
        monitor = GraphMonitor(db)
        v = monitor._check_vector_store()
        assert v["status"] == "degraded"


class TestGraphMonitorMetrics:
    def test_get_metrics_empty(self, db):
        result = GraphMonitor(db).get_metrics()
        assert result["queries"]["total"] == 0
        assert result["searches"]["total"] == 0
        assert result["cache"]["hit_rate"] == 0.0

    def test_get_metrics_after_activity(self, db, monkeypatch):
        mon = QueryMetrics()
        mon.add_query_latency(0.05)
        mon.add_search_latency(0.1)
        mon.add_cache_hit()
        mon.add_cache_hit()
        mon.add_cache_miss()
        monkeypatch.setattr("server.core.graph.monitoring.get_metrics", lambda: mon)
        result = GraphMonitor(db).get_metrics()
        assert result["queries"]["total"] == 1
        assert result["searches"]["total"] == 1
        assert result["cache"]["hit_rate"] == pytest.approx(66.67, abs=0.01)


class TestGraphStats:
    def test_get_graph_stats(self, db, seeded):
        stats = GraphMonitor(db).get_graph_stats()
        assert stats["node_count"] == 3
        assert stats["edge_count"] == 2
        # 平均度 = 2*2/3
        assert stats["avg_degree"] == pytest.approx(4 / 3, abs=0.0001)
        assert stats["node_types"] == {"concept": 2, "person": 1}
        assert stats["edge_types"] == {"related": 1, "knows": 1}

    def test_get_graph_stats_empty(self, db):
        stats = GraphMonitor(db).get_graph_stats()
        assert stats["node_count"] == 0
        assert stats["avg_degree"] == 0.0
        assert stats["graph_density"] == 0.0


class TestLatencyTracker:
    def test_query_tracker(self, mon):
        with LatencyTracker("query"):
            time.sleep(0.001)
        assert get_metrics().total_queries >= 1

    def test_search_tracker(self, mon):
        with LatencyTracker("search"):
            time.sleep(0.001)
        assert get_metrics().total_searches >= 1

    def test_unknown_type_noop(self):
        with LatencyTracker("other"):
            pass
        # 不抛异常即可


class TestBaseGraphRepository:
    def test_get_node(self, repo, seeded):
        node = repo.get_node(seeded["a"].id)
        assert node.id == seeded["a"].id
        assert node.type == "concept"

    def test_get_node_missing(self, repo):
        assert repo.get_node("nope") is None

    def test_get_edge(self, repo, seeded):
        edge = repo.get_edge(seeded["e1"].id)
        assert edge.id == seeded["e1"].id
        assert edge.source_id == seeded["a"].id

    def test_get_edge_missing(self, repo):
        assert repo.get_edge("nope") is None

    def test_neighbors_both(self, repo, seeded):
        nids = repo.get_neighbor_ids(seeded["b"].id, "both")
        assert set(nids) == {seeded["a"].id, seeded["c"].id}

    def test_neighbors_outgoing(self, repo, seeded):
        nids = repo.get_neighbor_ids(seeded["b"].id, "outgoing")
        assert nids == [seeded["c"].id]

    def test_neighbors_incoming(self, repo, seeded):
        nids = repo.get_neighbor_ids(seeded["b"].id, "incoming")
        assert nids == [seeded["a"].id]

    def test_neighbors_none(self, repo, seeded):
        assert repo.get_neighbor_ids("nope", "both") == []


class TestGraphExporter:
    def test_export_json_structure(self, db, seeded):
        data = json.loads(GraphExporter(db).export_json())
        assert data["metadata"]["node_count"] == 3
        assert data["metadata"]["edge_count"] == 2
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2

    def test_export_json_to_file(self, db, seeded, tmp_path):
        out = tmp_path / "graph.json"
        text = GraphExporter(db).export_json(str(out))
        assert out.exists()
        assert json.loads(text)["metadata"]["node_count"] == 3

    def test_export_graphml(self, db, seeded, tmp_path):
        out = tmp_path / "graph.graphml"
        text = GraphExporter(db).export_graphml(str(out))
        assert out.exists()
        assert "graphml" in text
        assert f'id="{seeded["a"].id}"' in text

    def test_export_dot(self, db, seeded, tmp_path):
        out = tmp_path / "graph.dot"
        text = GraphExporter(db).export_dot(str(out))
        assert out.exists()
        assert "digraph" in text
        assert f'"{seeded["a"].id}"' in text
        assert f'"{seeded["a"].id}" -> "{seeded["b"].id}"' in text

    def test_export_dot_empty(self, db, tmp_path):
        text = GraphExporter(db).export_dot(str(tmp_path / "empty.dot"))
        assert "digraph" in text