"""
多跳语义查询
"""

import logging
from collections import deque
from typing import Any, Dict, List, Optional, Set

from server.core.graph.database import Database
from server.core.graph.models import GraphNode, GraphEdge
from server.core.graph.vectorizer import get_vectorizer
from server.core.graph.repository import BaseGraphRepository

logger = logging.getLogger(__name__)


class SemanticQueryManager(BaseGraphRepository):
    """多跳语义查询管理器"""

    def __init__(self, db: Database):
        super().__init__(db)

    def semantic_query_with_hops(
        self,
        start_node_id: str,
        query: str,
        hops: int = 2,
        limit: int = 10,
        direction: str = "both",
    ) -> List[Dict[str, Any]]:
        """多跳语义查询

        Args:
            start_node_id: 起始节点 ID
            query: 语义查询文本
            hops: 跳数
            limit: 返回结果数量限制
            direction: 方向 ("outgoing", "incoming", "both")

        Returns:
            List[{node, similarity, path, path_edges}]
        """
        reachable_nodes = self._get_reachable_nodes(start_node_id, hops, direction)

        if not reachable_nodes:
            return []

        nodes_with_text = []
        for node_id in reachable_nodes:
            node = self.get_node(node_id)
            if node:
                text_content = self._extract_node_text(node)
                nodes_with_text.append((node_id, node, text_content))

        if not nodes_with_text:
            return []

        query_embedding = self._get_query_embedding(query)
        if query_embedding is None:
            return []

        results = []
        for node_id, node, text in nodes_with_text:
            node_embedding = self._get_text_embedding(text)
            if node_embedding is None:
                continue

            similarity = self._cosine_similarity(query_embedding, node_embedding)

            path = self._get_shortest_path(start_node_id, node_id)
            path_edges = self._get_path_edges(path) if path else []

            results.append({
                "node": node,
                "similarity": similarity,
                "path": path,
                "path_edges": path_edges,
            })

        results.sort(key=lambda x: x["similarity"], reverse=True)

        return results[:limit]

    def path_constrained_semantic_search(
        self,
        start_node_id: str,
        end_node_id: str,
        query: str,
        max_path_length: int = 5,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """路径约束的语义搜索

        在连接 start 和 end 的路径上，找到语义最相关的节点。

        Args:
            start_node_id: 起始节点 ID
            end_node_id: 目标节点 ID
            query: 语义查询文本
            max_path_length: 最大路径长度
            limit: 返回结果数量限制

        Returns:
            List[{node, similarity, path, path_edges}]
        """
        all_paths = self._find_all_paths(start_node_id, end_node_id, max_path_length)

        if not all_paths:
            return []

        path_nodes: Set[str] = set()
        for path in all_paths:
            path_nodes.update(path)

        nodes_with_text = []
        for node_id in path_nodes:
            if node_id == start_node_id or node_id == end_node_id:
                continue

            node = self.get_node(node_id)
            if node:
                text_content = self._extract_node_text(node)
                nodes_with_text.append((node_id, node, text_content))

        if not nodes_with_text:
            return []

        query_embedding = self._get_query_embedding(query)
        if query_embedding is None:
            return []

        results = []
        for node_id, node, text in nodes_with_text:
            node_embedding = self._get_text_embedding(text)
            if node_embedding is None:
                continue

            similarity = self._cosine_similarity(query_embedding, node_embedding)

            best_path = self._get_shortest_path(start_node_id, node_id)
            path_edges = self._get_path_edges(best_path) if best_path else []

            results.append({
                "node": node,
                "similarity": similarity,
                "path": best_path,
                "path_edges": path_edges,
            })

        results.sort(key=lambda x: x["similarity"], reverse=True)

        return results[:limit]

    def _get_reachable_nodes(
        self,
        start_id: str,
        max_hops: int,
        direction: str = "both",
    ) -> Set[str]:
        """使用 BFS 获取可达节点"""
        visited: Set[str] = set()
        queue = deque([(start_id, 0)])

        while queue:
            current_id, depth = queue.popleft()

            if current_id in visited:
                continue

            visited.add(current_id)

            if depth < max_hops:
                neighbor_ids = self.get_neighbor_ids(current_id, direction)
                for neighbor_id in neighbor_ids:
                    if neighbor_id not in visited:
                        queue.append((neighbor_id, depth + 1))

        return visited

    def _extract_node_text(self, node: GraphNode) -> str:
        """从节点提取文本内容"""
        parts = [node.name or ""]
        if node.type:
            parts.append(node.type)
        if node.properties:
            for key, value in node.properties.items():
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, (list, tuple)):
                    parts.extend(str(v) for v in value)
                else:
                    parts.append(str(value))
        return " ".join(parts)

    def _get_query_embedding(self, query: str) -> Optional[List[float]]:
        """获取查询文本的嵌入向量"""
        try:
            vectorizer = get_vectorizer()
            return vectorizer.embed(query)
        except Exception as e:
            logger.warning(f"Failed to get query embedding: {e}")
            return None

    def _get_text_embedding(self, text: str) -> Optional[List[float]]:
        """获取文本的嵌入向量"""
        try:
            vectorizer = get_vectorizer()
            return vectorizer.embed(text)
        except Exception as e:
            logger.warning(f"Failed to get text embedding: {e}")
            return None

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        if len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    def _get_shortest_path(self, start_id: str, end_id: str) -> Optional[List[str]]:
        """使用 BFS 找最短路径"""
        if start_id == end_id:
            return [start_id]

        visited: Set[str] = {start_id}
        queue = deque([(start_id, [start_id])])

        while queue:
            current_id, path = queue.popleft()

            neighbor_ids = self.get_neighbor_ids(current_id, "both")
            for neighbor_id in neighbor_ids:
                if neighbor_id == end_id:
                    return path + [neighbor_id]

                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, path + [neighbor_id]))

        return None

    def _find_all_paths(
        self,
        start_id: str,
        end_id: str,
        max_length: int,
    ) -> List[List[str]]:
        """找出所有简单路径"""
        results: List[List[str]] = []

        def dfs(current: str, path: List[str], depth: int):
            if depth >= max_length:
                return

            if current == end_id:
                results.append(path.copy())
                return

            neighbor_ids = self.get_neighbor_ids(current, "both")
            for neighbor_id in neighbor_ids:
                if neighbor_id not in path:
                    path.append(neighbor_id)
                    dfs(neighbor_id, path, depth + 1)
                    path.pop()

        dfs(start_id, [start_id], 0)
        return results

    def _get_path_edges(self, path: List[str]) -> List[GraphEdge]:
        """获取路径上的边"""
        if len(path) < 2:
            return []

        edges = []
        for i in range(len(path) - 1):
            source = path[i]
            target = path[i + 1]

            edge = self._get_edge_between(source, target)
            if edge:
                edges.append(edge)

        return edges

    def _get_edge_between(self, source_id: str, target_id: str) -> Optional[GraphEdge]:
        """获取两个节点之间的边"""
        query = """
            SELECT * FROM edges
            WHERE (source_id = ? AND target_id = ?)
               OR (source_id = ? AND target_id = ?)
            LIMIT 1
        """
        row = self.db.execute_one(query, (source_id, target_id, target_id, source_id))
        if row:
            return GraphEdge.from_dict(dict(row))
        return None
