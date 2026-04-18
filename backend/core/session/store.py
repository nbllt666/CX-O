import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

from .models import Session, SessionMessage, SessionStats, SessionType

logger = get_contextual_logger(__name__)


class SessionStore:
    """持久化会话存储

    使用 SQLite 存储会话数据，支持会话过期管理和自动清理
    """

    def __init__(self, db_path: str = "data/sessions.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(self.db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
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
                self._update_last_accessed(session_id)
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
        """删除消息"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if soft_delete:
                cursor.execute("UPDATE messages SET is_deleted = TRUE WHERE id = ?", (message_id,))
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
            cursor.execute(f"SELECT COUNT(*) FROM sessions {base_where}", params)
            total_sessions = cursor.fetchone()[0]

            # 激活会话数
            cursor.execute(
                f"SELECT COUNT(*) FROM sessions {base_where} AND is_active = TRUE", params
            )
            active_sessions = cursor.fetchone()[0]

            # 过期会话数
            now = datetime.now().isoformat()
            cursor.execute(
                f"""SELECT COUNT(*) FROM sessions {base_where} 
                    AND expires_at IS NOT NULL AND expires_at < ?""",
                params + [now],
            )
            expired_sessions = cursor.fetchone()[0]

            # 总消息数
            if workspace_id:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM messages m
                    JOIN sessions s ON m.session_id = s.id
                    WHERE s.workspace_id = ?
                """,
                    (workspace_id,),
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM messages")
            total_messages = cursor.fetchone()[0]

            avg_messages = total_messages / total_sessions if total_sessions > 0 else 0

            return SessionStats(
                total_sessions=total_sessions,
                active_sessions=active_sessions,
                expired_sessions=expired_sessions,
                total_messages=total_messages,
                avg_messages_per_session=round(avg_messages, 2),
            )

    def _update_last_accessed(self, session_id: str):
        """更新最后访问时间"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET last_accessed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), session_id),
            )
            conn.commit()

    def _row_to_session(self, row) -> Session:
        """将数据库行转换为 Session 对象"""
        return Session(
            id=row[0],
            workspace_id=row[1],
            title=row[2],
            user_id=row[3],
            session_type=SessionType(row[4]) if row[4] else SessionType.CHAT,
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
            last_accessed_at=datetime.fromisoformat(row[7]),
            message_count=row[8],
            summary=row[9],
            metadata=json.loads(row[10] or "{}"),
            is_active=bool(row[11]),
            expires_at=datetime.fromisoformat(row[12]) if row[12] else None,
        )

    def _row_to_message(self, row) -> SessionMessage:
        """将数据库行转换为 SessionMessage 对象"""
        return SessionMessage(
            id=row[0],
            session_id=row[1],
            role=row[2],
            content=row[3],
            content_type=row[4],
            metadata=json.loads(row[5] or "{}"),
            tokens=row[6],
            created_at=datetime.fromisoformat(row[7]),
            is_deleted=bool(row[8]),
        )


# 全局会话存储实例
_session_store: Optional[SessionStore] = None


def get_session_store(db_path: str = "data/sessions.db") -> SessionStore:
    """获取全局会话存储实例"""
    global _session_store
    if _session_store is None:
        _session_store = SessionStore(db_path)
    return _session_store
