"""
边 CRUD 操作
"""

import json
import logging
import re
from typing import Optional, List, Dict, Any

from server.core.graph.database import Database
from server.core.graph.models import GraphEdge, EdgeCreate, EdgeUpdate, SearchResult
from server.core.graph.config import GraphConfig

logger = logging.getLogger(__name__)


class EdgeManager:
    """边管理器"""

    def __init__(self, db: Database, config: GraphConfig):
        self.db = db
        self.config = config

    def create(self, edge_data: EdgeCreate, agent_id: str = "default") -> GraphEdge:
        if not self._node_exists(edge_data.source_id, agent_id):
            raise ValueError(f"源节点不存在: {edge_data.source_id}")
        if not self._node_exists(edge_data.target_id, agent_id):
            raise ValueError(f"目标节点不存在: {edge_data.target_id}")

        edge = GraphEdge.create(
            source_id=edge_data.source_id,
            target_id=edge_data.target_id,
            relation_type=edge_data.relation_type,
            properties=edge_data.properties,
            text_content=edge_data.text_content,
            agent_id=agent_id,
        )

        query = """
            INSERT INTO edges (id, source_id, target_id, relation_type, properties, text_content, vector_id, created_at, agent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.db.execute_modify(
            query,
            (
                edge.id,
                edge.source_id,
                edge.target_id,
                edge.relation_type,
                json.dumps(edge.properties),
                edge.text_content,
                edge.vector_id,
                edge.created_at.isoformat(),
                edge.agent_id,
            ),
        )

        logger.info(f"创建边: {edge.id} ({edge.source_id} -> {edge.target_id}, agent_id={agent_id})")
        return edge

    def get(self, edge_id: str, agent_id: str = "default") -> Optional[GraphEdge]:
        query = "SELECT * FROM edges WHERE id = ? AND agent_id = ?"
        row = self.db.execute_one(query, (edge_id, agent_id))
        if row:
            return GraphEdge.from_dict(dict(row))
        return None

    def update(self, edge_id: str, update_data: EdgeUpdate, agent_id: str = "default") -> Optional[GraphEdge]:
        edge = self.get(edge_id, agent_id)
        if not edge:
            return None

        if update_data.relation_type is not None:
            edge.relation_type = update_data.relation_type
        if update_data.properties is not None:
            edge.properties.update(update_data.properties)
        if update_data.text_content is not None:
            edge.text_content = update_data.text_content

        query = """
            UPDATE edges
            SET relation_type = ?, properties = ?, text_content = ?
            WHERE id = ? AND agent_id = ?
        """
        self.db.execute_modify(
            query,
            (
                edge.relation_type,
                json.dumps(edge.properties),
                edge.text_content,
                edge_id,
                agent_id,
            ),
        )

        logger.info(f"更新边: {edge_id}")
        return edge

    def delete(self, edge_id: str, agent_id: str = "default") -> bool:
        rowcount = self.db.execute_modify("DELETE FROM edges WHERE id = ? AND agent_id = ?", (edge_id, agent_id))
        logger.info(f"删除边: {edge_id}")
        return rowcount > 0

    def list(
        self,
        relation_type: Optional[str] = None,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        agent_id: str = "default",
    ) -> SearchResult:
        conditions = ["agent_id = ?"]
        params = [agent_id]

        if relation_type:
            conditions.append("relation_type = ?")
            params.append(relation_type)
        if source_id:
            conditions.append("source_id = ?")
            params.append(source_id)
        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)

        where_clause = " AND ".join(conditions)

        count_query = f"SELECT COUNT(*) as cnt FROM edges WHERE {where_clause}"
        result = self.db.execute_one(count_query, tuple(params))
        total = result["cnt"] if result else 0

        query = f"""
            SELECT * FROM edges
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        rows = self.db.execute(query, tuple(params))

        edges = [GraphEdge.from_dict(dict(row)) for row in rows]
        return SearchResult(items=edges, total=total, offset=offset, limit=limit)

    def get_outgoing(self, node_id: str, relation_type: Optional[str] = None, agent_id: str = "default") -> List[GraphEdge]:
        if relation_type:
            query = "SELECT * FROM edges WHERE source_id = ? AND relation_type = ? AND agent_id = ?"
            rows = self.db.execute(query, (node_id, relation_type, agent_id))
        else:
            query = "SELECT * FROM edges WHERE source_id = ? AND agent_id = ?"
            rows = self.db.execute(query, (node_id, agent_id))

        return [GraphEdge.from_dict(dict(row)) for row in rows]

    def get_incoming(self, node_id: str, relation_type: Optional[str] = None, agent_id: str = "default") -> List[GraphEdge]:
        if relation_type:
            query = "SELECT * FROM edges WHERE target_id = ? AND relation_type = ? AND agent_id = ?"
            rows = self.db.execute(query, (node_id, relation_type, agent_id))
        else:
            query = "SELECT * FROM edges WHERE target_id = ? AND agent_id = ?"
            rows = self.db.execute(query, (node_id, agent_id))

        return [GraphEdge.from_dict(dict(row)) for row in rows]

    def search(
        self,
        relation_type: Optional[str] = None,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        properties_filter: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
        agent_id: str = "default",
    ) -> SearchResult:
        conditions = ["agent_id = ?"]
        params = [agent_id]

        if relation_type:
            conditions.append("relation_type = ?")
            params.append(relation_type)
        if source_id:
            conditions.append("source_id = ?")
            params.append(source_id)
        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)

        if properties_filter:
            for key, value in properties_filter.items():
                if not re.match(r'^[a-zA-Z0-9_]+$', key):
                    continue
                conditions.append(f"json_extract(properties, '$.{key}') = ?")
                params.append(json.dumps(value))

        where_clause = " AND ".join(conditions)

        count_query = f"SELECT COUNT(*) as cnt FROM edges WHERE {where_clause}"
        result = self.db.execute_one(count_query, tuple(params))
        total = result["cnt"] if result else 0

        query = f"""
            SELECT * FROM edges
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        rows = self.db.execute(query, tuple(params))

        edges = [GraphEdge.from_dict(dict(row)) for row in rows]
        return SearchResult(items=edges, total=total, offset=offset, limit=limit)

    def _node_exists(self, node_id: str, agent_id: str = "default") -> bool:
        query = "SELECT 1 FROM nodes WHERE id = ? AND agent_id = ?"
        return self.db.execute_one(query, (node_id, agent_id)) is not None

    def count(self, relation_type: Optional[str] = None, agent_id: str = "default") -> int:
        if relation_type:
            query = "SELECT COUNT(*) as cnt FROM edges WHERE relation_type = ? AND agent_id = ?"
            result = self.db.execute_one(query, (relation_type, agent_id))
        else:
            query = "SELECT COUNT(*) as cnt FROM edges WHERE agent_id = ?"
            result = self.db.execute_one(query, (agent_id,))
        return result["cnt"] if result else 0
