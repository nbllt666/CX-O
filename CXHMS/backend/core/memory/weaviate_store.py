"""
Weaviate 向量存储实现
支持 Embedded Weaviate 和普通 Weaviate 两种模式
"""

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

if TYPE_CHECKING:
    from .vector_store import SyncResult

logger = get_contextual_logger(__name__)


@dataclass
class WeaviateConfig:
    """Weaviate 配置"""

    host: str = "localhost"
    port: int = 8080
    grpc_port: int = 50051
    embedded: bool = False
    vector_size: int = 768
    schema_class: str = "CXHMSMemory"
    api_key: Optional[str] = None


class WeaviateVectorStore:
    """Weaviate 向量存储实现"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        grpc_port: int = 50051,
        embedded: bool = False,
        vector_size: int = 768,
        schema_class: str = "CXHMSMemory",
        embedding_model=None,
        api_key: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.grpc_port = grpc_port
        self.embedded = embedded
        self.vector_size = vector_size
        self.schema_class = schema_class
        self.embedding_model = embedding_model
        self.api_key = api_key

        self._client = None
        self._lock = threading.Lock()
        self._initialize_client()

    def _initialize_client(self):
        """初始化 Weaviate 客户端"""
        try:
            import weaviate
            from weaviate.classes.init import AdditionalConfig, Timeout

            if self.embedded:
                # 使用 Embedded Weaviate
                self._client = weaviate.connect_to_embedded(
                    version="1.26.1", persistence_data_path="./data/weaviate_embedded"
                )
                logger.info("Embedded Weaviate 已启动")
            else:
                # 连接到普通 Weaviate
                headers = {}
                if self.api_key:
                    headers["X-OpenAI-Api-Key"] = self.api_key

                self._client = weaviate.connect_to_local(
                    host=self.host,
                    port=self.port,
                    grpc_port=self.grpc_port,
                    headers=headers,
                    additional_config=AdditionalConfig(
                        timeout=Timeout(init=2, query=45, insert=120)
                    ),
                )
                logger.info(f"Weaviate 客户端已连接: {self.host}:{self.port}")

            # 确保集合存在
            self._ensure_collection()

        except ImportError:
            logger.error("weaviate-client 未安装，请运行: pip install weaviate-client>=4.0.0")
            self._client = None
        except Exception as e:
            logger.error(f"Weaviate 初始化失败: {e}")
            self._client = None

    def _ensure_collection(self):
        """确保集合存在"""
        if not self._client:
            return

        try:
            # 检查集合是否已存在
            if not self._client.collections.exists(self.schema_class):
                # 创建新集合
                from weaviate.classes.config import Configure, DataType, Property

                self._client.collections.create(
                    name=self.schema_class,
                    vectorizer_config=Configure.Vectorizer.none(),
                    properties=[
                        Property(name="content", data_type=DataType.TEXT),
                        Property(name="memory_id", data_type=DataType.INT),
                        Property(name="memory_type", data_type=DataType.TEXT),
                        Property(name="importance", data_type=DataType.NUMBER),
                        Property(name="tags", data_type=DataType.TEXT_ARRAY),
                        Property(name="created_at", data_type=DataType.DATE),
                        Property(name="workspace_id", data_type=DataType.TEXT),
                        Property(name="is_archived", data_type=DataType.BOOL),
                        Property(name="emotion_score", data_type=DataType.NUMBER),
                    ],
                )
                logger.info(f"Weaviate 集合已创建: {self.schema_class}")
            else:
                logger.info(f"Weaviate 集合已存在: {self.schema_class}")

        except Exception as e:
            logger.error(f"创建/检查 Weaviate 集合失败: {e}")

    def is_available(self) -> bool:
        """检查向量存储是否可用"""
        if not self._client:
            return False
        try:
            return self._client.is_ready()
        except:
            return False

    async def add_memory_vector(
        self, memory_id: int, content: str, embedding: List[float], metadata: Dict = None
    ) -> bool:
        """添加记忆向量"""
        if not self._client:
            return False

        try:
            collection = self._client.collections.get(self.schema_class)

            # 准备数据对象
            data_object = {
                "content": content,
                "memory_id": memory_id,
                "memory_type": metadata.get("type", "long_term") if metadata else "long_term",
                "importance": metadata.get("importance_score", 0.6) if metadata else 0.6,
                "tags": metadata.get("tags", []) if metadata else [],
                "created_at": datetime.now().isoformat(),
                "workspace_id": metadata.get("workspace_id", "default") if metadata else "default",
                "is_archived": metadata.get("is_archived", False) if metadata else False,
                "emotion_score": metadata.get("emotion_score", 0.0) if metadata else 0.0,
            }

            # 插入数据
            collection.data.insert(properties=data_object, vector=embedding)

            logger.debug(f"Weaviate 向量已添加: memory_id={memory_id}")
            return True

        except Exception as e:
            logger.error(f"Weaviate 添加向量失败: {e}")
            return False

    async def search_similar(
        self,
        query_embedding: List[float],
        limit: int = 10,
        memory_type: str = None,
        min_score: float = 0.5,
        filters: Dict = None,
    ) -> List[Dict]:
        """搜索相似向量"""
        if not self._client:
            return []

        try:
            collection = self._client.collections.get(self.schema_class)

            # 构建查询
            query = collection.query.near_vector(
                near_vector=query_embedding, limit=limit, return_metadata=["distance"]
            )

            # 添加过滤器
            if memory_type or filters:
                from weaviate.classes.query import Filter

                filter_conditions = []
                if memory_type:
                    filter_conditions.append(Filter.by_property("memory_type").equal(memory_type))
                if filters:
                    if filters.get("is_archived") is not None:
                        filter_conditions.append(
                            Filter.by_property("is_archived").equal(filters["is_archived"])
                        )
                    if filters.get("workspace_id"):
                        filter_conditions.append(
                            Filter.by_property("workspace_id").equal(filters["workspace_id"])
                        )

                if filter_conditions:
                    query = query.with_filters(Filter.all_of(filter_conditions))

            # 执行查询
            results = query.objects

            # 处理结果
            filtered_results = []
            for obj in results:
                # Weaviate 返回的是距离，需要转换为相似度
                distance = obj.metadata.distance if obj.metadata else 0
                similarity_score = 1 - distance  # 将距离转换为相似度

                if similarity_score >= min_score:
                    filtered_results.append(
                        {
                            "memory_id": obj.properties.get("memory_id"),
                            "score": similarity_score,
                            "content": obj.properties.get("content"),
                            "metadata": {
                                "type": obj.properties.get("memory_type"),
                                "importance_score": obj.properties.get("importance"),
                                "tags": obj.properties.get("tags"),
                                "created_at": obj.properties.get("created_at"),
                                "workspace_id": obj.properties.get("workspace_id"),
                                "is_archived": obj.properties.get("is_archived"),
                            },
                        }
                    )

            return filtered_results

        except Exception as e:
            logger.error(f"Weaviate 向量搜索失败: {e}")
            return []

    async def delete_by_memory_id(self, memory_id: int) -> bool:
        """根据记忆ID删除向量"""
        if not self._client:
            return False

        try:
            collection = self._client.collections.get(self.schema_class)

            # 查找并删除
            from weaviate.classes.query import Filter

            result = collection.query.fetch_objects(
                filters=Filter.by_property("memory_id").equal(memory_id), limit=1
            )

            if result.objects:
                uuid = result.objects[0].uuid
                collection.data.delete_by_id(uuid)
                logger.debug(f"Weaviate 向量已删除: memory_id={memory_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Weaviate 删除向量失败: {e}")
            return False

    async def update_memory_vector(
        self, memory_id: int, content: str, embedding: List[float], metadata: Dict = None
    ) -> bool:
        """更新记忆向量"""
        if not self._client:
            return False

        try:
            # 先删除旧向量
            await self.delete_by_memory_id(memory_id)
            # 添加新向量
            return await self.add_memory_vector(memory_id, content, embedding, metadata)

        except Exception as e:
            logger.error(f"Weaviate 更新向量失败: {e}")
            return False

    async def get_vector_by_id(self, memory_id: int) -> Optional[Dict]:
        """根据ID获取向量"""
        if not self._client:
            return None

        try:
            collection = self._client.collections.get(self.schema_class)

            from weaviate.classes.query import Filter

            result = collection.query.fetch_objects(
                filters=Filter.by_property("memory_id").equal(memory_id),
                limit=1,
                include_vector=True,
            )

            if result.objects:
                obj = result.objects[0]
                return {
                    "memory_id": obj.properties.get("memory_id"),
                    "content": obj.properties.get("content"),
                    "vector": obj.vector,
                    "metadata": {
                        "type": obj.properties.get("memory_type"),
                        "importance_score": obj.properties.get("importance"),
                        "tags": obj.properties.get("tags"),
                        "created_at": obj.properties.get("created_at"),
                        "workspace_id": obj.properties.get("workspace_id"),
                        "is_archived": obj.properties.get("is_archived"),
                    },
                }

            return None

        except Exception as e:
            logger.error(f"Weaviate 获取向量失败: {e}")
            return None

    async def check_exists(self, memory_id: int) -> bool:
        """检查向量是否存在"""
        result = await self.get_vector_by_id(memory_id)
        return result is not None

    async def sync_with_sqlite(self, sqlite_manager, last_sync_time: str = None) -> "SyncResult":
        """与 SQLite 同步数据"""
        from .vector_store import SyncResult

        if not self._client:
            return SyncResult(errors=1, details=["Weaviate 不可用"])

        result = SyncResult(details=[])

        try:
            if last_sync_time:
                logger.info(f"开始增量同步 (since {last_sync_time})...")
            else:
                logger.info("开始 SQLite 与 Weaviate 全量数据同步...")

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

            result.total_checked = len(memories)

            for memory in memories:
                memory_id = memory["id"]
                content = memory["content"]

                try:
                    existing = await self.get_vector_by_id(memory_id)

                    if existing is None:
                        logger.info(f"Weaviate 向量不存在，创建: memory_id={memory_id}")
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
                        logger.info(f"Weaviate 内容不一致，更新: memory_id={memory_id}")
                        if self.embedding_model:
                            embedding = await self.embedding_model.get_embedding(content)
                            await self.update_memory_vector(
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
                f"Weaviate 同步完成: checked={result.total_checked}, synced={result.synced}, errors={result.errors}"
            )

        except Exception as e:
            result.errors += 1
            result.details.append(f"同步过程错误: {e}")
            logger.error(f"Weaviate 同步过程失败: {e}")

        return result

    def get_collection_info(self) -> Dict:
        """获取集合信息"""
        if not self._client:
            return {"error": "Weaviate 不可用"}

        try:
            collection = self._client.collections.get(self.schema_class)
            count = collection.aggregate.over_all(total_count=True).total_count

            return {
                "collection_name": self.schema_class,
                "vectors_count": count,
                "vector_size": self.vector_size,
                "embedded": self.embedded,
                "host": self.host if not self.embedded else "embedded",
                "port": self.port if not self.embedded else None,
            }
        except Exception as e:
            return {"error": str(e)}

    def clear_collection(self) -> bool:
        """清空集合"""
        if not self._client:
            return False

        try:
            collection = self._client.collections.get(self.schema_class)

            # 删除所有对象
            from weaviate.classes.query import Filter

            result = collection.query.fetch_objects(limit=1000)
            for obj in result.objects:
                collection.data.delete_by_id(obj.uuid)

            logger.info(f"Weaviate 集合已清空: {self.schema_class}")
            return True

        except Exception as e:
            logger.error(f"Weaviate 清空集合失败: {e}")
            return False

    def close(self):
        """关闭连接"""
        if self._client:
            try:
                self._client.close()
                logger.info("Weaviate 连接已关闭")
            except Exception as e:
                logger.warning(f"关闭 Weaviate 客户端失败: {e}")
            finally:
                self._client = None
