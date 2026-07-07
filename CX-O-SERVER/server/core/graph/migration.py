"""
Neo4j 数据迁移工具
"""

import json
import logging
from typing import Optional, List, Dict, Any, Generator
from datetime import datetime

from server.core.graph.database import Database
from server.core.graph.models import GraphNode, GraphEdge, NodeCreate, EdgeCreate
from server.core.graph.nodes import NodeManager
from server.core.graph.edges import EdgeManager
from server.core.graph.config import GraphConfig
from server.core.graph.vectorizer import TextVectorizer
from server.core.graph.semantic_search import SemanticSearch

logger = logging.getLogger(__name__)


class Neo4jExporter:
    """Neo4j 数据导出器"""

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None

    def connect(self) -> bool:
        """连接 Neo4j"""
        try:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            return True
        except ImportError:
            logger.error("neo4j 驱动未安装: pip install neo4j")
            return False
        except Exception as e:
            logger.error(f"连接 Neo4j 失败: {e}")
            return False

    def close(self) -> None:
        """关闭连接"""
        if self._driver:
            self._driver.close()

    def export_nodes(
        self,
        labels: Optional[List[str]] = None,
        batch_size: int = 1000,
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """导出节点
        
        Args:
            labels: 要导出的节点标签列表，None 表示所有
            batch_size: 每批数量
            
        Yields:
            每批节点数据
        """
        if not self._driver:
            if not self.connect():
                return

        def parse_properties(props: Dict) -> Dict[str, Any]:
            result = {}
            for key, value in props.items():
                if isinstance(value, dict):
                    result[key] = json.dumps(value)
                elif hasattr(value, 'isoformat'):
                    result[key] = value.isoformat()
                else:
                    result[key] = value
            return result

        with self._driver.session() as session:
            if labels:
                query = """
                    MATCH (n)
                    WHERE any(label IN labels(n) WHERE label IN $labels)
                    RETURN n
                """
            else:
                query = "MATCH (n) RETURN n"

            result = session.run(query, labels=labels or [])

            batch = []
            for record in result:
                node = record["n"]
                node_data = {
                    "id": node.id,
                    "labels": list(node.labels),
                    "properties": parse_properties(dict(node)),
                }
                batch.append(node_data)

                if len(batch) >= batch_size:
                    yield batch
                    batch = []

            if batch:
                yield batch

    def export_relationships(
        self,
        types: Optional[List[str]] = None,
        batch_size: int = 1000,
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """导出关系
        
        Args:
            types: 要导出的关系类型列表，None 表示所有
            batch_size: 每批数量
            
        Yields:
            每批关系数据
        """
        if not self._driver:
            if not self.connect():
                return

        with self._driver.session() as session:
            if types:
                query = """
                    MATCH (a)-[r]->(b)
                    WHERE type(r) IN $types
                    RETURN a, r, b
                """
            else:
                query = "MATCH (a)-[r]->(b) RETURN a, r, b"

            result = session.run(query, types=types or [])

            batch = []
            for record in result:
                rel = record["r"]
                rel_data = {
                    "id": rel.id,
                    "type": rel.type,
                    "start_node_id": record["a"].id,
                    "end_node_id": record["b"].id,
                    "properties": dict(rel),
                }
                batch.append(rel_data)

                if len(batch) >= batch_size:
                    yield batch
                    batch = []

            if batch:
                yield batch

    def get_stats(self) -> Dict[str, int]:
        """获取数据库统计信息"""
        if not self._driver:
            if not self.connect():
                return {"nodes": 0, "relationships": 0}

        with self._driver.session() as session:
            node_count = session.run("MATCH (n) RETURN count(n) as cnt").single()["cnt"]
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) as cnt").single()["cnt"]

            return {
                "nodes": node_count,
                "relationships": rel_count,
            }


class Neo4jImporter:
    """Neo4j 数据导入器"""

    def __init__(
        self,
        db: Database,
        semantic: SemanticSearch,
        vectorizer: TextVectorizer,
        config: GraphConfig = None,
    ):
        self.db = db
        self.semantic = semantic
        self.vectorizer = vectorizer
        self.config = config or GraphConfig()
        self.node_manager = NodeManager(db, self.config)
        self.edge_manager = EdgeManager(db, self.config)
        self._node_id_mapping: Dict[str, str] = {}

    def migrate_nodes(
        self,
        nodes_data: List[Dict[str, Any]],
        batch_size: int = 100,
    ) -> int:
        """批量导入节点
        
        Args:
            nodes_data: 节点数据列表
            batch_size: 批处理大小
            
        Returns:
            导入的节点数量
        """
        count = 0

        for i in range(0, len(nodes_data), batch_size):
            batch = nodes_data[i:i + batch_size]
            node_creates = []

            for node_data in batch:
                old_id = node_data.get("id")
                labels = node_data.get("labels", [])
                properties = node_data.get("properties", {})

                node_type = labels[0] if labels else "Unknown"
                text_content = self._extract_text_content(properties)

                node_create = NodeCreate(
                    type=node_type,
                    properties=properties,
                    text_content=text_content,
                )
                node_creates.append(node_create)

                if old_id:
                    self._node_id_mapping[old_id] = None

            created_nodes = self.node_manager.batch_create(node_creates)

            for old_id, new_node in zip(
                [nd.get("id") for nd in batch if nd.get("id")],
                created_nodes
            ):
                if old_id in self._node_id_mapping:
                    self._node_id_mapping[old_id] = new_node.id

            for node in created_nodes:
                if node.text_content:
                    self.semantic.add_vector(
                        node_id=node.id,
                        text_content=node.text_content,
                        node_type=node.type,
                    )

            count += len(created_nodes)
            logger.info(f"已导入 {count}/{len(nodes_data)} 节点")

        return count

    def migrate_relationships(
        self,
        rels_data: List[Dict[str, Any]],
        batch_size: int = 100,
    ) -> int:
        """批量导入关系
        
        Args:
            rels_data: 关系数据列表
            batch_size: 批处理大小
            
        Returns:
            导入的关系数量
        """
        count = 0

        for i in range(0, len(rels_data), batch_size):
            batch = rels_data[i:i + batch_size]

            for rel_data in batch:
                old_start_id = rel_data.get("start_node_id")
                old_end_id = rel_data.get("end_node_id")

                start_id = self._node_id_mapping.get(old_start_id)
                end_id = self._node_id_mapping.get(old_end_id)

                if not start_id or not end_id:
                    logger.warning(
                        f"跳过关系 {rel_data.get('id')}，节点映射不存在"
                    )
                    continue

                edge_create = EdgeCreate(
                    source_id=start_id,
                    target_id=end_id,
                    relation_type=rel_data.get("type", "RELATED"),
                    properties=rel_data.get("properties", {}),
                )

                try:
                    self.edge_manager.create(edge_create)
                    count += 1
                except Exception as e:
                    logger.error(f"创建边失败: {e}")

            logger.info(f"已导入 {count} 关系")

        return count

    def migrate_from_exporter(
        self,
        exporter: Neo4jExporter,
        batch_size: int = 1000,
    ) -> Dict[str, int]:
        """从导出器迁移所有数据
        
        Returns:
            {"nodes": 节点数, "relationships": 关系数}
        """
        stats = {"nodes": 0, "relationships": 0}

        logger.info("开始迁移节点...")
        for batch in exporter.export_nodes(batch_size=batch_size):
            stats["nodes"] += self.migrate_nodes(batch, batch_size)

        logger.info("开始迁移关系...")
        for batch in exporter.export_relationships(batch_size=batch_size):
            stats["relationships"] += self.migrate_relationships(batch, batch_size)

        return stats

    def _extract_text_content(self, properties: Dict[str, Any]) -> str:
        """从属性中提取文本内容"""
        text_fields = ["name", "title", "description", "text", "content"]

        for field in text_fields:
            if field in properties:
                value = properties[field]
                if isinstance(value, str):
                    return value

        return json.dumps(properties, ensure_ascii=False)

    def clear_mapping(self) -> None:
        """清除节点 ID 映射"""
        self._node_id_mapping.clear()


class MigrationManager:
    """迁移管理器"""

    def __init__(self, config: GraphConfig = None):
        self.config = config or GraphConfig()

    def migrate_from_neo4j(
        self,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "password",
        batch_size: int = 1000,
    ) -> Dict[str, Any]:
        """执行完整的 Neo4j 迁移
        
        Returns:
            迁移统计信息
        """
        from server.core.graph.database import Database, get_database
        from server.core.graph.semantic_search import SemanticSearch
        from server.core.graph.vectorizer import TextVectorizer

        db = get_database(self.config)
        db.initialize()

        semantic = SemanticSearch(self.config)
        semantic.initialize()

        vectorizer = TextVectorizer(self.config.embedding)

        exporter = Neo4jExporter(neo4j_uri, neo4j_user, neo4j_password)
        importer = Neo4jImporter(db, semantic, vectorizer, self.config)

        try:
            stats = exporter.get_stats()
            logger.info(f"源数据库统计: {stats}")

            result = importer.migrate_from_exporter(exporter, batch_size)

            return {
                "status": "success",
                "imported_nodes": result["nodes"],
                "imported_relationships": result["relationships"],
            }
        except Exception as e:
            logger.error(f"迁移失败: {e}")
            return {
                "status": "error",
                "error": str(e),
            }
        finally:
            exporter.close()
            semantic.close()
