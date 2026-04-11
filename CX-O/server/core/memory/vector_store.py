from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class QdrantVectorStore:
    COLLECTION_NAME = "memory_vectors"

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = None,
        vector_size: int = 768,
        embedding_model=None,
    ):
        self.host = host
        self.port = port
        self.collection_name = collection_name or self.COLLECTION_NAME
        self.vector_size = vector_size
        self.embedding_model = embedding_model

        self._client = None
        self._initialize_client()

    def _initialize_client(self):
        try:
            self._client = QdrantClient(host=self.host, port=self.port)
            self._ensure_collection()
            logger.info(f"Qdrant向量存储初始化完成: {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Qdrant初始化失败: {e}")
            self._client = None

    def _ensure_collection(self):
        if not self._client:
            return

        try:
            collections = self._client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.collection_name not in collection_names:
                self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
                )
                logger.info(f"创建Qdrant集合: {self.collection_name}")
        except Exception as e:
            logger.error(f"检查/创建集合失败: {e}")

    def is_available(self) -> bool:
        if not self._client:
            return False
        try:
            self._client.get_collections()
            return True
        except Exception:
            return False

    async def add_memory_vector(self, memory_id: int, content: str, embedding, metadata: dict = None) -> bool:
        if not self._client:
            return False

        try:
            self._client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=memory_id,
                        vector=embedding,
                        payload={
                            "content": content,
                            "memory_id": memory_id,
                            "metadata": metadata or {},
                        },
                    )
                ],
            )
            logger.debug(f"向量已添加: memory_id={memory_id}")
            return True
        except Exception as e:
            logger.error(f"添加向量失败: {e}")
            return False

    async def search_similar(
        self, query_embedding, limit: int = 10, memory_type: str = None, min_score: float = 0.5
    ) -> list:
        if not self._client:
            return []

        try:
            results = self._client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=limit,
            )

            filtered = []
            for result in results:
                if result.score >= min_score:
                    filtered.append(
                        {
                            "id": result.id,
                            "score": result.score,
                            "content": result.payload.get("content"),
                            "metadata": result.payload.get("metadata"),
                        }
                    )

            return filtered
        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            return []

    async def delete_by_memory_id(self, memory_id: int) -> bool:
        if not self._client:
            return False

        try:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[memory_id]),
            )
            return True
        except Exception as e:
            logger.error(f"删除向量失败: {e}")
            return False

    def get_collection_info(self) -> dict:
        if not self._client:
            return {"error": "客户端不可用"}

        try:
            info = self._client.get_collection(collection_name=self.collection_name)
            return {
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": str(info.status),
            }
        except Exception as e:
            return {"error": str(e)}

    def clear_collection(self) -> bool:
        if not self._client:
            return False

        try:
            self._client.delete_collection(collection_name=self.collection_name)
            self._ensure_collection()
            logger.info(f"集合已清空: {self.collection_name}")
            return True
        except Exception as e:
            logger.error(f"清空集合失败: {e}")
            return False

    def close(self):
        if self._client:
            try:
                self._client.close()
            except Exception as e:
                logger.warning(f"关闭Qdrant客户端失败: {e}")