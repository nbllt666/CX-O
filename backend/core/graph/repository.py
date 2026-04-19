"""
图数据访问基类
"""

from typing import Optional, List

from backend.core.graph.database import Database
from backend.core.graph.models import GraphNode


class BaseGraphRepository:
    """图数据访问基类，提供通用的节点和边查询方法"""

    def __init__(self, db: Database):
        self.db = db

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """获取节点

        Args:
            node_id: 节点 ID

        Returns:
            节点对象，不存在时返回 None
        """
        query = "SELECT * FROM nodes WHERE id = ?"
        row = self.db.execute_one(query, (node_id,))
        if row:
            return GraphNode.from_dict(dict(row))
        return None

    def get_neighbor_ids(self, node_id: str, direction: str = "both") -> List[str]:
        """获取邻居节点 ID

        Args:
            node_id: 节点 ID
            direction: 方向 ("outgoing", "incoming", "both")

        Returns:
            邻居节点 ID 列表
        """
        if direction == "outgoing":
            query = "SELECT target_id FROM edges WHERE source_id = ?"
            rows = self.db.execute(query, (node_id,))
            return [row["target_id"] for row in rows]
        elif direction == "incoming":
            query = "SELECT source_id FROM edges WHERE target_id = ?"
            rows = self.db.execute(query, (node_id,))
            return [row["source_id"] for row in rows]
        else:
            query = """
                SELECT target_id as neighbor_id FROM edges WHERE source_id = ?
                UNION
                SELECT source_id as neighbor_id FROM edges WHERE target_id = ?
            """
            rows = self.db.execute(query, (node_id, node_id))
            return [row["neighbor_id"] for row in rows]
