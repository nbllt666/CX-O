import asyncio
import json
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.core.exceptions import DatabaseError, MemoryOperationError, VectorStoreError
from backend.core.logging_config import get_contextual_logger

try:
    import orjson

    def json_dumps(obj, **kwargs):
        return orjson.dumps(obj).decode("utf-8")

    def json_loads(s, **kwargs):
        return orjson.loads(s)

except ImportError:
    import json

    def json_dumps(obj, **kwargs):
        return json.dumps(obj, **kwargs)

    def json_loads(s, **kwargs):
        return json.loads(s, **kwargs)


logger = get_contextual_logger(__name__)


class MemoryManager:
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
        self.archiver = None
        self.deduplication_engine = None
        self._last_sync_time: Optional[str] = None

        self._init_db()
        self._init_advanced_components()

        self._stop_event = threading.Event()
        self._cleanup_thread = None
        self._start_cleanup_task()

        logger.info(f"记忆管理器初始化完成: db={db_path}")
        self._initialized = True

    def _get_table_name(self, agent_id: str = "default") -> str:
        """获取Agent对应的记忆表名

        Args:
            agent_id: Agent唯一标识，默认为"default"

        Returns:
            表名
        """
        if agent_id == "default" or not agent_id:
            return "memories"
        safe_agent_id = re.sub(r"[^a-zA-Z0-9_]", "_", agent_id)
        if not re.match(r"^[a-zA-Z_]", safe_agent_id):
            safe_agent_id = "agent_" + safe_agent_id
        return f"memories_{safe_agent_id}"

    def _ensure_agent_table(self, agent_id: str):
        """确保Agent的记忆表存在，不存在则创建

        Args:
            agent_id: Agent唯一标识
        """
        table_name = self._get_table_name(agent_id)

        if agent_id == "default" or not agent_id:
            return  # 默认表已在_init_db中创建

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # 检查表是否存在
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
            )
            if cursor.fetchone():
                return  # 表已存在

            # 创建Agent专属记忆表
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    vector_id VARCHAR(100),
                    metadata TEXT,
                    importance INTEGER DEFAULT 3,
                    importance_score FLOAT DEFAULT 0.6,
                    decay_type VARCHAR(20) DEFAULT 'exponential',
                    decay_params TEXT,
                    reactivation_count INTEGER DEFAULT 0,
                    emotion_score FLOAT DEFAULT 0.0,
                    permanent BOOLEAN DEFAULT FALSE,
                    psychological_age FLOAT DEFAULT 1.0,
                    tags TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP,
                    archived_at TIMESTAMP,
                    is_deleted BOOLEAN DEFAULT FALSE,
                    source VARCHAR(50) DEFAULT 'user',
                    workspace_id VARCHAR(100) DEFAULT 'default',
                    agent_id VARCHAR(100) DEFAULT '{agent_id}'
                )
            """
            )

            # 创建索引
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_type ON {table_name}(type)
            """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_created ON {table_name}(created_at)
            """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_deleted ON {table_name}(is_deleted)
            """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_agent ON {table_name}(agent_id)
            """
            )

            # 记录到agent_memory_tables
            cursor.execute(
                """
                INSERT OR REPLACE INTO agent_memory_tables (agent_id, table_name, updated_at)
                VALUES (?, ?, ?)
            """,
                (agent_id, table_name, datetime.now().isoformat()),
            )

            conn.commit()
            logger.info(f"已创建Agent '{agent_id}' 的记忆表: {table_name}")
        except Exception as e:
            logger.error(f"创建Agent记忆表失败: {e}")
            raise
        finally:
            conn.close()

    def _init_advanced_components(self):
        """初始化高级组件（归档器、去重引擎）"""
        try:
            from backend.core.memory.archiver import AdvancedArchiver

            self.archiver = AdvancedArchiver(self)
            logger.info("归档器已初始化")
        except Exception as e:
            logger.warning(f"归档器初始化失败: {e}")
            self.archiver = None

        try:
            from backend.core.memory.deduplication import DeduplicationEngine

            self.deduplication_engine = DeduplicationEngine(self)
            logger.info("去重引擎已初始化")
        except Exception as e:
            logger.warning(f"去重引擎初始化失败: {e}")
            self.deduplication_engine = None

    def _run_async_sync(self, coro):
        """在同步方法中运行异步协程

        Args:
            coro: 异步协程对象

        Returns:
            协程的返回值
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        else:
            return asyncio.run(coro)

    def _sync_vector_for_memory(self, memory_id: int, content: str, metadata: Dict = None) -> bool:
        """同步记忆到向量数据库

        Args:
            memory_id: 记忆ID
            content: 记忆内容
            metadata: 元数据

        Returns:
            是否同步成功
        """
        if not self._vector_store or not self._embedding_model:
            logger.debug(f"向量存储或嵌入模型未启用，跳过向量同步: memory_id={memory_id}")
            return False

        try:

            async def _sync():
                embedding = await self._embedding_model.get_embedding(content)
                return await self._vector_store.add_memory_vector(
                    memory_id=memory_id, content=content, embedding=embedding, metadata=metadata
                )

            result = self._run_async_sync(_sync())
            if result:
                logger.info(f"向量同步成功: memory_id={memory_id}")
            return result
        except Exception as e:
            logger.warning(f"向量同步失败: memory_id={memory_id}, error={e}")
            return False

    def _update_vector_for_memory(
        self, memory_id: int, content: str, metadata: Dict = None
    ) -> bool:
        """更新记忆的向量

        Args:
            memory_id: 记忆ID
            content: 新的记忆内容
            metadata: 新的元数据

        Returns:
            是否更新成功
        """
        if not self._vector_store or not self._embedding_model:
            logger.debug(f"向量存储或嵌入模型未启用，跳过向量更新: memory_id={memory_id}")
            return False

        try:

            async def _update():
                await self._vector_store.delete_by_memory_id(memory_id)
                embedding = await self._embedding_model.get_embedding(content)
                return await self._vector_store.add_memory_vector(
                    memory_id=memory_id, content=content, embedding=embedding, metadata=metadata
                )

            result = self._run_async_sync(_update())
            if result:
                logger.info(f"向量更新成功: memory_id={memory_id}")
            return result
        except Exception as e:
            logger.warning(f"向量更新失败: memory_id={memory_id}, error={e}")
            return False

    def _delete_vector_for_memory(self, memory_id: int) -> bool:
        """删除记忆的向量

        Args:
            memory_id: 记忆ID

        Returns:
            是否删除成功
        """
        if not self._vector_store:
            logger.debug(f"向量存储未启用，跳过向量删除: memory_id={memory_id}")
            return False

        try:

            async def _delete():
                return await self._vector_store.delete_by_memory_id(memory_id)

            result = self._run_async_sync(_delete())
            if result:
                logger.info(f"向量删除成功: memory_id={memory_id}")
            return result
        except Exception as e:
            logger.warning(f"向量删除失败: memory_id={memory_id}, error={e}")
            return False

    def _start_cleanup_task(self):
        def cleanup_task():
            while not self._stop_event.wait(60):
                try:
                    self._cleanup_idle_connections()
                    self._check_vector_store_health()
                except Exception as e:
                    logger.warning(f"清理任务异常: {e}")
            logger.info("清理任务已停止")

        self._cleanup_thread = threading.Thread(
            target=cleanup_task, daemon=True, name="MemoryCleanup"
        )
        self._cleanup_thread.start()

    def _cleanup_idle_connections(self):
        idle_threshold = time.time() - 300
        with self._lock:
            idle_threads = []
            for tid, conn_info in list(self._connection_pool.items()):
                try:
                    if isinstance(conn_info, dict):
                        last_used = conn_info.get("last_used", 0)
                        if last_used < idle_threshold:
                            idle_threads.append(tid)
                    elif isinstance(conn_info, sqlite3.Connection):
                        last_used = getattr(conn_info, "_last_used", 0)
                        if last_used < idle_threshold:
                            idle_threads.append(tid)
                except Exception as e:
                    logger.warning(f"检查连接 {tid} 时出错: {e}")
                    idle_threads.append(tid)

            for tid in idle_threads:
                try:
                    conn_info = self._connection_pool[tid]
                    if isinstance(conn_info, dict):
                        conn_info["connection"].close()
                    else:
                        conn_info.close()
                    logger.debug(f"已清理空闲连接: {tid}")
                except Exception as e:
                    logger.warning(f"清理连接 {tid} 失败: {e}")
                finally:
                    del self._connection_pool[tid]

            if idle_threads:
                logger.info(f"清理了 {len(idle_threads)} 个空闲连接")

    def _check_vector_store_health(self):
        if self._vector_store and hasattr(self._vector_store, "is_available"):
            try:
                if not self._vector_store.is_available():
                    logger.warning("向量存储不可用，尝试重新初始化...")
                    self._vector_store = None
                    self._try_reinit_vector_store()
            except Exception as e:
                logger.warning(f"向量存储健康检查失败: {e}")
                self._vector_store = None

    def _try_reinit_vector_store(self):
        """尝试重新初始化向量存储"""
        try:
            if hasattr(self, "_vector_store_config") and self._vector_store_config:
                config = self._vector_store_config
                from backend.core.memory.vector_store import create_vector_store

                vector_store = create_vector_store(
                    backend=config.get("backend", "milvus_lite"),
                    db_path=config.get("milvus_db_path", "data/milvus_lite.db"),
                    vector_size=config.get("vector_size", 768),
                    embedding_model=self._embedding_model,
                )
                if vector_store and vector_store.is_available():
                    self._vector_store = vector_store
                    logger.info("向量存储重新初始化成功")
                else:
                    logger.warning("向量存储重新初始化失败")
        except Exception as e:
            logger.warning(f"重新初始化向量存储失败: {e}")

    def shutdown(self):
        logger.info("正在关闭记忆管理器...")
        self._stop_event.set()

        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)

        self.close_all_connections()

        if self._vector_store:
            try:
                self._vector_store.close()
            except Exception as e:
                logger.warning(f"关闭向量存储失败: {e}")
            self._vector_store = None

        logger.info("记忆管理器已关闭")

    def _init_db(self):
        import sqlite3

        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                vector_id VARCHAR(100),
                metadata TEXT,
                importance INTEGER DEFAULT 3,
                importance_score FLOAT DEFAULT 0.6,
                decay_type VARCHAR(20) DEFAULT 'exponential',
                decay_params TEXT,
                reactivation_count INTEGER DEFAULT 0,
                emotion_score FLOAT DEFAULT 0.0,
                permanent BOOLEAN DEFAULT FALSE,
                psychological_age FLOAT DEFAULT 1.0,
                tags TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                archived_at TIMESTAMP,
                is_deleted BOOLEAN DEFAULT FALSE,
                deleted_at TIMESTAMP,
                source VARCHAR(50) DEFAULT 'user',
                workspace_id VARCHAR(100) DEFAULT 'default',
                agent_id VARCHAR(100) DEFAULT 'default'
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation VARCHAR(50) NOT NULL,
                memory_id INTEGER,
                memory_type VARCHAR(50),
                session_id VARCHAR(36),
                operator VARCHAR(20) NOT NULL,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS permanent_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vector_id VARCHAR(100),
                content TEXT NOT NULL,
                importance_score FLOAT DEFAULT 1.0,
                emotion_score FLOAT DEFAULT 0.0,
                tags TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                metadata TEXT,
                source VARCHAR(50) DEFAULT 'user',
                verified BOOLEAN DEFAULT TRUE
            )
        """
        )

        # 创建 agent_memory_tables 表（用于记录Agent的记忆表映射）
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_memory_tables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id VARCHAR(100) NOT NULL UNIQUE,
                table_name VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            )
        """
        )

        # 检查并添加缺失的列（用于兼容旧数据库）
        def get_existing_columns(cursor, table_name: str) -> set:
            cursor.execute(f"PRAGMA table_info({table_name})")
            return {row[1] for row in cursor.fetchall()}

        # 1. memories 表的列
        memories_columns_to_add = [
            ("emotion_score", "FLOAT DEFAULT 0.0"),
            ("source", "VARCHAR(50) DEFAULT 'user'"),
            ("vector_id", "VARCHAR(100)"),
            ("importance_score", "FLOAT DEFAULT 1.0"),
            ("tags", "TEXT"),
            ("metadata", "TEXT"),
            ("updated_at", "TIMESTAMP"),
            ("archived_at", "TIMESTAMP"),
            ("is_deleted", "BOOLEAN DEFAULT FALSE"),
            ("deleted_at", "TIMESTAMP"),
            ("agent_id", "VARCHAR(100) DEFAULT 'default'"),
        ]

        existing_columns = get_existing_columns(cursor, "memories")
        for col_name, col_type in memories_columns_to_add:
            if col_name not in existing_columns:
                cursor.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_type}")
                logger.info(f"已添加 {col_name} 列到 memories 表")

        # 2. permanent_memories 表的列
        permanent_columns_to_add = [
            ("emotion_score", "FLOAT DEFAULT 0.0"),
            ("source", "VARCHAR(50) DEFAULT 'user'"),
            ("verified", "BOOLEAN DEFAULT TRUE"),
            ("vector_id", "VARCHAR(100)"),
            ("importance_score", "FLOAT DEFAULT 1.0"),
            ("tags", "TEXT"),
            ("metadata", "TEXT"),
            ("updated_at", "TIMESTAMP"),
        ]

        existing_columns = get_existing_columns(cursor, "permanent_memories")
        for col_name, col_type in permanent_columns_to_add:
            if col_name not in existing_columns:
                cursor.execute(f"ALTER TABLE permanent_memories ADD COLUMN {col_name} {col_type}")
                logger.info(f"已添加 {col_name} 列到 permanent_memories 表")

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)",
            "CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_memories_is_deleted ON memories(is_deleted)",
            "CREATE INDEX IF NOT EXISTS idx_memories_permanent ON memories(permanent)",
            "CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)",
            "CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace_id)",
        ]
        for idx in indexes:
            cursor.execute(idx)

        conn.commit()
        conn.close()

    def _get_connection(self):
        import sqlite3

        thread_id = threading.get_ident()

        with self._lock:
            if thread_id in self._connection_pool:
                conn_info = self._connection_pool[thread_id]
                if isinstance(conn_info, dict):
                    conn = conn_info["connection"]
                else:
                    conn = conn_info

                try:
                    conn.execute("SELECT 1")
                    if isinstance(conn_info, dict):
                        conn_info["last_used"] = time.time()
                    return conn
                except Exception:
                    # 连接已关闭或失效，需要重新创建
                    pass

                try:
                    if isinstance(conn_info, dict):
                        conn_info["connection"].close()
                    else:
                        conn.close()
                except Exception as e:
                    logger.warning(f"关闭旧连接失败: {e}")
                del self._connection_pool[thread_id]

        try:
            conn = sqlite3.connect(str(self.db_path), timeout=20.0, check_same_thread=False)
        except sqlite3.Error as e:
            logger.error(f"数据库连接失败: {e}")
            raise

        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")

        connection_info = {"connection": conn, "last_used": time.time()}

        with self._lock:
            self._connection_pool[thread_id] = connection_info

        return conn

    def _release_connection(self, conn=None):
        """释放连接（线程本地保留，下次复用）"""
        pass

    def close_all_connections(self):
        with self._lock:
            for thread_id, conn_info in list(self._connection_pool.items()):
                try:
                    if isinstance(conn_info, dict):
                        conn_info["connection"].close()
                    else:
                        conn_info.close()
                except Exception as e:
                    logger.warning(f"关闭连接失败: {e}")
            self._connection_pool.clear()

    def write_memory(
        self,
        content: str,
        memory_type: str = "long_term",
        importance: int = 3,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        permanent: bool = False,
        emotion_score: float = 0.0,
        workspace_id: str = "default",
        agent_id: str = "default",
    ) -> int:
        """写入记忆

        Args:
            content: 记忆内容
            memory_type: 记忆类型（long_term, short_term, permanent）
            importance: 重要性等级（1-5）
            tags: 标签列表
            metadata: 元数据
            permanent: 是否为永久记忆
            emotion_score: 情感分数
            workspace_id: 工作区ID
            agent_id: Agent ID，用于隔离不同Agent的记忆

        Returns:
            记忆ID

        Raises:
            DatabaseError: 数据库操作失败
        """
        # 确保Agent的记忆表存在
        self._ensure_agent_table(agent_id)
        table_name = self._get_table_name(agent_id)

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"""
                INSERT INTO {table_name} (
                    type, content, importance, importance_score,
                    decay_type, decay_params, reactivation_count,
                    emotion_score, permanent, psychological_age,
                    tags, metadata, created_at, workspace_id, agent_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    memory_type,
                    content,
                    importance,
                    0.6 if not permanent else 1.0,
                    "zero" if permanent else "exponential",
                    json_dumps({}),
                    0,
                    emotion_score,
                    permanent,
                    1.0,
                    json_dumps(tags or [], ensure_ascii=False),
                    json_dumps(metadata or {}, ensure_ascii=False),
                    datetime.now().isoformat(),
                    workspace_id,
                    agent_id,
                ),
            )

            memory_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO audit_logs (operation, memory_id, operator, details)
                VALUES (?, ?, ?, ?)
            """,
                (
                    "create",
                    memory_id,
                    "system",
                    json_dumps({"type": memory_type, "agent_id": agent_id}),
                ),
            )

            conn.commit()
            logger.info(f"记忆已写入: id={memory_id}, type={memory_type}, agent={agent_id}")

            try:
                vector_metadata = {
                    "type": memory_type,
                    "importance": importance,
                    "tags": tags or [],
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "permanent": permanent,
                    "emotion_score": emotion_score,
                }
                self._sync_vector_for_memory(memory_id, content, vector_metadata)
            except Exception as vec_e:
                logger.warning(f"向量同步失败，不影响主操作: memory_id={memory_id}, error={vec_e}")

            return memory_id
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"写入记忆失败: {e}", exc_info=True)
            raise

    def get_memory(self, memory_id: int, include_deleted: bool = False) -> Optional[Dict]:
        """获取记忆

        Args:
            memory_id: 记忆ID
            include_deleted: 是否包含已删除的记忆

        Returns:
            记忆字典，如果不存在则返回None
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = "SELECT * FROM memories WHERE id = ?"
            if not include_deleted:
                query += " AND is_deleted = FALSE"

            cursor.execute(query, (memory_id,))
            row = cursor.fetchone()

            if row:
                return self._row_to_memory(row)
            return None
        except Exception as e:
            logger.error(f"获取记忆失败: {e}", exc_info=True)
            return None

    def search_memories(
        self,
        query: Optional[str] = None,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        time_range: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
        include_deleted: bool = False,
        workspace_id: str = "default",
        agent_id: str = "default",
    ) -> List[Dict]:
        """搜索记忆

        Args:
            query: 搜索关键词
            memory_type: 记忆类型
            tags: 标签列表
            time_range: 时间范围（today, last_week, last_month）
            limit: 返回数量限制
            offset: 偏移量，用于分页
            include_deleted: 是否包含已删除的记忆
            workspace_id: 工作区ID
            agent_id: Agent ID，指定搜索哪个Agent的记忆表

        Returns:
            记忆列表
        """
        table_name = self._get_table_name(agent_id)

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            conditions = ["workspace_id = ?"]
            params = [workspace_id]

            if query:
                escaped_query = query.replace("%", "\\%").replace("_", "\\_")
                conditions.append("content LIKE ? ESCAPE '\\'")
                params.append(f"%{escaped_query[:500]}%")

            if memory_type:
                conditions.append("type = ?")
                params.append(memory_type)

            if tags:
                for tag in tags:
                    escaped_tag = tag.replace("%", "\\%").replace("_", "\\_")
                    conditions.append("tags LIKE ? ESCAPE '\\'")
                    params.append(f'%"{escaped_tag[:100]}"%')

            if time_range:
                from datetime import timedelta

                now = datetime.now()
                if time_range == "today":
                    start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
                elif time_range == "last_week":
                    start_time = now - timedelta(days=7)
                elif time_range == "last_month":
                    start_time = now - timedelta(days=30)
                else:
                    start_time = now - timedelta(days=1)
                conditions.append("created_at >= ?")
                params.append(start_time.isoformat())

            if not include_deleted:
                conditions.append("is_deleted = FALSE")

            where_clause = " AND ".join(conditions) if conditions else "1=1"
            params.append(limit)
            params.append(offset)

            cursor.execute(
                f"SELECT * FROM {table_name} WHERE {where_clause} ORDER BY importance DESC, created_at DESC LIMIT ? OFFSET ?",
                params,
            )

            rows = cursor.fetchall()
            return [self._row_to_memory(row) for row in rows]
        except Exception as e:
            logger.error(f"搜索记忆失败: {e}", exc_info=True)
            return []

    def update_memory(
        self,
        memory_id: int,
        new_content: str = None,
        new_tags: List[str] = None,
        new_importance: int = None,
        new_metadata: Dict = None,
        agent_id: str = "default",
    ) -> bool:
        """更新记忆

        Args:
            memory_id: 记忆ID
            new_content: 新内容
            new_tags: 新标签
            new_importance: 新重要性
            new_metadata: 新元数据
            agent_id: Agent ID，用于指定记忆表
        """
        table_name = self._get_table_name(agent_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            updates = []
            params = []

            if new_content is not None:
                updates.append("content = ?")
                params.append(new_content)

            if new_tags is not None:
                updates.append("tags = ?")
                params.append(json_dumps(new_tags, ensure_ascii=False))

            if new_importance is not None:
                updates.append("importance = ?")
                params.append(new_importance)

            if new_metadata is not None:
                updates.append("metadata = ?")
                params.append(json_dumps(new_metadata, ensure_ascii=False))

            if not updates:
                return False

            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(memory_id)

            query = (
                f"UPDATE {table_name} SET {', '.join(updates)} WHERE id = ? AND is_deleted = FALSE"
            )
            cursor.execute(query, params)

            success = cursor.rowcount > 0
            conn.commit()

            if success and new_content is not None:
                try:
                    vector_metadata = {
                        "tags": new_tags or [],
                        "importance": new_importance,
                        "agent_id": agent_id,
                    }
                    if new_metadata:
                        vector_metadata.update(new_metadata)
                    self._update_vector_for_memory(memory_id, new_content, vector_metadata)
                except Exception as vec_e:
                    logger.warning(
                        f"向量更新失败，不影响主操作: memory_id={memory_id}, error={vec_e}"
                    )

            return success
        except Exception as e:
            logger.error(f"更新记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False

    def delete_memory(
        self, memory_id: int, soft_delete: bool = True, agent_id: str = "default"
    ) -> bool:
        """删除记忆

        Args:
            memory_id: 记忆ID
            soft_delete: 是否软删除
            agent_id: Agent ID，用于指定记忆表
        """
        table_name = self._get_table_name(agent_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            if soft_delete:
                query = f"UPDATE {table_name} SET is_deleted = TRUE, updated_at = ? WHERE id = ? AND is_deleted = FALSE"
                params = (datetime.now().isoformat(), memory_id)
            else:
                query = f"DELETE FROM {table_name} WHERE id = ?"
                params = (memory_id,)

            cursor.execute(query, params)

            success = cursor.rowcount > 0

            if success:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, operator, details)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        "delete" if not soft_delete else "soft_delete",
                        memory_id,
                        "system",
                        json_dumps({"soft_delete": soft_delete, "agent_id": agent_id}),
                    ),
                )

            conn.commit()

            if success:
                try:
                    self._delete_vector_for_memory(memory_id)
                except Exception as vec_e:
                    logger.warning(
                        f"向量删除失败，不影响主操作: memory_id={memory_id}, error={vec_e}"
                    )

            return success
        except Exception as e:
            logger.error(f"删除记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False

    def restore_memory(self, memory_id: int, agent_id: str = "default") -> bool:
        """恢复软删除的记忆

        Args:
            memory_id: 记忆ID
            agent_id: Agent ID，用于指定记忆表
        """
        table_name = self._get_table_name(agent_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"""
                UPDATE {table_name} 
                SET is_deleted = FALSE, updated_at = ?
                WHERE id = ? AND is_deleted = TRUE
            """,
                (datetime.now().isoformat(), memory_id),
            )

            success = cursor.rowcount > 0

            if success:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, operator, details)
                    VALUES (?, ?, ?, ?)
                """,
                    ("restore", memory_id, "system", json_dumps({"agent_id": agent_id})),
                )

            conn.commit()
            return success
        except Exception as e:
            logger.error(f"恢复记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False

    def get_statistics(self, workspace_id: str = "default") -> Dict:
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE is_deleted = FALSE AND workspace_id = ?",
                (workspace_id,),
            )
            total = cursor.fetchone()[0]

            cursor.execute(
                "SELECT type, COUNT(*) FROM memories WHERE is_deleted = FALSE AND workspace_id = ? GROUP BY type",
                (workspace_id,),
            )
            by_type = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE is_deleted = TRUE AND workspace_id = ?",
                (workspace_id,),
            )
            soft_deleted = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE permanent = TRUE AND is_deleted = FALSE AND workspace_id = ?",
                (workspace_id,),
            )
            permanent = cursor.fetchone()[0]

            return {
                "total": total,
                "by_type": by_type,
                "soft_deleted": soft_deleted,
                "permanent": permanent,
            }
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}", exc_info=True)
            return {"total": 0, "by_type": {}, "soft_deleted": 0, "permanent": 0}

    def _row_to_memory(self, row) -> Dict:
        try:
            metadata = json_loads(row["metadata"] or "{}")
            tags = json_loads(row["tags"] or "[]")
            decay_params = json_loads(row["decay_params"] or "{}")
        except Exception:
            metadata = {}
            tags = []
            decay_params = {}

        return {
            "id": row["id"],
            "type": row["type"],
            "content": row["content"],
            "vector_id": row["vector_id"],
            "metadata": metadata,
            "importance": row["importance"],
            "importance_score": row["importance_score"],
            "decay_type": row["decay_type"],
            "decay_params": decay_params,
            "reactivation_count": row["reactivation_count"],
            "emotion_score": row["emotion_score"],
            "permanent": bool(row["permanent"]),
            "psychological_age": row["psychological_age"],
            "tags": tags,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived_at": row["archived_at"],
            "is_deleted": bool(row["is_deleted"]),
            "source": row["source"],
            "workspace_id": row["workspace_id"],
        }

    def enable_vector_search(
        self,
        embedding_model=None,
        vector_store=None,
        vector_backend: str = "chroma",
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        milvus_db_path: str = "data/milvus_lite.db",
        db_path: str = "data/chroma_db",
        collection_name: str = "memory_vectors",
        vector_size: int = 768,
        **kwargs,
    ):
        dimension = embedding_model.dimension if embedding_model else vector_size

        self._vector_store_config = {
            "backend": vector_backend,
            "milvus_db_path": milvus_db_path,
            "qdrant_host": qdrant_host,
            "qdrant_port": qdrant_port,
            "db_path": db_path,
            "collection_name": collection_name,
            "vector_size": dimension,
            "embedding_model": embedding_model,
        }

        if vector_store is None:
            try:
                from backend.core.memory.vector_store import create_vector_store

                if vector_backend == "chroma":
                    vector_store = create_vector_store(
                        backend="chroma",
                        db_path=db_path,
                        collection_name=collection_name,
                        vector_size=dimension,
                        embedding_model=embedding_model,
                    )
                elif vector_backend == "milvus_lite":
                    vector_store = create_vector_store(
                        backend="milvus_lite",
                        db_path=milvus_db_path,
                        vector_size=dimension,
                        embedding_model=embedding_model,
                    )
                elif vector_backend == "qdrant":
                    vector_store = create_vector_store(
                        backend="qdrant",
                        host=qdrant_host,
                        port=qdrant_port,
                        vector_size=dimension,
                        embedding_model=embedding_model,
                    )
                elif vector_backend in ["weaviate", "weaviate_embedded"]:
                    vector_store = create_vector_store(
                        backend=vector_backend,
                        vector_size=dimension,
                        embedding_model=embedding_model,
                        **kwargs,
                    )
                else:
                    logger.warning(f"未知的向量存储后端: {vector_backend}")
                    return

                self._vector_store = vector_store
            except ImportError as e:
                logger.warning(f"向量存储未安装，向量功能不可用: {e}")
                return
        else:
            self._vector_store = vector_store

        self._embedding_model = embedding_model

        if self._vector_store and self._embedding_model:
            from backend.core.memory.hybrid_search import HybridSearch

            self._hybrid_search = HybridSearch(
                vector_store=self._vector_store,
                sqlite_manager=self,
                embedding_model=self._embedding_model,
            )
            logger.info(f"向量搜索功能已启用 (后端: {vector_backend})")

    def is_vector_search_enabled(self) -> bool:
        with self._lock:
            return self._hybrid_search is not None and self._vector_store is not None

    async def semantic_search(
        self, query: str, memory_type: str = None, limit: int = 10
    ) -> List[Dict]:
        if not self.is_vector_search_enabled():
            return self.search_memories(query=query, memory_type=memory_type, limit=limit)

        try:
            results = await self._hybrid_search.semantic_search(
                query=query, memory_type=memory_type, limit=limit
            )
            return results
        except Exception as e:
            logger.error(f"语义搜索失败: {e}")
            return self.search_memories(query=query, memory_type=memory_type, limit=limit)

    async def hybrid_search(
        self,
        query: str,
        memory_type: str = None,
        tags: List[str] = None,
        limit: int = 10,
        workspace_id: str = None,
    ) -> List[Dict]:
        fallback = False

        if not self.is_vector_search_enabled():
            fallback = True
            results = self.search_memories(
                query=query, memory_type=memory_type, tags=tags, limit=limit
            )
            for result in results:
                result["fallback"] = fallback
            return results

        try:
            from backend.core.memory.hybrid_search import HybridSearchOptions

            options = HybridSearchOptions(
                query=query,
                memory_type=memory_type,
                tags=tags,
                limit=limit,
                workspace_id=workspace_id,
            )

            search_results = await self._hybrid_search.search(options)

            return [
                {
                    "memory_id": r.memory_id,
                    "content": r.content,
                    "score": r.score,
                    "source": r.source,
                    "metadata": r.metadata,
                    "fallback": fallback,
                }
                for r in search_results
            ]
        except Exception as e:
            logger.error(f"混合搜索失败: {e}")
            fallback = True
            results = self.search_memories(
                query=query, memory_type=memory_type, tags=tags, limit=limit
            )
            for result in results:
                result["fallback"] = fallback
            return results

    def write_permanent_memory(
        self,
        content: str,
        tags: List[str] = None,
        metadata: Dict = None,
        emotion_score: float = 0.0,
        source: str = "user",
        is_from_main: bool = True,
    ) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO permanent_memories (
                    content, importance_score, emotion_score,
                    tags, metadata, created_at, source, verified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    content,
                    1.0,
                    emotion_score,
                    json_dumps(tags or [], ensure_ascii=False),
                    json_dumps(metadata or {}, ensure_ascii=False),
                    datetime.now().isoformat(),
                    source,
                    is_from_main,
                ),
            )

            memory_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    "create_permanent",
                    memory_id,
                    None,
                    "main_model" if is_from_main else "secondary_model",
                    json_dumps({"source": source}),
                ),
            )

            conn.commit()
            logger.info(f"永久记忆已写入: id={memory_id}, source={source}")
            return memory_id
        except Exception as e:
            logger.error(f"写入永久记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise

    def get_permanent_memory(self, memory_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM permanent_memories WHERE id = ?", (memory_id,))
            row = cursor.fetchone()

            if row:
                return self._row_to_permanent_memory(row)
            return None
        except Exception as e:
            logger.error(f"获取永久记忆失败: {e}", exc_info=True)
            return None

    def get_permanent_memories(
        self, limit: int = 20, offset: int = 0, tags: List[str] = None
    ) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = "SELECT * FROM permanent_memories WHERE 1=1"
            params = []

            if tags:
                for tag in tags:
                    query += " AND tags LIKE ?"
                    params.append(f'%"{tag}"%')

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_permanent_memory(row) for row in rows]
        except Exception as e:
            logger.error(f"获取永久记忆列表失败: {e}", exc_info=True)
            return []

    def update_permanent_memory(
        self, memory_id: int, content: str = None, tags: List[str] = None, metadata: Dict = None
    ) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            updates = []
            params = []

            if content is not None:
                updates.append("content = ?")
                params.append(content)

            if tags is not None:
                updates.append("tags = ?")
                params.append(json_dumps(tags, ensure_ascii=False))

            if metadata is not None:
                updates.append("metadata = ?")
                params.append(json_dumps(metadata, ensure_ascii=False))

            if not updates:
                return False

            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(memory_id)

            query = f"UPDATE permanent_memories SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)

            success = cursor.rowcount > 0

            if success:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        "update_permanent",
                        memory_id,
                        None,
                        "system",
                        json_dumps({"updates": updates}),
                    ),
                )

            conn.commit()
            return success
        except Exception as e:
            logger.error(f"更新永久记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False

    def delete_permanent_memory(self, memory_id: int, is_from_main: bool = True) -> bool:
        if not is_from_main:
            logger.warning(f"副模型无权删除永久记忆: id={memory_id}")
            return False

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM permanent_memories WHERE id = ?", (memory_id,))

            success = cursor.rowcount > 0

            if success:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    ("delete_permanent", memory_id, None, "main_model", json_dumps({})),
                )

            conn.commit()
            return success
        except Exception as e:
            logger.error(f"删除永久记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False

    def _row_to_permanent_memory(self, row) -> Dict:
        try:
            metadata = json_loads(row["metadata"] or "{}")
            tags = json_loads(row["tags"] or "[]")
        except Exception:
            metadata = {}
            tags = []

        return {
            "id": row["id"],
            "content": row["content"],
            "importance_score": row["importance_score"],
            "emotion_score": row["emotion_score"],
            "tags": tags,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": metadata,
            "source": row["source"],
            "verified": bool(row["verified"]) if "verified" in row.keys() else True,
        }

    def search_memories_3d(
        self,
        query: str = None,
        memory_type: str = None,
        tags: List[str] = None,
        limit: int = 10,
        weights: Tuple[float, float, float] = (0.35, 0.25, 0.4),
        workspace_id: str = "default",
    ) -> List[Dict]:
        from backend.core.memory.decay import DecayCalculator

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            conditions = ["workspace_id = ?", "is_deleted = FALSE"]
            params = [workspace_id]

            if query:
                conditions.append("content LIKE ?")
                params.append(f"%{query}%")

            if memory_type:
                conditions.append("type = ?")
                params.append(memory_type)

            if tags:
                for tag in tags:
                    conditions.append("tags LIKE ?")
                    params.append(f'%"{tag}"%')

            where_clause = " AND ".join(conditions)
            params.append(limit * 2)

            cursor.execute(
                f"SELECT * FROM memories WHERE {where_clause} ORDER BY importance DESC, created_at DESC LIMIT ?",
                params,
            )

            rows = cursor.fetchall()
        except Exception as e:
            logger.error(f"3D搜索失败: {e}", exc_info=True)
            rows = []

        decay_calculator = DecayCalculator()
        scored_memories = []

        for row in rows:
            memory = self._row_to_memory(row)

            importance_score = decay_calculator.calculate_importance_score(memory)
            time_score = decay_calculator.calculate_time_score(memory, apply_reactivation=True)
            relevance_score = memory.get("score", 0.5)

            final_score = (
                importance_score * weights[0]
                + time_score * weights[1]
                + relevance_score * weights[2]
            )

            if memory.get("permanent"):
                final_score = min(final_score + 0.15, 1.0)

            final_score = min(final_score, 1.0)

            memory["final_score"] = final_score
            memory["component_scores"] = {
                "importance": importance_score,
                "time": time_score,
                "relevance": relevance_score,
            }
            memory["applied_weights"] = {
                "importance": weights[0],
                "time": weights[1],
                "relevance": weights[2],
            }

            scored_memories.append(memory)

        scored_memories.sort(key=lambda m: m["final_score"], reverse=True)

        return scored_memories[:limit]

    def recall_memory(self, memory_id: int, emotion_intensity: float = 0.0) -> Optional[Dict]:
        from backend.core.memory.decay import DecayCalculator

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT * FROM memories WHERE id = ? AND is_deleted = FALSE", (memory_id,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            memory = self._row_to_memory(row)

            reactivation_count = memory.get("reactivation_count", 0)
            decay_calculator = DecayCalculator()
            old_time_score = decay_calculator.calculate_time_score(memory, apply_reactivation=False)

            new_time_score = min(1.0, old_time_score * (1 + 0.2 * reactivation_count) + 0.1)
            emotion_bonus = 0.05 * abs(emotion_intensity)
            new_time_score = min(new_time_score + emotion_bonus, 1.0)

            new_reactivation_count = reactivation_count + 1
            new_emotion_score = (memory.get("emotion_score", 0.0) + abs(emotion_intensity)) / 2

            cursor.execute(
                """
                UPDATE memories
                SET reactivation_count = ?, emotion_score = ?, updated_at = ?
                WHERE id = ?
            """,
                (new_reactivation_count, new_emotion_score, datetime.now().isoformat(), memory_id),
            )

            cursor.execute(
                """
                INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    "recall",
                    memory_id,
                    None,
                    "system",
                    json_dumps(
                        {
                            "reactivation_count": new_reactivation_count,
                            "emotion_intensity": emotion_intensity,
                            "old_time_score": old_time_score,
                            "new_time_score": new_time_score,
                            "memory_type": memory.get("type"),
                        }
                    ),
                ),
            )

            conn.commit()

            logger.info(f"记忆已召回: id={memory_id}, reactivation_count={new_reactivation_count}")

            updated_memory = self.get_memory(memory_id)
            if updated_memory:
                updated_memory["reactivation_details"] = {
                    "old_time_score": old_time_score,
                    "new_time_score": new_time_score,
                    "emotion_bonus": emotion_bonus,
                    "reactivation_count": new_reactivation_count,
                }

            return updated_memory
        except Exception as e:
            logger.error(f"召回记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return None

    def batch_write_memories(self, memories: List[Dict], raise_on_error: bool = False) -> Dict:
        results = {"success": 0, "failed": 0, "errors": [], "memory_ids": []}

        for mem_data in memories:
            try:
                memory_id = self.write_memory(
                    content=mem_data.get("content", ""),
                    memory_type=mem_data.get("type", "long_term"),
                    importance=mem_data.get("importance", 3),
                    tags=mem_data.get("tags", []),
                    metadata=mem_data.get("metadata", {}),
                    permanent=mem_data.get("permanent", False),
                    emotion_score=mem_data.get("emotion_score", 0.0),
                    workspace_id=mem_data.get("workspace_id", "default"),
                )
                results["success"] += 1
                results["memory_ids"].append(memory_id)
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))
                if raise_on_error:
                    raise

        logger.info(f"批量写入完成: 成功={results['success']}, 失败={results['failed']}")
        return results

    def batch_update_memories(
        self, updates: List[Dict], raise_on_error: bool = False, agent_id: str = "default"
    ) -> Dict:
        """批量更新记忆

        Args:
            updates: 更新列表，每个包含 memory_id 和要更新的字段
            raise_on_error: 遇到错误是否抛出异常
            agent_id: Agent ID，用于指定记忆表
        """
        results = {"success": 0, "failed": 0, "errors": [], "updated_ids": []}

        for update_data in updates:
            try:
                memory_id = update_data.get("memory_id")
                if not memory_id:
                    raise ValueError("memory_id is required")

                success = self.update_memory(
                    memory_id=memory_id,
                    new_content=update_data.get("content"),
                    new_tags=update_data.get("tags"),
                    new_importance=update_data.get("importance"),
                    new_metadata=update_data.get("metadata"),
                    agent_id=agent_id,
                )

                if success:
                    results["success"] += 1
                    results["updated_ids"].append(memory_id)
                else:
                    results["failed"] += 1
                    results["errors"].append(f"Memory {memory_id} not found")
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))
                if raise_on_error:
                    raise

        logger.info(f"批量更新完成: 成功={results['success']}, 失败={results['failed']}")
        return results

    def batch_delete_memories(
        self,
        memory_ids: List[int],
        soft_delete: bool = True,
        raise_on_error: bool = False,
        agent_id: str = "default",
    ) -> Dict:
        """批量删除记忆

        Args:
            memory_ids: 记忆ID列表
            soft_delete: 是否软删除
            raise_on_error: 遇到错误是否抛出异常
            agent_id: Agent ID，用于指定记忆表
        """
        results = {"success": 0, "failed": 0, "errors": [], "deleted_ids": []}

        for memory_id in memory_ids:
            try:
                success = self.delete_memory(memory_id, soft_delete=soft_delete, agent_id=agent_id)

                if success:
                    results["success"] += 1
                    results["deleted_ids"].append(memory_id)
                else:
                    results["failed"] += 1
                    results["errors"].append(f"Memory {memory_id} not found")
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))
                if raise_on_error:
                    raise

        logger.info(f"批量删除完成: 成功={results['success']}, 失败={results['failed']}")
        return results

    def sync_decay_values(self, workspace_id: str = "default") -> Dict:
        """同步衰减值 - 已改为实时计算模式，此函数仅返回统计信息

        注意：时间分数现在实时计算，不再预存储到数据库
        """
        from backend.core.memory.decay import DecayCalculator

        try:
            # 获取所有记忆用于统计
            memories = self.search_memories(limit=10000, workspace_id=workspace_id)

            decay_calculator = DecayCalculator()
            total = len(memories)
            permanent_count = sum(1 for m in memories if m.get("permanent"))

            # 实时计算统计信息
            time_scores = []
            for memory in memories:
                if not memory.get("permanent"):
                    time_score = decay_calculator.calculate_time_score_realtime(
                        importance=memory.get(
                            "importance_score", memory.get("importance", 3) / 5.0
                        ),
                        created_at=memory.get("created_at", datetime.now().isoformat()),
                        decay_type=memory.get("decay_type", "exponential"),
                        decay_params=memory.get("decay_params"),
                        permanent=False,
                        reactivation_count=memory.get("reactivation_count", 0),
                        emotion_score=memory.get("emotion_score", 0.0),
                    )
                    time_scores.append(time_score)

            avg_time_score = sum(time_scores) / len(time_scores) if time_scores else 0.0

            logger.info(
                f"衰减统计完成: 总计={total}, 永久={permanent_count}, 平均时间分={avg_time_score:.3f}"
            )

            return {
                "updated": 0,  # 不再更新数据库
                "failed": 0,
                "total": total,
                "permanent_count": permanent_count,
                "avg_time_score": avg_time_score,
                "mode": "realtime",  # 标记为实时计算模式
            }
        except Exception as e:
            logger.error(f"统计衰减值失败: {e}", exc_info=True)
            return {"updated": 0, "failed": 0, "total": 0, "error": str(e)}

    def get_decay_statistics(self, workspace_id: str = "default") -> Dict:
        from backend.core.memory.decay import DecayCalculator

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM memories WHERE is_deleted = FALSE AND workspace_id = ?",
            (workspace_id,),
        )
        total = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT importance_score, COUNT(*)
            FROM memories
            WHERE is_deleted = FALSE AND workspace_id = ?
            GROUP BY importance_score
        """,
            (workspace_id,),
        )
        distribution = {row[0]: row[1] for row in cursor.fetchall()}

        decay_calculator = DecayCalculator()

        cursor.execute(
            "SELECT * FROM memories WHERE is_deleted = FALSE AND workspace_id = ?", (workspace_id,)
        )
        rows = cursor.fetchall()

        avg_time_score = 0.0
        avg_importance_score = 0.0
        reactivation_stats = {"total": 0, "avg_count": 0.0}

        for row in rows:
            memory = self._row_to_memory(row)

            if not memory.get("permanent"):
                time_score = decay_calculator.calculate_time_score(memory, apply_reactivation=True)
                avg_time_score += time_score

            avg_importance_score += memory.get("importance_score", 0.0)

            reactivation_count = memory.get("reactivation_count", 0)
            if reactivation_count > 0:
                reactivation_stats["total"] += 1
                reactivation_stats["avg_count"] += reactivation_count

        non_permanent_count = total - sum(
            1 for row in rows if self._row_to_memory(row).get("permanent")
        )

        if non_permanent_count > 0:
            avg_time_score /= non_permanent_count

        if total > 0:
            avg_importance_score /= total

        if reactivation_stats["total"] > 0:
            reactivation_stats["avg_count"] /= reactivation_stats["total"]

        return {
            "total_memories": total,
            "non_permanent_count": non_permanent_count,
            "permanent_count": total - non_permanent_count,
            "avg_time_score": round(avg_time_score, 4),
            "avg_importance_score": round(avg_importance_score, 4),
            "importance_distribution": distribution,
            "reactivation_stats": {
                "reactivated_count": reactivation_stats["total"],
                "avg_reactivation_count": round(reactivation_stats["avg_count"], 2),
            },
        }

    def get_memory_context(self, memory_id: int, depth: int = 2) -> Dict:
        """获取记忆的上下文信息

        Args:
            memory_id: 记忆ID
            depth: 上下文深度（查找相关记忆的层数）

        Returns:
            包含记忆上下文信息的字典
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 获取目标记忆
            cursor.execute(
                "SELECT * FROM memories WHERE id = ? AND is_deleted = FALSE", (memory_id,)
            )
            row = cursor.fetchone()

            if not row:
                return {"status": "error", "message": "记忆不存在"}

            target_memory = self._row_to_memory(row)

            # 获取相关记忆（基于标签和时间接近性）
            context_memories = []
            target_tags = set(target_memory.get("tags", []))
            target_time = target_memory.get("created_at", "")

            cursor.execute(
                """
                SELECT * FROM memories 
                WHERE id != ? AND is_deleted = FALSE 
                ORDER BY ABS(julianday(created_at) - julianday(?)) ASC
                LIMIT ?
            """,
                (memory_id, target_time, depth * 5),
            )

            for related_row in cursor.fetchall():
                related = self._row_to_memory(related_row)
                related_tags = set(related.get("tags", []))

                # 计算相似度
                tag_overlap = len(target_tags & related_tags)
                if tag_overlap > 0 or len(context_memories) < depth:
                    context_memories.append(
                        {
                            "memory": related,
                            "relevance_score": tag_overlap,
                            "relation_type": "temporal" if tag_overlap == 0 else "semantic",
                        }
                    )

            # 按相关度排序
            context_memories.sort(key=lambda x: x["relevance_score"], reverse=True)
            context_memories = context_memories[:depth]

            return {
                "status": "success",
                "target_memory": target_memory,
                "context_depth": depth,
                "related_memories": context_memories,
                "total_related": len(context_memories),
            }

        except Exception as e:
            logger.error(f"获取记忆上下文失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def cleanup_old_sessions(self, days: int = 30) -> Dict:
        """清理过期的会话记忆

        Args:
            days: 多少天前的会话被视为过期

        Returns:
            清理结果统计
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 查找过期的短期记忆
            cursor.execute(
                """
                SELECT id FROM memories 
                WHERE type = 'short_term' 
                AND is_deleted = FALSE
                AND julianday('now') - julianday(created_at) > ?
            """,
                (days,),
            )

            old_ids = [row[0] for row in cursor.fetchall()]

            if not old_ids:
                return {
                    "status": "success",
                    "cleaned_count": 0,
                    "message": "没有需要清理的过期会话",
                }

            # 软删除这些记忆
            placeholders = ",".join("?" * len(old_ids))
            cursor.execute(
                f"""
                UPDATE memories 
                SET is_deleted = TRUE, deleted_at = ?
                WHERE id IN ({placeholders})
            """,
                (datetime.now().isoformat(), *old_ids),
            )

            conn.commit()

            logger.info(f"清理了 {len(old_ids)} 个过期会话记忆")

            return {
                "status": "success",
                "cleaned_count": len(old_ids),
                "days_threshold": days,
                "message": f"成功清理 {len(old_ids)} 个过期会话记忆",
            }

        except Exception as e:
            logger.error(f"清理过期会话失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return {"status": "error", "message": str(e)}

    def search_by_tag(self, tag: str, workspace_id: str = "default", limit: int = 50) -> List[Dict]:
        """通过标签搜索记忆

        Args:
            tag: 要搜索的标签
            workspace_id: 工作区ID
            limit: 返回结果数量限制

        Returns:
            匹配的记忆列表
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 使用 JSON 搜索标签
            cursor.execute(
                """
                SELECT * FROM memories 
                WHERE is_deleted = FALSE 
                AND workspace_id = ?
                AND tags LIKE ?
                ORDER BY importance_score DESC, created_at DESC
                LIMIT ?
            """,
                (workspace_id, f'%"{tag}"%', limit),
            )

            results = []
            for row in cursor.fetchall():
                memory = self._row_to_memory(row)
                tags = memory.get("tags", [])
                if tag in tags:
                    results.append(memory)

            return results

        except Exception as e:
            logger.error(f"标签搜索失败: {e}", exc_info=True)
            return []

    def get_memory_timeline(self, workspace_id: str = "default", days: int = 30) -> Dict:
        """获取记忆时间线

        Args:
            workspace_id: 工作区ID
            days: 时间范围（天）

        Returns:
            按时间分组的记忆统计
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT 
                    date(created_at) as date,
                    COUNT(*) as count,
                    type,
                    AVG(importance_score) as avg_importance
                FROM memories 
                WHERE is_deleted = FALSE 
                AND workspace_id = ?
                AND julianday('now') - julianday(created_at) <= ?
                GROUP BY date(created_at), type
                ORDER BY date DESC
            """,
                (workspace_id, days),
            )

            timeline = {}
            for row in cursor.fetchall():
                date_str = row[0]
                if date_str not in timeline:
                    timeline[date_str] = {"total": 0, "types": {}, "avg_importance": 0.0}

                timeline[date_str]["types"][row[2]] = row[1]
                timeline[date_str]["total"] += row[1]
                timeline[date_str]["avg_importance"] = round(row[3], 4) if row[3] else 0.0

            return {
                "status": "success",
                "days": days,
                "timeline": timeline,
                "total_days": len(timeline),
            }

        except Exception as e:
            logger.error(f"获取时间线失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def get_memory_statistics(self, workspace_id: str = "default") -> Dict:
        """获取记忆统计信息

        Args:
            workspace_id: 工作区ID

        Returns:
            详细的记忆统计数据
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 基础统计
            cursor.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN type = 'long_term' THEN 1 ELSE 0 END) as long_term,
                    SUM(CASE WHEN type = 'short_term' THEN 1 ELSE 0 END) as short_term,
                    SUM(CASE WHEN permanent = TRUE THEN 1 ELSE 0 END) as permanent,
                    AVG(importance_score) as avg_importance,
                    AVG(emotion_score) as avg_emotion
                FROM memories 
                WHERE is_deleted = FALSE AND workspace_id = ?
            """,
                (workspace_id,),
            )

            row = cursor.fetchone()

            # 标签统计
            cursor.execute(
                """
                SELECT tags FROM memories 
                WHERE is_deleted = FALSE AND workspace_id = ?
            """,
                (workspace_id,),
            )

            tag_counts = {}
            for tag_row in cursor.fetchall():
                try:
                    tags = json.loads(tag_row[0]) if tag_row[0] else []
                    for tag in tags:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1
                except:
                    pass

            # 获取热门标签
            top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

            return {
                "status": "success",
                "workspace_id": workspace_id,
                "total_memories": row[0] or 0,
                "by_type": {
                    "long_term": row[1] or 0,
                    "short_term": row[2] or 0,
                    "permanent": row[3] or 0,
                },
                "avg_importance_score": round(row[4], 4) if row[4] else 0.0,
                "avg_emotion_score": round(row[5], 4) if row[5] else 0.0,
                "top_tags": top_tags,
                "total_unique_tags": len(tag_counts),
            }

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def get_session_memories(self, session_id: str, limit: int = 100) -> List[Dict]:
        """获取特定会话的记忆

        Args:
            session_id: 会话ID
            limit: 返回结果数量限制

        Returns:
            会话相关的记忆列表
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 从 audit_logs 中查找会话相关的记忆
            cursor.execute(
                """
                SELECT m.* FROM memories m
                JOIN audit_logs al ON m.id = al.memory_id
                WHERE al.session_id = ?
                AND m.is_deleted = FALSE
                ORDER BY al.timestamp DESC
                LIMIT ?
            """,
                (session_id, limit),
            )

            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_memory(row))

            return results

        except Exception as e:
            logger.error(f"获取会话记忆失败: {e}", exc_info=True)
            return []

    def batch_update_tags(
        self,
        memory_ids: List[int],
        tags: List[str],
        operation: str = "add",
        agent_id: str = "default",
    ) -> Dict:
        """批量更新记忆标签

        Args:
            memory_ids: 记忆ID列表
            tags: 标签列表
            operation: 操作类型 (add/remove/set)
            agent_id: Agent ID，用于指定记忆表

        Returns:
            更新结果
        """
        table_name = self._get_table_name(agent_id)
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            updated_count = 0
            failed_count = 0

            for memory_id in memory_ids:
                try:
                    cursor.execute(
                        f"SELECT tags FROM {table_name} WHERE id = ? AND is_deleted = FALSE",
                        (memory_id,),
                    )
                    row = cursor.fetchone()

                    if not row:
                        failed_count += 1
                        continue

                    try:
                        current_tags = set(json.loads(row[0]) if row[0] else [])
                    except:
                        current_tags = set()

                    if operation == "add":
                        current_tags.update(tags)
                    elif operation == "remove":
                        current_tags.difference_update(tags)
                    elif operation == "set":
                        current_tags = set(tags)

                    new_tags = list(current_tags)

                    cursor.execute(
                        f"""
                        UPDATE {table_name} 
                        SET tags = ?, updated_at = ?
                        WHERE id = ?
                    """,
                        (
                            json.dumps(new_tags, ensure_ascii=False),
                            datetime.now().isoformat(),
                            memory_id,
                        ),
                    )

                    updated_count += 1
                except Exception as e:
                    logger.warning(f"更新记忆 {memory_id} 标签失败: {e}")
                    failed_count += 1

            conn.commit()

            logger.info(f"批量更新标签: 成功 {updated_count} 条, 失败 {failed_count} 条")

            return {
                "status": "success",
                "updated_count": updated_count,
                "failed_count": failed_count,
                "operation": operation,
                "tags": tags,
            }

        except Exception as e:
            logger.error(f"批量更新标签失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return {"status": "error", "message": str(e)}

    def batch_archive_memories(self, memory_ids: List[int], agent_id: str = "default") -> Dict:
        """批量归档记忆

        Args:
            memory_ids: 记忆ID列表
            agent_id: Agent ID，用于指定记忆表

        Returns:
            归档结果
        """
        table_name = self._get_table_name(agent_id)
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            archived_count = 0
            failed_count = 0
            now = datetime.now().isoformat()

            for memory_id in memory_ids:
                try:
                    # 将记忆标记为归档状态（通过设置 archived_at 字段）
                    cursor.execute(
                        f"""
                        UPDATE {table_name} 
                        SET archived_at = ?, updated_at = ?
                        WHERE id = ? AND is_deleted = FALSE
                    """,
                        (now, now, memory_id),
                    )

                    if cursor.rowcount > 0:
                        archived_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.warning(f"归档记忆 {memory_id} 失败: {e}")
                    failed_count += 1

            conn.commit()

            logger.info(f"批量归档: 成功 {archived_count} 条, 失败 {failed_count} 条")

            return {
                "status": "success",
                "archived_count": archived_count,
                "failed_count": failed_count,
            }

        except Exception as e:
            logger.error(f"批量归档失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return {"status": "error", "message": str(e)}

    def get_memories_by_type(
        self, memory_type: str, workspace_id: str = "default", limit: int = 100
    ) -> List[Dict]:
        """按类型获取记忆

        Args:
            memory_type: 记忆类型 (long_term/short_term/permanent)
            workspace_id: 工作区ID
            limit: 返回结果数量限制

        Returns:
            指定类型的记忆列表
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if memory_type == "permanent":
                cursor.execute(
                    """
                    SELECT * FROM memories 
                    WHERE permanent = TRUE 
                    AND is_deleted = FALSE
                    AND workspace_id = ?
                    ORDER BY importance_score DESC
                    LIMIT ?
                """,
                    (workspace_id, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM memories 
                    WHERE type = ? 
                    AND is_deleted = FALSE
                    AND workspace_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (memory_type, workspace_id, limit),
                )

            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_memory(row))

            return results

        except Exception as e:
            logger.error(f"按类型获取记忆失败: {e}", exc_info=True)
            return []

    def get_memory_relationships(self, memory_id: int) -> Dict:
        """获取记忆的关系网络

        Args:
            memory_id: 记忆ID

        Returns:
            记忆关系信息
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 获取目标记忆
            cursor.execute(
                "SELECT * FROM memories WHERE id = ? AND is_deleted = FALSE", (memory_id,)
            )
            row = cursor.fetchone()

            if not row:
                return {"status": "error", "message": "记忆不存在"}

            target = self._row_to_memory(row)
            target_tags = set(target.get("tags", []))

            # 查找相关记忆
            relationships = []

            # 基于标签的相关性
            cursor.execute(
                """
                SELECT * FROM memories 
                WHERE id != ? AND is_deleted = FALSE
            """,
                (memory_id,),
            )

            for related_row in cursor.fetchall():
                related = self._row_to_memory(related_row)
                related_tags = set(related.get("tags", []))

                common_tags = target_tags & related_tags
                if common_tags:
                    relationships.append(
                        {
                            "memory_id": related["id"],
                            "relation_type": "tag_similarity",
                            "strength": len(common_tags),
                            "common_tags": list(common_tags),
                        }
                    )

            # 按关系强度排序
            relationships.sort(key=lambda x: x["strength"], reverse=True)

            return {
                "status": "success",
                "memory_id": memory_id,
                "relationships": relationships[:20],  # 限制返回数量
                "total_relationships": len(relationships),
            }

        except Exception as e:
            logger.error(f"获取记忆关系失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def get_memories_by_emotion(
        self, emotion_range: Tuple[float, float], workspace_id: str = "default", limit: int = 50
    ) -> List[Dict]:
        """按情感分数范围获取记忆

        Args:
            emotion_range: 情感分数范围 (min, max)
            workspace_id: 工作区ID
            limit: 返回结果数量限制

        Returns:
            符合条件的记忆列表
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            min_emotion, max_emotion = emotion_range

            cursor.execute(
                """
                SELECT * FROM memories 
                WHERE emotion_score >= ? 
                AND emotion_score <= ?
                AND is_deleted = FALSE
                AND workspace_id = ?
                ORDER BY ABS(emotion_score - ?) ASC
                LIMIT ?
            """,
                (min_emotion, max_emotion, workspace_id, (min_emotion + max_emotion) / 2, limit),
            )

            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_memory(row))

            return results

        except Exception as e:
            logger.error(f"按情感获取记忆失败: {e}", exc_info=True)
            return []
