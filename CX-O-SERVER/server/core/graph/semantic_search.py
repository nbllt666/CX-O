"""
语义检索
"""

import logging
from typing import Optional, List, Callable
from urllib.parse import urlparse
import numpy as np

from server.core.graph.config import GraphConfig, get_graph_config
from server.core.graph.vectorizer import get_vectorizer
from server.core.graph.models import GraphNode, SemanticSearchResult

logger = logging.getLogger(__name__)


class SemanticSearch:
    """语义搜索"""

    def __init__(self, config: GraphConfig = None):
        self.config = config or get_graph_config()
        self._client = None
        self._vectorizer = get_vectorizer()
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return

        try:
            import weaviate
            from weaviate.classes.init import AdditionalConfig, Timeout

            parsed = urlparse(self.config.weaviate.url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8090

            headers = {}
            if self.config.weaviate.api_key:
                headers["X-OpenAI-Api-Key"] = self.config.weaviate.api_key

            self._client = weaviate.connect_to_local(
                host=host,
                port=port,
                grpc_port=self.config.weaviate.grpc_port,
                headers=headers,
                additional_config=AdditionalConfig(
                    timeout=Timeout(init=2, query=3, insert=120)
                ),
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
        if not self._client:
            return

        try:
            from weaviate.classes.config import Configure, DataType, Property

            if not self._client.collections.exists("GraphNode"):
                self._client.collections.create(
                    name="GraphNode",
                    description="图数据库节点向量索引",
                    vectorizer_config=Configure.Vectorizer.none(),
                    properties=[
                        Property(name="node_id", data_type=DataType.TEXT),
                        Property(name="node_type", data_type=DataType.TEXT),
                        Property(name="text_content", data_type=DataType.TEXT),
                        Property(name="agent_id", data_type=DataType.TEXT),
                    ],
                )
                logger.info("创建 Weaviate collection: GraphNode")
        except Exception as e:
            logger.warning(f"创建 collection 失败: {e}")

    def add_vector(
        self,
        node_id: str,
        text_content: str,
        node_type: str,
        vector: Optional[np.ndarray] = None,
        agent_id: str = "default",
    ) -> str:
        if vector is None:
            vector = self._vectorizer.encode(text_content)

        if self._client:
            try:
                collection = self._client.collections.get("GraphNode")
                uuid = collection.data.insert(
                    properties={
                        "node_id": node_id,
                        "node_type": node_type,
                        "text_content": text_content,
                        "agent_id": agent_id,
                    },
                    vector=vector.tolist(),
                )
                return str(uuid)
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
        agent_id: str = "default",
    ) -> List[SemanticSearchResult]:
        if not self._initialized:
            self.initialize()

        results = []

        if self._client:
            try:
                from weaviate.classes.query import Filter

                query_vector = self._vectorizer.encode(query)
                collection = self._client.collections.get("GraphNode")

                filter_conditions = []
                if node_type:
                    filter_conditions.append(Filter.by_property("node_type").equal(node_type))
                if agent_id and agent_id != "default":
                    filter_conditions.append(Filter.by_property("agent_id").equal(agent_id))

                filters = None
                if len(filter_conditions) == 1:
                    filters = filter_conditions[0]
                elif len(filter_conditions) > 1:
                    filters = Filter.all_of(filter_conditions)

                result = collection.query.near_vector(
                    near_vector=query_vector.tolist(),
                    limit=limit,
                    return_properties=["node_id", "node_type", "text_content", "agent_id"],
                    return_metadata=["certainty"],
                    filters=filters,
                )

                for obj in result.objects:
                    score = obj.metadata.certainty or 0.0
                    props = obj.properties or {}
                    node = GraphNode(
                        id=props.get("node_id", ""),
                        type=props.get("node_type", ""),
                        text_content=props.get("text_content"),
                    )
                    results.append(SemanticSearchResult(
                        node=node,
                        score=score,
                    ))

            except Exception as e:
                logger.error(f"语义搜索失败: {e}")
                results = []

        if not results:
            results = self._fallback_search(query, node_type, limit, node_filter, agent_id)

        return results

    def _fallback_search(
        self,
        query: str,
        node_type: Optional[str],
        limit: int,
        node_filter: Optional[Callable],
        agent_id: str = "default",
    ) -> List[SemanticSearchResult]:
        query_words = set(query.lower().split())
        results = []

        from server.core.graph.database import get_database
        db = get_database(self.config)

        sql = "SELECT * FROM nodes WHERE text_content IS NOT NULL"
        params = []
        if node_type:
            sql += " AND type = ?"
            params.append(node_type)
        if agent_id and agent_id != "default":
            sql += " AND agent_id = ?"
            params.append(agent_id)

        rows = db.execute(sql, tuple(params))

        for row in rows:
            node = GraphNode.from_dict(dict(row))
            if node_filter and not node_filter(node.id):
                continue

            text_words = set(node.text_content.lower().split())
            score = len(query_words & text_words) / max(len(query_words), 1)

            if score > 0:
                results.append(SemanticSearchResult(
                    node=node,
                    score=score,
                ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    def delete_vector(self, node_id: str) -> bool:
        if self._client:
            try:
                from weaviate.classes.query import Filter
                collection = self._client.collections.get("GraphNode")
                collection.data.delete_many(
                    where=Filter.by_property("node_id").equal(node_id)
                )
                return True
            except Exception as e:
                logger.error(f"删除向量失败: {e}")
        return False

    def health_check(self) -> bool:
        if not self._client:
            return False
        try:
            return self._client.is_ready()
        except Exception as e:
            logger.error(f"Weaviate 健康检查失败: {e}")
            return False

    def encode_batch(self, texts: List[str]) -> np.ndarray:
        return self._vectorizer.encode_batch(texts)

    def compute_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        if len(vec1) != len(vec2):
            return 0.0
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(dot_product / (norm1 * norm2))

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
        self._initialized = False
