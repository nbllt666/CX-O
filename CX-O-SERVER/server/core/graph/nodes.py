"""
节点 CRUD 操作
"""

import json
import logging
import re
from typing import Optional, List, Dict, Any

from server.core.graph.database import Database
from server.core.graph.models import GraphNode, NodeCreate, NodeUpdate, SearchResult
from server.core.graph.config import GraphConfig

logger = logging.getLogger(__name__)


class NodeManager:
    """节点管理器"""

    def __init__(self, db: Database, config: GraphConfig):
        self.db = db
        self.config = config

    def create(self, node_data: NodeCreate, agent_id: str = "default") -> GraphNode:
        node = GraphNode.create(
            type=node_data.type,
            properties=node_data.properties,
            text_content=node_data.text_content,
            agent_id=agent_id,
        )

        query = """
            INSERT INTO nodes (id, type, properties, text_content, vector_id, created_at, updated_at, agent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.db.execute_modify(
            query,
            (
                node.id,
                node.type,
                json.dumps(node.properties),
                node.text_content,
                node.vector_id,
                node.created_at.isoformat(),
                node.updated_at.isoformat(),
                node.agent_id,
            ),
        )

        logger.info(f"创建节点: {node.id} (type={node.type}, agent_id={agent_id})")
        return node

    def get(self, node_id: str, agent_id: str = "default") -> Optional[GraphNode]:
        query = "SELECT * FROM nodes WHERE id = ? AND agent_id = ?"
        row = self.db.execute_one(query, (node_id, agent_id))
        if row:
            return GraphNode.from_dict(dict(row))
        return None

    def update(self, node_id: str, update_data: NodeUpdate, agent_id: str = "default") -> Optional[GraphNode]:
        node = self.get(node_id, agent_id)
        if not node:
            return None

        if update_data.type is not None:
            node.type = update_data.type
        if update_data.properties is not None:
            node.properties.update(update_data.properties)
        if update_data.text_content is not None:
            node.text_content = update_data.text_content

        from datetime import datetime
        node.updated_at = datetime.now()

        query = """
            UPDATE nodes
            SET type = ?, properties = ?, text_content = ?, updated_at = ?
            WHERE id = ? AND agent_id = ?
        """
        self.db.execute_modify(
            query,
            (
                node.type,
                json.dumps(node.properties),
                node.text_content,
                node.updated_at.isoformat(),
                node_id,
                agent_id,
            ),
        )

        logger.info(f"更新节点: {node_id}")
        return node

    def delete(self, node_id: str, cascade: bool = True, agent_id: str = "default") -> bool:
        if cascade:
            self.db.execute_modify("DELETE FROM edges WHERE (source_id = ? OR target_id = ?) AND agent_id = ?", (node_id, node_id, agent_id))
            rowcount = self.db.execute_modify("DELETE FROM nodes WHERE id = ? AND agent_id = ?", (node_id, agent_id))
        else:
            rowcount = self.db.execute_modify("DELETE FROM nodes WHERE id = ? AND agent_id = ?", (node_id, agent_id))

        logger.info(f"删除节点: {node_id} (cascade={cascade})")
        return rowcount > 0

    def list(
        self,
        node_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        agent_id: str = "default",
    ) -> SearchResult:
        if node_type:
            count_query = "SELECT COUNT(*) as cnt FROM nodes WHERE type = ? AND agent_id = ?"
            count_params = (node_type, agent_id)
            query = "SELECT * FROM nodes WHERE type = ? AND agent_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?"
            query_params = (node_type, agent_id, limit, offset)
        else:
            count_query = "SELECT COUNT(*) as cnt FROM nodes WHERE agent_id = ?"
            count_params = (agent_id,)
            query = "SELECT * FROM nodes WHERE agent_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?"
            query_params = (agent_id, limit, offset)

        total = self.db.execute_one(count_query, count_params)
        total = total["cnt"] if total else 0
        rows = self.db.execute(query, query_params)

        nodes = [GraphNode.from_dict(dict(row)) for row in rows]
        return SearchResult(items=nodes, total=total, offset=offset, limit=limit)

    def batch_create(self, nodes_data: List[NodeCreate], agent_id: str = "default") -> List[GraphNode]:
        nodes = []
        operations = []

        for node_data in nodes_data:
            node_agent_id = node_data.agent_id or agent_id
            node = GraphNode.create(
                type=node_data.type,
                properties=node_data.properties,
                text_content=node_data.text_content,
                agent_id=node_agent_id,
            )
            nodes.append(node)
            operations.append(
                (
                    """
                    INSERT INTO nodes (id, type, properties, text_content, vector_id, created_at, updated_at, agent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node.id,
                        node.type,
                        json.dumps(node.properties),
                        node.text_content,
                        node.vector_id,
                        node.created_at.isoformat(),
                        node.updated_at.isoformat(),
                        node.agent_id,
                    ),
                )
            )

        self.db.transaction(operations)
        logger.info(f"批量创建节点: {len(nodes)} 个")
        return nodes

    def batch_delete(self, node_ids: List[str], agent_id: str = "default") -> int:
        operations = []
        for node_id in node_ids:
            operations.append(
                ("DELETE FROM edges WHERE (source_id = ? OR target_id = ?) AND agent_id = ?", (node_id, node_id, agent_id))
            )
            operations.append(("DELETE FROM nodes WHERE id = ? AND agent_id = ?", (node_id, agent_id)))

        self.db.transaction(operations)
        logger.info(f"批量删除节点: {len(node_ids)} 个")
        return len(node_ids)

    def search(
        self,
        node_type: Optional[str] = None,
        properties_filter: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
        agent_id: str = "default",
    ) -> SearchResult:
        conditions = ["agent_id = ?"]
        params = [agent_id]

        if node_type:
            conditions.append("type = ?")
            params.append(node_type)

        if properties_filter:
            for key, value in properties_filter.items():
                if not re.match(r'^[a-zA-Z0-9_]+$', key):
                    continue
                conditions.append(f"json_extract(properties, '$.{key}') = ?")
                params.append(json.dumps(value))

        where_clause = " AND ".join(conditions)

        count_query = f"SELECT COUNT(*) as cnt FROM nodes WHERE {where_clause}"
        total = self.db.execute_one(count_query, tuple(params))["cnt"]

        query = f"""
            SELECT * FROM nodes
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        rows = self.db.execute(query, tuple(params))

        nodes = [GraphNode.from_dict(dict(row)) for row in rows]
        return SearchResult(items=nodes, total=total, offset=offset, limit=limit)

    def exists(self, node_id: str, agent_id: str = "default") -> bool:
        query = "SELECT 1 FROM nodes WHERE id = ? AND agent_id = ?"
        return self.db.execute_one(query, (node_id, agent_id)) is not None

    def count(self, node_type: Optional[str] = None, agent_id: str = "default") -> int:
        if node_type:
            query = "SELECT COUNT(*) as cnt FROM nodes WHERE type = ? AND agent_id = ?"
            result = self.db.execute_one(query, (node_type, agent_id))
        else:
            query = "SELECT COUNT(*) as cnt FROM nodes WHERE agent_id = ?"
            result = self.db.execute_one(query, (agent_id,))
        return result["cnt"] if result else 0
        return result["cnt"] if result else 0
