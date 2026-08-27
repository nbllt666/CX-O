"""任务调度器——周期性触发任务执行与失败重试。"""
import asyncio

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class TaskScheduler:
    """定时任务调度器 - 周期性扫描并执行到期的定时任务"""

    def __init__(self, task_manager, interval_seconds: int = 60, max_retries: int = 3):
        self.task_manager = task_manager
        self.interval_seconds = interval_seconds
        self.max_retries = max_retries
        self._retry_counts = {}
        self._task = None
        self._stop_event = asyncio.Event()

    async def start(self):
        """启动任务调度器"""
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_periodically())
            logger.info(f"任务调度器已启动，间隔: {self.interval_seconds}秒")

    async def stop(self):
        """停止任务调度器"""
        if self._task:
            self._stop_event.set()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None
            logger.info("任务调度器已停止")

    async def _run_periodically(self):
        """定期处理到期任务"""
        while not self._stop_event.is_set():
            try:
                await self._process_due_tasks()
            except Exception as e:
                logger.error(f"处理到期任务失败: {e}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def _process_due_tasks(self):
        """获取并执行所有到期任务"""
        due_tasks = self.task_manager.get_due_tasks()
        for task in due_tasks:
            await self._execute_task(task)

    async def _execute_task(self, task):
        """执行单个定时任务"""
        task_id = task["id"]
        action = task.get("action", {})
        atype = action.get("type")
        schedule = task.get("schedule") or {}
        try:
            if atype == "tool":
                from server.core.tools import tool_registry

                result = await tool_registry.call_tool_async(
                    action["tool_name"], action.get("parameters", {})
                )
                logger.info(f"定时任务执行工具完成: id={task_id}, result={result}")
            elif atype == "reminder":
                logger.info(f"定时提醒: id={task_id}, message={action.get('message')}")
            else:
                logger.warning(f"未知任务类型: id={task_id}, type={atype}")
            self.task_manager.mark_executed(task_id, success=True)
            self._retry_counts.pop(task_id, None)
        except Exception as e:
            logger.error(f"定时任务执行失败: id={task_id}, error={e}")
            # 一次性任务失败不置终态：保留 next_run 允许重试（最多 max_retries 次），
            # 只有成功或重试耗尽时才置 once 终态。
            if schedule.get("type") == "once" and self._retry_counts.get(task_id, 0) < self.max_retries:
                self._retry_counts[task_id] = self._retry_counts.get(task_id, 0) + 1
                return
            self.task_manager.mark_executed(task_id, success=False)
            self._retry_counts.pop(task_id, None)
