"""
server/core/context/manager.py
===============================
对话会话与消息历史的上下文管理器。

对外契约：
  - ``ContextManager``：管理会话（sessions）与消息（messages）的持久化，
    基于 SQLite（默认 ``data/sessions.db``），线程本地连接 + LRU 会话缓存。
  - 关键方法：
    - ``get_recent_messages(session_id, limit)``：取最近 N 条消息（LLM 上下文用，避免最旧 N 条缺陷）
    - ``ensure_session(...)``：get-or-create 会话（消除调用方样板）
    - ``create_session / get_session / add_message / get_messages``：会话与消息基础操作
  - ``ContextManager`` 单例由 ``server.dependencies.get_context_manager`` 提供。
"""
import json
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from server.core.logging_config import get_contextual_logger
from server.core.utils import run_io

logger = get_contextual_logger(__name__)


class ContextManager:
    """上下文管理器

    负责管理对话会话和消息历史，支持Mono上下文和LRU缓存

    Attributes:
        db_path: 数据库文件路径
    """

    def __init__(self, db_path: str = "data/sessions.db") -> None:
        """初始化上下文管理器

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._local = threading.local()
        self._connection_lock = threading.Lock()
        # BUG-B-M3 修复: 记录所有线程创建的连接,shutdown() 时统一关闭,
        # 避免仅关闭当前线程连接导致其他线程连接泄漏。
        self._all_connections: List = []
        self._init_db()

    def _get_connection(self):
        """获取线程本地数据库连接"""
        if not hasattr(self._local, "connection") or self._local.connection is None:
            import sqlite3

            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=268435456")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.connection = conn
            with self._connection_lock:
                self._all_connections.append(conn)
        return self._local.connection

    def close_connection(self):
        """关闭当前线程的数据库连接"""
        if hasattr(self._local, "connection") and self._local.connection:
            try:
                self._local.connection.close()
            except Exception as e:
                logger.warning(f"关闭数据库连接失败: {e}")
            self._local.connection = None

    def shutdown(self):
        """关闭所有连接

        BUG-B-M3 修复: 关闭所有线程创建的连接,而不仅仅是当前线程的连接,
        避免多线程场景下其他线程连接泄漏。
        """
        with self._connection_lock:
            connections_to_close = list(self._all_connections)
            self._all_connections.clear()
        for conn in connections_to_close:
            try:
                conn.close()
            except Exception as e:
                logger.warning(f"关闭数据库连接失败: {e}")
        if hasattr(self._local, "connection"):
            self._local.connection = None
        logger.info("上下文管理器已关闭")

    def clear_cache(self):
        """清理缓存"""
        logger.info("上下文管理器缓存已清理")

    def _init_db(self):
        import sqlite3

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path, timeout=20.0)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id VARCHAR(36) PRIMARY KEY,
                workspace_id VARCHAR(100) DEFAULT 'default',
                title VARCHAR(500),
                user_id VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                message_count INTEGER DEFAULT 0,
                summary TEXT,
                metadata TEXT,
                is_active BOOLEAN DEFAULT TRUE
            )
        """
        )

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
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """
        )

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)",
        ]
        for idx in indexes:
            cursor.execute(idx)

        conn.commit()
        conn.close()

    def create_session(
        self,
        workspace_id: str = "default",
        title: str = "",
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """创建会话

        Args:
            workspace_id: 工作区ID
            title: 会话标题
            user_id: 用户ID
            metadata: 元数据
            session_id: 自定义会话ID（可选）

        Returns:
            会话ID
        """
        session_id = session_id or str(uuid.uuid4())
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO sessions (id, workspace_id, title, user_id, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                session_id,
                workspace_id,
                title or "新对话",
                user_id,
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )

        conn.commit()

        logger.info(f"会话已创建: id={session_id}")
        return session_id

    def ensure_session(
        self,
        session_id: str,
        workspace_id: str = "default",
        title: str = "",
        metadata: Optional[Dict] = None,
    ) -> str:
        """获取会话，不存在则创建（get-or-create）。

        消除调用方重复的「get_session 为 None 再 create_session」样板代码。

        Args:
            session_id: 会话ID
            workspace_id: 工作区ID
            title: 会话标题
            metadata: 元数据

        Returns:
            会话ID（已存在时原样返回，不存在时创建后返回）
        """
        if self.get_session(session_id) is None:
            try:
                self.create_session(
                    workspace_id=workspace_id,
                    title=title,
                    session_id=session_id,
                    metadata=metadata,
                )
            except Exception as e:
                # D2: get-then-create 的 TOCTOU——并发对同一 session_id 调用时
                # 双双判 None 后同时 INSERT 同主键，后到者抛 IntegrityError。
                # 冲突属"另一路已创建"，回查确认后正常返回；非冲突异常原样抛出。
                import sqlite3

                if not isinstance(e, sqlite3.IntegrityError) or self.get_session(session_id) is None:
                    raise
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_session(row)
        return None

    def get_sessions(
        self, workspace_id: str = "default", limit: int = 20, active_only: bool = True
    ) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM sessions WHERE workspace_id = ?"
        params = [workspace_id]

        if active_only:
            query += " AND is_active = TRUE"

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [self._row_to_session(row) for row in rows]

    def update_session(self, session_id: str, **kwargs) -> bool:
        """更新会话的标题、摘要或激活状态，返回是否更新成功。"""
        conn = self._get_connection()
        cursor = conn.cursor()

        updates = []
        params = []

        if "title" in kwargs:
            updates.append("title = ?")
            params.append(kwargs["title"])

        if "summary" in kwargs:
            updates.append("summary = ?")
            params.append(kwargs["summary"])

        if "is_active" in kwargs:
            updates.append("is_active = ?")
            params.append(kwargs["is_active"])

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(session_id)

        query = f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        success = cursor.rowcount > 0
        conn.commit()

        return success

    def delete_session(self, session_id: str) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

        success = cursor.rowcount > 0
        conn.commit()

        return success

    def clear_all_sessions(self) -> int:
        """删除所有会话和消息

        Returns:
            删除的会话数量
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # 获取会话数量
        cursor.execute("SELECT COUNT(*) FROM sessions")
        count = cursor.fetchone()[0]

        # 删除所有消息
        cursor.execute("DELETE FROM messages")
        # 删除所有会话
        cursor.execute("DELETE FROM sessions")

        conn.commit()
        return count

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        content_type: str = "text",
        metadata: Dict = None,
        tokens: int = 0,
    ) -> str:
        valid_roles = {"system", "user", "assistant", "tool"}
        if role not in valid_roles:
            raise ValueError(f"无效的 role: {role}, 必须是 {valid_roles} 之一")
        message_id = str(uuid.uuid4())
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO messages (id, session_id, role, content, content_type, metadata, tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                message_id,
                session_id,
                role,
                content,
                content_type,
                json.dumps(metadata or {}, ensure_ascii=False),
                tokens,
                datetime.now().isoformat(),
            ),
        )

        cursor.execute(
            """
            UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?
        """,
            (datetime.now().isoformat(), session_id),
        )

        conn.commit()

        return message_id

    def get_messages(
        self, session_id: str, limit: int = 50, offset: int = 0, include_deleted: bool = False
    ) -> List[Dict]:
        """分页获取会话消息列表（默认升序、排除已删除）。"""
        conn = self._get_connection()
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

    def get_recent_messages(self, session_id: str, limit: int = 50) -> List[Dict]:
        """获取最近 limit 条消息（按 created_at 升序返回）。

        单次 SQL 查询（ORDER BY created_at DESC LIMIT）即可取最近 N 条，
        避免 get_messages 的 count+offset 两次往返，用于实时语音等热路径。
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM messages WHERE session_id = ? AND is_deleted = FALSE ORDER BY created_at DESC LIMIT ?"
        cursor.execute(query, (session_id, limit))
        rows = cursor.fetchall()

        # DESC 查询行序为 新→旧，反转回升序返回，与 get_messages 语义一致
        return [self._row_to_message(row) for row in reversed(rows)]

    def delete_message(self, message_id: str) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("UPDATE messages SET is_deleted = TRUE WHERE id = ?", (message_id,))
        success = cursor.rowcount > 0
        conn.commit()

        return success

    def update_message(
        self,
        message_id: str,
        content: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """更新单条消息的 content / content_type / metadata（仅更新非 None 字段）。

        Args:
            message_id: 消息ID
            content: 新内容（None 表示不修改）
            content_type: 新内容类型（None 表示不修改）
            metadata: 新元数据（None 表示不修改）

        Returns:
            是否更新成功
        """
        updates = []
        params = []

        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if content_type is not None:
            updates.append("content_type = ?")
            params.append(content_type)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata, ensure_ascii=False))

        if not updates:
            return False

        params.append(message_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(f"UPDATE messages SET {', '.join(updates)} WHERE id = ?", params)
        success = cursor.rowcount > 0
        conn.commit()

        return success

    def get_message_count(self, session_id: str) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND is_deleted = FALSE",
            (session_id,),
        )
        count = cursor.fetchone()[0]

        return count

    def clear_session_messages(self, session_id: str) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor.execute("UPDATE sessions SET message_count = 0 WHERE id = ?", (session_id,))
        success = cursor.rowcount >= 0
        conn.commit()

        return success

    def _row_to_session(self, row) -> Dict:
        return {
            "id": row[0],
            "workspace_id": row[1],
            "title": row[2],
            "user_id": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "message_count": row[6],
            "summary": row[7],
            "metadata": json.loads(row[8] or "{}"),
            "is_active": bool(row[9]),
        }

    def _row_to_message(self, row) -> Dict:
        return {
            "id": row[0],
            "session_id": row[1],
            "role": row[2],
            "content": row[3],
            "content_type": row[4],
            "metadata": json.loads(row[5] or "{}"),
            "tokens": row[6],
            "created_at": row[7],
            "is_deleted": bool(row[8]),
        }

    def get_statistics(self, workspace_id: str = "default") -> Dict:
        """返回工作区的会话与消息统计信息。"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM sessions WHERE workspace_id = ?", (workspace_id,))
        total_sessions = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM sessions WHERE workspace_id = ? AND is_active = TRUE",
            (workspace_id,),
        )
        active_sessions = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM messages m JOIN sessions s ON m.session_id = s.id WHERE s.workspace_id = ?",
            (workspace_id,),
        )
        total_messages = cursor.fetchone()[0]

        avg_messages = total_messages / total_sessions if total_sessions > 0 else 0

        return {
            "total_sessions": total_sessions,
            "active_sessions": active_sessions,
            "total_messages": total_messages,
            "avg_messages_per_session": round(avg_messages, 2),
        }

    def add_mono_context(
        self, session_id: str, content: str, rounds: int = 1, metadata: Dict = None
    ) -> bool:
        """添加Mono上下文（保持信息在上下文中）"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            expires_at = datetime.now() + timedelta(hours=rounds)
            cursor.execute(
                """
                INSERT INTO messages (id, session_id, role, content, content_type, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(uuid.uuid4()),
                    session_id,
                    "mono",
                    content,
                    "mono_context",
                    json.dumps(
                        {
                            **(metadata or {}),
                            "expires_at": expires_at.isoformat(),
                            "rounds": rounds,
                        },
                        ensure_ascii=False,
                    ),
                    datetime.now().isoformat(),
                ),
            )

            cursor.execute(
                """
                UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?
            """,
                (datetime.now().isoformat(), session_id),
            )

            conn.commit()

            logger.info(f"Mono上下文已添加: session_id={session_id}, rounds={rounds}")
            return True
        except Exception as e:
            logger.error(f"添加Mono上下文失败: {e}")
            return False

    def get_mono_context(self, session_id: str) -> List[Dict]:
        """获取有效的Mono上下文"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ? AND content_type = 'mono_context' AND is_deleted = FALSE
                ORDER BY created_at DESC
            """,
                (session_id,),
            )

            rows = cursor.fetchall()

            now = datetime.now()
            valid_contexts = []

            for row in rows:
                message = self._row_to_message(row)
                metadata = message.get("metadata", {})
                expires_at_str = metadata.get("expires_at")

                if expires_at_str:
                    try:
                        expires_at = datetime.fromisoformat(expires_at_str)
                        if expires_at > now:
                            valid_contexts.append(message)
                    except Exception:
                        pass

            return valid_contexts
        except Exception as e:
            logger.error(f"获取Mono上下文失败: {e}")
            return []

    def clear_expired_mono(self, session_id: str = None) -> int:
        """清理过期的Mono上下文"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            now = datetime.now()

            if session_id:
                cursor.execute(
                    """
                    UPDATE messages
                    SET is_deleted = TRUE
                    WHERE session_id = ? AND content_type = 'mono_context'
                    AND json_extract(metadata, '$.expires_at') < ?
                """,
                    (session_id, now.isoformat()),
                )
            else:
                cursor.execute(
                    """
                    UPDATE messages
                    SET is_deleted = TRUE
                    WHERE content_type = 'mono_context'
                    AND json_extract(metadata, '$.expires_at') < ?
                """,
                    (now.isoformat(),),
                )

            deleted_count = cursor.rowcount

            conn.commit()

            if deleted_count > 0:
                logger.info(f"清理了 {deleted_count} 条过期Mono上下文")

            return deleted_count
        except Exception as e:
            logger.error(f"清理过期Mono上下文失败: {e}")
            return 0

    # ------------------------------------------------------------------ #
    # 异步变体：把同步 sqlite 移入有界 IO 线程池，供 async 热路径调用。
    # 每个方法均委托给同名同步实现，返回值与异常语义保持一致。
    # ------------------------------------------------------------------ #
    async def create_session_async(self, *args, **kwargs) -> str:
        return await run_io(self.create_session, *args, **kwargs)

    async def ensure_session_async(self, *args, **kwargs) -> str:
        return await run_io(self.ensure_session, *args, **kwargs)

    async def get_session_async(self, *args, **kwargs) -> Optional[Dict]:
        return await run_io(self.get_session, *args, **kwargs)

    async def get_sessions_async(self, *args, **kwargs) -> List[Dict]:
        return await run_io(self.get_sessions, *args, **kwargs)

    async def update_session_async(self, *args, **kwargs) -> bool:
        return await run_io(self.update_session, *args, **kwargs)

    async def add_message_async(self, *args, **kwargs) -> str:
        return await run_io(self.add_message, *args, **kwargs)

    async def get_messages_async(self, *args, **kwargs) -> List[Dict]:
        return await run_io(self.get_messages, *args, **kwargs)

    async def get_recent_messages_async(self, *args, **kwargs) -> List[Dict]:
        return await run_io(self.get_recent_messages, *args, **kwargs)

    async def get_statistics_async(self, *args, **kwargs) -> Dict:
        return await run_io(self.get_statistics, *args, **kwargs)
