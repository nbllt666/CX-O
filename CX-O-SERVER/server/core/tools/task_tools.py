"""
任务管理工具 - 供记忆管理模型（assistant）调用的任务清单与定时任务工具
"""

from typing import Any, Dict, List

from server.core.tasks import get_task_manager
from .registry import tool_registry


def register_task_tools():
    """注册所有任务管理工具"""

    # 1. create_task - 创建任务
    tool_registry.register(
        name="create_task",
        description="创建一个新的任务。可设置标题、描述、优先级、标签和截止日期。",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "任务标题"},
                "description": {"type": "string", "description": "任务描述"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "优先级",
                    "default": "medium",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签列表",
                },
                "due_date": {"type": "string", "description": "截止日期（ISO 格式）"},
            },
            "required": ["title"],
        },
        function=create_task,
        category="assistant",
        tags=["task", "create"],
        examples=["创建一个高优先级任务：完成项目报告"],
    )

    # 2. list_tasks - 列出任务
    tool_registry.register(
        name="list_tasks",
        description="列出任务清单，可按状态、优先级、标签过滤。",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                    "description": "任务状态",
                },
                "priority": {"type": "string", "description": "优先级（low/medium/high）"},
                "tag": {"type": "string", "description": "标签"},
            },
        },
        function=list_tasks,
        category="assistant",
        tags=["task", "list", "query"],
        examples=["列出所有待处理的任务", "查找高优先级任务"],
    )

    # 3. get_task - 获取任务详情
    tool_registry.register(
        name="get_task",
        description="根据任务ID获取任务详情。",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
            },
            "required": ["task_id"],
        },
        function=get_task,
        category="assistant",
        tags=["task", "get"],
        examples=["获取任务ID为abc123的详情"],
    )

    # 4. update_task - 更新任务
    tool_registry.register(
        name="update_task",
        description="更新已存在的任务字段（标题、描述、状态、优先级、标签、截止日期）。",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
                "title": {"type": "string", "description": "任务标题"},
                "description": {"type": "string", "description": "任务描述"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                    "description": "任务状态",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "优先级",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签列表",
                },
                "due_date": {"type": "string", "description": "截止日期（ISO 格式）"},
            },
            "required": ["task_id"],
        },
        function=update_task,
        category="assistant",
        tags=["task", "update"],
        examples=["更新任务abc123的状态为in_progress"],
    )

    # 5. complete_task - 完成任务
    tool_registry.register(
        name="complete_task",
        description="将指定任务标记为已完成。",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
            },
            "required": ["task_id"],
        },
        function=complete_task,
        category="assistant",
        tags=["task", "complete"],
        examples=["完成任务abc123"],
    )

    # 6. delete_task - 删除任务
    tool_registry.register(
        name="delete_task",
        description="删除指定任务。",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
            },
            "required": ["task_id"],
        },
        function=delete_task,
        category="assistant",
        tags=["task", "delete"],
        examples=["删除任务abc123"],
    )

    # 7. create_scheduled_task - 创建定时任务
    tool_registry.register(
        name="create_scheduled_task",
        description="创建一个定时任务，可按一次、间隔、每日、每周方式调度。",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "任务名称"},
                "action": {"type": "object", "description": "触发动作: {type: 'tool'|'reminder', tool_name: str, parameters: object, message: str}"},
                "schedule": {"type": "object", "description": "调度配置: {type: 'once'|'interval'|'daily'|'weekly', run_at: str, interval_seconds: int}"},
                "enabled": {"type": "boolean", "description": "是否启用", "default": True},
            },
            "required": ["name", "action", "schedule"],
        },
        function=create_scheduled_task,
        category="assistant",
        tags=["scheduled_task", "create"],
        examples=["创建每天9点提醒开会任务"],
    )

    # 8. list_scheduled_tasks - 列出定时任务
    tool_registry.register(
        name="list_scheduled_tasks",
        description="列出现有定时任务，可选择只返回启用的任务。",
        parameters={
            "type": "object",
            "properties": {
                "enabled_only": {"type": "boolean", "description": "只返回启用的任务"},
            },
        },
        function=list_scheduled_tasks,
        category="assistant",
        tags=["scheduled_task", "list", "query"],
        examples=["列出所有定时任务"],
    )

    # 9. get_scheduled_task - 获取定时任务详情
    tool_registry.register(
        name="get_scheduled_task",
        description="根据任务ID获取定时任务详情。",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
            },
            "required": ["task_id"],
        },
        function=get_scheduled_task,
        category="assistant",
        tags=["scheduled_task", "get"],
        examples=["获取定时任务ID为abc123的详情"],
    )

    # 10. update_scheduled_task - 更新定时任务
    tool_registry.register(
        name="update_scheduled_task",
        description="更新定时任务字段（名称、动作、调度、启用状态）。",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
                "name": {"type": "string", "description": "任务名称"},
                "action": {"type": "object", "description": "触发动作: {type: 'tool'|'reminder', tool_name: str, parameters: object, message: str}"},
                "schedule": {"type": "object", "description": "调度配置: {type: 'once'|'interval'|'daily'|'weekly', run_at: str, interval_seconds: int}"},
                "enabled": {"type": "boolean", "description": "是否启用"},
            },
            "required": ["task_id"],
        },
        function=update_scheduled_task,
        category="assistant",
        tags=["scheduled_task", "update"],
        examples=["更新定时任务abc123的调度为每天10点"],
    )

    # 11. pause_scheduled_task - 暂停定时任务
    tool_registry.register(
        name="pause_scheduled_task",
        description="暂停指定定时任务（设置enabled为false）。",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
            },
            "required": ["task_id"],
        },
        function=pause_scheduled_task,
        category="assistant",
        tags=["scheduled_task", "pause"],
        examples=["暂停定时任务abc123"],
    )

    # 12. resume_scheduled_task - 恢复定时任务
    tool_registry.register(
        name="resume_scheduled_task",
        description="恢复指定定时任务（设置enabled为true并重新计算下次运行时间）。",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
            },
            "required": ["task_id"],
        },
        function=resume_scheduled_task,
        category="assistant",
        tags=["scheduled_task", "resume"],
        examples=["恢复定时任务abc123"],
    )

    # 13. delete_scheduled_task - 删除定时任务
    tool_registry.register(
        name="delete_scheduled_task",
        description="删除指定定时任务。",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
            },
            "required": ["task_id"],
        },
        function=delete_scheduled_task,
        category="assistant",
        tags=["scheduled_task", "delete"],
        examples=["删除定时任务abc123"],
    )


# ----- task list tools -----

def create_task(title: str, description: str = None, priority: str = None,
                tags: List[str] = None, due_date: str = None) -> Dict[str, Any]:
    """创建任务"""
    try:
        tm = get_task_manager()
        kwargs = {}
        if description is not None:
            kwargs["description"] = description
        if priority is not None:
            kwargs["priority"] = priority
        if tags is not None:
            kwargs["tags"] = tags
        if due_date is not None:
            kwargs["due_date"] = due_date
        return tm.create_task(title=title, **kwargs)
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_tasks(status: str = None, priority: str = None, tag: str = None) -> Any:
    """列出任务"""
    try:
        tm = get_task_manager()
        return tm.list_tasks(status=status, priority=priority, tag=tag)
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_task(task_id: str) -> Dict[str, Any]:
    """获取任务"""
    try:
        tm = get_task_manager()
        task = tm.get_task(task_id)
        if task is None:
            return {"success": False, "error": "任务不存在"}
        return task
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_task(task_id: str, title: str = None, description: str = None,
                status: str = None, priority: str = None,
                tags: List[str] = None, due_date: str = None) -> Dict[str, Any]:
    """更新任务"""
    try:
        tm = get_task_manager()
        fields = {}
        if title is not None:
            fields["title"] = title
        if description is not None:
            fields["description"] = description
        if status is not None:
            fields["status"] = status
        if priority is not None:
            fields["priority"] = priority
        if tags is not None:
            fields["tags"] = tags
        if due_date is not None:
            fields["due_date"] = due_date
        result = tm.update_task(task_id, **fields)
        if result is None:
            return {"success": False, "error": "任务不存在"}
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def complete_task(task_id: str) -> Dict[str, Any]:
    """完成任务"""
    try:
        tm = get_task_manager()
        result = tm.complete_task(task_id)
        if result is None:
            return {"success": False, "error": "任务不存在"}
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_task(task_id: str) -> Dict[str, Any]:
    """删除任务"""
    try:
        tm = get_task_manager()
        success = tm.delete_task(task_id)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ----- scheduled task tools -----

def create_scheduled_task(name: str, action: Dict[str, Any], schedule: Dict[str, Any],
                          enabled: bool = None) -> Dict[str, Any]:
    """创建定时任务"""
    try:
        tm = get_task_manager()
        kwargs = {}
        if enabled is not None:
            kwargs["enabled"] = enabled
        return tm.create_scheduled_task(name=name, action=action, schedule=schedule, **kwargs)
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_scheduled_tasks(enabled_only: bool = None) -> Any:
    """列出定时任务"""
    try:
        tm = get_task_manager()
        kwargs = {}
        if enabled_only is not None:
            kwargs["enabled_only"] = enabled_only
        return tm.list_scheduled_tasks(**kwargs)
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_scheduled_task(task_id: str) -> Dict[str, Any]:
    """获取定时任务"""
    try:
        tm = get_task_manager()
        task = tm.get_scheduled_task(task_id)
        if task is None:
            return {"success": False, "error": "任务不存在"}
        return task
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_scheduled_task(task_id: str, name: str = None, action: Dict[str, Any] = None,
                          schedule: Dict[str, Any] = None, enabled: bool = None) -> Dict[str, Any]:
    """更新定时任务"""
    try:
        tm = get_task_manager()
        fields = {}
        if name is not None:
            fields["name"] = name
        if action is not None:
            fields["action"] = action
        if schedule is not None:
            fields["schedule"] = schedule
        if enabled is not None:
            fields["enabled"] = enabled
        result = tm.update_scheduled_task(task_id, **fields)
        if result is None:
            return {"success": False, "error": "任务不存在"}
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def pause_scheduled_task(task_id: str) -> Dict[str, Any]:
    """暂停定时任务"""
    try:
        tm = get_task_manager()
        result = tm.pause_scheduled_task(task_id)
        if result is None:
            return {"success": False, "error": "任务不存在"}
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def resume_scheduled_task(task_id: str) -> Dict[str, Any]:
    """恢复定时任务"""
    try:
        tm = get_task_manager()
        result = tm.resume_scheduled_task(task_id)
        if result is None:
            return {"success": False, "error": "任务不存在"}
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_scheduled_task(task_id: str) -> Dict[str, Any]:
    """删除定时任务"""
    try:
        tm = get_task_manager()
        success = tm.delete_scheduled_task(task_id)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}
