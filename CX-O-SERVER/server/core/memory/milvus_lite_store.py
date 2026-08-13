"""Milvus Lite 向量存储适配器——基于 Milvus Lite 的向量读写与集合管理。"""
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


class MilvusLiteVectorStore:
    """基于 Milvus Lite 的向量存储实现，提供单文件数据库的向量读写、检索与集合管理。"""

    COLLECTION_NAME = "memory_vectors"

    def __init__(
        self,
        db_path: str = "data/milvus_lite.db",
        vector_size: int = 768,
        collection_name: str = None,
        embedding_model=None,
    ):
        """初始化 Milvus Lite 客户端与向量集合，按需创建集合并完成连接。"""
        self.db_path = db_path
        self.vector_size = vector_size
        self.collection_name = collection_name or self.COLLECTION_NAME
        self.embedding_model = embedding_model

        self._client = None
        self._collection = None
        self._lock = threading.Lock()
        self._initialize_client()

    def _initialize_client(self):
        try:
            from pymilvus import MilvusClient

            os.makedirs(
                os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else ".",
                exist_ok=True,
            )

            self._client = MilvusClient(self.db_path)
            self._ensure_collection()
            logger.info(f"Milvus Lite向量存储初始化完成: {self.db_path}")
        except ImportError:
            logger.warning("pymilvus未安装，向量功能不可用")
            self._client = None
        except Exception as e:
            logger.error(f"Milvus Lite初始化失败: {e}")
            self._client = None

    def _ensure_collection(self):
        if not self._client:
            return

        try:
            collections = self._client.list_collections()

            if self.collection_name not in collections:
                self._client.create_collection(
                    collection_name=self.collection_name,
                    dimension=self.vector_size,
                    metric_type="COSINE",
                )
                logger.info(f"创建Milvus Lite集合: {self.collection_name}")
        except Exception as e:
            logger.error(f"检查/创建集合失败: {e}")

    def is_available(self) -> bool:
        """检查 Milvus Lite 客户端是否可用。"""
        return self._client is not None

    async def add_memory_vector(
        self, memory_id: int, content: str, embedding: List[float], metadata: Dict = None
    ) -> bool:
        """向 Milvus 集合插入一条记忆向量记录，成功返回 True。"""
        if not self._client:
            return False

        try:
            data = [
                {
                    "id": memory_id,
                    "vector": embedding,
                    "content": content,
                    "memory_id": memory_id,
                    "created_at": datetime.now().isoformat(),
                    **(metadata or {}),
                }
            ]

            self._client.insert(collection_name=self.collection_name, data=data)
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
        """按查询向量检索相似记忆，将余弦距离归一化为相似度并按 min_score 过滤后返回。"""
        if min_score is None:
            min_score = Settings().config.limits.memory.vector_min_score
        if not self._client:
            return []

        try:
            results = self._client.search(
                collection_name=self.collection_name,
                data=[query_embedding],
                limit=limit,
                output_fields=["content", "memory_id", "created_at"],
            )

            filtered_results = []
            for result in results[0]:
                # Milvus 使用 COSINE 度量时，返回的是余弦距离 (1 - 余弦相似度)
                # distance 范围 [0, 2]，需要转换为相似度
                # 相似度 = 1 - distance，范围 [-1, 1]
                # 归一化到 [0, 1]: (1 - distance + 1) / 2 = (2 - distance) / 2
                cosine_distance = result["distance"]
                similarity_score = (2 - cosine_distance) / 2
                if similarity_score >= min_score:
                    filtered_results.append(
                        {
                            "memory_id": result["id"],
                            "score": similarity_score,
                            "content": result["entity"].get("content"),
                            "metadata": result["entity"],
                        }
                    )

            return filtered_results
        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            return []

    async def delete_by_memory_id(self, memory_id: int) -> bool:
        """按记忆 ID 从集合删除向量。"""
        if not self._client:
            return False

        try:
            self._client.delete(collection_name=self.collection_name, ids=[memory_id])
            return True
        except Exception as e:
            logger.error(f"删除向量失败: {e}")
            return False

    async def get_vector_by_id(self, memory_id: int) -> Optional[Dict]:
        """按记忆 ID 查询向量条目，返回内容与元数据，不存在返回 None。"""
        if not self._client:
            return None

        try:
            if not isinstance(memory_id, int):
                logger.warning(f"无效的memory_id类型: {type(memory_id)}, 期望int")
                return None

            results = self._client.query(
                collection_name=self.collection_name,
                filter=f"memory_id == {memory_id}",
                output_fields=["content", "memory_id", "created_at"],
            )

            if results:
                r = results[0]
                return {"memory_id": r["id"], "content": r.get("content"), "metadata": r}
            return None
        except Exception as e:
            logger.error(f"获取向量失败: {e}")
            return None

    async def check_exists(self, memory_id: int) -> bool:
        """检查指定记忆 ID 的向量是否已存在。"""
        result = await self.get_vector_by_id(memory_id)
        return result is not None

    async def sync_with_sqlite(self, sqlite_manager, last_sync_time: str = None) -> SyncResult:
        """将 SQLite 记忆数据增量或全量同步到 Milvus Lite，返回同步统计结果。"""
        if not self._client:
            return SyncResult(errors=1, details=["Milvus Lite不可用"])

        result = SyncResult(details=[])

        try:
            if last_sync_time:
                logger.info(f"开始增量同步 (since {last_sync_time})...")
            else:
                logger.info("开始SQLite与Milvus Lite全量数据同步...")

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

            milvus_ids = set()
            result.total_checked = len(memories)

            for memory in memories:
                memory_id = memory["id"]
                content = memory["content"]
                milvus_ids.add(memory_id)

                try:
                    existing = await self.get_vector_by_id(memory_id)

                    if existing is None:
                        logger.info(f"向量不存在，创建: memory_id={memory_id}")
                        if self.embedding_model:
                            embedding = await self.embedding_model.get_embedding(content)
                            await self.add_memory_vector(
                                memory_id=memory_id,
                                content=content,
                                embedding=embedding,
                                metadata=memory,
                            )
                            result.synced += 1
                            result.details.append(f"创建: {memory_id}")
                    elif existing.get("content") != content:
                        logger.info(f"内容不一致，更新: memory_id={memory_id}")
                        if self.embedding_model:
                            embedding = await self.embedding_model.get_embedding(content)
                            await self.delete_by_memory_id(memory_id)
                            await self.add_memory_vector(
                                memory_id=memory_id,
                                content=content,
                                embedding=embedding,
                                metadata=memory,
                            )
                            result.synced += 1
                            result.details.append(f"更新: {memory_id}")

                except Exception as e:
                    result.errors += 1
                    logger.error(f"同步记忆失败: {memory_id}, {e}")

            logger.info(
                f"同步完成: checked={result.total_checked}, synced={result.synced}, errors={result.errors}"
            )

        except Exception as e:
            result.errors += 1
            result.details.append(f"同步过程错误: {e}")
            logger.error(f"同步过程失败: {e}")

        return result

    def get_collection_info(self) -> Dict:
        """返回集合的行数、状态、名称与向量维度信息。"""
        if not self._client:
            return {"error": "Milvus Lite不可用"}

        try:
            info = self._client.get_collection_stats(collection_name=self.collection_name)
            return {
                "row_count": info.get("row_count", 0),
                "status": "active",
                "collection_name": self.collection_name,
                "dimension": self.vector_size,
            }
        except Exception as e:
            return {"error": str(e)}

    def clear_collection(self) -> bool:
        """清空并重建集合。"""
        if not self._client:
            return False

        try:
            self._client.drop_collection(collection_name=self.collection_name)
            self._ensure_collection()
            logger.info(f"集合已清空: {self.collection_name}")
            return True
        except Exception as e:
            logger.error(f"清空集合失败: {e}")
            return False

    def close(self):
        """关闭 Milvus Lite 客户端连接。"""
        if self._client:
            try:
                self._client.close()
            except Exception as e:
                logger.warning(f"关闭Milvus Lite客户端失败: {e}")
