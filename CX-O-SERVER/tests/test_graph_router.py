"""server.api.routers.graph 路由测试。

monkeypatch graph 模块的 _get_or_create_graph_database + GraphMonitor/SemanticQueryManager/
GraphExporter，返回假 graph 对象（用真实 GraphNode/GraphEdge dataclass 构造返回值）。
覆盖 node/edge/traversal/semantic/health/metrics/stats/algorithm/query-hops/path-constrained/export/config。

运行：python -m pytest tests/test_graph_router.py -v
"""
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import graph as graph_mod
from server.core.graph.models import GraphNode, GraphEdge


def _node(nid="n1", ntype="thing"):
    return GraphNode.create(type=ntype, properties={"k": "v"}, agent_id="default").__class__(
        id=nid, type=ntype, properties={"k": "v"}, text_content="t", agent_id="default"
    )


def _edge(eid="e1"):
    return GraphEdge.create(source_id="n1", target_id="n2", relation_type="rel").__class__(
        id=eid, source_id="n1", target_id="n2", relation_type="rel", agent_id="default"
    )


class FakeNodes:
    def create(self, data, agent_id="default"):
        return _node("n1", data.type)

    def search(self, **kw):
        return [_node("n1"), _node("n2")]

    def batch_create(self, nodes_data):
        return [_node("n1"), _node("n2")]

    def get(self, node_id, agent_id="default"):
        return _node(node_id) if node_id == "n1" else None

    def update(self, node_id, update_data, agent_id="default"):
        return _node(node_id) if node_id == "n1" else None

    def delete(self, node_id, cascade=True, agent_id="default"):
        return None


class FakeEdges:
    def create(self, data, agent_id="default"):
        return _edge()

    def search(self, **kw):
        return [_edge()]

    def get(self, edge_id, agent_id="default"):
        return _edge(edge_id) if edge_id == "e1" else None

    def update(self, edge_id, update_data, agent_id="default"):
        return _edge(edge_id) if edge_id == "e1" else None

    def delete(self, edge_id, agent_id="default"):
        return None


class FakeTraversal:
    def get_neighbors(self, node_id, max_depth=1, direction="both", agent_id="default"):
        return [(_node(), [_edge()])]

    def bfs_traverse(self, start_id, max_depth, node_type_filter, agent_id):
        return [_node()]

    def dfs_traverse(self, start_id, max_depth, node_type_filter, agent_id):
        return [_node()]

    def shortest_path(self, start_id, end_id, max_length, agent_id="default"):
        return SimpleNamespace(path=["n1", "n2"], length=1, edges=[_edge()])

    def pagerank(self, damping=0.85, max_iterations=100, agent_id="default"):
        return {"n1": 0.5}

    def get_important_nodes(self, limit=10, agent_id="default"):
        return [{"node": _node(), "pagerank": 0.5}]

    def community_detection(self, method="lpa", agent_id="default"):
        return [{"id": 0, "nodes": ["n1"]}]

    def get_community_stats(self, agent_id="default"):
        return {"total_communities": 1}


class FakeSemantic:
    def search(self, query, node_type, limit, agent_id):
        return [{"node_id": "n1", "node_type": "thing", "text_content": "t", "score": 0.9}]


class FakeHybrid:
    def filtered_semantic_search(self, query, node_type, properties_filter, limit, agent_id):
        return [{"node_id": "n1", "node_type": "thing", "text_content": "t", "score": 0.8}]

    def semantic_neighbors(self, node_id, limit, depth, agent_id):
        return [{"node_id": "n2", "score": 0.7}]


class FakeGraph:
    def __init__(self):
        self.nodes = FakeNodes()
        self.edges = FakeEdges()
        self.traversal = FakeTraversal()
        self.semantic = FakeSemantic()
        self.hybrid = FakeHybrid()
        self.db = object()
        self.config = SimpleNamespace(
            database_path="/tmp/graph.db",
            auto_create_schema=True,
            pool_size=5,
            timeout=10,
            weaviate=SimpleNamespace(url="http://w", api_key="secret", vector_dim=128,
                                     batch_size=1, ef_construction=64, max_connections=10),
            embedding=SimpleNamespace(model="m", batch_size=8, device="cpu", cache_folder="/tmp/c"),
        )

    def health_check(self):
        return {"overall": "healthy"}


class FakeMonitor:
    def __init__(self, db):
        self.db = db

    def get_graph_stats(self, agent_id="default"):
        return {"node_count": 2, "edge_count": 1, "node_types": {"thing": 2}}

    def get_metrics(self):
        return {"query_time_ms": 1.5}


class FakeSQM:
    def __init__(self, db):
        self.db = db

    def semantic_query_with_hops(self, **kw):
        return [{"node": _node(), "similarity": 0.9, "path": ["n1", "n2"]}]

    def path_constrained_semantic_search(self, **kw):
        return [{"node": _node(), "similarity": 0.8, "path": ["n1", "n2"]}]


class FakeExporter:
    def __init__(self, db):
        self.db = db

    def export_json(self):
        return '{"nodes": [], "edges": []}'

    def export_graphml(self, file_path):
        return None

    def export_dot(self, file_path):
        return None


@pytest.fixture
def client(monkeypatch):
    mgr = FakeGraph()
    monkeypatch.setattr(graph_mod, "_get_or_create_graph_database", lambda agent_id="default": mgr)
    monkeypatch.setattr(graph_mod, "GraphMonitor", FakeMonitor)
    monkeypatch.setattr(graph_mod, "SemanticQueryManager", FakeSQM)
    monkeypatch.setattr(graph_mod, "GraphExporter", FakeExporter)
    app = FastAPI()
    app.include_router(graph_mod.router)
    return TestClient(app, raise_server_exceptions=False)


class TestNodes:
    def test_create(self, client):
        r = client.post("/nodes", json={"type": "thing"})
        assert r.status_code == 200
        assert r.json()["id"] == "n1"

    def test_search(self, client):
        r = client.get("/nodes/search")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_batch_create(self, client):
        r = client.post("/nodes/batch", json=[{"type": "thing"}, {"type": "concept"}])
        assert r.status_code == 200
        assert r.json()["created"] == 2

    def test_get(self, client):
        r = client.get("/nodes/n1")
        assert r.status_code == 200
        assert r.json()["id"] == "n1"

    def test_get_404(self, client):
        r = client.get("/nodes/nope")
        assert r.status_code == 404

    def test_update(self, client):
        r = client.put("/nodes/n1", json={"type": "concept"})
        assert r.status_code == 200

    def test_update_404(self, client):
        r = client.put("/nodes/nope", json={"type": "concept"})
        assert r.status_code == 404

    def test_delete(self, client):
        r = client.delete("/nodes/n1")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_neighbors(self, client):
        r = client.get("/nodes/n1/neighbors")
        assert r.status_code == 200
        assert r.json()["neighbors"][0]["node"]["id"] == "n1"

    def test_neighbors_invalid_direction_422(self, client):
        r = client.get("/nodes/n1/neighbors", params={"direction": "sideways"})
        assert r.status_code == 422


class TestEdges:
    def test_create(self, client):
        r = client.post("/edges", json={"source_id": "n1", "target_id": "n2", "relation_type": "rel"})
        assert r.status_code == 200
        assert r.json()["id"] == "e1"

    def test_search(self, client):
        r = client.get("/edges/search")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_get(self, client):
        r = client.get("/edges/e1")
        assert r.status_code == 200
        assert r.json()["id"] == "e1"

    def test_get_404(self, client):
        r = client.get("/edges/nope")
        assert r.status_code == 404

    def test_update_404(self, client):
        r = client.put("/edges/nope", json={"relation_type": "x"})
        assert r.status_code == 404

    def test_delete(self, client):
        r = client.delete("/edges/e1")
        assert r.status_code == 200


class TestTraversal:
    def test_bfs(self, client):
        r = client.post("/traverse/bfs", json={"start_id": "n1"})
        assert r.status_code == 200
        assert r.json()["nodes"][0]["id"] == "n1"

    def test_dfs(self, client):
        r = client.post("/traverse/dfs", json={"start_id": "n1"})
        assert r.status_code == 200

    def test_shortest_path(self, client):
        r = client.get("/paths/shortest", params={"start_id": "n1", "end_id": "n2"})
        assert r.status_code == 200
        assert r.json()["length"] == 1


class TestSemantic:
    def test_search(self, client):
        r = client.post("/semantic/search", json={"query": "q"})
        assert r.status_code == 200
        assert r.json()["results"][0]["node_id"] == "n1"

    def test_hybrid(self, client):
        r = client.post("/semantic/hybrid", json={"query": "q"})
        assert r.status_code == 200
        assert r.json()["results"][0]["score"] == 0.8

    def test_neighbors(self, client):
        r = client.get("/semantic/neighbors/n1")
        assert r.status_code == 200
        assert r.json()["results"][0]["node_id"] == "n2"


class TestHealthMetrics:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["overall"] == "healthy"

    def test_status(self, client):
        r = client.get("/status")
        assert r.status_code == 200
        body = r.json()
        assert body["connected"] is True
        assert body["graph_enabled"] is True
        assert body["libraries"]["thing"]["entity_count"] == 2
        assert body["libraries"]["user"]["relation_count"] == 1
        assert body["database_path"] == "/tmp/graph.db"

    def test_metrics(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert r.json()["query_time_ms"] == 1.5

    def test_stats(self, client):
        r = client.get("/stats")
        assert r.status_code == 200
        assert r.json()["node_count"] == 2


class TestAlgorithm:
    def test_pagerank(self, client):
        r = client.get("/algorithm/pagerank")
        assert r.status_code == 200
        assert r.json()["scores"]["n1"] == 0.5

    def test_important_nodes(self, client):
        r = client.get("/algorithm/important-nodes")
        assert r.status_code == 200
        assert r.json()["nodes"][0]["pagerank"] == 0.5

    def test_communities(self, client):
        r = client.get("/algorithm/communities")
        assert r.status_code == 200
        assert r.json()["communities"][0]["id"] == 0

    def test_communities_invalid_422(self, client):
        r = client.get("/algorithm/communities", params={"method": "bad"})
        assert r.status_code == 422

    def test_community_stats(self, client):
        r = client.get("/algorithm/community-stats")
        assert r.status_code == 200
        assert r.json()["stats"]["total_communities"] == 1


class TestQueryHops:
    def test_query_hops(self, client):
        r = client.post("/semantic/query-hops", json={"start_node_id": "n1", "query": "q"})
        assert r.status_code == 200
        assert r.json()["results"][0]["similarity"] == 0.9

    def test_path_constrained(self, client):
        r = client.post("/semantic/path-constrained",
                        json={"start_node_id": "n1", "end_node_id": "n2", "query": "q"})
        assert r.status_code == 200
        assert r.json()["results"][0]["similarity"] == 0.8


class TestExport:
    def test_json(self, client):
        r = client.get("/export/json")
        assert r.status_code == 200
        assert r.json()["format"] == "json"

    def test_graphml(self, client):
        r = client.get("/export/graphml")
        assert r.status_code == 200
        assert r.json()["status"] == "exported"

    def test_dot(self, client):
        r = client.get("/export/dot")
        assert r.status_code == 200
        assert r.json()["format"] == "dot"


class TestConfig:
    def test_config(self, client):
        r = client.get("/config")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["config"]["database_path"] == "/tmp/graph.db"
        assert body["config"]["weaviate"]["api_key"] == "***"
        assert body["config"]["embedding"]["model"] == "m"