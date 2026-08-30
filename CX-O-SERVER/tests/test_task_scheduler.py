"""server.core.tasks.scheduler (TaskScheduler) 单元测试。

覆盖到期任务处理、工具/提醒执行、失败标记与生命周期。
运行：python -m pytest tests/test_task_scheduler.py -v
"""
import asyncio

import pytest

from server.core.tasks.scheduler import TaskScheduler


class FakeTaskManager:
    def __init__(self, due=None):
        self.due = due or []
        self.executed = []
        self.marks = []

    def get_due_tasks(self):
        return self.due

    def mark_executed(self, task_id, success=True):
        self.marks.append((task_id, success))


def _tool_task(task_id="t1"):
    return {"id": task_id, "action": {"type": "tool", "tool_name": "search", "parameters": {}}}


def _reminder_task(task_id="t2"):
    return {"id": task_id, "action": {"type": "reminder", "message": "记得喝水"}}


@pytest.fixture
def fmg():
    return FakeTaskManager()


@pytest.fixture
def sched(fmg):
    return TaskScheduler(task_manager=fmg, interval_seconds=60)


class TestExecuteReminder:
    @pytest.mark.asyncio
    async def test_success(self, sched, fmg):
        await sched._execute_task(_reminder_task("r1"))
        assert ("r1", True) in fmg.marks

    @pytest.mark.asyncio
    async def test_unknown_type(self, sched, fmg):
        await sched._execute_task({"id": "u", "action": {"type": "bad"}})
        assert ("u", True) in fmg.marks


class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_success(self, sched, fmg, monkeypatch):
        async def fake_call(tool_name, parameters):
            return {"ok": True}

        monkeypatch.setattr("server.core.tools.tool_registry.call_tool_async", fake_call)
        await sched._execute_task(_tool_task("tool1"))
        assert ("tool1", True) in fmg.marks

    @pytest.mark.asyncio
    async def test_failure_marks_false(self, sched, fmg, monkeypatch):
        async def fake_call(tool_name, parameters):
            raise RuntimeError("boom")

        monkeypatch.setattr("server.core.tools.tool_registry.call_tool_async", fake_call)
        await sched._execute_task(_tool_task("tool2"))
        assert ("tool2", False) in fmg.marks


class TestOnceRetry:
    """一次性任务失败重试：失败不置终态（保留 next_run），超过 max_retries 才终态化。"""

    async def _flaky(self, sched, fmg, monkeypatch, task_id, max_retries):
        async def fake_call(tool_name, parameters):
            raise RuntimeError("boom")

        monkeypatch.setattr("server.core.tools.tool_registry.call_tool_async", fake_call)
        sched.max_retries = max_retries
        task = {"id": task_id, "action": {"type": "tool", "tool_name": "x", "parameters": {}},
                "schedule": {"type": "once"}}
        return task

    @pytest.mark.asyncio
    async def test_failure_does_not_mark_executed_until_retries(self, sched, fmg, monkeypatch):
        task = await self._flaky(sched, fmg, monkeypatch, "once1", max_retries=3)
        await sched._execute_task(task)  # 第 1 次失败
        assert not fmg.marks  # 不置终态，允许重试

    @pytest.mark.asyncio
    async def test_failure_marks_terminal_after_max_retries(self, sched, fmg, monkeypatch):
        task = await self._flaky(sched, fmg, monkeypatch, "once2", max_retries=2)
        for _ in range(3):  # 失败第 3 次时耗尽重试
            await sched._execute_task(task)
        assert ("once2", False) in fmg.marks


class TestProcessDue:
    @pytest.mark.asyncio
    async def test_processes_all_due(self, sched, fmg):
        fmg.due = [_reminder_task("a"), _reminder_task("b")]
        await sched._process_due_tasks()
        assert ("a", True) in fmg.marks
        assert ("b", True) in fmg.marks

    @pytest.mark.asyncio
    async def test_no_due(self, sched, fmg):
        fmg.due = []
        await sched._process_due_tasks()
        assert fmg.marks == []


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self, sched):
        await sched.start()
        assert sched._task is not None
        await sched.stop()
        assert sched._task is None

    @pytest.mark.asyncio
    async def test_start_idempotent(self, sched):
        await sched.start()
        task1 = sched._task
        await sched.start()
        assert sched._task is task1
        await sched.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self, sched):
        await sched.stop()
        assert sched._task is None


class TestToolTimeout:
    """G1/A2: 挂起工具经 wait_for 超时后按执行失败处理，不再永久阻塞调度循环。"""

    @staticmethod
    def _patch_hanging_tool(monkeypatch):
        async def hanging(tool_name, parameters):
            await asyncio.Event().wait()  # 永不 set → 模拟挂起工具

        monkeypatch.setattr("server.core.tools.tool_registry.call_tool_async", hanging)

    @pytest.mark.asyncio
    async def test_hanging_tool_times_out_marks_failure(self, fmg, monkeypatch):
        self._patch_hanging_tool(monkeypatch)
        sched = TaskScheduler(task_manager=fmg, tool_timeout_seconds=0.05)
        task = {"id": "hang1", "action": {"type": "tool", "tool_name": "x", "parameters": {}}}
        # 无超时保护时本调用将永久挂起；外层 wait_for 仅作测试兜底
        await asyncio.wait_for(sched._execute_task(task), timeout=5.0)
        assert ("hang1", False) in fmg.marks

    @pytest.mark.asyncio
    async def test_once_task_timeout_keeps_retry_budget(self, fmg, monkeypatch):
        self._patch_hanging_tool(monkeypatch)
        sched = TaskScheduler(
            task_manager=fmg, tool_timeout_seconds=0.05, max_retries=2
        )
        task = {
            "id": "hang2",
            "action": {"type": "tool", "tool_name": "x", "parameters": {}},
            "schedule": {"type": "once"},
        }
        await asyncio.wait_for(sched._execute_task(task), timeout=5.0)
        assert not fmg.marks  # once 任务未耗尽重试不置终态
        assert sched._retry_counts["hang2"] == 1  # 重试额度已记录

    @pytest.mark.asyncio
    async def test_stop_reachable_while_tool_hanging(self, fmg, monkeypatch):
        """挂起工具超时后调度循环可回到 stop_event 检查，stop() 必须可达。"""
        self._patch_hanging_tool(monkeypatch)
        fmg.due = [
            {"id": "hang3", "action": {"type": "tool", "tool_name": "x", "parameters": {}}}
        ]
        sched = TaskScheduler(
            task_manager=fmg, interval_seconds=0.05, tool_timeout_seconds=0.05
        )
        await sched.start()
        await asyncio.sleep(0.2)  # 让调度循环进入挂起工具执行
        await asyncio.wait_for(sched.stop(), timeout=5.0)
        assert sched._task is None

    def test_default_timeout_constant(self):
        from server.core.tasks.scheduler import DEFAULT_TOOL_TIMEOUT_SECONDS

        assert DEFAULT_TOOL_TIMEOUT_SECONDS == 300

    def test_resolve_timeout_prefers_injected_value(self, fmg):
        sched = TaskScheduler(task_manager=fmg, tool_timeout_seconds=42)
        assert sched._resolve_tool_timeout() == 42.0

    def test_resolve_timeout_falls_back_to_default(self, fmg):
        # 本项目 config 无 tasks.tool_timeout_seconds 配置节 → 回退模块级默认值
        sched = TaskScheduler(task_manager=fmg)
        assert sched._resolve_tool_timeout() == 300.0