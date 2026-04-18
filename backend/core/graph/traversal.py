"""
图遍历算法
"""

import heapq
import logging
from typing import Optional, List, Dict, Set, Tuple, Any
from collections import deque

from backend.core.graph.database import Database
from backend.core.graph.models import GraphNode, GraphEdge, PathResult
from backend.core.graph.config import GraphConfig

logger = logging.getLogger(__name__)


class TraversalManager:
    """图遍历管理器"""

    def __init__(self, db: Database, config: GraphConfig):
        self.db = db
        self.config = config

    def get_neighbors(
        self,
        node_id: str,
        max_depth: int = 1,
        direction: str = "both"
    ) -> List[Tuple[GraphNode, List[GraphEdge]]]:
        """获取节点的邻居节点

        Args:
            node_id: 节点 ID
            max_depth: 最大深度
            direction: 方向 ("outgoing", "incoming", "both")

        Returns:
            [(邻居节点, [连接的边]), ...]
        """
        result = []
        visited: Set[str] = set()
        queue = deque([(node_id, 0)])

        while queue:
            current_id, depth = queue.popleft()

            if current_id in visited or depth > max_depth:
                continue

            visited.add(current_id)

            if depth > 0:
                node = self._get_node(current_id)
                if node:
                    edges = self._get_edges_for_node(current_id, direction)
                    result.append((node, edges))

            if depth < max_depth:
                neighbor_ids = self._get_neighbor_ids(current_id, direction)
                for neighbor_id in neighbor_ids:
                    if neighbor_id not in visited:
                        queue.append((neighbor_id, depth + 1))

        return result

    def bfs_traverse(
        self,
        start_id: str,
        max_depth: int = 10,
        node_type_filter: Optional[str] = None,
    ) -> List[GraphNode]:
        """广度优先遍历

        Returns:
            按 BFS 顺序排列的节点列表
        """
        result = []
        visited: Set[str] = set()
        queue = deque([(start_id, 0)])

        while queue:
            current_id, depth = queue.popleft()

            if current_id in visited:
                continue

            visited.add(current_id)

            node = self._get_node(current_id)
            if node:
                if node_type_filter is None or node.type == node_type_filter:
                    result.append(node)

            if depth < max_depth:
                neighbor_ids = self._get_neighbor_ids(current_id, "both")
                for neighbor_id in neighbor_ids:
                    if neighbor_id not in visited:
                        queue.append((neighbor_id, depth + 1))

        return result

    def dfs_traverse(
        self,
        start_id: str,
        max_depth: int = 10,
        node_type_filter: Optional[str] = None,
    ) -> List[GraphNode]:
        """深度优先遍历

        Returns:
            按 DFS 顺序排列的节点列表
        """
        result = []
        visited: Set[str] = set()

        def dfs(node_id: str, depth: int):
            if node_id in visited or depth > max_depth:
                return

            visited.add(node_id)

            node = self._get_node(node_id)
            if node:
                if node_type_filter is None or node.type == node_type_filter:
                    result.append(node)

            if depth < max_depth:
                neighbor_ids = self._get_neighbor_ids(node_id, "both")
                for neighbor_id in neighbor_ids:
                    if neighbor_id not in visited:
                        dfs(neighbor_id, depth + 1)

        dfs(start_id, 0)
        return result

    def shortest_path(
        self,
        start_id: str,
        end_id: str,
        max_length: int = 10,
    ) -> Optional[PathResult]:
        """Dijkstra 最短路径算法

        Returns:
            最短路径，如果不存在则返回 None
        """
        if start_id == end_id:
            return PathResult(path=[start_id], edges=[], length=0)

        distances: Dict[str, float] = {start_id: 0}
        previous: Dict[str, Tuple[str, Optional[str]]] = {}  # node_id -> (prev_node_id, edge_id)
        pq = [(0, start_id)]
        visited: Set[str] = set()

        while pq:
            current_dist, current_id = heapq.heappop(pq)

            if current_id in visited:
                continue

            visited.add(current_id)

            if current_id == end_id:
                break

            if current_dist > max_length:
                continue

            edges = self._get_edges_for_node(current_id, "outgoing")
            for edge in edges:
                neighbor_id = edge.target_id
                weight = 1.0  # 可以根据边属性调整权重

                new_dist = current_dist + weight
                if neighbor_id not in distances or new_dist < distances[neighbor_id]:
                    distances[neighbor_id] = new_dist
                    previous[neighbor_id] = (current_id, edge.id)
                    heapq.heappush(pq, (new_dist, neighbor_id))

        if end_id not in previous and end_id != start_id:
            return None

        path = []
        edges = []
        current = end_id

        while current != start_id:
            path.append(current)
            if current in previous:
                prev_node, edge_id = previous[current]
                path.append(prev_node)
                if edge_id:
                    edge = self.get_edge(edge_id)
                    if edge:
                        edges.append(edge)
                current = prev_node
            else:
                break

        path.append(start_id)
        path.reverse()
        edges.reverse()

        return PathResult(
            path=path,
            edges=edges,
            length=len(path) - 1
        )

    def all_paths(
        self,
        start_id: str,
        end_id: str,
        max_length: int = 5,
    ) -> List[PathResult]:
        """找出所有简单路径（限制最大长度）

        Returns:
            所有路径列表
        """
        results = []

        def dfs(current: str, path: List[str], edges: List[GraphEdge], depth: int):
            if current == end_id:
                results.append(PathResult(
                    path=path.copy(),
                    edges=edges.copy(),
                    length=len(path) - 1
                ))
                return

            if depth >= max_length:
                return

            neighbor_edges = self._get_edges_for_node(current, "outgoing")
            for edge in neighbor_edges:
                neighbor = edge.target_id
                if neighbor not in path:
                    path.append(neighbor)
                    edges.append(edge)
                    dfs(neighbor, path, edges, depth + 1)
                    path.pop()
                    edges.pop()

        dfs(start_id, [start_id], [], 0)
        return results

    def get_edge(self, edge_id: str) -> Optional[GraphEdge]:
        """获取边"""
        query = "SELECT * FROM edges WHERE id = ?"
        row = self.db.execute_one(query, (edge_id,))
        if row:
            return GraphEdge.from_dict(dict(row))
        return None

    def _get_node(self, node_id: str) -> Optional[GraphNode]:
        """获取节点"""
        query = "SELECT * FROM nodes WHERE id = ?"
        row = self.db.execute_one(query, (node_id,))
        if row:
            return GraphNode.from_dict(dict(row))
        return None

    def _get_neighbor_ids(self, node_id: str, direction: str = "both") -> List[str]:
        """获取邻居节点 ID"""
        if direction == "outgoing":
            query = "SELECT target_id FROM edges WHERE source_id = ?"
            rows = self.db.execute(query, (node_id,))
            return [row["target_id"] for row in rows]
        elif direction == "incoming":
            query = "SELECT source_id FROM edges WHERE target_id = ?"
            rows = self.db.execute(query, (node_id,))
            return [row["source_id"] for row in rows]
        else:  # both
            query = """
                SELECT target_id as neighbor_id FROM edges WHERE source_id = ?
                UNION
                SELECT source_id as neighbor_id FROM edges WHERE target_id = ?
            """
            rows = self.db.execute(query, (node_id, node_id))
            return [row["neighbor_id"] for row in rows]

    def _get_edges_for_node(self, node_id: str, direction: str = "both") -> List[GraphEdge]:
        """获取与节点相关的边"""
        if direction == "outgoing":
            query = "SELECT * FROM edges WHERE source_id = ?"
            rows = self.db.execute(query, (node_id,))
        elif direction == "incoming":
            query = "SELECT * FROM edges WHERE target_id = ?"
            rows = self.db.execute(query, (node_id,))
        else:  # both
            query = "SELECT * FROM edges WHERE source_id = ? OR target_id = ?"
            rows = self.db.execute(query, (node_id, node_id))

        return [GraphEdge.from_dict(dict(row)) for row in rows]

    def pagerank(
        self,
        damping: float = 0.85,
        max_iterations: int = 100,
        tolerance: float = 1e-6,
    ) -> Dict[str, float]:
        """PageRank 算法

        Args:
            damping: 阻尼系数，默认 0.85
            max_iterations: 最大迭代次数
            tolerance: 收敛阈值

        Returns:
            Dict[node_id, pagerank_score]
        """
        all_nodes = self.db.execute("SELECT id FROM nodes")
        node_ids = [row["id"] for row in all_nodes]
        n = len(node_ids)

        if n == 0:
            return {}

        inlinks: Dict[str, Set[str]] = {node_id: set() for node_id in node_ids}
        outlinks: Dict[str, int] = {node_id: 0 for node_id in node_ids}

        all_edges = self.db.execute("SELECT source_id, target_id FROM edges")
        for edge in all_edges:
            source, target = edge["source_id"], edge["target_id"]
            if source in inlinks and target in inlinks:
                inlinks[target].add(source)
                outlinks[source] += 1

        pagerank_scores = {node_id: 1.0 / n for node_id in node_ids}

        for iteration in range(max_iterations):
            new_scores = {}
            max_diff = 0.0

            for node_id in node_ids:
                rank_sum = 0.0
                for predecessor in inlinks[node_id]:
                    if outlinks[predecessor] > 0:
                        rank_sum += pagerank_scores[predecessor] / outlinks[predecessor]

                new_score = (1 - damping) / n + damping * rank_sum
                new_scores[node_id] = new_score
                max_diff = max(max_diff, abs(new_score - pagerank_scores[node_id]))

            pagerank_scores = new_scores

            if max_diff < tolerance:
                logger.debug(f"PageRank converged after {iteration + 1} iterations")
                break

        return pagerank_scores

    def get_important_nodes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最重要的节点

        Args:
            limit: 返回数量限制

        Returns:
            [{node, pagerank}, ...]
        """
        pagerank_scores = self.pagerank()

        sorted_nodes = sorted(
            pagerank_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        results = []
        for node_id, score in sorted_nodes[:limit]:
            node = self._get_node(node_id)
            if node:
                results.append({
                    "node": node,
                    "pagerank": score,
                })

        return results

    def community_detection(
        self,
        method: str = "lpa",
    ) -> Dict[int, List[str]]:
        """社区发现算法

        Args:
            method: 算法类型 ("lpa"=Label Propagation, "louvain"=简化Louvain)

        Returns:
            Dict[community_id, List[node_id]]
        """
        all_nodes = self.db.execute("SELECT id FROM nodes")
        node_ids = [row["id"] for row in all_nodes]

        if not node_ids:
            return {}

        if method == "lpa":
            return self._lpa_community_detection(node_ids)
        elif method == "louvain":
            return self._louvain_community_detection(node_ids)
        else:
            logger.warning(f"Unknown method {method}, using LPA")
            return self._lpa_community_detection(node_ids)

    def _lpa_community_detection(self, node_ids: List[str]) -> Dict[int, List[str]]:
        """Label Propagation Algorithm"""
        import random

        edges = self.db.execute("SELECT source_id, target_id FROM edges")
        neighbors: Dict[str, Set[str]] = {node_id: set() for node_id in node_ids}

        for edge in edges:
            source, target = edge["source_id"], edge["target_id"]
            if source in neighbors and target in neighbors:
                neighbors[source].add(target)
                neighbors[target].add(source)

        labels: Dict[str, int] = {node_id: i for i, node_id in enumerate(node_ids)}
        label_to_nodes: Dict[int, Set[str]] = {i: {node_id} for i, node_id in enumerate(node_ids)}

        max_iterations = 50
        for iteration in range(max_iterations):
            nodes_shuffled = node_ids.copy()
            random.shuffle(nodes_shuffled)
            changed = False

            for node_id in nodes_shuffled:
                if not neighbors[node_id]:
                    continue

                neighbor_labels = [labels[neighbor] for neighbor in neighbors[node_id]]
                if not neighbor_labels:
                    continue

                label_counts: Dict[int, int] = {}
                for label in neighbor_labels:
                    label_counts[label] = label_counts.get(label, 0) + 1

                max_count = max(label_counts.values())
                candidate_labels = [l for l, c in label_counts.items() if c == max_count]

                new_label = random.choice(candidate_labels) if len(candidate_labels) > 1 else candidate_labels[0]

                if new_label != labels[node_id]:
                    old_label = labels[node_id]
                    labels[node_id] = new_label

                    label_to_nodes[old_label].discard(node_id)
                    label_to_nodes[new_label].add(node_id)
                    if not label_to_nodes[old_label]:
                        del label_to_nodes[old_label]

                    changed = True

            if not changed:
                break

        return {i: list(node_set) for i, node_set in label_to_nodes.items()}

    def _louvain_community_detection(self, node_ids: List[str]) -> Dict[int, List[str]]:
        """Simplified Louvain-like algorithm based on modularity optimization"""
        edges = self.db.execute("SELECT source_id, target_id FROM edges")
        neighbors: Dict[str, Set[str]] = {node_id: set() for node_id in node_ids}

        for edge in edges:
            source, target = edge["source_id"], edge["target_id"]
            if source in neighbors and target in neighbors:
                neighbors[source].add(target)
                neighbors[target].add(source)

        labels: Dict[str, int] = {node_id: i for i, node_id in enumerate(node_ids)}
        communities: Dict[int, List[str]] = {i: [node_id] for i, node_id in enumerate(node_ids)}

        m = sum(len(neighbors[n]) for n in node_ids) / 2
        if m == 0:
            return communities

        def modularity(communities: Dict[int, List[str]]) -> float:
            q = 0.0
            for comm_nodes in communities.values():
                for i in comm_nodes:
                    for j in comm_nodes:
                        if j in neighbors[i]:
                            q += 1
            return q / (2 * m) if m > 0 else 0.0

        improved = True
        iteration = 0
        max_iterations = 20

        while improved and iteration < max_iterations:
            improved = False
            iteration += 1

            for node_id in node_ids:
                current_label = labels[node_id]
                current_community = communities[current_label]

                if len(current_community) <= 1:
                    continue

                neighbor_communities: Dict[int, Set[str]] = {}
                for neighbor in neighbors[node_id]:
                    neighbor_label = labels[neighbor]
                    if neighbor_label not in neighbor_communities:
                        neighbor_communities[neighbor_label] = set()
                    neighbor_communities[neighbor_label].add(neighbor)

                best_label = current_label
                best_q = modularity(communities)

                for comm_label, comm_nodes in neighbor_communities.items():
                    if comm_label == current_label:
                        continue

                    communities[comm_label].append(node_id)
                    communities[current_label].remove(node_id)

                    new_q = modularity(communities)
                    if new_q > best_q:
                        best_q = new_q
                        best_label = comm_label
                        improved = True
                    else:
                        communities[current_label].append(node_id)
                        communities[comm_label].remove(node_id)

                labels[node_id] = best_label
                if best_label != current_label:
                    communities[best_label] = communities.get(best_label, [])
                    if node_id not in communities[best_label]:
                        communities[best_label].append(node_id)
                    if node_id in communities[current_label]:
                        communities[current_label].remove(node_id)
                    if not communities[current_label]:
                        del communities[current_label]

        remapped: Dict[int, List[str]] = {}
        for i, (_, nodes) in enumerate(communities.items()):
            remapped[i] = nodes

        return remapped

    def get_community_stats(self) -> Dict[str, Any]:
        """获取社区统计信息

        Returns:
            {
                "num_communities": int,
                "avg_community_size": float,
                "largest_community_size": int,
                "smallest_community_size": int,
                "communities": Dict[community_id, List[node_id]]
            }
        """
        communities = self.community_detection()

        if not communities:
            return {
                "num_communities": 0,
                "avg_community_size": 0.0,
                "largest_community_size": 0,
                "smallest_community_size": 0,
                "communities": {},
            }

        sizes = [len(nodes) for nodes in communities.values()]

        return {
            "num_communities": len(communities),
            "avg_community_size": sum(sizes) / len(sizes),
            "largest_community_size": max(sizes),
            "smallest_community_size": min(sizes),
            "communities": communities,
        }
