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