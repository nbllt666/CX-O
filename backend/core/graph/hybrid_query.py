"""
混合查询（图+语义）
"""

import logging
from typing import Optional, List, Dict, Any

from backend.core.graph.database import Database
from backend.core.graph.semantic_search import SemanticSearch
from backend.core.graph.models import GraphNode, GraphEdge, SemanticSearchResult, SearchResult
from backend.core.graph.config import GraphConfig
from backend.core.graph.traversal import TraversalManager

logger = logging.getLogger(__name__)


class HybridQueryManager:
    """混合查询管理器"""

    def __init__(self, db: Database, semantic: SemanticSearch, config: GraphConfig):
        self.db = db
        self.semantic = semantic
        self.config = config
        self.traversal = TraversalManager(db, config)

    def semantic_neighbors(
        self,
        node_id: str,
        limit: int = 10,
        depth: int = 1,
    ) -> List[SemanticSearchResult]:
        """找到与指定节点语义最相似的邻居

        Args:
            node_id: 节点 ID
            limit: 返回数量
            depth: 邻居深度

        Returns:
            语义相似的邻居节点列表
        """
        node = self._get_node(node_id)
        if not node or not node.text_content:
            return []

        neighbors = self.traversal.get_neighbors(node_id, max_depth=depth)
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
        )

        return results

    def filtered_semantic_search(
        self,
        query: str,
        node_type: Optional[str] = None,
        properties_filter: Optional[Dict[str, Any]] = None,
        limit: int = 10,
    ) -> List[SemanticSearchResult]:
        """带属性过滤的语义搜索

        Args:
            query: 查询文本
            node_type: 节点类型
            properties_filter: 属性过滤器
            limit: 返回数量

        Returns:
            匹配的节点列表
        """
        results = self.semantic.search(
            query=query,
            node_type=node_type,
            limit=limit * 2,
        )

        if properties_filter:
            filtered = []
            for result in results:
                node = self._get_node(result.node_id)
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
        """语义路径发现（在路径搜索中融入语义相似度）

        Args:
            start_id: 起始节点
            end_id: 目标节点
            semantic_weight: 语义权重 (0-1)
            max_length: 最大路径长度

        Returns:
            包含语义相似度的路径列表
        """
        from backend.core.graph.models import PathResult

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
        """计算路径的语义相似度"""
        if not path_result.path:
            return 0.0

        texts = []
        for node_id in path_result.path:
            node = self._get_node(node_id)
            if node and node.text_content:
                texts.append(node.text_content)

        if len(texts) < 2:
            return 0.0

        vectors = self.semantic._vectorizer.encode_batch(texts)
        similarities = []
        for i in range(len(vectors) - 1):
            sim = np.dot(vectors[i], vectors[i+1]) / (
                np.linalg.norm(vectors[i]) * np.linalg.norm(vectors[i+1])
            )
            similarities.append(sim)

        return sum(similarities) / len(similarities) if similarities else 0.0

    def _get_node(self, node_id: str) -> Optional[GraphNode]:
        """获取节点"""
        query = "SELECT * FROM nodes WHERE id = ?"
        row = self.db.execute_one(query, (node_id,))
        if row:
            return GraphNode.from_dict(dict(row))
        return None

    def _matches_filter(self, node: GraphNode, filter_dict: Dict[str, Any]) -> bool:
        """检查节点是否匹配过滤器"""
        for key, value in filter_dict.items():
            if key not in node.properties:
                return False
            if node.properties[key] != value:
                return False
        return True