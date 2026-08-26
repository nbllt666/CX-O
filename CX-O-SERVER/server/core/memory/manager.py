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
- _DreamMixin: 梦境记忆写入与生命周期（type='dream' 软隔离）

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
from .mixins.dream_mixin import _DreamMixin
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
    _DreamMixin,
):
    """记忆管理器

    负责记忆的创建、查询、更新、删除等操作，支持向量搜索和衰减计算

    Attributes:
        db_path: 数据库文件路径
        _vector_store: 向量存储实例
        _embedding_model: 嵌入模型实例
        _hybrid_search: 混合搜索实例
    """

    _instances: Dict[str, "MemoryManager"] = {}
    _lock = threading.Lock()
    _init_lock = threading.Lock()  # H7: 类级初始化互斥锁（防并发首次 __init__ 双初始化）

    def __new__(cls, db_path: str = "data/memories.db") -> "MemoryManager":
        """按 db_path 获取记忆管理器实例。

        Args:
            db_path: 数据库文件路径

        Returns:
            MemoryManager实例。相同 ``db_path`` 复用同一实例；不同 ``db_path``
            得到相互独立实例——修复原固定全局单例 + ``__init__`` 短路导致
            不同 db_path 复用同一实例、后传路径被首次初始化慢忽略的问题。
            默认 ``MemoryManager(db_path="data/memories.db")`` 用法保持不变。
        """
        key = str(db_path)
        instance = cls._instances.get(key)
        if instance is None:
            with cls._lock:
                instance = cls._instances.get(key)
                if instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instances[key] = instance
        cls._instance = instance  # 兼容既有引用：指向最近获取的实例
        return instance

    def __init__(self, db_path: str = "data/memories.db") -> None:
        """初始化记忆管理器

        Args:
            db_path: 数据库文件路径
        """
        if self._initialized:
            return

        # H7: __new__ 的单例锁只保证实例只创建一次，两个线程并发首次
        # __init__ 仍会同时进入完整初始化（双 _init_db / 双清理线程 /
        # 重复加载高级组件与向量存储）。以类级锁串行化初始化并二次检查，
        # 保证初始化恰好执行一次。
        with MemoryManager._init_lock:
            if self._initialized:
                return
            self._initialize(db_path)

    def _initialize(self, db_path: str) -> None:
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
