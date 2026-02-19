import asyncio
from datetime import datetime, timedelta
from typing import Optional

from backend.core.logging_config import get_contextual_logger

from .store import SessionStore

logger = get_contextual_logger(__name__)


class SessionCleanupTask:
    """会话清理任务

    定期清理过期会话，释放存储空间
    """

    def __init__(
        self,
        session_store: SessionStore,
        cleanup_interval_minutes: int = 60,
        max_session_age_days: int = 30,
    ):
        self.session_store = session_store
        self.cleanup_interval = timedelta(minutes=cleanup_interval_minutes)
        self.max_session_age = timedelta(days=max_session_age_days)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """启动清理任务"""
        if self._running:
            logger.warning("清理任务已在运行")
            return

        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"会话清理任务已启动，间隔: {self.cleanup_interval}")

    async def stop(self):
        """停止清理任务"""
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
        """清理循环"""
        while self._running:
            try:
                await self._perform_cleanup()
            except Exception as e:
                logger.error(f"会话清理失败: {e}")

            await asyncio.sleep(self.cleanup_interval.total_seconds())

    async def _perform_cleanup(self):
        """执行清理"""
        # 清理过期会话
        expired_count = self.session_store.cleanup_expired_sessions()

        # 清理长期未访问的会话
        old_count = await self._cleanup_old_sessions()

        total = expired_count + old_count
        if total > 0:
            logger.info(f"会话清理完成: 过期 {expired_count} 个, 长期未访问 {old_count} 个")

    async def _cleanup_old_sessions(self) -> int:
        """清理长期未访问的会话"""
        cutoff_date = datetime.now() - self.max_session_age

        # 获取所有会话
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
        """立即执行一次清理"""
        await self._perform_cleanup()


# 全局清理任务实例
_cleanup_task: Optional[SessionCleanupTask] = None


async def start_session_cleanup(
    session_store: SessionStore, cleanup_interval_minutes: int = 60, max_session_age_days: int = 30
):
    """启动全局会话清理任务"""
    global _cleanup_task
    if _cleanup_task is None:
        _cleanup_task = SessionCleanupTask(
            session_store=session_store,
            cleanup_interval_minutes=cleanup_interval_minutes,
            max_session_age_days=max_session_age_days,
        )
    await _cleanup_task.start()


async def stop_session_cleanup():
    """停止全局会话清理任务"""
    global _cleanup_task
    if _cleanup_task:
        await _cleanup_task.stop()
        _cleanup_task = None
