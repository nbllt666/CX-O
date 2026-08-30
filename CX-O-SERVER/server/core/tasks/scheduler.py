"""任务调度器——周期性触发任务执行与失败重试。"""
import asyncio

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 单工具执行超时（秒）（G1/A2）：防止挂起工具永久阻塞调度循环、使
# _run_periodically 的 stop_event 检查永不可达。配置钩子：优先经构造参数
# TaskScheduler(tool_timeout_seconds=...) 注入；config.py 未来若增设
# tasks.tool_timeout_seconds 配置节，_resolve_tool_timeout 会自动读取，
# 缺失/读取失败时回退本默认值。
DEFAULT_TOOL_TIMEOUT_SECONDS = 300


class TaskScheduler:
    """定时任务调度器 - 周期性扫描并执行到期的定时任务"""

    def __init__(
        self,
        task_manager,
        interval_seconds: int = 60,
        max_retries: int = 3,
        tool_timeout_seconds=None,
    ):
        self.task_manager = task_manager
        self.interval_seconds = interval_seconds
        self.max_retries = max_retries
        # 工具执行超时（秒）；None 时经 _resolve_tool_timeout 解析（配置钩子）
        self.tool_timeout_seconds = tool_timeout_seconds
        self._retry_counts = {}
        self._task = None
        self._stop_event = asyncio.Event()

    def _resolve_tool_timeout(self) -> float:
        """解析工具执行超时（秒）：构造注入 > 配置节（预留） > 模块级默认值。"""
        if self.tool_timeout_seconds is not None:
            return float(self.tool_timeout_seconds)
        try:
            # 配置钩子：config.py 增设 tasks.tool_timeout_seconds 后自动生效
            from server.config import get_config

            tasks_cfg = getattr(get_config(), "tasks", None)
            timeout = getattr(tasks_cfg, "tool_timeout_seconds", None)
            if timeout:
                return float(timeout)
        except Exception:  # noqa: BLE001 - 配置不可用时回退默认值，不影响调度
            pass
        return float(DEFAULT_TOOL_TIMEOUT_SECONDS)

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

                # G1/A2: wait_for 超时保护——挂起工具不再永久阻塞调度循环，
                # 超时按执行失败处理，走既有重试/终态路径
                result = await asyncio.wait_for(
                    tool_registry.call_tool_async(
                        action["tool_name"], action.get("parameters", {})
                    ),
                    timeout=self._resolve_tool_timeout(),
                )
                logger.info(f"定时任务执行工具完成: id={task_id}, result={result}")
            elif atype == "reminder":
                logger.info(f"定时提醒: id={task_id}, message={action.get('message')}")
            else:
                logger.warning(f"未知任务类型: id={task_id}, type={atype}")
            self.task_manager.mark_executed(task_id, success=True)
            self._retry_counts.pop(task_id, None)
        except asyncio.TimeoutError:
            logger.error(
                f"定时任务执行超时（挂起工具已中止）: id={task_id}, "
                f"tool={action.get('tool_name')}, timeout={self._resolve_tool_timeout()}s"
            )
            self._handle_execution_failure(task_id, schedule)
        except Exception as e:
            logger.error(f"定时任务执行失败: id={task_id}, error={e}")
            self._handle_execution_failure(task_id, schedule)

    def _handle_execution_failure(self, task_id, schedule):
        """执行失败统一处理：once 任务保留重试额度，重试耗尽置终态。

        一次性任务失败不置终态：保留 next_run 允许重试（最多 max_retries 次），
        只有成功或重试耗尽时才置 once 终态。
        """
        if schedule.get("type") == "once" and self._retry_counts.get(task_id, 0) < self.max_retries:
            self._retry_counts[task_id] = self._retry_counts.get(task_id, 0) + 1
            return
        self.task_manager.mark_executed(task_id, success=False)
        self._retry_counts.pop(task_id, None)
