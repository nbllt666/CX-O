"""
SQLite 数据库连接管理
"""

import sqlite3
import threading
import logging
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

from server.core.graph.config import GraphConfig, get_graph_config

logger = logging.getLogger(__name__)


class Database:
    """SQLite 数据库连接管理器"""

    def __init__(self, config: GraphConfig = None):
        self.config = config or get_graph_config()
        self.db_path = self.config.database_path
        self.timeout = self.config.timeout
        self._lock = threading.Lock()
        self._init_lock = threading.Lock()
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.timeout,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            self._local.connection = conn
        return self._local.connection

    @contextmanager
    def get_cursor(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise
        finally:
            cursor.close()

    def initialize(self) -> None:
        with self._init_lock:
            self._create_tables()

    def _create_tables(self) -> None:
        # 注意：CREATE INDEX ... ON nodes(agent_id) 必须在 agent_id 列存在之后才能执行。
        # 旧版 schema 没有 agent_id 列，CREATE TABLE IF NOT EXISTS 会跳过现有表，
        # 此时 CREATE INDEX agent_id 会报 "no such column"。
        # 因此先 CREATE TABLE（不含 agent_id 索引），再迁移补列，最后统一建索引。
        with self.get_cursor() as cursor:
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    properties TEXT NOT NULL DEFAULT '{}',
                    text_content TEXT,
                    vector_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    agent_id VARCHAR(100) DEFAULT 'default'
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
                CREATE INDEX IF NOT EXISTS idx_nodes_created_at ON nodes(created_at);

                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    properties TEXT NOT NULL DEFAULT '{}',
                    text_content TEXT,
                    vector_id TEXT,
                    created_at TEXT NOT NULL,
                    agent_id VARCHAR(100) DEFAULT 'default',
                    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
                CREATE INDEX IF NOT EXISTS idx_edges_relation_type ON edges(relation_type);

                CREATE TABLE IF NOT EXISTS traversal_paths (
                    path_id TEXT PRIMARY KEY,
                    node_ids TEXT NOT NULL,
                    edge_ids TEXT,
                    depth INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            logger.info("图数据库表结构创建完成")

        # 迁移：为旧版 schema（无 agent_id 列）补充字段 + 建索引。
        # 注意：原 CXHMS 代码用 try/except SELECT agent_id 检测，但 get_cursor 的 except 会
        # 重新抛出异常，导致迁移逻辑永远不执行。改用 PRAGMA table_info 反射式检测列是否存在。
        self._migrate_add_agent_id_column()

    def _migrate_add_agent_id_column(self) -> None:
        """检测并补充 nodes/edges 的 agent_id 列 + 索引（CXHMS 旧版 schema 兼容）。"""
        for table in ("nodes", "edges"):
            with self.get_cursor() as cursor:
                cursor.execute(f"PRAGMA table_info({table})")
                columns = [row["name"] for row in cursor.fetchall()]
            if "agent_id" not in columns:
                with self.get_cursor() as cursor:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN agent_id VARCHAR(100) DEFAULT 'default'")
                logger.info(f"图数据库迁移：{table} 表添加 agent_id 字段")
            with self.get_cursor() as cursor:
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_agent_id ON {table}(agent_id)")

    def health_check(self) -> bool:
        try:
            with self.get_cursor() as cursor:
                cursor.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"数据库健康检查失败: {e}")
            return False

    def close(self) -> None:
        """关闭当前线程的数据库连接。"""
        if hasattr(self._local, 'connection') and self._local.connection:
            try:
                self._local.connection.close()
            except Exception as e:
                logger.warning(f"关闭数据库连接失败: {e}")
            finally:
                self._local.connection = None

    def execute(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def execute_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        results = self.execute(query, params)
        return results[0] if results else None

    def execute_modify(self, query: str, params: tuple = ()) -> int:
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            return cursor.rowcount

    def execute_many(self, query: str, params_list: List[tuple]) -> int:
        with self.get_cursor() as cursor:
            cursor.executemany(query, params_list)
            return cursor.rowcount

    def transaction(self, operations: List[Tuple[str, tuple]]) -> None:
        """在单个事务中依次执行多条写入操作。"""
        with self.get_cursor() as cursor:
            for query, params in operations:
                cursor.execute(query, params)


_db_instances: Dict[str, "Database"] = {}
_db_lock = threading.Lock()


def get_database(config: GraphConfig = None, agent_id: str = "default") -> Database:
    """获取数据库实例（按 agent_id 注册表）。

    当 ``agent_id`` 不在注册表中时，按需创建新的 :class:`Database`，
    使用 per-agent 的 db_path，调用 :meth:`Database.initialize` 创建 schema，
    存入注册表并返回。未提供 ``agent_id`` 时使用 ``'default'``。
    """
    if agent_id not in _db_instances:
        with _db_lock:
            if agent_id not in _db_instances:
                agent_config = config or get_graph_config(agent_id=agent_id)
                db = Database(agent_config)
                db.initialize()
                _db_instances[agent_id] = db
                logger.info(f"图数据库已按需创建: agent_id={agent_id}, path={db.db_path}")
    return _db_instances[agent_id]


def get_database_if_exists(agent_id: str = "default") -> Optional[Database]:
    """返回已注册的数据库实例，不存在时返回 None（不创建）。"""
    return _db_instances.get(agent_id)


def remove_database(agent_id: str) -> Optional[Database]:
    """从注册表移除并关闭对应 agent 的数据库实例，返回被移除的实例。"""
    with _db_lock:
        db = _db_instances.pop(agent_id, None)
    if db is not None:
        try:
            db.close()
        except Exception as e:
            logger.warning(f"关闭图数据库失败 (agent_id={agent_id}): {e}")
    return db
