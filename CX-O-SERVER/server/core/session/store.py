"""会话存储——会话与消息的 SQLite 持久化读写。

H2 修复（第四轮体检 E组）：本存储为 CXO-Tuner evolution 集成出口专属，
默认库迁移至独立文件 ``data/tuner_sessions.db``，不再与 ContextManager 的
聊天会话库 ``data/sessions.db``（10列结构）共用同一 SQLite 文件。
此前两套建表语句（13列 vs 10列）先后写同一文件导致"先建者赢"，
另一方 SELECT * 位置索引串位。迁移后所有权格局：
  - ``data/sessions.db``      -> 唯一 owner: server.core.context.manager.ContextManager
  - ``data/tuner_sessions.db``-> 唯一 owner: server.core.session.store.SessionStore
"""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from server.config import _resolve_data_path
from server.core.logging_config import get_contextual_logger
from server.core.utils import run_io

from .models import Session, SessionMessage, SessionStats, SessionType

logger = get_contextual_logger(__name__)

# Tuner 会话独立库默认相对路径（经 _resolve_data_path 归一化为项目根绝对路径）
DEFAULT_TUNER_SESSIONS_DB = "data/tuner_sessions.db"
# 环境覆盖先例对齐 server/core/graph/config.py（裸名 env + 路径归一化）
TUNER_SESSION_DB_ENV = "TUNER_SESSION_DB"


def get_tuner_session_db_path() -> str:
    """解析 Tuner 会话库路径。

    优先级：TUNER_SESSION_DB 环境变量 > 项目根归一化的 data/tuner_sessions.db。
    绝对路径原样返回，相对路径按项目根解析（复用 server/config.py 归一化机制）。
    """
    env_path = os.getenv(TUNER_SESSION_DB_ENV)
    if env_path:
        return _resolve_data_path(env_path)
    return _resolve_data_path(DEFAULT_TUNER_SESSIONS_DB)


class SessionStore:
    """持久化会话存储

    使用 SQLite 存储会话数据，支持会话过期管理和自动清理。
    默认使用独立的 data/tuner_sessions.db（H2 双 schema 收敛修复）。
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = get_tuner_session_db_path() if db_path is None else db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(self.db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        # H2 条目5: 开启外键约束，硬删 sessions 父行时级联删除 messages 子行
        # （本模块自建的 messages 表定义带 ON DELETE CASCADE）
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """初始化数据库表"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 会话表
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id VARCHAR(36) PRIMARY KEY,
                    workspace_id VARCHAR(100) DEFAULT 'default',
                    title VARCHAR(500),
                    user_id VARCHAR(100),
                    session_type VARCHAR(20) DEFAULT 'chat',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    message_count INTEGER DEFAULT 0,
                    summary TEXT,
                    metadata TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    expires_at TIMESTAMP
                )
            """
            )

            # 消息表
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id VARCHAR(36) PRIMARY KEY,
                    session_id VARCHAR(36) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    content_type VARCHAR(20) DEFAULT 'text',
                    metadata TEXT,
                    tokens INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_deleted BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            """
            )

            # 创建索引
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id)",
                "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at)",
                "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)",
                "CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(is_active)",
                "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role)",
            ]
            for idx in indexes:
                cursor.execute(idx)

            conn.commit()
            logger.info(f"会话数据库初始化完成: {self.db_path}")

    def create_session(
        self,
        workspace_id: str = "default",
        title: str = "",
        user_id: Optional[str] = None,
        session_type: SessionType = SessionType.CHAT,
        metadata: Optional[Dict] = None,
        expires_in_days: Optional[int] = None,
    ) -> Session:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        now = datetime.now()

        expires_at = None
        if expires_in_days:
            expires_at = now + timedelta(days=expires_in_days)

        session = Session(
            id=session_id,
            workspace_id=workspace_id,
            title=title or "新对话",
            user_id=user_id,
            session_type=session_type,
            created_at=now,
            updated_at=now,
            last_accessed_at=now,
            metadata=metadata or {},
            expires_at=expires_at,
        )

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sessions (id, workspace_id, title, user_id, session_type,
                    created_at, updated_at, last_accessed_at, message_count, summary,
                    metadata, is_active, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    session.id,
                    session.workspace_id,
                    session.title,
                    session.user_id,
                    session.session_type.value,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                    session.last_accessed_at.isoformat(),
                    session.message_count,
                    session.summary,
                    json.dumps(session.metadata, ensure_ascii=False),
                    session.is_active,
                    session.expires_at.isoformat() if session.expires_at else None,
                ),
            )
            conn.commit()

        logger.info(f"会话已创建: id={session_id}, type={session_type.value}")
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()

            if row:
                # 写放大修复: 命中即更新 last_accessed_at。原实现调 _update_last_accessed
                # 另开一个完整连接周期 UPDATE+commit，每读一次多一次连接开销；
                # 现内联到当前连接同事务提交，读路径收敛为单连接周期。
                cursor.execute(
                    "UPDATE sessions SET last_accessed_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), session_id),
                )
                conn.commit()
                return self._row_to_session(row)
            return None

    def get_sessions(
        self,
        workspace_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_type: Optional[SessionType] = None,
        active_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Session]:
        """获取会话列表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM sessions WHERE 1=1"
            params = []

            if workspace_id:
                query += " AND workspace_id = ?"
                params.append(workspace_id)

            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)

            if session_type:
                query += " AND session_type = ?"
                params.append(session_type.value)

            if active_only:
                query += " AND is_active = TRUE"
                query += " AND (expires_at IS NULL OR expires_at > ?)"
                params.append(datetime.now().isoformat())

            query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_session(row) for row in rows]

    def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        metadata: Optional[Dict] = None,
        is_active: Optional[bool] = None,
        expires_in_days: Optional[int] = None,
    ) -> bool:
        """更新会话"""
        updates = []
        params = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)

        if summary is not None:
            updates.append("summary = ?")
            params.append(summary)

        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata, ensure_ascii=False))

        if is_active is not None:
            updates.append("is_active = ?")
            params.append(is_active)

        if expires_in_days is not None:
            expires_at = datetime.now() + timedelta(days=expires_in_days)
            updates.append("expires_at = ?")
            params.append(expires_at.isoformat())

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(session_id)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()

            success = cursor.rowcount > 0
            if success:
                logger.debug(f"会话已更新: id={session_id}")
            return success

    def delete_session(self, session_id: str, soft_delete: bool = True) -> bool:
        """删除会话"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if soft_delete:
                cursor.execute(
                    "UPDATE sessions SET is_active = FALSE, updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), session_id),
                )
            else:
                cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

            conn.commit()
            success = cursor.rowcount > 0

            if success:
                logger.info(f"会话已删除: id={session_id}, soft={soft_delete}")
            return success

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        content_type: str = "text",
        metadata: Optional[Dict] = None,
        tokens: int = 0,
    ) -> SessionMessage:
        """添加消息"""
        message_id = str(uuid.uuid4())
        now = datetime.now()

        message = SessionMessage(
            id=message_id,
            session_id=session_id,
            role=role,
            content=content,
            content_type=content_type,
            metadata=metadata or {},
            tokens=tokens,
            created_at=now,
        )

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 插入消息
            cursor.execute(
                """
                INSERT INTO messages (id, session_id, role, content, content_type,
                    metadata, tokens, created_at, is_deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    message.id,
                    message.session_id,
                    message.role,
                    message.content,
                    message.content_type,
                    json.dumps(message.metadata, ensure_ascii=False),
                    message.tokens,
                    message.created_at.isoformat(),
                    message.is_deleted,
                ),
            )

            # 更新会话消息计数和时间
            cursor.execute(
                """
                UPDATE sessions 
                SET message_count = message_count + 1, updated_at = ?, last_accessed_at = ?
                WHERE id = ?
            """,
                (now.isoformat(), now.isoformat(), session_id),
            )

            conn.commit()

        return message

    def get_messages(
        self, session_id: str, limit: int = 50, offset: int = 0, include_deleted: bool = False
    ) -> List[SessionMessage]:
        """获取消息列表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM messages WHERE session_id = ?"
            params = [session_id]

            if not include_deleted:
                query += " AND is_deleted = FALSE"

            query += " ORDER BY created_at ASC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_message(row) for row in rows]

    def delete_message(self, message_id: str, soft_delete: bool = True) -> bool:
        """删除消息。

        H2 条目3: 软删消息时同事务回减所属会话 message_count（下限 0），
        消除计数只增不减的漂移。
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if soft_delete:
                cursor.execute("UPDATE messages SET is_deleted = TRUE WHERE id = ?", (message_id,))
                if cursor.rowcount > 0:
                    cursor.execute(
                        """
                        UPDATE sessions
                        SET message_count = MAX(message_count - 1, 0), updated_at = ?
                        WHERE id = (SELECT session_id FROM messages WHERE id = ?)
                    """,
                        (datetime.now().isoformat(), message_id),
                    )
            else:
                cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))

            conn.commit()
            return cursor.rowcount > 0

    def get_expired_sessions(self) -> List[Session]:
        """获取已过期的会话"""
        now = datetime.now().isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM sessions 
                WHERE expires_at IS NOT NULL AND expires_at < ? AND is_active = TRUE
            """,
                (now,),
            )
            rows = cursor.fetchall()

            return [self._row_to_session(row) for row in rows]

    def cleanup_expired_sessions(self) -> int:
        """清理过期会话"""
        expired = self.get_expired_sessions()
        count = 0

        for session in expired:
            if self.delete_session(session.id, soft_delete=False):
                count += 1

        if count > 0:
            logger.info(f"已清理 {count} 个过期会话")
        return count

    def delete_sessions_last_accessed_before(self, cutoff: datetime, page_size: int = 500) -> int:
        """硬删最后访问时间早于 cutoff 的会话及其关联消息（游标分页）。

        H2 条目4: 取代旧的"SELECT 分页 + offset 前推"方案——删除后前推
        offset 会造成分页漂移、跳过未扫描会话。本实现固定谓词
        ``last_accessed_at < cutoff`` 反复取批，已删行不影响剩余集合的匹配性，
        天然无漂移；批次行数 < page_size 或空即终止。

        Args:
            cutoff: 截止时间（严格小于该时间的会话被删除）。
            page_size: 单批大小（默认 500，远低于 SQLite 变量参数上限）。

        Returns:
            删除的会话数量。
        """
        total = 0
        cutoff_iso = cutoff.isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            while True:
                cursor.execute(
                    "SELECT id FROM sessions WHERE last_accessed_at < ? LIMIT ?",
                    (cutoff_iso, page_size),
                )
                rows = cursor.fetchall()
                if not rows:
                    break
                ids = [r["id"] for r in rows]
                placeholders = ",".join("?" * len(ids))
                # 显式级联硬删关联消息：防老库 FK 未开/表定义无 CASCADE 时残留孤儿
                cursor.execute(
                    f"DELETE FROM messages WHERE session_id IN ({placeholders})", ids
                )
                cursor.execute(f"DELETE FROM sessions WHERE id IN ({placeholders})", ids)
                total += len(ids)
                if len(rows) < page_size:
                    break
            conn.commit()

        return total

    def get_statistics(self, workspace_id: Optional[str] = None) -> SessionStats:
        """获取统计信息"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 基础查询条件
            base_where = "WHERE 1=1"
            params = []
            if workspace_id:
                base_where += " AND workspace_id = ?"
                params.append(workspace_id)

            # 总会话数
            cursor.execute(f"SELECT COUNT(*) AS cnt FROM sessions {base_where}", params)
            total_sessions = cursor.fetchone()["cnt"]

            # 激活会话数
            cursor.execute(
                f"SELECT COUNT(*) AS cnt FROM sessions {base_where} AND is_active = TRUE", params
            )
            active_sessions = cursor.fetchone()["cnt"]

            # 过期会话数
            now = datetime.now().isoformat()
            cursor.execute(
                f"""SELECT COUNT(*) AS cnt FROM sessions {base_where}
                    AND expires_at IS NOT NULL AND expires_at < ?""",
                params + [now],
            )
            expired_sessions = cursor.fetchone()["cnt"]

            # 总消息数
            if workspace_id:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM messages m
                    JOIN sessions s ON m.session_id = s.id
                    WHERE s.workspace_id = ?
                """,
                    (workspace_id,),
                )
            else:
                cursor.execute("SELECT COUNT(*) AS cnt FROM messages")
            total_messages = cursor.fetchone()["cnt"]

            avg_messages = total_messages / total_sessions if total_sessions > 0 else 0

            return SessionStats(
                total_sessions=total_sessions,
                active_sessions=active_sessions,
                expired_sessions=expired_sessions,
                total_messages=total_messages,
                avg_messages_per_session=round(avg_messages, 2),
            )

    def _row_to_session(self, row) -> Session:
        """将数据库行转换为 Session 对象。

        H2 条目1: 使用列名访问（row_factory=sqlite3.Row），消除 SELECT *
        位置索引在多 schema 共存/演进时串位的根因。
        """
        return Session(
            id=row["id"],
            workspace_id=row["workspace_id"],
            title=row["title"],
            user_id=row["user_id"],
            session_type=SessionType(row["session_type"]) if row["session_type"] else SessionType.CHAT,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_accessed_at=datetime.fromisoformat(row["last_accessed_at"]),
            message_count=row["message_count"],
            summary=row["summary"],
            metadata=json.loads(row["metadata"] or "{}"),
            is_active=bool(row["is_active"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
        )

    def _row_to_message(self, row) -> SessionMessage:
        """将数据库行转换为 SessionMessage 对象（列名访问，见 _row_to_session 注）。"""
        return SessionMessage(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            content_type=row["content_type"],
            metadata=json.loads(row["metadata"] or "{}"),
            tokens=row["tokens"],
            created_at=datetime.fromisoformat(row["created_at"]),
            is_deleted=bool(row["is_deleted"]),
        )

    # ------------------------------------------------------------------ #
    # 异步变体：把同步 sqlite 移入有界 IO 线程池，供 async 热路径调用。
    # 每个方法均委托给同名同步实现，返回值与异常语义保持一致。
    # ------------------------------------------------------------------ #
    async def create_session_async(self, *args, **kwargs) -> Session:
        return await run_io(self.create_session, *args, **kwargs)

    async def get_session_async(self, *args, **kwargs) -> Optional[Session]:
        return await run_io(self.get_session, *args, **kwargs)

    async def get_sessions_async(self, *args, **kwargs) -> List[Session]:
        return await run_io(self.get_sessions, *args, **kwargs)

    async def update_session_async(self, *args, **kwargs) -> bool:
        return await run_io(self.update_session, *args, **kwargs)

    async def delete_session_async(self, *args, **kwargs) -> bool:
        return await run_io(self.delete_session, *args, **kwargs)

    async def add_message_async(self, *args, **kwargs) -> SessionMessage:
        return await run_io(self.add_message, *args, **kwargs)

    async def get_messages_async(self, *args, **kwargs) -> List[SessionMessage]:
        return await run_io(self.get_messages, *args, **kwargs)

    async def delete_message_async(self, *args, **kwargs) -> bool:
        return await run_io(self.delete_message, *args, **kwargs)

    async def get_statistics_async(self, *args, **kwargs) -> SessionStats:
        return await run_io(self.get_statistics, *args, **kwargs)

    async def cleanup_expired_sessions_async(self, *args, **kwargs) -> int:
        return await run_io(self.cleanup_expired_sessions, *args, **kwargs)


# 全局会话存储实例
_session_store: Optional[SessionStore] = None


def get_session_store(db_path: Optional[str] = None) -> SessionStore:
    """获取全局会话存储实例。

    H2 修复：db_path 缺省时解析为独立的 Tuner 会话库（TUNER_SESSION_DB
    环境变量优先，否则项目根 data/tuner_sessions.db），与 ContextManager
    的 data/sessions.db 彻底分离。单例语义不变。
    """
    global _session_store
    if _session_store is None:
        _session_store = SessionStore(db_path)
    return _session_store
