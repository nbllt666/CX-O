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


def _validate_property_key(key: str) -> str:
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', key):
        raise ValueError(f"Invalid property key: {key}")
    return key


class NodeManager:
    """节点管理器"""

    def __init__(self, db: Database, config: GraphConfig):
        self.db = db
        self.config = config

    def create(self, node_data: NodeCreate) -> GraphNode:
        """创建节点"""
        node = GraphNode.create(
            type=node_data.type,
            properties=node_data.properties,
            text_content=node_data.text_content,
        )

        query = """
            INSERT INTO nodes (id, type, properties, text_content, vector_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
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
            ),
        )

        logger.info(f"创建节点: {node.id} (type={node.type})")
        return node

    def get(self, node_id: str) -> Optional[GraphNode]:
        """获取单个节点"""
        query = "SELECT * FROM nodes WHERE id = ?"
        row = self.db.execute_one(query, (node_id,))
        if row:
            return GraphNode.from_dict(dict(row))
        return None

    def update(self, node_id: str, update_data: NodeUpdate) -> Optional[GraphNode]:
        """更新节点"""
        node = self.get(node_id)
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
            WHERE id = ?
        """
        self.db.execute_modify(
            query,
            (
                node.type,
                json.dumps(node.properties),
                node.text_content,
                node.updated_at.isoformat(),
                node_id,
            ),
        )

        logger.info(f"更新节点: {node_id}")
        return node

    def delete(self, node_id: str, cascade: bool = True) -> bool:
        """删除节点（可选级联删除边）"""
        if cascade:
            operations = [
                ("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id)),
                ("DELETE FROM nodes WHERE id = ?", (node_id,)),
            ]
            self.db.transaction(operations)
        else:
            self.db.execute_modify("DELETE FROM nodes WHERE id = ?", (node_id,))

        logger.info(f"删除节点: {node_id} (cascade={cascade})")
        return True

    def list(
        self,
        node_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchResult:
        """列出节点（支持分页）"""
        if node_type:
            count_query = "SELECT COUNT(*) as cnt FROM nodes WHERE type = ?"
            count_params = (node_type,)
            query = "SELECT * FROM nodes WHERE type = ? ORDER BY created_at DESC LIMIT ? OFFSET ?"
            query_params = (node_type, limit, offset)
        else:
            count_query = "SELECT COUNT(*) as cnt FROM nodes"
            count_params = ()
            query = "SELECT * FROM nodes ORDER BY created_at DESC LIMIT ? OFFSET ?"
            query_params = (limit, offset)

        # BUG-B-M13 修复: execute_one 查询失败时返回 None,
        # 原实现直接 ["cnt"] 索引会抛出 TypeError。
        result = self.db.execute_one(count_query, count_params)
        total = result["cnt"] if result else 0
        rows = self.db.execute(query, query_params)

        nodes = [GraphNode.from_dict(dict(row)) for row in rows]
        return SearchResult(items=nodes, total=total, offset=offset, limit=limit)

    def batch_create(self, nodes_data: List[NodeCreate]) -> List[GraphNode]:
        """批量创建节点"""
        nodes = []
        operations = []

        for node_data in nodes_data:
            node = GraphNode.create(
                type=node_data.type,
                properties=node_data.properties,
                text_content=node_data.text_content,
            )
            nodes.append(node)
            operations.append(
                (
                    """
                    INSERT INTO nodes (id, type, properties, text_content, vector_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node.id,
                        node.type,
                        json.dumps(node.properties),
                        node.text_content,
                        node.vector_id,
                        node.created_at.isoformat(),
                        node.updated_at.isoformat(),
                    ),
                )
            )

        self.db.transaction(operations)
        logger.info(f"批量创建节点: {len(nodes)} 个")
        return nodes

    def batch_delete(self, node_ids: List[str]) -> int:
        """批量删除节点"""
        operations = []
        for node_id in node_ids:
            operations.append(
                ("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))
            )
            operations.append(("DELETE FROM nodes WHERE id = ?", (node_id,)))

        self.db.transaction(operations)
        logger.info(f"批量删除节点: {len(node_ids)} 个")
        return len(node_ids)

    def search(
        self,
        node_type: Optional[str] = None,
        properties_filter: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchResult:
        """按类型和属性搜索节点"""
        conditions = []
        params = []

        if node_type:
            conditions.append("type = ?")
            params.append(node_type)

        if properties_filter:
            for key, value in properties_filter.items():
                _validate_property_key(key)
                conditions.append(f"json_extract(properties, '$.{key}') = ?")
                # BUG-B-M12 修复: json_extract 返回带类型的值(int/bool 等),
                # 原实现统一用 json.dumps(value) 序列化为 JSON 字符串,
                # 导致非字符串类型(int/bool/float)永远无法匹配,过滤失效。
                # 修复: 仅对 dict/list 做 json.dumps,
                # 字符串和标量类型直接使用原始值进行参数化比较。
                if isinstance(value, (dict, list)):
                    params.append(json.dumps(value))
                else:
                    params.append(value)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

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

    def exists(self, node_id: str) -> bool:
        """检查节点是否存在"""
        query = "SELECT 1 FROM nodes WHERE id = ?"
        return self.db.execute_one(query, (node_id,)) is not None

    def count(self, node_type: Optional[str] = None) -> int:
        """统计节点数量"""
        if node_type:
            query = "SELECT COUNT(*) as cnt FROM nodes WHERE type = ?"
            result = self.db.execute_one(query, (node_type,))
        else:
            query = "SELECT COUNT(*) as cnt FROM nodes"
            result = self.db.execute_one(query)
        return result["cnt"] if result else 0
