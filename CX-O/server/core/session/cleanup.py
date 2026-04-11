import asyncio
from datetime import datetime, timedelta
from typing import Optional

from server.core.logging_config import get_contextual_logger

from .store import SessionStore

logger = get_contextual_logger(__name__)


class SessionCleanupTask:
    def __init__(self, session_store: SessionStore, cleanup_interval_minutes: int = 60, max_session_age_days: int = 30):
        self.session_store = session_store
        self.cleanup_interval = timedelta(minutes=cleanup_interval_minutes)
        self.max_session_age = timedelta(days=max_session_age_days)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._running:
            logger.warning("清理任务已在运行")
            return
        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"会话清理任务已启动，间隔: {self.cleanup_interval}")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("会话清理任务已停止")

    async def _cleanup_loop(self):
        while self._running:
            try:
                await self._perform_cleanup()
            except Exception as e:
                logger.error(f"会话清理失败: {e}")
            await asyncio.sleep(self.cleanup_interval.total_seconds())

    async def _perform_cleanup(self):
        expired_count = self.session_store.cleanup_expired_sessions()
        old_count = await self._cleanup_old_sessions()
        total = expired_count + old_count
        if total > 0:
            logger.info(f"会话清理完成: 过期 {expired_count} 个, 长期未访问 {old_count} 个")

    async def _cleanup_old_sessions(self) -> int:
        cutoff_date = datetime.now() - self.max_session_age
        all_sessions = self.session_store.get_sessions(active_only=False, limit=10000)
        count = 0
        for session in all_sessions:
            if session.last_accessed_at < cutoff_date:
                if self.session_store.delete_session(session.id, soft_delete=False):
                    count += 1
        if count > 0:
            logger.info(f"已清理 {count} 个长期未访问的会话")
        return count

    async def run_once(self):
        await self._perform_cleanup()


_cleanup_task: Optional[SessionCleanupTask] = None


async def start_session_cleanup(session_store: SessionStore, cleanup_interval_minutes: int = 60, max_session_age_days: int = 30):
    global _cleanup_task
    if _cleanup_task is None:
        _cleanup_task = SessionCleanupTask(session_store=session_store, cleanup_interval_minutes=cleanup_interval_minutes,
                                          max_session_age_days=max_session_age_days)
    await _cleanup_task.start()


async def stop_session_cleanup():
    global _cleanup_task
    if _cleanup_task:
        await _cleanup_task.stop()
        _cleanup_task = None