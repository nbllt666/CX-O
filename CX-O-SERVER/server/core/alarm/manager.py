"""提醒管理器——定时提醒的创建、调度、触发与持久化。"""
import asyncio
import logging
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_DELAY = 86400 * 30  # 最大延迟 30 天（秒）
MAX_MESSAGE_LENGTH = 1000  # 提醒消息最大长度

# 项目根（CX-O-SERVER）：本文件位于 server/core/alarm/ 下，向上 4 级即项目根。
# 与 agents.py/admin.py 的 _PROJECT_ROOT 模式对齐（rules-0 §三：禁止相对路径）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_DB_PATH = str(_PROJECT_ROOT / "data" / "alarms.db")


class _SilentHandler(logging.NullHandler):
    """A handler that silently ignores all log records."""

    def emit(self, record):
        pass


def _silence_logger():
    """Silence the alarm logger to prevent logging errors during shutdown."""
    if not logger.handlers or all(isinstance(h, logging.NullHandler) for h in logger.handlers):
        return
    logger.handlers = [_SilentHandler()]


def _safe_log(level, msg):
    """Safely log a message, ignoring errors if logging is unavailable."""
    try:
        logger.log(level, msg)
    except (ValueError, AttributeError, OSError):
        pass


@dataclass
class Alarm:
    id: str
    agent_id: str
    message: str
    trigger_time: datetime
    created_at: datetime
    status: str = "pending"
    triggered_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "agent_id": self.agent_id,
            "message": self.message,
            "trigger_time": self.trigger_time.isoformat(),
            "created_at": self.created_at.isoformat(),
            "status": self.status,
        }
        if self.triggered_at:
            result["triggered_at"] = self.triggered_at.isoformat()
        return result


class AlarmManager:
    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = db_path
        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._conn_lock = threading.Lock()  # BUG-B05 修复: 保护 _connection_cache
        self._on_trigger_callback = None
        self._shutdown = False
        self._connection_cache: Dict[int, sqlite3.Connection] = {}
        self._ensure_db()

    def _ensure_db(self):
        os.makedirs(
            os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else ".", exist_ok=True
        )
        # BUG-B05 修复: 仅首次调用建表;此处使用临时连接,不再依赖 _get_connection 缓存
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS alarms (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    trigger_time TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    triggered_at TEXT
                )
            """
            )
            conn.commit()
        finally:
            conn.close()

    def _get_connection(self) -> sqlite3.Connection:
        """获取当前线程的缓存连接(线程级单例)

        BUG-B05 修复: 增加 ``_conn_lock`` 保护缓存字典的并发访问;命中失败或
        缓存命中时连接的 ``SELECT 1`` 健康检查也会在锁内完成,避免在多线程
        场景下重复创建连接导致缓存膨胀。
        """
        thread_id = threading.get_ident()

        with self._conn_lock:
            cached = self._connection_cache.get(thread_id)
            if cached is not None:
                try:
                    cached.execute("SELECT 1")
                    return cached
                except Exception:
                    # 连接已损坏,清理并重新创建
                    try:
                        cached.close()
                    except Exception:
                        pass
                    self._connection_cache.pop(thread_id, None)

            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")
            conn.execute("PRAGMA busy_timeout=30000")
            self._connection_cache[thread_id] = conn
            return conn

    def _close_all_connections(self):
        """关闭并清理所有缓存连接(用于 shutdown / 单元测试)"""
        with self._conn_lock:
            for conn in list(self._connection_cache.values()):
                try:
                    conn.close()
                except Exception:
                    pass
            self._connection_cache.clear()

    def set_trigger_callback(self, callback):
        self._on_trigger_callback = callback

    def create_alarm(self, agent_id: str, seconds: int, message: str) -> str:
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id 必须是非空字符串")
        if not isinstance(seconds, (int, float)) or seconds <= 0 or seconds > MAX_DELAY:
            raise ValueError(f"seconds 必须在 (0, {MAX_DELAY}] 范围内")
        if not isinstance(message, str) or len(message) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"message 长度不能超过 {MAX_MESSAGE_LENGTH} 字符")
        alarm_id = str(uuid.uuid4())
        now = datetime.now()
        trigger_time = now + timedelta(seconds=seconds)

        alarm = Alarm(
            id=alarm_id,
            agent_id=agent_id,
            message=message,
            trigger_time=trigger_time,
            created_at=now,
            status="pending",
        )

        # BUG-B05 修复: 复用缓存连接,不再主动 close
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO alarms (id, agent_id, message, trigger_time, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                alarm.id,
                alarm.agent_id,
                alarm.message,
                alarm.trigger_time.isoformat(),
                alarm.created_at.isoformat(),
                alarm.status,
            ),
        )
        conn.commit()

        self._schedule_alarm(alarm)
        _safe_log(
            logging.INFO, f"创建提醒: {alarm_id}, agent={agent_id}, trigger_at={trigger_time}"
        )
        return alarm_id

    async def acreate_alarm(self, agent_id: str, seconds: int, message: str) -> str:
        """异步版本的 create_alarm:在事件循环线程中通过线程池执行同步调用,避免阻塞"""
        return await asyncio.to_thread(self.create_alarm, agent_id, seconds, message)

    def get_alarm(self, alarm_id: str) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM alarms WHERE id = ?", (alarm_id,))
        row = cursor.fetchone()

        if row:
            return dict(row)
        return None

    async def aget_alarm(self, alarm_id: str) -> Optional[Dict]:
        return await asyncio.to_thread(self.get_alarm, alarm_id)

    def get_alarms_by_agent(self, agent_id: str, include_triggered: bool = False) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()

        if include_triggered:
            cursor.execute(
                "SELECT * FROM alarms WHERE agent_id = ? ORDER BY trigger_time DESC", (agent_id,)
            )
        else:
            cursor.execute(
                "SELECT * FROM alarms WHERE agent_id = ? AND status = 'pending' ORDER BY trigger_time",
                (agent_id,),
            )

        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    async def aget_alarms_by_agent(self, agent_id: str, include_triggered: bool = False) -> List[Dict]:
        return await asyncio.to_thread(self.get_alarms_by_agent, agent_id, include_triggered)

    def cancel_alarm(self, alarm_id: str) -> bool:
        with self._lock:
            if alarm_id in self._timers:
                self._timers[alarm_id].cancel()
                del self._timers[alarm_id]

        # BUG-B05 修复: 复用缓存连接
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE alarms SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
            (alarm_id,),
        )
        affected = cursor.rowcount
        conn.commit()

        if affected > 0:
            _safe_log(logging.INFO, f"取消提醒: {alarm_id}")
            return True
        return False

    async def acancel_alarm(self, alarm_id: str) -> bool:
        return await asyncio.to_thread(self.cancel_alarm, alarm_id)

    def mark_triggered(self, alarm_id: str) -> bool:
        now = datetime.now()
        # BUG-B05 修复: 复用缓存连接
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE alarms SET status = 'triggered', triggered_at = ? WHERE id = ?",
            (now.isoformat(), alarm_id),
        )
        affected = cursor.rowcount
        conn.commit()

        with self._lock:
            if alarm_id in self._timers:
                del self._timers[alarm_id]

        return affected > 0

    async def amark_triggered(self, alarm_id: str) -> bool:
        return await asyncio.to_thread(self.mark_triggered, alarm_id)

    def get_pending_alarms(self) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM alarms WHERE status = 'pending' ORDER BY trigger_time")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    async def aget_pending_alarms(self) -> List[Dict]:
        return await asyncio.to_thread(self.get_pending_alarms)

    def _schedule_alarm(self, alarm: Alarm):
        now = datetime.now()
        delay = (alarm.trigger_time - now).total_seconds()

        if delay <= 0:
            self._trigger_alarm(alarm)
            return

        def trigger():
            self._trigger_alarm(alarm)

        timer = threading.Timer(delay, trigger)
        with self._lock:
            self._timers[alarm.id] = timer
        timer.start()

    def _trigger_alarm(self, alarm: Alarm):
        if self._shutdown:
            return
        self.mark_triggered(alarm.id)
        _safe_log(
            logging.INFO, f"提醒触发: {alarm.id}, agent={alarm.agent_id}, message={alarm.message}"
        )

        if self._on_trigger_callback and not self._shutdown:
            try:
                self._on_trigger_callback(alarm.agent_id, alarm.message)
            except Exception as e:
                if not self._shutdown:
                    _safe_log(logging.ERROR, f"提醒回调失败: {e}")

    def restore_pending_alarms(self):
        pending = self.get_pending_alarms()
        now = datetime.now()

        for alarm_data in pending:
            trigger_time = datetime.fromisoformat(alarm_data["trigger_time"])
            alarm = Alarm(
                id=alarm_data["id"],
                agent_id=alarm_data["agent_id"],
                message=alarm_data["message"],
                trigger_time=trigger_time,
                created_at=datetime.fromisoformat(alarm_data["created_at"]),
                status=alarm_data["status"],
            )

            if trigger_time <= now:
                self._trigger_alarm(alarm)
            else:
                self._schedule_alarm(alarm)

        _safe_log(logging.INFO, f"恢复 {len(pending)} 个待触发提醒")

    async def arestore_pending_alarms(self):
        """异步版本的 restore_pending_alarms:在事件循环线程中通过线程池执行同步调用"""
        await asyncio.to_thread(self.restore_pending_alarms)

    def shutdown(self):
        self._shutdown = True
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        # BUG-B05 修复: 关闭并清空缓存的连接,避免进程退出时持有文件句柄
        self._close_all_connections()
        _silence_logger()


_alarm_manager: Optional[AlarmManager] = None


def get_alarm_manager() -> AlarmManager:
    global _alarm_manager
    if _alarm_manager is None:
        _alarm_manager = AlarmManager()
    return _alarm_manager


def reset_alarm_manager():
    """重置全局 AlarmManager 实例（用于测试）"""
    global _alarm_manager
    if _alarm_manager is not None:
        _alarm_manager.shutdown()
        _alarm_manager = None
