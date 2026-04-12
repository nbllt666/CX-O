import asyncio
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class _SilentHandler(logging.Handler):
    """静默日志处理器，仅在 shutdown 时使用"""
    def emit(self, record):
        try:
            msg = self.format(record)
            # 保存到内存，避免 shutdown 时丢失日志
            if not hasattr(_SilentHandler, '_buffer'):
                _SilentHandler._buffer = []
            _SilentHandler._buffer.append(msg)
        except Exception:
            self.handleError(record)


def _silence_logger():
    """静默日志记录器，避免 shutdown 时的异常"""
    if not logger.handlers or all(isinstance(h, logging.NullHandler) for h in logger.handlers):
        return
    for handler in logger.handlers:
        try:
            handler.flush()
            handler.close()
        except Exception:
            pass
    logger.handlers = []


def _safe_log(level, msg):
    """安全日志记录，避免异常"""
    try:
        logger.log(level, msg)
    except (ValueError, AttributeError, OSError) as e:
        # 如果日志系统已关闭，忽略错误
        if not hasattr(logging, '_shutdown') or not logging._shutdown:
            print(f"[ALARM] {msg}")  # 降级到标准输出


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
        result = {"id": self.id, "agent_id": self.agent_id, "message": self.message, "trigger_time": self.trigger_time.isoformat(),
                 "created_at": self.created_at.isoformat(), "status": self.status}
        if self.triggered_at:
            result["triggered_at"] = self.triggered_at.isoformat()
        return result


class AlarmManager:
    def __init__(self, db_path: str = "data/alarms.db"):
        self.db_path = db_path
        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._on_trigger_callback = None
        self._shutdown = False
        self._connection_cache: Dict[int, sqlite3.Connection] = {}
        self._ensure_db()

    def _ensure_db(self):
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else ".", exist_ok=True)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS alarms (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, message TEXT NOT NULL,
                          trigger_time TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT DEFAULT 'pending', triggered_at TEXT)""")
        conn.commit()
        self._close_connection(conn)

    def _get_connection(self) -> sqlite3.Connection:
        thread_id = threading.get_ident()
        if thread_id in self._connection_cache:
            conn = self._connection_cache[thread_id]
            try:
                conn.execute("SELECT 1")
                return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                del self._connection_cache[thread_id]
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA busy_timeout=30000")
        self._connection_cache[thread_id] = conn
        return conn

    def _close_connection(self, conn: sqlite3.Connection):
        try:
            conn.close()
        except Exception:
            pass

    def set_trigger_callback(self, callback):
        self._on_trigger_callback = callback

    def create_alarm(self, agent_id: str, seconds: int, message: str) -> str:
        alarm_id = str(uuid.uuid4())
        now = datetime.now()
        trigger_time = now + timedelta(seconds=seconds)
        alarm = Alarm(id=alarm_id, agent_id=agent_id, message=message, trigger_time=trigger_time, created_at=now, status="pending")
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO alarms (id, agent_id, message, trigger_time, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
                      (alarm.id, alarm.agent_id, alarm.message, alarm.trigger_time.isoformat(), alarm.created_at.isoformat(), alarm.status))
        conn.commit()
        conn.close()
        self._schedule_alarm(alarm)
        _safe_log(logging.INFO, f"创建提醒: {alarm_id}, agent={agent_id}, trigger_at={trigger_time}")
        return alarm_id

    def get_alarm(self, alarm_id: str) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM alarms WHERE id = ?", (alarm_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_alarms_by_agent(self, agent_id: str, include_triggered: bool = False) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        if include_triggered:
            cursor.execute("SELECT * FROM alarms WHERE agent_id = ? ORDER BY trigger_time DESC", (agent_id,))
        else:
            cursor.execute("SELECT * FROM alarms WHERE agent_id = ? AND status = 'pending' ORDER BY trigger_time", (agent_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def cancel_alarm(self, alarm_id: str) -> bool:
        with self._lock:
            if alarm_id in self._timers:
                self._timers[alarm_id].cancel()
                del self._timers[alarm_id]
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE alarms SET status = 'cancelled' WHERE id = ? AND status = 'pending'", (alarm_id,))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        if affected > 0:
            _safe_log(logging.INFO, f"取消提醒: {alarm_id}")
            return True
        return False

    def mark_triggered(self, alarm_id: str) -> bool:
        now = datetime.now()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE alarms SET status = 'triggered', triggered_at = ? WHERE id = ?", (now.isoformat(), alarm_id))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        with self._lock:
            if alarm_id in self._timers:
                del self._timers[alarm_id]
        return affected > 0

    def get_pending_alarms(self) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM alarms WHERE status = 'pending' ORDER BY trigger_time")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

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
        _safe_log(logging.INFO, f"提醒触发: {alarm.id}, agent={alarm.agent_id}, message={alarm.message}")
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
            alarm = Alarm(id=alarm_data["id"], agent_id=alarm_data["agent_id"], message=alarm_data["message"],
                         trigger_time=trigger_time, created_at=datetime.fromisoformat(alarm_data["created_at"]), status=alarm_data["status"])
            if trigger_time <= now:
                self._trigger_alarm(alarm)
            else:
                self._schedule_alarm(alarm)
        _safe_log(logging.INFO, f"恢复 {len(pending)} 个待触发提醒")

    def shutdown(self):
        self._shutdown = True
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        _silence_logger()


_alarm_manager: Optional[AlarmManager] = None


def get_alarm_manager() -> AlarmManager:
    global _alarm_manager
    if _alarm_manager is None:
        _alarm_manager = AlarmManager()
    return _alarm_manager


def reset_alarm_manager():
    global _alarm_manager
    if _alarm_manager is not None:
        _alarm_manager.shutdown()
        _alarm_manager = None