"""
图数据库健康检查和监控
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict

from server.core.graph.database import Database

logger = logging.getLogger(__name__)


@dataclass
class QueryMetrics:
    total_queries: int = 0
    total_searches: int = 0
    query_latencies: deque = field(default_factory=lambda: deque(maxlen=1000))
    search_latencies: deque = field(default_factory=lambda: deque(maxlen=1000))
    cache_hits: int = 0
    cache_misses: int = 0

    def add_query_latency(self, latency: float):
        self.query_latencies.append(latency)
        self.total_queries += 1

    def add_search_latency(self, latency: float):
        self.search_latencies.append(latency)
        self.total_searches += 1

    def add_cache_hit(self):
        self.cache_hits += 1

    def add_cache_miss(self):
        self.cache_misses += 1

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

    def get_latency_p95(self) -> float:
        if not self.query_latencies:
            return 0.0
        sorted_latencies = sorted(self.query_latencies)
        index = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[index] if index < len(sorted_latencies) else sorted_latencies[-1]

    def get_search_latency_p95(self) -> float:
        if not self.search_latencies:
            return 0.0
        sorted_latencies = sorted(self.search_latencies)
        index = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[index] if index < len(sorted_latencies) else sorted_latencies[-1]


_global_metrics = QueryMetrics()


def get_metrics() -> QueryMetrics:
    return _global_metrics


class GraphMonitor:
    """图数据库监控器"""

    def __init__(self, db: Database):
        self.db = db

    def health_check(self) -> Dict[str, Any]:
        db_status = self._check_database()
        vector_status = self._check_vector_store()

        node_count = self._get_node_count()
        edge_count = self._get_edge_count()

        overall_status = "healthy"
        if db_status["status"] != "ok":
            overall_status = "degraded"
        if node_count == 0 and edge_count == 0:
            overall_status = "degraded"

        return {
            "status": overall_status,
            "database": db_status,
            "vector_store": vector_status,
            "node_count": node_count,
            "edge_count": edge_count,
            "timestamp": datetime.now().isoformat(),
        }

    def get_metrics(self) -> Dict[str, Any]:
        metrics = get_metrics()

        return {
            "queries": {
                "total": metrics.total_queries,
                "latency_p95_ms": round(metrics.get_latency_p95() * 1000, 2),
                "recent_latencies_ms": [round(l * 1000, 2) for l in list(metrics.query_latencies)[-10:]],
            },
            "searches": {
                "total": metrics.total_searches,
                "latency_p95_ms": round(metrics.get_search_latency_p95() * 1000, 2),
            },
            "cache": {
                "hits": metrics.cache_hits,
                "misses": metrics.cache_misses,
                "hit_rate": round(metrics.cache_hit_rate * 100, 2),
            },
        }

    def get_graph_stats(self, agent_id: str = "default") -> Dict[str, Any]:
        node_count = self._get_node_count(agent_id)
        edge_count = self._get_edge_count(agent_id)

        avg_degree = (2 * edge_count / node_count) if node_count > 0 else 0.0

        max_possible_edges = node_count * (node_count - 1) / 2
        graph_density = (2 * edge_count / max_possible_edges) if max_possible_edges > 0 else 0.0

        node_types = self._get_node_type_distribution(agent_id)
        edge_types = self._get_edge_type_distribution(agent_id)

        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "avg_degree": round(avg_degree, 4),
            "graph_density": round(graph_density, 6),
            "node_types": node_types,
            "edge_types": edge_types,
        }

    def _check_database(self) -> Dict[str, Any]:
        try:
            start = time.time()
            self.db.execute("SELECT 1")
            latency = time.time() - start

            return {
                "status": "ok",
                "latency_ms": round(latency * 1000, 2),
            }
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "status": "error",
                "error": str(e),
            }

    def _check_vector_store(self) -> Dict[str, Any]:
        try:
            from server.core.graph.semantic_search import SemanticSearch
            from server.core.graph.config import GraphConfig

            config = GraphConfig()
            semantic = SemanticSearch(config)

            if semantic._initialized:
                return {
                    "status": "ok",
                    "backend": "weaviate",
                }
            else:
                return {
                    "status": "degraded",
                    "reason": "Weaviate not available, using fallback mode",
                }
        except Exception as e:
            logger.warning(f"Vector store check failed: {e}")
            return {
                "status": "degraded",
                "reason": str(e),
            }

    def _get_node_count(self, agent_id: str = "default") -> int:
        try:
            result = self.db.execute_one("SELECT COUNT(*) as cnt FROM nodes WHERE agent_id = ?", (agent_id,))
            return result["cnt"] if result else 0
        except Exception:
            return 0

    def _get_edge_count(self, agent_id: str = "default") -> int:
        try:
            result = self.db.execute_one("SELECT COUNT(*) as cnt FROM edges WHERE agent_id = ?", (agent_id,))
            return result["cnt"] if result else 0
        except Exception:
            return 0

    def _get_node_type_distribution(self, agent_id: str = "default") -> Dict[str, int]:
        try:
            query = """
                SELECT type, COUNT(*) as cnt
                FROM nodes
                WHERE type IS NOT NULL AND type != '' AND agent_id = ?
                GROUP BY type
            """
            rows = self.db.execute(query, (agent_id,))
            return {row["type"]: row["cnt"] for row in rows}
        except Exception:
            return {}

    def _get_edge_type_distribution(self, agent_id: str = "default") -> Dict[str, int]:
        try:
            query = """
                SELECT relation_type, COUNT(*) as cnt
                FROM edges
                WHERE relation_type IS NOT NULL AND relation_type != '' AND agent_id = ?
                GROUP BY relation_type
            """
            rows = self.db.execute(query, (agent_id,))
            return {row["relation_type"]: row["cnt"] for row in rows}
        except Exception:
            return {}


class LatencyTracker:
    """延迟跟踪装饰器"""

    def __init__(self, metric_type: str = "query"):
        self.metric_type = metric_type

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency = time.time() - self.start
        metrics = get_metrics()

        if self.metric_type == "query":
            metrics.add_query_latency(latency)
        elif self.metric_type == "search":
            metrics.add_search_latency(latency)
