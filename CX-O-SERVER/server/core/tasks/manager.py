"""任务管理器——任务的创建、持久化、状态推进与调度接入。"""
import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))，禁止相对路径）
# CX-O 迁移版：_THIS_DIR     = c:\CX-O\CX-O-SERVER\server\core\tasks
#   _PROJECT_ROOT = c:\CX-O\CX-O-SERVER（上 3 级）
# 与 decision_core.py L35-37 路径锚点模式对齐。
# D13 修复（20260719）：原 _TASKS_DIR = "data/tasks" 为相对路径，依赖 cwd 解析。
#   修复为绝对路径，消除 cwd 依赖。
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
_TASKS_DIR = os.path.join(_PROJECT_ROOT, "data", "tasks")
_TASK_LIST_FILE = os.path.join(_TASKS_DIR, "task_list.json")
_SCHEDULED_TASKS_FILE = os.path.join(_TASKS_DIR, "scheduled_tasks.json")

_VALID_STATUSES = {"pending", "in_progress", "completed"}
_VALID_PRIORITIES = {"low", "medium", "high"}
_VALID_ACTION_TYPES = {"tool", "reminder"}
_VALID_SCHEDULE_TYPES = {"once", "interval", "daily", "weekly"}


class TaskManager:
    """任务管理器 - 管理任务清单与定时任务，JSON 持久化 + 内存缓存 + 线程锁"""

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        os.makedirs(_TASKS_DIR, exist_ok=True)
        self._lock = threading.Lock()
        self._tasks: List[Dict[str, Any]] = []
        self._scheduled_tasks: List[Dict[str, Any]] = []
        self._load_tasks()
        self._load_scheduled_tasks()
        logger.info("任务管理器初始化完成")

    # ----- persistence helpers -----

    def _load_tasks(self) -> None:
        if os.path.exists(_TASK_LIST_FILE):
            try:
                with open(_TASK_LIST_FILE, "r", encoding="utf-8") as f:
                    self._tasks = json.load(f)
            except Exception as e:
                logger.error(f"加载任务清单失败: {e}")
                self._tasks = []

    def _save_tasks(self) -> None:
        try:
            with open(_TASK_LIST_FILE, "w", encoding="utf-8") as f:
                json.dump(self._tasks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存任务清单失败: {e}")
            raise

    def _load_scheduled_tasks(self) -> None:
        if os.path.exists(_SCHEDULED_TASKS_FILE):
            try:
                with open(_SCHEDULED_TASKS_FILE, "r", encoding="utf-8") as f:
                    self._scheduled_tasks = json.load(f)
            except Exception as e:
                logger.error(f"加载定时任务失败: {e}")
                self._scheduled_tasks = []

    def _save_scheduled_tasks(self) -> None:
        try:
            with open(_SCHEDULED_TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._scheduled_tasks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存定时任务失败: {e}")
            raise

    # ----- task list (任务清单) -----

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        tags: Optional[List[str]] = None,
        due_date: Optional[str] = None,
    ) -> dict:
        """创建一条新任务并持久化，返回任务字典。"""
        if priority not in _VALID_PRIORITIES:
            raise ValueError(f"无效的优先级: {priority}")
        now = datetime.now().isoformat()
        task = {
            "id": uuid.uuid4().hex,
            "title": title,
            "description": description,
            "status": "pending",
            "priority": priority,
            "tags": tags if tags is not None else [],
            "due_date": due_date,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._tasks.append(task)
            self._save_tasks()
        logger.info(f"创建任务: id={task['id']}, title={title}")
        return task

    def list_tasks(
        self,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[dict]:
        with self._lock:
            tasks = list(self._tasks)
        result = []
        for t in tasks:
            if status is not None and t.get("status") != status:
                continue
            if priority is not None and t.get("priority") != priority:
                continue
            if tag is not None and tag not in t.get("tags", []):
                continue
            result.append(t)
        return result

    def get_task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            for t in self._tasks:
                if t["id"] == task_id:
                    return dict(t)
        return None

    def update_task(self, task_id: str, **fields) -> Optional[dict]:
        allowed = {"title", "description", "status", "priority", "tags", "due_date"}
        with self._lock:
            for t in self._tasks:
                if t["id"] == task_id:
                    for k, v in fields.items():
                        if k not in allowed:
                            continue
                        if k == "status" and v not in _VALID_STATUSES:
                            raise ValueError(f"无效的状态: {v}")
                        if k == "priority" and v not in _VALID_PRIORITIES:
                            raise ValueError(f"无效的优先级: {v}")
                        t[k] = v
                    t["updated_at"] = datetime.now().isoformat()
                    self._save_tasks()
                    return dict(t)
        return None

    def complete_task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            for t in self._tasks:
                if t["id"] == task_id:
                    t["status"] = "completed"
                    t["updated_at"] = datetime.now().isoformat()
                    self._save_tasks()
                    return dict(t)
        return None

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            for i, t in enumerate(self._tasks):
                if t["id"] == task_id:
                    del self._tasks[i]
                    self._save_tasks()
                    return True
        return False

    # ----- scheduled tasks (定时任务) -----

    def _validate_action(self, action: Dict[str, Any]) -> None:
        if not isinstance(action, dict):
            raise ValueError("action 必须是字典")
        atype = action.get("type")
        if atype not in _VALID_ACTION_TYPES:
            raise ValueError(f"无效的 action 类型: {atype}")
        if atype == "tool" and not action.get("tool_name"):
            raise ValueError("tool 类型必须提供 tool_name")
        if atype == "reminder" and not action.get("message"):
            raise ValueError("reminder 类型必须提供 message")
        action.setdefault("parameters", {})

    def _validate_schedule(self, schedule: Dict[str, Any]) -> None:
        if not isinstance(schedule, dict):
            raise ValueError("schedule 必须是字典")
        stype = schedule.get("type")
        if stype not in _VALID_SCHEDULE_TYPES:
            raise ValueError(f"无效的 schedule 类型: {stype}")
        if stype == "once" and not schedule.get("run_at"):
            raise ValueError("once 类型必须提供 run_at")
        if stype == "interval" and not schedule.get("interval_seconds"):
            raise ValueError("interval 类型必须提供 interval_seconds")
        if stype in ("daily", "weekly") and not schedule.get("run_at"):
            raise ValueError("daily/weekly 类型必须提供 run_at")

    def _compute_next_run(self, schedule: Dict[str, Any]) -> Optional[str]:
        stype = schedule.get("type")
        now = datetime.now()
        if stype == "once":
            return schedule.get("run_at")
        if stype == "interval":
            secs = schedule.get("interval_seconds")
            if not secs:
                return None
            return (now + timedelta(seconds=int(secs))).isoformat()
        if stype in ("daily", "weekly"):
            run_at = schedule.get("run_at")
            if not run_at:
                return None
            t = datetime.strptime(run_at, "%H:%M").time()
            target = datetime.combine(now.date(), t)
            step_days = 1 if stype == "daily" else 7
            while target <= now:
                target += timedelta(days=step_days)
            return target.isoformat()
        return None

    def create_scheduled_task(
        self,
        name: str,
        action: Dict[str, Any],
        schedule: Dict[str, Any],
        enabled: bool = True,
    ) -> dict:
        self._validate_action(action)
        self._validate_schedule(schedule)
        action = dict(action)
        action.setdefault("parameters", {})
        schedule = dict(schedule)
        now = datetime.now().isoformat()
        next_run = self._compute_next_run(schedule) if enabled else None
        task = {
            "id": uuid.uuid4().hex,
            "name": name,
            "action": action,
            "schedule": schedule,
            "enabled": enabled,
            "last_run": None,
            "next_run": next_run,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._scheduled_tasks.append(task)
            self._save_scheduled_tasks()
        logger.info(f"创建定时任务: id={task['id']}, name={name}")
        return task

    def list_scheduled_tasks(self, enabled_only: bool = False) -> List[dict]:
        with self._lock:
            tasks = list(self._scheduled_tasks)
        if enabled_only:
            tasks = [t for t in tasks if t.get("enabled")]
        return tasks

    def get_scheduled_task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            for t in self._scheduled_tasks:
                if t["id"] == task_id:
                    return dict(t)
        return None

    def update_scheduled_task(self, task_id: str, **fields) -> Optional[dict]:
        allowed = {"name", "action", "schedule", "enabled"}
        with self._lock:
            for t in self._scheduled_tasks:
                if t["id"] == task_id:
                    schedule_changed = False
                    enabled_false_to_true = False
                    for k, v in fields.items():
                        if k not in allowed:
                            continue
                        if k == "action":
                            self._validate_action(v)
                            v = dict(v)
                            v.setdefault("parameters", {})
                        if k == "schedule":
                            self._validate_schedule(v)
                            v = dict(v)
                            schedule_changed = True
                        if k == "enabled":
                            if not t.get("enabled") and v:
                                enabled_false_to_true = True
                        t[k] = v
                    if schedule_changed or enabled_false_to_true:
                        t["next_run"] = self._compute_next_run(t["schedule"])
                    t["updated_at"] = datetime.now().isoformat()
                    self._save_scheduled_tasks()
                    return dict(t)
        return None

    def pause_scheduled_task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            for t in self._scheduled_tasks:
                if t["id"] == task_id:
                    t["enabled"] = False
                    t["updated_at"] = datetime.now().isoformat()
                    self._save_scheduled_tasks()
                    return dict(t)
        return None

    def resume_scheduled_task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            for t in self._scheduled_tasks:
                if t["id"] == task_id:
                    t["enabled"] = True
                    t["next_run"] = self._compute_next_run(t["schedule"])
                    t["updated_at"] = datetime.now().isoformat()
                    self._save_scheduled_tasks()
                    return dict(t)
        return None

    def delete_scheduled_task(self, task_id: str) -> bool:
        with self._lock:
            for i, t in enumerate(self._scheduled_tasks):
                if t["id"] == task_id:
                    del self._scheduled_tasks[i]
                    self._save_scheduled_tasks()
                    return True
        return False

    def get_due_tasks(self) -> List[dict]:
        now = datetime.now()
        result = []
        with self._lock:
            for t in self._scheduled_tasks:
                if not t.get("enabled"):
                    continue
                next_run = t.get("next_run")
                if not next_run:
                    continue
                try:
                    nr = datetime.fromisoformat(next_run)
                except Exception:
                    continue
                if nr <= now:
                    result.append(dict(t))
        return result

    def mark_executed(self, task_id: str, success: bool = True) -> None:
        """记录定时任务已执行，并计算下次运行时间（一次性任务则置空）。"""
        with self._lock:
            for t in self._scheduled_tasks:
                if t["id"] == task_id:
                    now = datetime.now().isoformat()
                    t["last_run"] = now
                    stype = t["schedule"].get("type")
                    if stype == "once":
                        t["next_run"] = None
                    else:
                        t["next_run"] = self._compute_next_run(t["schedule"])
                    t["updated_at"] = now
                    self._save_scheduled_tasks()
                    return


# 模块级单例
_TASK_MANAGER: Optional[TaskManager] = None
_task_manager_lock = threading.Lock()


def get_task_manager() -> TaskManager:
    global _TASK_MANAGER
    if _TASK_MANAGER is None:
        with _task_manager_lock:
            if _TASK_MANAGER is None:
                _TASK_MANAGER = TaskManager()
    return _TASK_MANAGER
