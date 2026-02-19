import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class SyncResult:
    total_checked: int = 0
    synced: int = 0
    removed: int = 0
    errors: int = 0
    details: List[str] = None


class ChromaVectorStore:
    """Chroma向量存储实现 - 支持Windows/Linux/macOS"""

    COLLECTION_NAME = "memory_vectors"

    def __init__(
        self,
        db_path: str = "data/chroma_db",
        vector_size: int = 768,
        collection_name: str = None,
        embedding_model=None,
        persistent: bool = True,
    ):
        self.db_path = db_path
        self.vector_size = vector_size
        self.collection_name = collection_name or self.COLLECTION_NAME
        self.embedding_model = embedding_model
        self.persistent = persistent

        self._client = None
        self._collection = None
        self._lock = threading.Lock()
        self._initialize_client()

    def _initialize_client(self):
        try:
            import chromadb

            os.environ["ANONYMIZED_TELEMETRY"] = "False"
            os.environ["CHROMA_TELEMETRY"] = "False"

            if self.persistent:
                os.makedirs(
                    os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else ".",
                    exist_ok=True,
                )
                self._client = chromadb.PersistentClient(path=self.db_path)
            else:
                self._client = chromadb.EphemeralClient()

            self._ensure_collection()
            mode = "持久化" if self.persistent else "内存"
            logger.info(f"Chroma向量存储初始化完成 ({mode}模式): {self.collection_name}")
        except ImportError:
            logger.warning("chromadb未安装，向量功能不可用")
            self._client = None
        except Exception as e:
            logger.error(f"Chroma初始化失败: {e}")
            self._client = None

    def _ensure_collection(self):
        if not self._client:
            return

        try:
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name, metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"Chroma集合已就绪: {self.collection_name}")
        except Exception as e:
            logger.error(f"检查/创建集合失败: {e}")

    def is_available(self) -> bool:
        return self._client is not None and self._collection is not None

    async def add_memory_vector(
        self, memory_id: int, content: str, embedding: List[float], metadata: Dict = None
    ) -> bool:
        if not self._collection:
            return False

        try:
            self._collection.add(
                ids=[str(memory_id)],
                embeddings=[embedding],
                documents=[content],
                metadatas=[
                    {
                        "memory_id": memory_id,
                        "created_at": datetime.now().isoformat(),
                        **(metadata or {}),
                    }
                ],
            )
            logger.debug(f"向量已添加: memory_id={memory_id}")
            return True
        except Exception as e:
            logger.error(f"添加向量失败: {e}")
            return False

    async def search_similar(
        self,
        query_embedding: List[float],
        limit: int = 10,
        memory_type: str = None,
        min_score: float = 0.5,
    ) -> List[Dict]:
        if not self._collection:
            return []

        try:
            where_filter = None
            if memory_type:
                where_filter = {"type": memory_type}

            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )

            if not results or not results.get("ids") or not results["ids"][0]:
                return []

            formatted_results = []
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results.get("distances") else 0
                similarity = 1 - distance

                if similarity < min_score:
                    continue

                formatted_results.append(
                    {
                        "id": int(doc_id),
                        "score": similarity,
                        "content": results["documents"][0][i] if results.get("documents") else "",
                        "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    }
                )

            return formatted_results
        except Exception as e:
            logger.error(f"搜索向量失败: {e}")
            return []

    async def delete_by_memory_id(self, memory_id: int) -> bool:
        if not self._collection:
            return False

        try:
            self._collection.delete(ids=[str(memory_id)])
            logger.debug(f"向量已删除: memory_id={memory_id}")
            return True
        except Exception as e:
            logger.error(f"删除向量失败: {e}")
            return False

    async def get_vector_by_id(self, memory_id: int) -> Optional[Dict]:
        if not self._collection:
            return None

        try:
            results = self._collection.get(
                ids=[str(memory_id)], include=["documents", "metadatas", "embeddings"]
            )

            if not results or not results.get("ids"):
                return None

            return {
                "id": int(results["ids"][0]),
                "content": results["documents"][0] if results.get("documents") else "",
                "metadata": results["metadatas"][0] if results.get("metadatas") else {},
                "embedding": results["embeddings"][0] if results.get("embeddings") else None,
            }
        except Exception as e:
            logger.error(f"获取向量失败: {e}")
            return None

    async def check_exists(self, memory_id: int) -> bool:
        if not self._collection:
            return False

        try:
            results = self._collection.get(ids=[str(memory_id)])
            return bool(results and results.get("ids"))
        except Exception as e:
            logger.error(f"检查向量存在失败: {e}")
            return False

    async def sync_with_sqlite(self, sqlite_manager, last_sync_time: str = None) -> SyncResult:
        result = SyncResult()

        if not self._collection or not sqlite_manager:
            return result

        try:
            if last_sync_time:
                logger.info(f"开始增量同步 (since {last_sync_time})...")
            else:
                logger.info("开始SQLite与Chroma全量数据同步...")

            memories = sqlite_manager.search_memories(
                memory_type=None, limit=10000, include_deleted=False
            )

            if last_sync_time:
                memories = [
                    m
                    for m in memories
                    if m.get("updated_at") and m.get("updated_at") > last_sync_time
                ]
                logger.info(f"增量同步: 筛选出 {len(memories)} 条需要同步的记忆")

            for memory in memories:
                memory_id = memory.get("id")
                content = memory.get("content", "")

                result.total_checked += 1

                exists = await self.check_exists(memory_id)

                if not exists and content:
                    if self.embedding_model:
                        embedding = await self.embedding_model.get_embedding(content)
                        if embedding:
                            success = await self.add_memory_vector(
                                memory_id=memory_id,
                                content=content,
                                embedding=embedding,
                                metadata={
                                    "type": memory.get("type"),
                                    "importance": memory.get("importance"),
                                },
                            )
                            if success:
                                result.synced += 1
                            else:
                                result.errors += 1
                        else:
                            result.errors += 1
                    else:
                        result.errors += 1
                        if result.details is None:
                            result.details = []
                        result.details.append(f"无法生成嵌入: memory_id={memory_id}")
                elif exists and content:
                    existing = await self.get_vector_by_id(memory_id)
                    if existing and existing.get("content") != content:
                        if self.embedding_model:
                            embedding = await self.embedding_model.get_embedding(content)
                            if embedding:
                                await self.delete_by_memory_id(memory_id)
                                success = await self.add_memory_vector(
                                    memory_id=memory_id,
                                    content=content,
                                    embedding=embedding,
                                    metadata={
                                        "type": memory.get("type"),
                                        "importance": memory.get("importance"),
                                    },
                                )
                                if success:
                                    result.synced += 1
                                else:
                                    result.errors += 1

            logger.info(
                f"同步完成: checked={result.total_checked}, synced={result.synced}, errors={result.errors}"
            )
            return result
        except Exception as e:
            logger.error(f"同步失败: {e}")
            result.errors += 1
            return result

    def get_collection_info(self) -> Dict:
        if not self._collection:
            return {"status": "unavailable"}

        try:
            count = self._collection.count()
            return {
                "status": "available",
                "name": self.collection_name,
                "count": count,
                "db_path": self.db_path,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def clear_collection(self) -> bool:
        if not self._client:
            return False

        try:
            self._client.delete_collection(name=self.collection_name)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name, metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"集合已清空: {self.collection_name}")
            return True
        except Exception as e:
            logger.error(f"清空集合失败: {e}")
            return False

    def close(self):
        self._client = None
        self._collection = None
        logger.info("Chroma连接已关闭")
