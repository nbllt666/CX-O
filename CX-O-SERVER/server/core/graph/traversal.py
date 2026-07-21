"""
图遍历算法
"""

import heapq
import logging
from typing import Optional, List, Dict, Set, Tuple, Any
from collections import deque

from server.core.graph.database import Database
from server.core.graph.models import GraphNode, GraphEdge, PathResult
from server.core.graph.config import GraphConfig
from server.core.graph.repository import BaseGraphRepository

logger = logging.getLogger(__name__)


class TraversalManager(BaseGraphRepository):
    """图遍历管理器"""

    def __init__(self, db: Database, config: GraphConfig):
        super().__init__(db)
        self.config = config

    def get_neighbors(
        self,
        node_id: str,
        max_depth: int = 1,
        direction: str = "both",
        agent_id: str = "default",
    ) -> List[Tuple[GraphNode, List[GraphEdge]]]:
        result = []
        visited: Set[str] = set()
        queue = deque([(node_id, 0)])

        while queue:
            current_id, depth = queue.popleft()

            if current_id in visited or depth > max_depth:
                continue

            visited.add(current_id)

            if depth > 0:
                node = self.get_node(current_id, agent_id)
                if node:
                    edges = self._get_edges_for_node(current_id, direction, agent_id)
                    result.append((node, edges))

            if depth < max_depth:
                neighbor_ids = self.get_neighbor_ids(current_id, direction, agent_id)
                for neighbor_id in neighbor_ids:
                    if neighbor_id not in visited:
                        queue.append((neighbor_id, depth + 1))

        return result

    def bfs_traverse(
        self,
        start_id: str,
        max_depth: int = 10,
        node_type_filter: Optional[str] = None,
        agent_id: str = "default",
    ) -> List[GraphNode]:
        result = []
        visited: Set[str] = set()
        queue = deque([(start_id, 0)])

        while queue:
            current_id, depth = queue.popleft()

            if current_id in visited:
                continue

            visited.add(current_id)

            node = self.get_node(current_id, agent_id)
            if node:
                if node_type_filter is None or node.type == node_type_filter:
                    result.append(node)

            if depth < max_depth:
                neighbor_ids = self.get_neighbor_ids(current_id, "both", agent_id)
                for neighbor_id in neighbor_ids:
                    if neighbor_id not in visited:
                        queue.append((neighbor_id, depth + 1))

        return result

    def dfs_traverse(
        self,
        start_id: str,
        max_depth: int = 10,
        node_type_filter: Optional[str] = None,
        agent_id: str = "default",
    ) -> List[GraphNode]:
        result = []
        visited: Set[str] = set()

        def dfs(node_id: str, depth: int):
            if node_id in visited or depth > max_depth:
                return

            visited.add(node_id)

            node = self.get_node(node_id, agent_id)
            if node:
                if node_type_filter is None or node.type == node_type_filter:
                    result.append(node)

            if depth < max_depth:
                neighbor_ids = self.get_neighbor_ids(node_id, "both", agent_id)
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
        agent_id: str = "default",
    ) -> Optional[PathResult]:
        if start_id == end_id:
            return PathResult(path=[start_id], edges=[], length=0)

        distances: Dict[str, float] = {start_id: 0}
        previous: Dict[str, Tuple[str, Optional[str]]] = {}
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

            edges = self._get_edges_for_node(current_id, "outgoing", agent_id)
            for edge in edges:
                neighbor_id = edge.target_id
                weight = 1.0

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
                if edge_id:
                    edge = self.get_edge(edge_id, agent_id)
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
        agent_id: str = "default",
    ) -> List[PathResult]:
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

            neighbor_edges = self._get_edges_for_node(current, "outgoing", agent_id)
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

    def _get_edges_for_node(self, node_id: str, direction: str = "both", agent_id: str = "default") -> List[GraphEdge]:
        if direction == "outgoing":
            query = "SELECT * FROM edges WHERE source_id = ? AND agent_id = ?"
            rows = self.db.execute(query, (node_id, agent_id))
        elif direction == "incoming":
            query = "SELECT * FROM edges WHERE target_id = ? AND agent_id = ?"
            rows = self.db.execute(query, (node_id, agent_id))
        else:
            query = "SELECT * FROM edges WHERE (source_id = ? OR target_id = ?) AND agent_id = ?"
            rows = self.db.execute(query, (node_id, node_id, agent_id))

        return [GraphEdge.from_dict(dict(row)) for row in rows]

    def pagerank(
        self,
        damping: float = 0.85,
        max_iterations: int = 100,
        tolerance: float = 1e-6,
        agent_id: str = "default",
    ) -> Dict[str, float]:
        all_nodes = self.db.execute("SELECT id FROM nodes WHERE agent_id = ?", (agent_id,))
        node_ids = [row["id"] for row in all_nodes]
        n = len(node_ids)

        if n == 0:
            return {}

        inlinks: Dict[str, Set[str]] = {node_id: set() for node_id in node_ids}
        outlinks: Dict[str, int] = {node_id: 0 for node_id in node_ids}

        all_edges = self.db.execute("SELECT source_id, target_id FROM edges WHERE agent_id = ?", (agent_id,))
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

    def get_important_nodes(self, limit: int = 10, agent_id: str = "default") -> List[Dict[str, Any]]:
        pagerank_scores = self.pagerank(agent_id=agent_id)

        sorted_nodes = sorted(
            pagerank_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        results = []
        for node_id, score in sorted_nodes[:limit]:
            node = self.get_node(node_id, agent_id)
            if node:
                results.append({
                    "node": node,
                    "pagerank": score,
                })

        return results

    def community_detection(
        self,
        method: str = "lpa",
        agent_id: str = "default",
    ) -> Dict[int, List[str]]:
        all_nodes = self.db.execute("SELECT id FROM nodes WHERE agent_id = ?", (agent_id,))
        node_ids = [row["id"] for row in all_nodes]

        if not node_ids:
            return {}

        if method == "lpa":
            return self._lpa_community_detection(node_ids, agent_id)
        elif method == "louvain":
            return self._louvain_community_detection(node_ids, agent_id)
        else:
            logger.warning(f"Unknown method {method}, using LPA")
            return self._lpa_community_detection(node_ids, agent_id)

    def _lpa_community_detection(self, node_ids: List[str], agent_id: str = "default") -> Dict[int, List[str]]:
        import random

        edges = self.db.execute("SELECT source_id, target_id FROM edges WHERE agent_id = ?", (agent_id,))
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

    def _louvain_community_detection(self, node_ids: List[str], agent_id: str = "default") -> Dict[int, List[str]]:
        edges = self.db.execute("SELECT source_id, target_id FROM edges WHERE agent_id = ?", (agent_id,))
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
                in_edges = 0
                degree_sum = 0
                for i in comm_nodes:
                    degree_sum += len(neighbors[i])
                    for j in comm_nodes:
                        if j in neighbors[i]:
                            in_edges += 1
                q += (in_edges / (2 * m)) - (degree_sum / (2 * m)) ** 2
            return q

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

                    # Always revert to current_label so each candidate is
                    # evaluated from the same baseline (node in current_label)
                    communities[current_label].append(node_id)
                    communities[comm_label].remove(node_id)

                labels[node_id] = best_label
                if best_label != current_label:
                    communities[best_label].append(node_id)
                    communities[current_label].remove(node_id)
                    if not communities[current_label]:
                        del communities[current_label]

        remapped: Dict[int, List[str]] = {}
        for i, (_, nodes) in enumerate(communities.items()):
            remapped[i] = nodes

        return remapped

    def get_community_stats(self, agent_id: str = "default") -> Dict[str, Any]:
        communities = self.community_detection(agent_id=agent_id)

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
