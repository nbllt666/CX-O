"""Chroma 向量存储适配器——基于 Chroma 的向量读写与集合管理。"""
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from server.config import Settings
from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class SyncResult:
    """向量库与 SQLite 同步结果，统计检查总数、同步数、删除数与错误数及详情。"""
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
        """初始化 Chroma 客户端与向量集合，支持持久化或内存模式。"""
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
        """检查 Chroma 客户端与集合是否可用。"""
        return self._client is not None and self._collection is not None

    async def add_memory_vector(
        self, memory_id: int, content: str, embedding: List[float], metadata: Dict = None
    ) -> bool:
        """向集合添加一个记忆向量。"""
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
        min_score: float = None,
    ) -> List[Dict]:
        """按查询向量检索相似记忆，余弦距离归一化为相似度并按 min_score 过滤后返回结果列表。"""
        if min_score is None:
            min_score = Settings().config.limits.memory.vector_min_score
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
                # Chroma 使用 cosine 空间时，distance 是余弦距离
                # 范围 [0, 2]，需要归一化到 [0, 1]
                # 相似度 = (2 - distance) / 2
                similarity = (2 - distance) / 2

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
        """按记忆 ID 从集合删除向量。"""
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
        """按记忆 ID 获取向量条目，返回内容、元数据与嵌入向量，不存在返回 None。"""
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
        """检查指定记忆 ID 的向量是否已存在。"""
        if not self._collection:
            return False

        try:
            results = self._collection.get(ids=[str(memory_id)])
            return bool(results and results.get("ids"))
        except Exception as e:
            logger.error(f"检查向量存在失败: {e}")
            return False

    async def sync_with_sqlite(self, sqlite_manager, last_sync_time: str = None) -> SyncResult:
        """将 SQLite 记忆数据与向量库同步。"""
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
        """返回集合的可用状态、名称、向量数量与存储路径。"""
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
        """删除并重建当前向量集合以清空全部向量，成功返回 True。"""
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
        """关闭 Chroma 连接并释放客户端与集合引用。"""
        self._client = None
        self._collection = None
        logger.info("Chroma连接已关闭")
