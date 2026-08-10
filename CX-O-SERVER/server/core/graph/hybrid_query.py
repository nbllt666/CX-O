"""
混合查询（图+语义）
"""

import logging
from typing import Optional, List, Dict, Any

from server.core.graph.database import Database
from server.core.graph.semantic_search import SemanticSearch
from server.core.graph.models import GraphNode, SemanticSearchResult
from server.core.graph.config import GraphConfig
from server.core.graph.traversal import TraversalManager
from server.core.graph.repository import BaseGraphRepository

logger = logging.getLogger(__name__)


class HybridQueryManager(BaseGraphRepository):
    """混合查询管理器"""

    def __init__(self, db: Database, semantic: SemanticSearch, config: GraphConfig):
        super().__init__(db)
        self.semantic = semantic
        self.config = config
        self.traversal = TraversalManager(db, config)

    def semantic_neighbors(
        self,
        node_id: str,
        limit: int = 10,
        depth: int = 1,
        agent_id: str = "default",
    ) -> List[SemanticSearchResult]:
        node = self.get_node(node_id, agent_id=agent_id)
        if not node or not node.text_content:
            return []

        neighbors = self.traversal.get_neighbors(node_id, max_depth=depth, agent_id=agent_id)
        neighbor_texts = [
            (n.id, n.text_content or "", n.type)
            for n, _ in neighbors if n.text_content
        ]

        if not neighbor_texts:
            return []

        query = node.text_content
        results = self.semantic.search(
            query=query,
            node_type=None,
            limit=limit,
            node_filter=lambda nid: nid in [n[0] for n in neighbor_texts],
            agent_id=agent_id,
        )

        return results

    def filtered_semantic_search(
        self,
        query: str,
        node_type: Optional[str] = None,
        properties_filter: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        agent_id: str = "default",
    ) -> List[SemanticSearchResult]:
        results = self.semantic.search(
            query=query,
            node_type=node_type,
            limit=limit * 2,
            agent_id=agent_id,
        )

        if properties_filter:
            filtered = []
            for result in results:
                node = self.get_node(result.node.id, agent_id=agent_id)
                if node and self._matches_filter(node, properties_filter):
                    filtered.append(result)
            results = filtered

        return results[:limit]

    def semantic_path_discovery(
        self,
        start_id: str,
        end_id: str,
        semantic_weight: float = 0.3,
        max_length: int = 5,
    ) -> List[Dict[str, Any]]:
        all_paths = self.traversal.all_paths(start_id, end_id, max_length)

        scored_paths = []
        for path_result in all_paths:
            semantic_score = self._calculate_path_semantic_score(path_result)

            edge_count = len(path_result.edges)
            structural_score = 1.0 / (edge_count + 1)

            combined_score = (1 - semantic_weight) * structural_score + semantic_weight * semantic_score

            scored_paths.append({
                "path": path_result.path,
                "length": path_result.length,
                "semantic_score": semantic_score,
                "structural_score": structural_score,
                "combined_score": combined_score,
            })

        scored_paths.sort(key=lambda x: x["combined_score"], reverse=True)
        return scored_paths

    def _calculate_path_semantic_score(self, path_result) -> float:
        if not path_result.path:
            return 0.0

        texts = []
        for node_id in path_result.path:
            node = self.get_node(node_id)
            if node and node.text_content:
                texts.append(node.text_content)

        if len(texts) < 2:
            return 0.0

        vectors = self.semantic.encode_batch(texts)
        similarities = []
        for i in range(len(vectors) - 1):
            sim = self.semantic.compute_similarity(vectors[i], vectors[i+1])
            similarities.append(sim)

        return sum(similarities) / len(similarities) if similarities else 0.0

    def _matches_filter(self, node: GraphNode, filter_dict: Dict[str, Any]) -> bool:
        for key, value in filter_dict.items():
            if key not in node.properties:
                return False
            if node.properties[key] != value:
                return False
        return True
