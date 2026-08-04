"""记忆管理器 (Facade)

原 2998 行的 MemoryManager 已按功能域拆分为 8 个 mixin：
- _MemoryDBMixin: DB 基础设施（schema 初始化、连接池、清理、关闭）
- _GraphIntegrationMixin: 图数据库集成
- _VectorIntegrationMixin: 向量存储集成与向量搜索
- _MemoryCRUDMixin: 核心 CRUD 操作（含 async 包装）
- _PermanentMemoryMixin: 永久记忆操作
- _AdvancedSearchMixin: 高级搜索（3D 搜索、回忆、衰减、上下文）
- _BatchOperationsMixin: 批量操作
- _QueryHelpersMixin: 查询辅助

本文件仅保留单例 (__new__) 和初始化 (__init__) 逻辑，所有方法由 mixin 提供。
"""
import threading
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from .mixins._common import logger
from .mixins.advanced_mixin import _AdvancedSearchMixin
from .mixins.batch_mixin import _BatchOperationsMixin
from .mixins.crud_mixin import _MemoryCRUDMixin
from .mixins.db_mixin import _MemoryDBMixin
from .mixins.graph_mixin import _GraphIntegrationMixin
from .mixins.permanent_mixin import _PermanentMemoryMixin
from .mixins.query_mixin import _QueryHelpersMixin
from .mixins.decision_mixin import _DecisionMixin
from .mixins.vector_mixin import _VectorIntegrationMixin

if TYPE_CHECKING:
    from server.core.memory.graph_store import GraphStoreBase


class MemoryManager(
    _MemoryDBMixin,
    _GraphIntegrationMixin,
    _VectorIntegrationMixin,
    _MemoryCRUDMixin,
    _PermanentMemoryMixin,
    _AdvancedSearchMixin,
    _BatchOperationsMixin,
    _QueryHelpersMixin,
    _DecisionMixin,
):
    """记忆管理器

    负责记忆的创建、查询、更新、删除等操作，支持向量搜索和衰减计算

    Attributes:
        db_path: 数据库文件路径
        _vector_store: 向量存储实例
        _embedding_model: 嵌入模型实例
        _hybrid_search: 混合搜索实例
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = "data/memories.db") -> "MemoryManager":
        """创建单例实例

        Args:
            db_path: 数据库文件路径

        Returns:
            MemoryManager实例
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: str = "data/memories.db") -> None:
        """初始化记忆管理器

        Args:
            db_path: 数据库文件路径
        """
        if self._initialized:
            return

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._local = threading.local()
        self._connection_pool: Dict[int, Dict] = {}

        self._vector_store = None
        self._embedding_model = None
        self._hybrid_search = None
        self._llm_client = None
        self.archiver = None
        self.deduplication_engine = None
        self.vectorization_queue = None
        self._last_sync_time: Optional[str] = None

        self._graph_stores: Dict[str, "GraphStoreBase"] = {}
        self._graph_enabled = False
        self._init_graph_stores()

        self._init_db()
        self._init_advanced_components()

        self._stop_event = threading.Event()
        self._cleanup_thread = None
        self._start_cleanup_task()

        self._check_deprecated_config()

        # B4.3: 初始化 rejected_content 表（DecisionCore D6_REJECT 落地）
        self._init_rejected_content_table()

        logger.info(f"记忆管理器初始化完成: db={db_path}")
        self._initialized = True
