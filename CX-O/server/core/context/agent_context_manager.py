import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class AgentContextManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path: str = "data/memories.db") -> "AgentContextManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: str = "data/memories.db") -> None:
        if self._initialized:
            return
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._connection_pool: Dict[int, sqlite3.Connection] = {}
        self._init_db()
        logger.info(f"Agent上下文管理器初始化完成: db={db_path}")
        self._initialized = True

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        cursor = conn.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS agent_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id VARCHAR(100) NOT NULL UNIQUE,
            session_id VARCHAR(36),
            context_data TEXT,
            memory_state TEXT,
            last_active TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS agent_context_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id VARCHAR(100) NOT NULL,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_contexts_agent_id ON agent_contexts(agent_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_context_messages_agent_id ON agent_context_messages(agent_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_context_messages_created ON agent_context_messages(created_at)")
        conn.commit()
        conn.close()
        logger.info("Agent上下文表初始化完成")

    def _get_connection(self) -> sqlite3.Connection:
        thread_id = threading.get_ident()
        if thread_id in self._connection_pool:
            conn = self._connection_pool[thread_id]
            try:
                conn.execute("SELECT 1")
                return conn
            except Exception:
                pass
        conn = sqlite3.connect(str(self.db_path), timeout=20.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        self._connection_pool[thread_id] = conn
        return conn

    def save_context(self, agent_id: str, messages: List[Dict[str, Any]], memory_state: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            context_data = json.dumps(messages, ensure_ascii=False)
            memory_state_json = json.dumps(memory_state, ensure_ascii=False) if memory_state else None
            cursor.execute("""INSERT INTO agent_contexts (agent_id, session_id, context_data, memory_state, last_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(agent_id) DO UPDATE SET
                session_id = excluded.session_id, context_data = excluded.context_data, memory_state = excluded.memory_state,
                last_active = excluded.last_active, updated_at = excluded.updated_at""",
                (agent_id, session_id, context_data, memory_state_json, now, now))
            conn.commit()
            logger.debug(f"Agent '{agent_id}' 上下文已保存")
        except Exception as e:
            logger.error(f"保存Agent上下文失败: {e}")
            raise

    def load_context(self, agent_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT context_data FROM agent_contexts WHERE agent_id = ?", (agent_id,))
            row = cursor.fetchone()
            if row and row[0]:
                messages = json.loads(row[0])
                if len(messages) > limit:
                    messages = messages[-limit:]
                return messages
            return []
        except Exception as e:
            logger.error(f"加载Agent上下文失败: {e}")
            return []

    def append_message(self, agent_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
            cursor.execute("INSERT INTO agent_context_messages (agent_id, role, content, metadata) VALUES (?, ?, ?, ?)",
                (agent_id, role, content, metadata_json))
            conn.commit()
            logger.debug(f"Agent '{agent_id}' 消息已追加: role={role}")
        except Exception as e:
            logger.error(f"追加Agent消息失败: {e}")
            raise

    def get_message_history(self, agent_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""SELECT role, content, metadata, created_at FROM agent_context_messages
                WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?""", (agent_id, limit))
            rows = cursor.fetchall()
            return [{"role": row[0], "content": row[1], "metadata": json.loads(row[2]) if row[2] else None, "created_at": row[3]} for row in reversed(rows)]
        except Exception as e:
            logger.error(f"获取Agent消息历史失败: {e}")
            return []

    def clear_context(self, agent_id: str):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM agent_contexts WHERE agent_id = ?", (agent_id,))
            cursor.execute("DELETE FROM agent_context_messages WHERE agent_id = ?", (agent_id,))
            conn.commit()
            logger.info(f"Agent '{agent_id}' 上下文已清空")
        except Exception as e:
            logger.error(f"清空Agent上下文失败: {e}")
            raise

    def get_context_summary(self, agent_id: str) -> Dict[str, Any]:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT session_id, last_active, created_at, updated_at FROM agent_contexts WHERE agent_id = ?", (agent_id,))
            context_row = cursor.fetchone()
            cursor.execute("SELECT COUNT(*), role FROM agent_context_messages WHERE agent_id = ? GROUP BY role", (agent_id,))
            role_counts = {row[1]: row[0] for row in cursor.fetchall()}
            return {
                "agent_id": agent_id, "has_context": context_row is not None,
                "session_id": context_row[0] if context_row else None,
                "last_active": context_row[1] if context_row else None,
                "created_at": context_row[2] if context_row else None,
                "updated_at": context_row[3] if context_row else None,
                "total_messages": sum(role_counts.values()), "role_counts": role_counts,
            }
        except Exception as e:
            logger.error(f"获取Agent上下文摘要失败: {e}")
            return {"agent_id": agent_id, "error": str(e)}

    def update_last_active(self, agent_id: str):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute("UPDATE agent_contexts SET last_active = ?, updated_at = ? WHERE agent_id = ?", (now, now, agent_id))
            conn.commit()
        except Exception as e:
            logger.error(f"更新Agent最后活跃时间失败: {e}")

    def cleanup_old_messages(self, agent_id: str, keep_count: int = 1000):
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM agent_context_messages WHERE agent_id = ? ORDER BY created_at DESC LIMIT -1 OFFSET ?", (agent_id, keep_count))
            ids_to_delete = [row[0] for row in cursor.fetchall()]
            if ids_to_delete:
                placeholders = ",".join("?" * len(ids_to_delete))
                cursor.execute(f"DELETE FROM agent_context_messages WHERE id IN ({placeholders})", ids_to_delete)
                conn.commit()
                logger.info(f"Agent '{agent_id}' 已清理 {len(ids_to_delete)} 条旧消息")
        except Exception as e:
            logger.error(f"清理Agent旧消息失败: {e}")

    def close_all_connections(self):
        for thread_id, conn in list(self._connection_pool.items()):
            try:
                conn.close()
                logger.debug(f"已关闭连接: thread={thread_id}")
            except Exception as e:
                logger.warning(f"关闭连接失败: thread={thread_id}, error={e}")
        self._connection_pool.clear()