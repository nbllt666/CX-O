import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class SyncResult:
    total_checked: int = 0
    synced: int = 0
    removed: int = 0
    errors: int = 0
    details: List[str] = None


class VectorStoreBase:
    """向量存储基类"""

    def is_available(self) -> bool:
        """检查向量存储是否可用"""
        raise NotImplementedError

    async def add_memory_vector(
        self, memory_id: int, content: str, embedding: List[float], metadata: Dict = None
    ) -> bool:
        """添加记忆向量"""
        raise NotImplementedError

    async def search_similar(
        self,
        query_embedding: List[float],
        limit: int = 10,
        memory_type: str = None,
        min_score: float = 0.5,
    ) -> List[Dict]:
        """搜索相似向量"""
        raise NotImplementedError

    async def delete_by_memory_id(self, memory_id: int) -> bool:
        """根据记忆ID删除向量"""
        raise NotImplementedError

    async def get_vector_by_id(self, memory_id: int) -> Optional[Dict]:
        """根据ID获取向量"""
        raise NotImplementedError

    async def check_exists(self, memory_id: int) -> bool:
        """检查向量是否存在"""
        raise NotImplementedError

    async def sync_with_sqlite(self, sqlite_manager, last_sync_time: str = None) -> SyncResult:
        """与SQLite同步数据

        Args:
            sqlite_manager: SQLite管理器实例
            last_sync_time: 上次同步时间，用于增量同步
        """
        raise NotImplementedError

    def get_collection_info(self) -> Dict:
        """获取集合信息"""
        raise NotImplementedError

    def clear_collection(self) -> bool:
        """清空集合"""
        raise NotImplementedError

    def close(self):
        """关闭连接"""
        raise NotImplementedError


def create_vector_store(backend: str = "weaviate", **kwargs) -> VectorStoreBase:
    """
    创建向量存储实例

    Args:
        backend: 向量存储后端类型 ("weaviate", "weaviate_embedded")
        **kwargs: 向量存储配置参数

    Returns:
        VectorStoreBase: 向量存储实例
    """
    if backend == "weaviate":
        from .weaviate_store import WeaviateVectorStore

        return WeaviateVectorStore(embedded=False, **kwargs)
    elif backend == "weaviate_embedded":
        from .weaviate_store import WeaviateVectorStore

        return WeaviateVectorStore(embedded=True, **kwargs)
    else:
        logger.warning(f"不支持的向量存储后端: {backend}，仅支持 weaviate 和 weaviate_embedded")
        from .weaviate_store import WeaviateVectorStore

        return WeaviateVectorStore(embedded=False, **kwargs)
