"""server.core.tasks.manager (TaskManager) 单元测试。

覆盖任务清单 CRUD、定时任务校验/生命周期、到期与执行标记、JSON 持久化。
运行：python -m pytest tests/test_task_manager.py -v
"""
from datetime import datetime

import pytest

from server.core import tasks as tasks_pkg
from server.core.tasks.manager import TaskManager


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks_pkg.manager, "_TASK_LIST_FILE", str(tmp_path / "task_list.json"))
    monkeypatch.setattr(
        tasks_pkg.manager, "_SCHEDULED_TASKS_FILE", str(tmp_path / "scheduled.json")
    )
    return TaskManager()


class TestCreateTask:
    def test_create_defaults(self, manager):
        t = manager.create_task("标题")
        assert t["title"] == "标题"
        assert t["status"] == "pending"
        assert t["priority"] == "medium"
        assert t["tags"] == []
        assert t["due_date"] is None
        assert t["id"]

    def test_create_with_fields(self, manager):
        t = manager.create_task("T", priority="high", tags=["a"], due_date="2026-01-01")
        assert t["priority"] == "high"
        assert t["tags"] == ["a"]
        assert t["due_date"] == "2026-01-01"

    def test_invalid_priority(self, manager):
        with pytest.raises(ValueError):
            manager.create_task("T", priority="urgent")


class TestListTasks:
    def test_filters_by_status(self, manager):
        a = manager.create_task("A")
        manager.complete_task(a["id"])
        manager.create_task("B")
        pending = manager.list_tasks(status="pending")
        completed = manager.list_tasks(status="completed")
        assert len(pending) == 1
        assert len(completed) == 1
        assert completed[0]["id"] == a["id"]

    def test_filters_by_tag(self, manager):
        manager.create_task("A", tags=["work"])
        manager.create_task("B", tags=["home"])
        tasks = manager.list_tasks(tag="work")
        assert len(tasks) == 1
        assert tasks[0]["tags"] == ["work"]

    def test_filters_by_priority(self, manager):
        manager.create_task("A", priority="high")
        manager.create_task("B", priority="low")
        assert len(manager.list_tasks(priority="high")) == 1


class TestGetTask:
    def test_found(self, manager):
        t = manager.create_task("T")
        assert manager.get_task(t["id"])["title"] == "T"

    def test_not_found(self, manager):
        assert manager.get_task("nope") is None


class TestUpdateTask:
    def test_update_fields(self, manager):
        t = manager.create_task("T")
        updated = manager.update_task(t["id"], title="新", priority="high")
        assert updated["title"] == "新"
        assert updated["priority"] == "high"

    def test_invalid_status(self, manager):
        t = manager.create_task("T")
        with pytest.raises(ValueError):
            manager.update_task(t["id"], status="done")

    def test_invalid_priority(self, manager):
        t = manager.create_task("T")
        with pytest.raises(ValueError):
            manager.update_task(t["id"], priority="urgent")

    def test_unknown_field_ignored(self, manager):
        t = manager.create_task("T")
        updated = manager.update_task(t["id"], bogus_field=1)
        assert updated["title"] == "T"

    def test_not_found(self, manager):
        assert manager.update_task("nope", title="x") is None


class TestCompleteDelete:
    def test_complete(self, manager):
        t = manager.create_task("T")
        done = manager.complete_task(t["id"])
        assert done["status"] == "completed"
        assert manager.get_task(t["id"])["status"] == "completed"

    def test_complete_not_found(self, manager):
        assert manager.complete_task("nope") is None

    def test_delete(self, manager):
        t = manager.create_task("T")
        assert manager.delete_task(t["id"]) is True
        assert manager.get_task(t["id"]) is None

    def test_delete_not_found(self, manager):
        assert manager.delete_task("nope") is False


class TestCreateScheduled:
    def test_tool_action(self, manager):
        t = manager.create_scheduled_task(
            "任务", {"type": "tool", "tool_name": "search"}, {"type": "once", "run_at": "2099-01-01T00:00:00"}
        )
        assert t["action"]["parameters"] == {}
        assert t["enabled"] is True
        assert t["next_run"] == "2099-01-01T00:00:00"

    def test_tool_missing_name(self, manager):
        with pytest.raises(ValueError):
            manager.create_scheduled_task("t", {"type": "tool"}, {"type": "once", "run_at": "x"})

    def test_reminder_missing_message(self, manager):
        with pytest.raises(ValueError):
            manager.create_scheduled_task("t", {"type": "reminder"}, {"type": "once", "run_at": "x"})

    def test_invalid_action_type(self, manager):
        with pytest.raises(ValueError):
            manager.create_scheduled_task("t", {"type": "bad"}, {"type": "once", "run_at": "x"})

    def test_once_missing_run_at(self, manager):
        with pytest.raises(ValueError):
            manager.create_scheduled_task("t", {"type": "tool", "tool_name": "x"}, {"type": "once"})

    def test_interval_computes_next_run(self, manager):
        t = manager.create_scheduled_task(
            "t", {"type": "tool", "tool_name": "x"}, {"type": "interval", "interval_seconds": 60}
        )
        nr = datetime.fromisoformat(t["next_run"])
        assert nr > datetime.now()

    def test_disabled_no_next_run(self, manager):
        t = manager.create_scheduled_task(
            "t",
            {"type": "tool", "tool_name": "x"},
            {"type": "once", "run_at": "2099-01-01T00:00:00"},
            enabled=False,
        )
        assert t["next_run"] is None


class TestScheduledCrud:
    def test_list_enabled_only(self, manager):
        a = manager.create_scheduled_task("a", {"type": "tool", "tool_name": "x"}, {"type": "interval", "interval_seconds": 10})
        manager.create_scheduled_task("b", {"type": "tool", "tool_name": "x"}, {"type": "once", "run_at": "2099-01-01T00:00:00"}, enabled=False)
        assert len(manager.list_scheduled_tasks(enabled_only=True)) == 1
        assert len(manager.list_scheduled_tasks()) == 2

    def test_get(self, manager):
        t = manager.create_scheduled_task("a", {"type": "tool", "tool_name": "x"}, {"type": "interval", "interval_seconds": 10})
        assert manager.get_scheduled_task(t["id"])["name"] == "a"
        assert manager.get_scheduled_task("nope") is None

    def test_update_name(self, manager):
        t = manager.create_scheduled_task("a", {"type": "tool", "tool_name": "x"}, {"type": "interval", "interval_seconds": 10})
        updated = manager.update_scheduled_task(t["id"], name="b")
        assert updated["name"] == "b"

    def test_update_schedule_recomputes(self, manager):
        t = manager.create_scheduled_task(
            "a", {"type": "tool", "tool_name": "x"}, {"type": "once", "run_at": "2099-01-01T00:00:00"}
        )
        updated = manager.update_scheduled_task(t["id"], schedule={"type": "interval", "interval_seconds": 30})
        nr = datetime.fromisoformat(updated["next_run"])
        assert nr > datetime.now()

    def test_update_enable_recomputes(self, manager):
        t = manager.create_scheduled_task(
            "a", {"type": "tool", "tool_name": "x"}, {"type": "once", "run_at": "2099-01-01T00:00:00"}, enabled=False
        )
        updated = manager.update_scheduled_task(t["id"], enabled=True)
        assert updated["next_run"] == "2099-01-01T00:00:00"

    def test_update_not_found(self, manager):
        assert manager.update_scheduled_task("nope", name="x") is None

    def test_update_atomic_on_validation_error(self, manager):
        # G5：混合字段（合法 name + 非法 schedule）应整体不应用，不留半更新
        t = manager.create_scheduled_task(
            "a", {"type": "tool", "tool_name": "x"}, {"type": "interval", "interval_seconds": 10}
        )
        with pytest.raises(ValueError):
            manager.update_scheduled_task(
                t["id"],
                name="renamed",
                schedule={"type": "bad_type"},
            )
        got = manager.get_scheduled_task(t["id"])
        assert got["name"] == "a"  # name 未被部分应用
        assert got["schedule"]["type"] == "interval"

    def test_pause_resume(self, manager):
        t = manager.create_scheduled_task("a", {"type": "tool", "tool_name": "x"}, {"type": "interval", "interval_seconds": 10})
        assert manager.pause_scheduled_task(t["id"])["enabled"] is False
        resumed = manager.resume_scheduled_task(t["id"])
        assert resumed["enabled"] is True
        assert resumed["next_run"] is not None

    def test_delete(self, manager):
        t = manager.create_scheduled_task("a", {"type": "tool", "tool_name": "x"}, {"type": "interval", "interval_seconds": 10})
        assert manager.delete_scheduled_task(t["id"]) is True
        assert manager.delete_scheduled_task(t["id"]) is False


class TestDueAndExecute:
    def test_due_tasks(self, manager):
        past = "2000-01-01T00:00:00"
        manager.create_scheduled_task("past1", {"type": "tool", "tool_name": "x"}, {"type": "once", "run_at": past})
        manager.create_scheduled_task(
            "past_disabled", {"type": "tool", "tool_name": "x"}, {"type": "once", "run_at": past}, enabled=False
        )
        manager.create_scheduled_task("future", {"type": "tool", "tool_name": "x"}, {"type": "once", "run_at": "2099-01-01T00:00:00"})
        due = manager.get_due_tasks()
        names = [t["name"] for t in due]
        assert "past1" in names
        assert "past_disabled" not in names
        assert "future" not in names

    def test_mark_executed_once(self, manager):
        t = manager.create_scheduled_task("o", {"type": "tool", "tool_name": "x"}, {"type": "once", "run_at": "2000-01-01T00:00:00"})
        manager.mark_executed(t["id"])
        got = manager.get_scheduled_task(t["id"])
        assert got["last_run"] is not None
        assert got["next_run"] is None

    def test_mark_executed_interval(self, manager):
        t = manager.create_scheduled_task("i", {"type": "tool", "tool_name": "x"}, {"type": "interval", "interval_seconds": 60})
        manager.mark_executed(t["id"])
        got = manager.get_scheduled_task(t["id"])
        assert got["next_run"] is not None
        assert datetime.fromisoformat(got["next_run"]) > datetime.now()


class TestPersistence:
    def test_tasks_reload(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tasks_pkg.manager, "_TASK_LIST_FILE", str(tmp_path / "task_list.json"))
        monkeypatch.setattr(tasks_pkg.manager, "_SCHEDULED_TASKS_FILE", str(tmp_path / "scheduled.json"))
        m1 = TaskManager()
        t = m1.create_task("持久化")
        s = m1.create_scheduled_task("s", {"type": "tool", "tool_name": "x"}, {"type": "once", "run_at": "2099-01-01T00:00:00"})
        m2 = TaskManager()
        assert m2.get_task(t["id"])["title"] == "持久化"
        assert m2.get_scheduled_task(s["id"])["name"] == "s"