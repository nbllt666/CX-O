"""
记忆管理模型工具 - 供记忆管理模型（assistant）调用的工具
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from .registry import tool_registry

_MEMORY_MANAGER = None
_SECONDARY_ROUTER = None
_CONTEXT_MANAGER = None


def set_dependencies(memory_manager=None, secondary_router=None, context_manager=None):
    """设置依赖的组件"""
    global _MEMORY_MANAGER, _SECONDARY_ROUTER, _CONTEXT_MANAGER
    _MEMORY_MANAGER = memory_manager
    _SECONDARY_ROUTER = secondary_router
    _CONTEXT_MANAGER = context_manager


def get_memory_manager():
    """获取记忆管理器"""
    return _MEMORY_MANAGER


def get_secondary_router():
    """获取副模型路由器"""
    return _SECONDARY_ROUTER


def get_context_manager():
    """获取上下文管理器"""
    return _CONTEXT_MANAGER


def register_assistant_tools():
    """注册所有记忆管理模型工具"""

    # 1. update_memory_node - 修改记忆
    tool_registry.register(
        name="update_memory_node",
        description="更新已存在的记忆节点内容。用于修正或补充记忆信息。",
        parameters={
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "要修改的记忆ID"},
                "new_content": {"type": "string", "description": "新的记忆内容"},
            },
            "required": ["memory_id", "new_content"],
        },
        function=update_memory_node,
        category="assistant",
        tags=["memory", "update", "edit"],
        examples=["更新记忆ID123的内容为新的内容"],
    )

    # 2. search_memories - 搜索记忆
    tool_registry.register(
        name="search_memories",
        description="检索记忆库中的相关内容，支持关键词搜索。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询"},
                "time_range": {
                    "type": "string",
                    "description": "时间范围（如 'last_week', '2024-01'）",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量限制",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["query"],
        },
        function=search_memories,
        category="assistant",
        tags=["memory", "search", "query"],
        examples=["搜索关于工作的记忆", "查找用户提到喜欢的颜色"],
    )

    # 3. delete_memory - 删除记忆（软删除）
    tool_registry.register(
        name="delete_memory",
        description="删除指定记忆。执行软删除，记忆会在7天后自动清理，也可通过restore_memory恢复。",
        parameters={
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "要删除的记忆ID"},
                "reason": {"type": "string", "description": "删除原因"},
            },
            "required": ["memory_id", "reason"],
        },
        function=delete_memory,
        category="assistant",
        tags=["memory", "delete", "soft_delete"],
        examples=["删除过时或错误的信息"],
    )

    # 4. merge_memories - 合并记忆
    tool_registry.register(
        name="merge_memories",
        description="将多个相似记忆合并为一个记忆。",
        parameters={
            "type": "object",
            "properties": {
                "memory_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要合并的记忆ID列表",
                    "minItems": 2,
                },
                "merged_content": {"type": "string", "description": "合并后的记忆内容"},
            },
            "required": ["memory_ids", "merged_content"],
        },
        function=merge_memories,
        category="assistant",
        tags=["memory", "merge", "combine"],
        examples=["合并多条关于同一主题的记忆"],
    )

    # 5. clean_expired - 清理过期记忆
    tool_registry.register(
        name="clean_expired",
        description="清理已软删除超过7天的记忆。",
        parameters={"type": "object", "properties": {}},
        function=clean_expired,
        category="assistant",
        tags=["memory", "cleanup", "expired"],
        examples=["清理过期的已删除记忆"],
    )

    # 6. export_memories - 导出记忆
    tool_registry.register(
        name="export_memories",
        description="导出记忆数据为指定格式。",
        parameters={
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["json", "csv"], "description": "导出格式"},
                "memory_type": {
                    "type": "string",
                    "enum": ["permanent", "long_term", "all"],
                    "description": "导出的记忆类型",
                },
            },
            "required": ["format"],
        },
        function=export_memories,
        category="assistant",
        tags=["memory", "export", "backup"],
        examples=["导出所有记忆为JSON格式"],
    )

    # 7. get_memory_stats - 获取记忆统计
    tool_registry.register(
        name="get_memory_stats",
        description="获取记忆库统计信息，包括数量、大小、各类型分布等。",
        parameters={"type": "object", "properties": {}},
        function=get_memory_stats,
        category="assistant",
        tags=["memory", "stats", "statistics"],
        examples=["查看当前记忆库状态"],
    )

    # 8. search_by_time - 按时间搜索
    tool_registry.register(
        name="search_by_time",
        description="按时间范围检索记忆。",
        parameters={
            "type": "object",
            "properties": {
                "start_time": {
                    "type": "string",
                    "description": "开始时间（ISO格式，如 2024-01-01T00:00:00）",
                },
                "end_time": {"type": "string", "description": "结束时间（ISO格式）"},
            },
            "required": ["start_time", "end_time"],
        },
        function=search_by_time,
        category="assistant",
        tags=["memory", "search", "time"],
        examples=["查找2024年1月的所有记忆"],
    )

    # 9. search_by_tag - 按标签搜索
    tool_registry.register(
        name="search_by_tag",
        description="按标签检索记忆。",
        parameters={
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签列表",
                    "minItems": 1,
                }
            },
            "required": ["tags"],
        },
        function=search_by_tag,
        category="assistant",
        tags=["memory", "search", "tag"],
        examples=["查找带有'重要'标签的记忆"],
    )

    # 10. bulk_delete - 批量删除（软删除）
    tool_registry.register(
        name="bulk_delete",
        description="批量删除记忆（软删除）。",
        parameters={
            "type": "object",
            "properties": {
                "memory_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要删除的记忆ID列表",
                    "minItems": 2,
                },
                "reason": {"type": "string", "description": "删除原因"},
            },
            "required": ["memory_ids", "reason"],
        },
        function=bulk_delete,
        category="assistant",
        tags=["memory", "delete", "bulk", "batch"],
        examples=["批量删除多条过时记忆"],
    )

    # 11. restore_memory - 恢复记忆
    tool_registry.register(
        name="restore_memory",
        description="恢复软删除的记忆。",
        parameters={
            "type": "object",
            "properties": {"memory_id": {"type": "string", "description": "要恢复的记忆ID"}},
            "required": ["memory_id"],
        },
        function=restore_memory,
        category="assistant",
        tags=["memory", "restore", "recover"],
        examples=["恢复误删的记忆"],
    )

    # 12. search_similar_memories - 搜索相似记忆
    tool_registry.register(
        name="search_similar_memories",
        description="搜索与指定记忆相似的其他记忆。",
        parameters={
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "参考记忆ID"},
                "threshold": {
                    "type": "number",
                    "description": "相似度阈值（0-1），默认0.7",
                    "default": 0.7,
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量限制",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["memory_id"],
        },
        function=search_similar_memories,
        category="assistant",
        tags=["memory", "similar", "search"],
        examples=["查找与某条记忆相似的其他记忆"],
    )

    # 13. get_chat_history - 读取聊天记录
    tool_registry.register(
        name="get_chat_history",
        description="读取指定会话的聊天历史。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID"},
                "limit": {
                    "type": "integer",
                    "description": "返回消息数量限制",
                    "default": 50,
                    "minimum": 1,
                    "maximum": 200,
                },
            },
            "required": ["session_id"],
        },
        function=get_chat_history,
        category="assistant",
        tags=["chat", "history", "conversation"],
        examples=["读取某个会话的聊天记录"],
    )

    # 14. get_similar_memories - 相似记忆
    tool_registry.register(
        name="get_similar_memories",
        description="获取与给定内容相似的记忆。",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "参考内容"},
                "limit": {
                    "type": "integer",
                    "description": "返回数量限制",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["content"],
        },
        function=get_similar_memories,
        category="assistant",
        tags=["memory", "similar", "search"],
        examples=["查找与给定内容相似的记忆"],
    )

    # 15. get_memory_logs - 记忆管理日志
    tool_registry.register(
        name="get_memory_logs",
        description="获取记忆管理操作日志。",
        parameters={
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "特定记忆的日志，不传则返回所有日志",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量限制",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 1000,
                },
            },
        },
        function=get_memory_logs,
        category="assistant",
        tags=["memory", "log", "history"],
        examples=["查看记忆操作日志"],
    )

    # 16. get_available_commands - 获取可用命令
    tool_registry.register(
        name="get_available_commands",
        description="获取所有可用的记忆管理命令列表及其描述。",
        parameters={"type": "object", "properties": {}},
        function=get_available_commands,
        category="assistant",
        tags=["commands", "list", "help"],
        examples=["查看我可以使用哪些命令"],
    )


def update_memory_node(memory_id: str, new_content: str) -> Dict[str, Any]:
    """修改记忆"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        success = mm.update_memory(memory_id=memory_id, new_content=new_content)
        return {
            "status": "updated" if success else "failed",
            "memory_id": memory_id,
            "new_content_preview": new_content[:100],
        }
    except Exception as e:
        return {"error": f"修改记忆失败: {str(e)}"}


def search_memories(query: str, time_range: str = None, limit: int = 10) -> Dict[str, Any]:
    """搜索记忆"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        memories = mm.search_memories(query=query, time_range=time_range, limit=limit)
        return {
            "query": query,
            "count": len(memories),
            "memories": [
                {
                    "id": m.get("id"),
                    "content": m.get("content", "")[:200],
                    "importance": m.get("importance"),
                    "created_at": m.get("created_at"),
                }
                for m in memories
            ],
        }
    except Exception as e:
        return {"error": f"搜索记忆失败: {str(e)}"}


def delete_memory(memory_id: str, reason: str) -> Dict[str, Any]:
    """删除记忆（软删除）"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        success = mm.soft_delete(memory_id=memory_id, reason=reason)
        return {
            "status": "deleted" if success else "failed",
            "memory_id": memory_id,
            "reason": reason,
            "soft_delete": True,
        }
    except Exception as e:
        return {"error": f"删除记忆失败: {str(e)}"}


def merge_memories(memory_ids: List[str], merged_content: str) -> Dict[str, Any]:
    """合并记忆"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        merged_id = mm.merge_memories(memory_ids=memory_ids, merged_content=merged_content)
        return {
            "status": "success",
            "merged_memory_id": merged_id,
            "original_count": len(memory_ids),
            "merged_content_preview": merged_content[:100],
        }
    except Exception as e:
        return {"error": f"合并记忆失败: {str(e)}"}


def clean_expired() -> Dict[str, Any]:
    """清理过期记忆"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        cleaned = mm.clean_expired(days=7)
        return {"status": "completed", "cleaned_count": cleaned}
    except Exception as e:
        return {"error": f"清理过期记忆失败: {str(e)}"}


def export_memories(format: str, memory_type: str = "all") -> Dict[str, Any]:
    """导出记忆"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        data = mm.export_memories(format=format, memory_type=memory_type)
        return {"status": "success", "format": format, "memory_type": memory_type, "data": data}
    except Exception as e:
        return {"error": f"导出记忆失败: {str(e)}"}


def get_memory_stats() -> Dict[str, Any]:
    """获取记忆统计"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        stats = mm.get_statistics()
        return stats
    except Exception as e:
        return {"error": f"获取统计失败: {str(e)}"}


def search_by_time(start_time: str, end_time: str) -> Dict[str, Any]:
    """按时间搜索"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        memories = mm.search_by_time(start=start_time, end=end_time)
        return {
            "start_time": start_time,
            "end_time": end_time,
            "count": len(memories),
            "memories": [
                {
                    "id": m.get("id"),
                    "content": m.get("content", "")[:200],
                    "created_at": m.get("created_at"),
                }
                for m in memories
            ],
        }
    except Exception as e:
        return {"error": f"按时间搜索失败: {str(e)}"}


def search_by_tag(tags: List[str]) -> Dict[str, Any]:
    """按标签搜索"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        memories = mm.search_by_tags(tags=tags)
        return {
            "tags": tags,
            "count": len(memories),
            "memories": [
                {
                    "id": m.get("id"),
                    "content": m.get("content", "")[:200],
                    "tags": m.get("tags", []),
                }
                for m in memories
            ],
        }
    except Exception as e:
        return {"error": f"按标签搜索失败: {str(e)}"}


def bulk_delete(memory_ids: List[str], reason: str) -> Dict[str, Any]:
    """批量删除（软删除）"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        result = mm.bulk_soft_delete(ids=memory_ids, reason=reason)
        return {
            "status": "completed",
            "deleted_count": result.get("success", 0),
            "failed_count": result.get("failed", 0),
            "reason": reason,
            "soft_delete": True,
        }
    except Exception as e:
        return {"error": f"批量删除失败: {str(e)}"}


def restore_memory(memory_id: str) -> Dict[str, Any]:
    """恢复记忆"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        success = mm.restore(memory_id=memory_id)
        return {"status": "restored" if success else "failed", "memory_id": memory_id}
    except Exception as e:
        return {"error": f"恢复记忆失败: {str(e)}"}


def search_similar_memories(
    memory_id: str, threshold: float = 0.7, limit: int = 10
) -> Dict[str, Any]:
    """搜索相似记忆"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        similar = mm.find_similar(memory_id=memory_id, threshold=threshold, limit=limit)
        return {
            "reference_memory_id": memory_id,
            "threshold": threshold,
            "count": len(similar),
            "similar_memories": similar,
        }
    except Exception as e:
        return {"error": f"搜索相似记忆失败: {str(e)}"}


def get_chat_history(session_id: str, limit: int = 50) -> Dict[str, Any]:
    """读取聊天记录"""
    cm = get_context_manager()
    if not cm:
        return {"error": "上下文管理器不可用"}

    try:
        messages = cm.get_messages(session_id=session_id, limit=limit)
        return {"session_id": session_id, "count": len(messages), "messages": messages}
    except Exception as e:
        return {"error": f"读取聊天记录失败: {str(e)}"}


def get_similar_memories(content: str, limit: int = 10) -> Dict[str, Any]:
    """相似记忆"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        memories = mm.find_similar_by_content(content=content, limit=limit)
        return {
            "content_preview": content[:100],
            "count": len(memories),
            "similar_memories": memories,
        }
    except Exception as e:
        return {"error": f"搜索相似记忆失败: {str(e)}"}


def get_memory_logs(memory_id: str = None, limit: int = 100) -> Dict[str, Any]:
    """记忆管理日志"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        logs = mm.get_operation_logs(memory_id=memory_id, limit=limit)
        return {"memory_id": memory_id, "count": len(logs), "logs": logs[-limit:]}
    except Exception as e:
        return {"error": f"获取日志失败: {str(e)}"}


def get_available_commands() -> Dict[str, Any]:
    """获取可用命令"""
    router = get_secondary_router()
    if not router:
        return {"error": "副模型路由器不可用"}

    try:
        commands = router.get_available_commands()
        return {"status": "success", "commands": commands}
    except Exception as e:
        return {"error": f"获取可用命令失败: {str(e)}"}
