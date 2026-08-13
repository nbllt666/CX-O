"""MemoryManager mixin: DB infrastructure (schema init, connection pool, cleanup, shutdown).

Extracted from manager.py as part of H5 mixin split.
"""
import re
import sqlite3
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING


from ._common import logger

if TYPE_CHECKING:
    pass


class _MemoryDBMixin:
    """DB infrastructure mixin: schema init, connection pool, cleanup, shutdown."""

    def _check_deprecated_config(self):
        """检查并警告已弃用的配置"""
        try:
            from server.config import get_settings
            settings = get_settings()
            if hasattr(settings, 'config') and hasattr(settings.config, 'memory'):
                memory_config = settings.config.memory
                vector_backend = getattr(memory_config, 'vector_backend', None)

                deprecated_backends = ['chroma', 'milvus_lite', 'qdrant']
                if vector_backend and vector_backend.lower() in deprecated_backends:
                    logger.warning(
                        f"检测到已弃用的向量存储后端配置: vector_backend='{vector_backend}'。"
                        f"Chroma、Milvus Lite 和 Qdrant 已不再支持。"
                        f"请更改为 'weaviate' 或 'weaviate_embedded'。"
                        f"详见配置迁移文档。"
                    )

                if hasattr(memory_config, 'milvus_lite') and memory_config.milvus_lite:
                    logger.warning(
                        "检测到已弃用的 Milvus Lite 配置。"
                        "Milvus Lite 已不再支持，请更改为使用 Weaviate。"
                    )

                if hasattr(memory_config, 'qdrant') and memory_config.qdrant:
                    logger.warning(
                        "检测到已弃用的 Qdrant 配置。"
                        "Qdrant 已不再支持，请更改为使用 Weaviate。"
                    )

                if hasattr(memory_config, 'chroma') and memory_config.chroma:
                    logger.warning(
                        "检测到已弃用的 Chroma 配置。"
                        "Chroma 已不再支持，请更改为使用 Weaviate。"
                    )
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"配置兼容性检查跳过: {e}")

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
        # 注：原第二道 regex 回退分支已移除——经第一道 re.sub 清洗后 safe_agent_id
        # 仅含 [a-zA-Z0-9_]，再经上面的前缀补全，必满足 ^[a-zA-Z_][a-zA-Z0-9_]*$，
        # 故回退分支不可达，属死代码
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
                    agent_id VARCHAR(100) DEFAULT 'default'
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
                from server.core.memory.vector_store import create_vector_store

                backend = config.get("backend", "weaviate")
                if backend not in ["weaviate", "weaviate_embedded"]:
                    logger.warning(f"不支持的向量存储后端: {backend}，仅支持 weaviate 和 weaviate_embedded")
                    return

                vector_store = create_vector_store(
                    backend=backend,
                    host=config.get("weaviate_host", "localhost"),
                    port=config.get("weaviate_port", 8080),
                    grpc_port=config.get("weaviate_grpc_port", 50051),
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

        # 停止向量化队列
        if self.vectorization_queue:
            self.vectorization_queue.stop()
            self.vectorization_queue = None

        self.close_all_connections()

        if self._vector_store:
            try:
                self._vector_store.close()
            except Exception as e:
                logger.warning(f"关闭向量存储失败：{e}")
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
        current_time = time.time()

        with self._lock:
            if thread_id in self._connection_pool:
                conn_info = self._connection_pool[thread_id]
                if isinstance(conn_info, dict):
                    conn = conn_info["connection"]
                    last_used = conn_info.get("last_used", 0)
                else:
                    conn = conn_info
                    last_used = current_time

                try:
                    conn.execute("SELECT 1")

                    if isinstance(conn_info, dict):
                        conn_info["last_used"] = current_time
                        conn_info["use_count"] = conn_info.get("use_count", 0) + 1

                        if current_time - last_used > 300 and conn_info.get("use_count", 0) > 100:
                            conn.close()
                            del self._connection_pool[thread_id]
                            conn = None
                        else:
                            return conn
                    else:
                        return conn
                except Exception:
                    logger.warning(
                        "复用连接失败，将重建: thread_id=%s", thread_id, exc_info=True
                    )

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
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.execute("PRAGMA busy_timeout=30000")

        connection_info = {
            "connection": conn, 
            "last_used": current_time,
            "use_count": 0
        }

        with self._lock:
            self._connection_pool[thread_id] = connection_info

        return conn

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
