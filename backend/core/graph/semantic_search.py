"""
语义检索
"""

import logging
from typing import Optional, List, Dict, Any, Callable
import numpy as np

from backend.core.graph.config import GraphConfig, get_graph_config
from backend.core.graph.vectorizer import get_vectorizer, TextVectorizer
from backend.core.graph.models import GraphNode, SemanticSearchResult

logger = logging.getLogger(__name__)


class SemanticSearch:
    """语义搜索"""

    def __init__(self, config: GraphConfig = None):
        self.config = config or get_graph_config()
        self._client = None
        self._vectorizer = get_vectorizer()
        self._initialized = False

    def initialize(self) -> None:
        """初始化语义搜索（连接 Weaviate）"""
        if self._initialized:
            return

        try:
            import weaviate
            self._client = weaviate.Client(
                url=self.config.weaviate.url,
                auth_client_secret=weaviate.AuthApiKey(self.config.weaviate.api_key)
                    if self.config.weaviate.api_key else None,
            )
            self._ensure_schema()
            self._initialized = True
            logger.info(f"语义搜索初始化完成: {self.config.weaviate.url}")
        except ImportError:
            logger.warning("weaviate-client 未安装，语义搜索将使用本地模式")
            self._client = None
        except Exception as e:
            logger.warning(f"连接 Weaviate 失败: {e}，使用本地模式")
            self._client = None

    def _ensure_schema(self) -> None:
        """确保 Weaviate schema 存在"""
        if not self._client:
            return

        schema = {
            "class": "GraphNode",
            "description": "图数据库节点向量索引",
            "vectorizer": "none",
            "vectorIndexConfig": {
                "efConstruction": self.config.weaviate.ef_construction,
                "maxConnections": self.config.weaviate.max_connections,
            },
            "properties": [
                {"name": "node_id", "dataType": ["string"]},
                {"name": "node_type", "dataType": ["string"]},
                {"name": "text_content", "dataType": ["text"]},
            ]
        }

        try:
            if not self._client.schema.exists("GraphNode"):
                self._client.schema.create_class(schema)
                logger.info("创建 Weaviate schema: GraphNode")
        except Exception as e:
            logger.warning(f"创建 schema 失败: {e}")

    def add_vector(
        self,
        node_id: str,
        text_content: str,
        node_type: str,
        vector: Optional[np.ndarray] = None,
    ) -> str:
        """添加向量到索引

        Returns:
            vector_id
        """
        if vector is None:
            vector = self._vectorizer.encode(text_content)

        if self._client:
            try:
                vector_id = f"{node_id}_vector"
                self._client.data_object.create(
                    class_name="GraphNode",
                    data_object={
                        "node_id": node_id,
                        "node_type": node_type,
                        "text_content": text_content,
                    },
                    vector=vector.tolist(),
                )
                return vector_id
            except Exception as e:
                logger.error(f"添加向量失败: {e}")
                return node_id
        else:
            return node_id

    def search(
        self,
        query: str,
        node_type: Optional[str] = None,
        limit: int = 10,
        node_filter: Optional[Callable[[str], bool]] = None,
    ) -> List[SemanticSearchResult]:
        """语义搜索

        Args:
            query: 查询文本
            node_type: 节点类型过滤
            limit: 返回数量
            node_filter: 自定义节点过滤器

        Returns:
            [(节点, 相似度分数), ...]
        """
        if not self._initialized:
            self.initialize()

        results = []

        if self._client:
            try:
                query_vector = self._vectorizer.encode(query)

                where_filter = None
                if node_type:
                    where_filter = {
                        "path": ["node_type"],
                        "operator": "Equal",
                        "valueString": node_type
                    }

                search = self._client.query.get(
                    "GraphNode",
                    ["node_id", "node_type", "text_content", "_additional {certainty}"]
                ).with_near_vector(
                    {"vector": query_vector.tolist()}
                ).with_limit(limit)

                if where_filter:
                    search = search.with_where(where_filter)

                response = search.do()
                nodes = response.get("data", {}).get("Get", {}).get("GraphNode", [])

                for item in nodes:
                    score = item.get("_additional", {}).get("certainty", 0.0)
                    results.append(SemanticSearchResult(
                        node_id=item["node_id"],
                        node_type=item["node_type"],
                        text_content=item["text_content"],
                        score=score,
                    ))

            except Exception as e:
                logger.error(f"语义搜索失败: {e}")
                results = []

        if not results:
            results = self._fallback_search(query, node_type, limit, node_filter)

        return results

    def _fallback_search(
        self,
        query: str,
        node_type: Optional[str],
        limit: int,
        node_filter: Optional[Callable],
    ) -> List[SemanticSearchResult]:
        """回退搜索模式（不使用 Weaviate）"""
        query_words = set(query.lower().split())
        results = []

        from backend.core.graph.database import get_database
        db = get_database(self.config)

        sql = "SELECT * FROM nodes WHERE text_content IS NOT NULL"
        params = []
        if node_type:
            sql += " AND type = ?"
            params.append(node_type)

        rows = db.execute(sql, tuple(params))

        for row in rows:
            node = GraphNode.from_dict(dict(row))
            if node_filter and not node_filter(node.id):
                continue

            text_words = set(node.text_content.lower().split())
            score = len(query_words & text_words) / max(len(query_words), 1)

            if score > 0:
                results.append(SemanticSearchResult(
                    node_id=node.id,
                    node_type=node.type,
                    text_content=node.text_content,
                    score=score,
                ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    def delete_vector(self, node_id: str) -> bool:
        """删除向量"""
        if self._client:
            try:
                self._client.data_object.delete(
                    class_name="GraphNode",
                    where={"path": ["node_id"], "operator": "Equal", "valueString": node_id}
                )
                return True
            except Exception as e:
                logger.error(f"删除向量失败: {e}")
        return True

    def health_check(self) -> bool:
        """健康检查"""
        if not self._client:
            return True
        try:
            self._client.schema.get()
            return True
        except Exception as e:
            logger.error(f"Weaviate 健康检查失败: {e}")
            return False

    def encode_batch(self, texts: List[str]) -> np.ndarray:
        """批量编码文本为向量

        Args:
            texts: 文本列表

        Returns:
            向量数组
        """
        return self._vectorizer.encode_batch(texts)

    def compute_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """计算两个向量的余弦相似度

        Args:
            vec1: 第一个向量
            vec2: 第二个向量

        Returns:
            余弦相似度 (0-1)
        """
        if len(vec1) != len(vec2):
            return 0.0
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(dot_product / (norm1 * norm2))

    def close(self) -> None:
        """关闭连接"""
        if self._client:
            self._client = None
        self._vectorizer.close()
        self._initialized = False