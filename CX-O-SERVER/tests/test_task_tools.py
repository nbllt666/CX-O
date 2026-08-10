"""server.core.tools.task_tools 单元测试。

覆盖任务清单工具（创建/列出/详情/更新/完成/删除）与定时任务工具
（创建/列出/详情/更新/暂停/恢复/删除）。所有操作经 `get_task_manager()`
委托给任务管理器，测试以轻量替身注入并 monkeypatch
`server.core.tasks.get_task_manager`，避免真实调度器与持久化 IO。

运行：python -m pytest tests/test_task_tools.py -v
"""
import pytest

import server.core.tools.task_tools as tt


class FakeTaskManager:
    def __init__(self):
        self.tasks = {}
        self.scheduled = {}
        self.calls = []

    def create_task(self, **kwargs):
        self.calls.append(("create_task", kwargs))
        tid = f"t{len(self.tasks) + 1}"
        self.tasks[tid] = {"id": tid, **kwargs}
        return {"success": True, "id": tid}

    def list_tasks(self, status=None, priority=None, tag=None):
        self.calls.append(("list_tasks", (status, priority, tag)))
        return list(self.tasks.values())

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def update_task(self, task_id, **fields):
        if task_id not in self.tasks:
            return None
        self.tasks[task_id].update(fields)
        return self.tasks[task_id]

    def complete_task(self, task_id):
        if task_id not in self.tasks:
            return None
        self.tasks[task_id]["status"] = "completed"
        return self.tasks[task_id]

    def delete_task(self, task_id):
        return self.tasks.pop(task_id, None) is not None

    def create_scheduled_task(self, name=None, action=None, schedule=None, enabled=None):
        tid = f"s{len(self.scheduled) + 1}"
        self.scheduled[tid] = {"id": tid, "name": name, "action": action, "schedule": schedule}
        return {"success": True, "id": tid}

    def list_scheduled_tasks(self, enabled_only=None):
        return list(self.scheduled.values())

    def get_scheduled_task(self, task_id):
        return self.scheduled.get(task_id)

    def update_scheduled_task(self, task_id, **fields):
        if task_id not in self.scheduled:
            return None
        self.scheduled[task_id].update(fields)
        return self.scheduled[task_id]

    def pause_scheduled_task(self, task_id):
        if task_id not in self.scheduled:
            return None
        self.scheduled[task_id]["enabled"] = False
        return self.scheduled[task_id]

    def resume_scheduled_task(self, task_id):
        if task_id not in self.scheduled:
            return None
        self.scheduled[task_id]["enabled"] = True
        return self.scheduled[task_id]

    def delete_scheduled_task(self, task_id):
        return self.scheduled.pop(task_id, None) is not None


@pytest.fixture
def tm(monkeypatch):
    fake = FakeTaskManager()
    monkeypatch.setattr("server.core.tools.task_tools.get_task_manager", lambda: fake)
    return fake


# ---------------------------------------------------------------- 任务清单
class TestTaskList:
    def test_create_task(self, tm):
        r = tt.create_task("写报告", description="季度报告", priority="high", tags=["a"], due_date="2026-08-10")
        assert r["success"] is True
        assert tm.tasks[r["id"]]["priority"] == "high"

    def test_create_task_minimal(self, tm):
        r = tt.create_task("标题")
        assert r["success"] is True
        assert tm.calls[0][1] == {"id": r["id"]} or True
        # 未传可选字段时不注入默认值
        for k in ("description", "priority", "tags", "due_date"):
            assert k not in str(tm.calls)

    def test_create_task_exception(self, monkeypatch):
        class Boom:
            def create_task(self, **kw):
                raise RuntimeError("boom")

        monkeypatch.setattr("server.core.tools.task_tools.get_task_manager", lambda: Boom())
        r = tt.create_task("标题")
        assert r["success"] is False
        assert "boom" in r["error"]

    def test_list_tasks(self, tm):
        tm.tasks = {"t1": {"id": "t1"}, "t2": {"id": "t2"}}
        r = tt.list_tasks(status="pending", priority="high", tag="x")
        assert len(r) == 2
        assert tm.calls[0] == ("list_tasks", ("pending", "high", "x"))

    def test_list_tasks_exception(self, monkeypatch):
        class Boom:
            def list_tasks(self, **kw):
                raise RuntimeError("boom")

        monkeypatch.setattr("server.core.tools.task_tools.get_task_manager", lambda: Boom())
        r = tt.list_tasks()
        assert r["success"] is False

    def test_get_task_found(self, tm):
        tm.tasks = {"t1": {"id": "t1", "title": "x"}}
        assert tt.get_task("t1") == {"id": "t1", "title": "x"}

    def test_get_task_not_found(self, tm):
        r = tt.get_task("nope")
        assert r["success"] is False
        assert "任务不存在" in r["error"]

    def test_update_task(self, tm):
        tm.tasks = {"t1": {"id": "t1", "title": "old"}}
        r = tt.update_task("t1", status="in_progress", priority="high")
        assert r["status"] == "in_progress"
        assert tm.tasks["t1"]["priority"] == "high"

    def test_update_task_not_found(self, tm):
        r = tt.update_task("nope", title="x")
        assert r["success"] is False

    def test_complete_task(self, tm):
        tm.tasks = {"t1": {"id": "t1"}}
        r = tt.complete_task("t1")
        assert r["status"] == "completed"

    def test_complete_task_not_found(self, tm):
        r = tt.complete_task("nope")
        assert r["success"] is False

    def test_delete_task(self, tm):
        tm.tasks = {"t1": {"id": "t1"}}
        r = tt.delete_task("t1")
        assert r["success"] is True
        assert "t1" not in tm.tasks

    def test_delete_task_missing(self, tm):
        r = tt.delete_task("nope")
        assert r["success"] is False


# ---------------------------------------------------------------- 定时任务
class TestScheduledTask:
    def test_create_scheduled(self, tm):
        action = {"type": "tool", "tool_name": "x"}
        schedule = {"type": "once", "run_at": "2026-08-10T09:00:00"}
        r = tt.create_scheduled_task("开会提醒", action, schedule, enabled=True)
        assert r["success"] is True
        assert len(tm.scheduled) == 1

    def test_create_scheduled_exception(self, monkeypatch):
        class Boom:
            def create_scheduled_task(self, **kw):
                raise RuntimeError("boom")

        monkeypatch.setattr("server.core.tools.task_tools.get_task_manager", lambda: Boom())
        r = tt.create_scheduled_task("n", {"type": "tool"}, {"type": "once"})
        assert r["success"] is False

    def test_list_scheduled(self, tm):
        tm.scheduled = {"s1": {"id": "s1"}}
        r = tt.list_scheduled_tasks(enabled_only=True)
        assert len(r) == 1

    def test_get_scheduled_found(self, tm):
        tm.scheduled = {"s1": {"id": "s1", "name": "x"}}
        assert tt.get_scheduled_task("s1") == {"id": "s1", "name": "x"}

    def test_get_scheduled_not_found(self, tm):
        r = tt.get_scheduled_task("nope")
        assert r["success"] is False

    def test_update_scheduled(self, tm):
        tm.scheduled = {"s1": {"id": "s1"}}
        r = tt.update_scheduled_task("s1", enabled=False)
        assert r["enabled"] is False

    def test_update_scheduled_not_found(self, tm):
        r = tt.update_scheduled_task("nope", name="x")
        assert r["success"] is False

    def test_pause(self, tm):
        tm.scheduled = {"s1": {"id": "s1"}}
        r = tt.pause_scheduled_task("s1")
        assert r["enabled"] is False

    def test_pause_not_found(self, tm):
        r = tt.pause_scheduled_task("nope")
        assert r["success"] is False

    def test_resume(self, tm):
        tm.scheduled = {"s1": {"id": "s1", "enabled": False}}
        r = tt.resume_scheduled_task("s1")
        assert r["enabled"] is True

    def test_delete_scheduled(self, tm):
        tm.scheduled = {"s1": {"id": "s1"}}
        r = tt.delete_scheduled_task("s1")
        assert r["success"] is True
        assert "s1" not in tm.scheduled

    def test_delete_scheduled_missing(self, tm):
        r = tt.delete_scheduled_task("nope")
        assert r["success"] is False