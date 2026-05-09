"""
边 CRUD 操作
"""

import json
import logging
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

    def create(self, edge_data: EdgeCreate) -> GraphEdge:
        """创建边"""
        # 验证源节点和目标节点存在
        if not self._node_exists(edge_data.source_id):
            raise ValueError(f"源节点不存在: {edge_data.source_id}")
        if not self._node_exists(edge_data.target_id):
            raise ValueError(f"目标节点不存在: {edge_data.target_id}")

        edge = GraphEdge.create(
            source_id=edge_data.source_id,
            target_id=edge_data.target_id,
            relation_type=edge_data.relation_type,
            properties=edge_data.properties,
            text_content=edge_data.text_content,
        )

        query = """
            INSERT INTO edges (id, source_id, target_id, relation_type, properties, text_content, vector_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )

        logger.info(f"创建边: {edge.id} ({edge.source_id} -> {edge.target_id})")
        return edge

    def get(self, edge_id: str) -> Optional[GraphEdge]:
        """获取单个边"""
        query = "SELECT * FROM edges WHERE id = ?"
        row = self.db.execute_one(query, (edge_id,))
        if row:
            return GraphEdge.from_dict(dict(row))
        return None

    def update(self, edge_id: str, update_data: EdgeUpdate) -> Optional[GraphEdge]:
        """更新边"""
        edge = self.get(edge_id)
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
            WHERE id = ?
        """
        self.db.execute_modify(
            query,
            (
                edge.relation_type,
                json.dumps(edge.properties),
                edge.text_content,
                edge_id,
            ),
        )

        logger.info(f"更新边: {edge_id}")
        return edge

    def delete(self, edge_id: str) -> bool:
        """删除边"""
        self.db.execute_modify("DELETE FROM edges WHERE id = ?", (edge_id,))
        logger.info(f"删除边: {edge_id}")
        return True

    def list(
        self,
        relation_type: Optional[str] = None,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchResult:
        """列出边（支持分页和过滤）"""
        conditions = []
        params = []

        if relation_type:
            conditions.append("relation_type = ?")
            params.append(relation_type)
        if source_id:
            conditions.append("source_id = ?")
            params.append(source_id)
        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        count_query = f"SELECT COUNT(*) as cnt FROM edges WHERE {where_clause}"
        total = self.db.execute_one(count_query, tuple(params))["cnt"]

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

    def get_outgoing(self, node_id: str, relation_type: Optional[str] = None) -> List[GraphEdge]:
        """获取从指定节点出发的所有边"""
        if relation_type:
            query = "SELECT * FROM edges WHERE source_id = ? AND relation_type = ?"
            rows = self.db.execute(query, (node_id, relation_type))
        else:
            query = "SELECT * FROM edges WHERE source_id = ?"
            rows = self.db.execute(query, (node_id,))

        return [GraphEdge.from_dict(dict(row)) for row in rows]

    def get_incoming(self, node_id: str, relation_type: Optional[str] = None) -> List[GraphEdge]:
        """获取指向指定节点的所有边"""
        if relation_type:
            query = "SELECT * FROM edges WHERE target_id = ? AND relation_type = ?"
            rows = self.db.execute(query, (node_id, relation_type))
        else:
            query = "SELECT * FROM edges WHERE target_id = ?"
            rows = self.db.execute(query, (node_id,))

        return [GraphEdge.from_dict(dict(row)) for row in rows]

    def search(
        self,
        relation_type: Optional[str] = None,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        properties_filter: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchResult:
        """搜索边"""
        conditions = []
        params = []

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
                conditions.append(f"json_extract(properties, '$.{key}') = ?")
                params.append(json.dumps(value))

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        count_query = f"SELECT COUNT(*) as cnt FROM edges WHERE {where_clause}"
        total = self.db.execute_one(count_query, tuple(params))["cnt"]

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

    def _node_exists(self, node_id: str) -> bool:
        """检查节点是否存在"""
        query = "SELECT 1 FROM nodes WHERE id = ?"
        return self.db.execute_one(query, (node_id,)) is not None

    def count(self, relation_type: Optional[str] = None) -> int:
        """统计边数量"""
        if relation_type:
            query = "SELECT COUNT(*) as cnt FROM edges WHERE relation_type = ?"
            result = self.db.execute_one(query, (relation_type,))
        else:
            query = "SELECT COUNT(*) as cnt FROM edges"
            result = self.db.execute_one(query)
        return result["cnt"] if result else 0
