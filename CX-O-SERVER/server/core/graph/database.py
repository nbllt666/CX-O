"""
SQLite 数据库连接管理
"""

import sqlite3
import threading
import logging
import re
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

from server.core.graph.config import GraphConfig, get_graph_config

logger = logging.getLogger(__name__)

# 第四轮全面体检 §6.3 第12条：edges 表唯一 DDL 真相源（建表与 FK schema 迁移共用，
# 防止两处定义漂移）。外键声明采用"不带 ON DELETE 子句的普通 RESTRICT"——删除仍被
# 边引用的节点时 SQLite 直接 IntegrityError，应用层由 nodes.delete 的 cascade 参数
# 决定"显式先删边后删节点（全删）"或"有边则明确拒绝"，取消旧的静默悬挂边行为。
_EDGES_TABLE_DDL = """
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
        FOREIGN KEY (source_id) REFERENCES nodes(id),
        FOREIGN KEY (target_id) REFERENCES nodes(id)
    );
"""


class Database:
    """SQLite 数据库连接管理器"""

    def __init__(self, config: GraphConfig = None):
        self.config = config or get_graph_config()
        self.db_path = self.config.database_path
        self.timeout = self.config.timeout
        self._lock = threading.Lock()
        self._init_lock = threading.Lock()
        self._local = threading.local()
        # D1: 全局连接登记（check_same_thread=False 使每个线程持有独立连接，
        # 仅关闭当前线程的 thread-local 会让其它线程的连接永不关闭）。
        self._conn_lock = threading.Lock()
        self._all_connections: "set" = set()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.timeout,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # 第四轮全面体检 §6.3 第12条：统一开启外键约束（对齐 memory db_mixin /
            # session store / context manager 的连接级做法），使 DDL 中 FOREIGN KEY
            # 真正生效，杜绝悬挂边。每个新建 thread-local 连接都必须设置。
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.connection = conn
            with self._conn_lock:
                self._all_connections.add(conn)
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
        # 注意：脚本含 DEFAULT '{}' 字面量，不可改为 f-string（{} 会被误解析），
        # 因此 edges DDL 以独立 executescript 段落执行（唯一真相源 _EDGES_TABLE_DDL）。
        with self.get_cursor() as cursor:
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
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
            """)
            cursor.executescript(self._edges_ddl())
            cursor.executescript("""
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
        self._migrate_add_name_column()
        # 第四轮 §6.3 第12条：edges 表外键 schema 迁移（补齐缺失 FK / 把旧
        # ON DELETE CASCADE 重建为 RESTRICT 形态）。放在列迁移之后执行，
        # 保证重建复制数据时旧表已具备全部九列。
        self._migrate_edges_foreign_keys()

    @classmethod
    def _edges_ddl(cls) -> str:
        """返回 edges 建表 DDL（唯一真相源，见模块级 _EDGES_TABLE_DDL）。"""
        return _EDGES_TABLE_DDL

    def _migrate_add_name_column(self) -> None:
        """检测并补充 nodes 表的 name 列（旧版 schema 兼容，幂等）。

        与 agent_id 迁移同一风格：先用 PRAGMA table_info 反射检测列是否存在，
        不存在才 ALTER TABLE ADD COLUMN。new table 的 CREATE TABLE 已含 name 列，
        因此该迁移对新建库零操作，仅对旧库补列。
        """
        with self.get_cursor() as cursor:
            cursor.execute("PRAGMA table_info(nodes)")
            columns = [row["name"] for row in cursor.fetchall()]
        if "name" not in columns:
            with self.get_cursor() as cursor:
                cursor.execute("ALTER TABLE nodes ADD COLUMN name TEXT NOT NULL DEFAULT ''")
            logger.info("图数据库迁移：nodes 表添加 name 字段")

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

    # ---- edges 外键 schema 迁移（第四轮全面体检 §6.3 第12条）----

    _EDGES_COPY_COLUMNS = (
        "id, source_id, target_id, relation_type, properties, "
        "text_content, vector_id, created_at, agent_id"
    )
    _EDGES_FK_MIGRATE_OLD_NAME = "edges_fk_migrate_old"

    @staticmethod
    def _edges_ddl_up_to_date(ddl: str) -> bool:
        """判断 sqlite_master 中 edges 建表 SQL 是否已是目标 FK 形态（幂等检测）。

        目标形态：source_id/target_id 均以 ``FOREIGN KEY ... REFERENCES nodes(id)``
        显式声明，且不带 ``ON DELETE CASCADE``——无 ON DELETE 子句即默认 RESTRICT，
        删除仍被引用的节点将 IntegrityError，由应用层 nodes.delete(cascade=...) 决定
        "显式先删边再删节点"或"有边明确拒绝"。缺任一 FK 或含旧 CASCADE 均判定需迁移。
        """
        normalized = re.sub(r"\s+", " ", ddl).upper().replace("NODES (", "NODES(")
        for col in ("SOURCE_ID", "TARGET_ID"):
            if f"FOREIGN KEY ({col}) REFERENCES NODES(ID)" not in normalized:
                return False
        return "ON DELETE CASCADE" not in normalized

    def _migrate_edges_foreign_keys(self) -> None:
        """edges 表轻量 schema migration：补齐/校正 FOREIGN KEY 声明（事务化 + 幂等）。

        CREATE TABLE IF NOT EXISTS 无法修改已存在的旧表；盘上存量库可能出现两类旧
        结构：(a) 完全无 FOREIGN KEY 子句；(b) 含旧契约 ON DELETE CASCADE。本方法
        读取 sqlite_master 中的建表 SQL 检测，不达标则按 rename → create new(FK
        RESTRICT) → copy data → drop old 四步重建，全程单个显式事务，任一步失败
        整体回滚不留半成品（残留的 rename 中间表也在事务内先清理）。检测达标则零
        操作直接返回——重启重复初始化天然幂等跳过。

        存量悬挂边兼容：旧行为（cascade=False 静默保留悬挂边）可能已在盘中产生
        source/target 不指向任何节点的脏边；复制阶段按新完整性策略剔除悬挂边并
        warning 记录数量，避免携带违反 FK 的数据导致迁移整体失败。
        """
        rows = self.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='edges'")
        if not rows or not (rows[0].get("sql") or ""):
            return
        if self._edges_ddl_up_to_date(rows[0]["sql"]):
            return

        create_new_sql = self._edges_ddl().replace("IF NOT EXISTS ", "")
        old_name = self._EDGES_FK_MIGRATE_OLD_NAME
        copy_cols = self._EDGES_COPY_COLUMNS
        required_cols = {c.strip() for c in copy_cols.replace("\n", "").split(",")}

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor.execute("PRAGMA table_info(edges)")
            existing_cols = {row["name"] for row in cursor.fetchall()}
            missing = required_cols - existing_cols
            if missing:
                raise RuntimeError(f"edges 表缺少列 {sorted(missing)}，外键迁移无法安全进行")

            # 迁移前统计悬挂边（仅用于日志留痕），随后一律按新契约剔除。
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM edges e "
                "WHERE NOT EXISTS(SELECT 1 FROM nodes n WHERE n.id = e.source_id) "
                "   OR NOT EXISTS(SELECT 1 FROM nodes n WHERE n.id = e.target_id)"
            )
            dangling_cnt = cursor.fetchone()["cnt"]

            cursor.execute(f"DROP TABLE IF EXISTS {old_name}")  # 清理历史失败残留（若有）
            cursor.execute(f"ALTER TABLE edges RENAME TO {old_name}")
            cursor.execute(create_new_sql)
            cursor.execute(
                f"INSERT INTO edges ({copy_cols}) SELECT {copy_cols} FROM {old_name} e "
                "WHERE EXISTS(SELECT 1 FROM nodes n WHERE n.id = e.source_id) "
                "AND EXISTS(SELECT 1 FROM nodes n WHERE n.id = e.target_id)"
            )
            kept_cnt = cursor.execute("SELECT COUNT(*) AS cnt FROM edges").fetchone()["cnt"]
            cursor.execute(f"DROP TABLE {old_name}")
            # DROP 旧表会连带删除附着的索引，此处在新表上统一重建。
            for index_sql in (
                "CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)",
                "CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)",
                "CREATE INDEX IF NOT EXISTS idx_edges_relation_type ON edges(relation_type)",
                "CREATE INDEX IF NOT EXISTS idx_edges_agent_id ON edges(agent_id)",
            ):
                cursor.execute(index_sql)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"图数据库迁移失败：edges 表外键重建已回滚: {e}")
            raise
        finally:
            cursor.close()

        if dangling_cnt:
            logger.warning(
                f"图数据库迁移清理 {dangling_cnt} 条悬挂边（旧 cascade=False 契约遗留），"
                f"有效边 {kept_cnt} 条完整保留"
            )
        logger.info("图数据库迁移完成：edges 表外键声明升级为 REFERENCES nodes(id)（默认 RESTRICT，无级联）")

    def health_check(self) -> bool:
        try:
            with self.get_cursor() as cursor:
                cursor.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"数据库健康检查失败: {e}")
            return False

    def close(self) -> None:
        """关闭全部线程缓存过的数据库连接（对齐 core/context/manager.py 模式）。

        旧实现仅关闭当前线程的 thread-local 连接，其他线程各自持有的
        check_same_thread=False 连接永不关闭 → 跨线程资源泄漏。
        """
        with self._conn_lock:
            conns = list(self._all_connections)
            self._all_connections.clear()
        for conn in conns:
            try:
                conn.close()
            except Exception as e:
                logger.warning(f"关闭数据库连接失败: {e}")
        if hasattr(self._local, 'connection'):
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


def close_all_databases() -> None:
    """关闭并清空全部已注册的图数据库实例（服务 shutdown 时调用）。

    第五轮 M5：per-agent 图库由依赖层懒创建，若关闭段只关 services 上的
    显式引用（恒为 None，死代码），懒创建的实例从不 close，重启间句柄泄漏。
    统一按注册表逐一关闭。
    """
    with _db_lock:
        agents = list(_db_instances.keys())
    for agent_id in agents:
        remove_database(agent_id)
