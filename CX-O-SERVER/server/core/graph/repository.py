"""
图数据访问基类
"""

from typing import Optional, List

from server.core.graph.database import Database
from server.core.graph.models import GraphNode, GraphEdge


class BaseGraphRepository:
    """图数据访问基类，提供通用的节点和边查询方法"""

    def __init__(self, db: Database):
        self.db = db

    def get_node(self, node_id: str, agent_id: str = "default") -> Optional[GraphNode]:
        query = "SELECT * FROM nodes WHERE id = ? AND agent_id = ?"
        row = self.db.execute_one(query, (node_id, agent_id))
        if row:
            return GraphNode.from_dict(dict(row))
        return None

    def get_neighbor_ids(self, node_id: str, direction: str = "both", agent_id: str = "default") -> List[str]:
        if direction == "outgoing":
            query = "SELECT target_id FROM edges WHERE source_id = ? AND agent_id = ?"
            rows = self.db.execute(query, (node_id, agent_id))
            return [row["target_id"] for row in rows]
        elif direction == "incoming":
            query = "SELECT source_id FROM edges WHERE target_id = ? AND agent_id = ?"
            rows = self.db.execute(query, (node_id, agent_id))
            return [row["source_id"] for row in rows]
        else:
            query = """
                SELECT target_id as neighbor_id FROM edges WHERE source_id = ? AND agent_id = ?
                UNION
                SELECT source_id as neighbor_id FROM edges WHERE target_id = ? AND agent_id = ?
            """
            rows = self.db.execute(query, (node_id, agent_id, node_id, agent_id))
            return [row["neighbor_id"] for row in rows]

    def get_edge(self, edge_id: str, agent_id: str = "default") -> Optional[GraphEdge]:
        query = "SELECT * FROM edges WHERE id = ? AND agent_id = ?"
        row = self.db.execute_one(query, (edge_id, agent_id))
        if row:
            return GraphEdge.from_dict(dict(row))
        return None
