"""
主模型工具 - 供主模型（main）调用的工具
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .registry import tool_registry

_MEMORY_MANAGER = None
_SECONDARY_ROUTER = None
_CONTEXT_MANAGER = None
_ACP_MANAGER = None


def set_dependencies(
    memory_manager=None, secondary_router=None, context_manager=None, acp_manager=None
):
    """设置依赖的组件"""
    global _MEMORY_MANAGER, _SECONDARY_ROUTER, _CONTEXT_MANAGER, _ACP_MANAGER
    _MEMORY_MANAGER = memory_manager
    _SECONDARY_ROUTER = secondary_router
    _CONTEXT_MANAGER = context_manager
    _ACP_MANAGER = acp_manager


def get_memory_manager():
    """获取记忆管理器"""
    return _MEMORY_MANAGER


def get_secondary_router():
    """获取副模型路由器"""
    return _SECONDARY_ROUTER


def get_context_manager():
    """获取上下文管理器"""
    return _CONTEXT_MANAGER


def get_acp_manager():
    """获取 ACP 管理器"""
    return _ACP_MANAGER


def register_master_tools():
    """注册所有主模型工具"""

    # 1. write_long_term_memory - 写入长期记忆
    tool_registry.register(
        name="write_long_term_memory",
        description="将关键信息写入长期记忆库。这些信息会在后续对话中被检索和使用。",
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要记忆的内容（用户的重要信息、偏好、事件等）",
                },
                "importance": {
                    "type": "integer",
                    "enum": [1, 2, 3, 4, 5],
                    "description": "重要性等级（1-5），5为最重要",
                    "default": 3,
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签列表，用于后续检索",
                    "default": [],
                },
            },
            "required": ["content"],
        },
        function=write_long_term_memory,
        category="memory",
        tags=["memory", "long_term", "save"],
        examples=["记住用户喜欢蓝色", "保存这个重要的日期：2024年1月1日", "记录用户的工作是程序员"],
    )

    # 2. search_all_memories - 搜索所有记忆
    tool_registry.register(
        name="search_all_memories",
        description="跨所有记忆库进行语义检索，获取与当前话题相关的记忆。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询（描述你想要找的信息）"},
                "memory_type": {
                    "type": "string",
                    "enum": ["permanent", "long_term", "all"],
                    "description": "记忆类型筛选（permanent=永久记忆，long_term=长期记忆，all=全部）",
                    "default": "all",
                },
                "time_range": {
                    "type": "string",
                    "description": "时间范围筛选（如 'last_week', 'last_month', 'today'）",
                    "default": None,
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量限制",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["query"],
        },
        function=search_all_memories,
        category="memory",
        tags=["memory", "search", "recall"],
        examples=["用户之前说过喜欢什么颜色？", "查找关于工作的记忆", "搜索今天的对话内容"],
    )

    # 3. call_assistant - 调用记忆管理模型
    tool_registry.register(
        name="call_assistant",
        description="向记忆管理模型发送指令，获取其专业处理结果。适用于需要记忆管理模型处理的复杂任务。",
        parameters={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "给记忆管理模型的消息/指令，可以是自然语言描述你想要它做什么",
                }
            },
            "required": ["message"],
        },
        function=call_assistant,
        category="system",
        tags=["assistant", "memory", "task"],
        examples=["帮我总结今天的所有对话", "分析这条记忆的重要性", "提取这段文字的关键要点"],
    )

    # 4. set_alarm - 设置提醒
    tool_registry.register(
        name="set_alarm",
        description="设置一个定时提醒。在指定秒数后，系统会向用户发送提醒消息。",
        parameters={
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": "多少秒后提醒（最小1秒，最大86400秒即24小时）",
                },
                "message": {"type": "string", "description": "提醒消息内容"},
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID（可选，默认为 'default'）",
                    "default": "default",
                },
            },
            "required": ["seconds", "message"],
        },
        function=set_alarm,
        category="reminder",
        tags=["alarm", "reminder", "schedule"],
        examples=["5分钟后提醒我喝水", "1小时后提醒我开会", "设置一个30秒后的测试提醒"],
    )

    # 4.1 get_alarms - 获取提醒列表
    tool_registry.register(
        name="get_alarms",
        description="获取当前 Agent 的提醒列表。",
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID（可选，默认为 'default'）",
                    "default": "default",
                },
                "include_triggered": {
                    "type": "boolean",
                    "description": "是否包含已触发的提醒",
                    "default": False,
                },
            },
            "required": [],
        },
        function=get_alarms,
        category="reminder",
        tags=["alarm", "reminder", "list"],
        examples=["查看我的提醒列表", "获取所有提醒（包括已触发的）"],
    )

    # 4.2 cancel_alarm - 取消提醒
    tool_registry.register(
        name="cancel_alarm",
        description="取消一个已设置的提醒。",
        parameters={
            "type": "object",
            "properties": {"alarm_id": {"type": "string", "description": "要取消的提醒 ID"}},
            "required": ["alarm_id"],
        },
        function=cancel_alarm,
        category="reminder",
        tags=["alarm", "reminder", "cancel"],
        examples=["取消提醒 abc123", "删除刚才设置的提醒"],
    )

    # 5. mono - 保持上下文
    tool_registry.register(
        name="mono",
        description="将某些信息保持在接下来的对话上下文中。这对于需要跨多轮记住的信息很有用。",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要保持在上下文中的信息"},
                "session_id": {
                    "type": "string",
                    "description": "会话ID（可选，如果不提供则记录到当前对话）",
                },
                "rounds": {
                    "type": "integer",
                    "description": "保持的对话轮数（默认1轮）",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["content"],
        },
        function=mono,
        category="context",
        tags=["context", "mono", "remember"],
        examples=["记住我们现在在讨论项目A", "保持这个信息：在接下来的对话中用户叫张三"],
    )

    # 6. write_permanent_memory - 写入永久记忆
    tool_registry.register(
        name="write_permanent_memory",
        description="将关键信息写入永久记忆库。永久记忆永远不会被衰减或删除，适合存储用户的核心理念、重要事实等。",
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要永久记住的内容（用户的核心信念、重要事实、关键偏好等）",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签列表，用于后续检索",
                    "default": [],
                },
            },
            "required": ["content"],
        },
        function=write_permanent_memory,
        category="memory",
        tags=["memory", "permanent", "save"],
        examples=[
            "永久记住用户的名字叫张三",
            "记住用户是素食主义者",
            "保存用户的核心理念：诚实是最重要的品质",
        ],
    )

    # 7. acp_list_agents - 列出可用的远程 Agent
    tool_registry.register(
        name="acp_list_agents",
        description="列出 ACP 网络中所有可用的远程 Agent。可以查看哪些 Agent 在线并可以连接。",
        parameters={
            "type": "object",
            "properties": {
                "online_only": {
                    "type": "boolean",
                    "description": "是否只显示在线的 Agent",
                    "default": True,
                }
            },
            "required": [],
        },
        function=acp_list_agents,
        category="acp",
        tags=["acp", "agent", "network"],
        examples=["列出所有在线的 Agent", "查看网络中有哪些 Agent"],
    )

    # 8. acp_connect - 连接到远程 Agent
    tool_registry.register(
        name="acp_connect",
        description="连接到 ACP 网络中的远程 Agent，建立通信通道。",
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "要连接的远程 Agent ID"},
                "host": {
                    "type": "string",
                    "description": "远程 Agent 的主机地址（可选，如果 Agent 已注册则不需要）",
                },
                "port": {"type": "integer", "description": "远程 Agent 的端口（可选）"},
            },
            "required": ["agent_id"],
        },
        function=acp_connect,
        category="acp",
        tags=["acp", "connect", "network"],
        examples=["连接到 Agent 'assistant-001'", "连接到远程 Agent"],
    )

    # 9. acp_disconnect - 断开与远程 Agent 的连接
    tool_registry.register(
        name="acp_disconnect",
        description="断开与远程 Agent 的连接。",
        parameters={
            "type": "object",
            "properties": {"connection_id": {"type": "string", "description": "要断开的连接 ID"}},
            "required": ["connection_id"],
        },
        function=acp_disconnect,
        category="acp",
        tags=["acp", "disconnect", "network"],
        examples=["断开与 Agent 的连接"],
    )

    # 10. acp_send_message - 向远程 Agent 发送消息
    tool_registry.register(
        name="acp_send_message",
        description="向远程 Agent 发送消息。",
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "目标 Agent ID"},
                "message": {"type": "string", "description": "要发送的消息内容"},
                "message_type": {
                    "type": "string",
                    "enum": ["chat", "task", "query"],
                    "description": "消息类型",
                    "default": "chat",
                },
            },
            "required": ["agent_id", "message"],
        },
        function=acp_send_message,
        category="acp",
        tags=["acp", "message", "network"],
        examples=["向 Agent 发送消息", "请求其他 Agent 帮助处理任务"],
    )

    # 11. acp_create_group - 创建 Agent 群组
    tool_registry.register(
        name="acp_create_group",
        description="创建一个 Agent 群组，用于群组通信和协作。",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "群组名称"},
                "description": {"type": "string", "description": "群组描述", "default": ""},
            },
            "required": ["name"],
        },
        function=acp_create_group,
        category="acp",
        tags=["acp", "group", "network"],
        examples=["创建一个项目协作群组", "创建讨论组"],
    )

    # 12. acp_join_group - 加入群组
    tool_registry.register(
        name="acp_join_group",
        description="加入一个已存在的 Agent 群组。",
        parameters={
            "type": "object",
            "properties": {"group_id": {"type": "string", "description": "要加入的群组 ID"}},
            "required": ["group_id"],
        },
        function=acp_join_group,
        category="acp",
        tags=["acp", "group", "network"],
        examples=["加入协作群组"],
    )

    # 13. acp_leave_group - 离开群组
    tool_registry.register(
        name="acp_leave_group",
        description="离开一个 Agent 群组。",
        parameters={
            "type": "object",
            "properties": {"group_id": {"type": "string", "description": "要离开的群组 ID"}},
            "required": ["group_id"],
        },
        function=acp_leave_group,
        category="acp",
        tags=["acp", "group", "network"],
        examples=["离开协作群组"],
    )


def write_long_term_memory(
    content: str = None,
    importance: int = 3,
    tags: List[str] = None,
    # 别名参数（兼容模型不同调用方式）
    message: str = None,
    priority: int = None,
    tag: str = None,
) -> Dict[str, Any]:
    """写入长期记忆"""
    # 参数别名映射
    content = content or message
    if priority is not None:
        importance = priority
    if tag and not tags:
        tags = [tag]

    if not content:
        return {"error": "内容不能为空"}

    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        memory_id = mm.write_memory(
            content=content, memory_type="long_term", importance=importance, tags=tags or []
        )
        return {
            "status": "success",
            "message": f"记忆已保存",
            "memory_id": memory_id,
            "content_preview": content[:100] + "..." if len(content) > 100 else content,
        }
    except Exception as e:
        return {"error": f"保存记忆失败: {str(e)}"}


def search_all_memories(
    query: str, memory_type: str = "all", time_range: str = None, limit: int = 10
) -> Dict[str, Any]:
    """搜索所有记忆"""
    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        memories = mm.search_memories(
            query=query,
            memory_type=memory_type if memory_type != "all" else None,
            time_range=time_range,
            limit=limit,
        )
        return {
            "status": "success",
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


async def call_assistant(message: str) -> Dict[str, Any]:
    """调用记忆管理模型"""
    router = get_secondary_router()
    if not router:
        return {"error": "记忆管理模型不可用"}

    try:
        from backend.core.memory.secondary_router import SecondaryCommand, SecondaryInstruction

        instruction = SecondaryInstruction(
            command="custom", parameters={"user_message": message}, priority=1  # 自定义指令
        )

        result = await router.execute_command(instruction, is_from_main=True)

        return {
            "status": result.status,
            "message": message,
            "response": result.output.get("response", "") or str(result.output),
            "execution_time_ms": result.execution_time_ms,
        }
    except Exception as e:
        return {"error": f"调用记忆管理模型失败: {str(e)}"}


def set_alarm(seconds: int, message: str, agent_id: str = "default") -> Dict[str, Any]:
    """设置提醒

    Args:
        seconds: 秒数（1-86400，即24小时内）
        message: 提醒消息
        agent_id: Agent ID（可选）

    Returns:
        包含 alarm_id 和 scheduled_time 的字典
    """
    if not (1 <= seconds <= 86400):
        return {"error": "秒数必须在1-86400之间（24小时内）"}

    try:
        from backend.core.alarm import get_alarm_manager

        alarm_mgr = get_alarm_manager()
        alarm_id = alarm_mgr.create_alarm(agent_id, seconds, message)

        return {
            "status": "scheduled",
            "alarm_id": alarm_id,
            "seconds": seconds,
            "message": message,
            "scheduled_time": (datetime.now() + timedelta(seconds=seconds)).isoformat(),
        }
    except Exception as e:
        return {"error": f"设置提醒失败: {str(e)}"}


def get_alarms(agent_id: str = "default", include_triggered: bool = False) -> Dict[str, Any]:
    """获取提醒列表

    Args:
        agent_id: Agent ID
        include_triggered: 是否包含已触发的提醒

    Returns:
        提醒列表
    """
    try:
        from backend.core.alarm import get_alarm_manager

        alarm_mgr = get_alarm_manager()
        alarms = alarm_mgr.get_alarms_by_agent(agent_id, include_triggered)

        return {"status": "success", "agent_id": agent_id, "count": len(alarms), "alarms": alarms}
    except Exception as e:
        return {"error": f"获取提醒列表失败: {str(e)}"}


def cancel_alarm(alarm_id: str) -> Dict[str, Any]:
    """取消提醒

    Args:
        alarm_id: 提醒ID

    Returns:
        取消结果
    """
    try:
        from backend.core.alarm import get_alarm_manager

        alarm_mgr = get_alarm_manager()
        success = alarm_mgr.cancel_alarm(alarm_id)

        if success:
            return {"status": "cancelled", "alarm_id": alarm_id}
        else:
            return {"status": "not_found", "alarm_id": alarm_id, "error": "提醒不存在或已触发"}
    except Exception as e:
        return {"error": f"取消提醒失败: {str(e)}"}


def mono(content: str, session_id: str = None, rounds: int = 1) -> Dict[str, Any]:
    """保持上下文"""
    cm = get_context_manager()
    if not cm:
        return {"error": "上下文管理器不可用"}

    if not session_id:
        return {
            "status": "info",
            "message": "内容已记录，将在后续对话中保持。请提供 session_id 以持久化存储。",
            "content": content,
            "rounds": rounds,
            "session_id": None,
        }

    try:
        result = cm.add_mono_context(session_id=session_id, content=content, rounds=rounds)
        if result:
            from datetime import datetime, timedelta

            expires_at = datetime.now() + timedelta(rounds=rounds)
            return {
                "status": "success",
                "message": "上下文已添加，将在指定轮数内保持",
                "content": content,
                "rounds": rounds,
                "session_id": session_id,
                "expires_after_rounds": rounds,
                "added_at": datetime.now().isoformat(),
            }
        else:
            return {
                "status": "failed",
                "error": "添加上下文失败",
                "content": content,
                "session_id": session_id,
            }
    except Exception as e:
        return {"error": f"添加上下文信息失败: {str(e)}"}


def write_permanent_memory(
    content: str = None,
    tags: List[str] = None,
    # 别名参数（兼容模型不同调用方式）
    message: str = None,
    tag: str = None,
) -> Dict[str, Any]:
    """写入永久记忆"""
    # 参数别名映射
    content = content or message
    if tag and not tags:
        tags = [tag]

    if not content:
        return {"error": "内容不能为空"}

    mm = get_memory_manager()
    if not mm:
        return {"error": "记忆管理器不可用"}

    try:
        memory_id = mm.write_permanent_memory(content=content, tags=tags or [], is_from_main=True)
        return {
            "status": "success",
            "message": "永久记忆已保存",
            "memory_id": memory_id,
            "content_preview": content[:100] + "..." if len(content) > 100 else content,
        }
    except Exception as e:
        return {"error": f"保存永久记忆失败: {str(e)}"}


async def acp_list_agents(online_only: bool = True) -> Dict[str, Any]:
    """列出可用的远程 Agent"""
    acp = get_acp_manager()
    if not acp:
        return {"error": "ACP 管理器不可用"}

    try:
        agents = await acp.list_agents(online_only=online_only)
        return {"status": "success", "count": len(agents), "agents": agents}
    except Exception as e:
        return {"error": f"获取 Agent 列表失败: {str(e)}"}


async def acp_connect(agent_id: str, host: str = None, port: int = None) -> Dict[str, Any]:
    """连接到远程 Agent"""
    acp = get_acp_manager()
    if not acp:
        return {"error": "ACP 管理器不可用"}

    try:
        import uuid

        from backend.core.acp.manager import ACPConnectionInfo

        # 检查 Agent 是否已注册
        agent = await acp.get_agent(agent_id)
        if agent:
            host = host or agent.get("host", "")
            port = port or agent.get("port", 0)

        if not host:
            return {"error": f"Agent '{agent_id}' 未注册，请提供 host 和 port"}

        connection = ACPConnectionInfo(
            id=str(uuid.uuid4()),
            local_agent_id=acp._local_agent_id,
            remote_agent_id=agent_id,
            remote_agent_name=agent.get("name", agent_id) if agent else agent_id,
            host=host,
            port=port,
            status="connected",
            connected_at=datetime.now().isoformat(),
        )

        await acp.create_connection(connection)

        return {
            "status": "success",
            "connection_id": connection.id,
            "remote_agent_id": agent_id,
            "remote_agent_name": connection.remote_agent_name,
            "host": host,
            "port": port,
        }
    except Exception as e:
        return {"error": f"连接 Agent 失败: {str(e)}"}


async def acp_disconnect(connection_id: str) -> Dict[str, Any]:
    """断开与远程 Agent 的连接"""
    acp = get_acp_manager()
    if not acp:
        return {"error": "ACP 管理器不可用"}

    try:
        success = await acp.delete_connection(connection_id)
        if success:
            return {"status": "success", "message": f"连接 {connection_id} 已断开"}
        else:
            return {"error": f"连接 {connection_id} 不存在"}
    except Exception as e:
        return {"error": f"断开连接失败: {str(e)}"}


async def acp_send_message(
    agent_id: str, message: str, message_type: str = "chat"
) -> Dict[str, Any]:
    """向远程 Agent 发送消息"""
    acp = get_acp_manager()
    if not acp:
        return {"error": "ACP 管理器不可用"}

    try:
        import uuid

        from backend.core.acp.manager import ACPMessageInfo

        msg = ACPMessageInfo(
            id=str(uuid.uuid4()),
            from_agent_id=acp._local_agent_id,
            to_agent_id=agent_id,
            message_type=message_type,
            content=message,
            created_at=datetime.now().isoformat(),
        )

        await acp.send_message(msg)

        return {
            "status": "success",
            "message_id": msg.id,
            "to_agent_id": agent_id,
            "message_type": message_type,
        }
    except Exception as e:
        return {"error": f"发送消息失败: {str(e)}"}


async def acp_create_group(name: str, description: str = "") -> Dict[str, Any]:
    """创建 Agent 群组"""
    acp = get_acp_manager()
    if not acp:
        return {"error": "ACP 管理器不可用"}

    try:
        import uuid

        from backend.core.acp.manager import ACPGroupInfo

        group = ACPGroupInfo(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            creator_id=acp._local_agent_id,
            creator_name=acp._local_agent_name,
            members=[
                {
                    "agent_id": acp._local_agent_id,
                    "agent_name": acp._local_agent_name,
                    "joined_at": datetime.now().isoformat(),
                }
            ],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )

        await acp.create_group(group)

        return {"status": "success", "group_id": group.id, "name": name, "description": description}
    except Exception as e:
        return {"error": f"创建群组失败: {str(e)}"}


async def acp_join_group(group_id: str) -> Dict[str, Any]:
    """加入群组"""
    acp = get_acp_manager()
    if not acp:
        return {"error": "ACP 管理器不可用"}

    try:
        member = {
            "agent_id": acp._local_agent_id,
            "agent_name": acp._local_agent_name,
            "joined_at": datetime.now().isoformat(),
        }

        success = await acp.add_group_member(group_id, member)

        if success:
            return {"status": "success", "group_id": group_id, "message": f"已加入群组 {group_id}"}
        else:
            return {"error": f"群组 {group_id} 不存在"}
    except Exception as e:
        return {"error": f"加入群组失败: {str(e)}"}


async def acp_leave_group(group_id: str) -> Dict[str, Any]:
    """离开群组"""
    acp = get_acp_manager()
    if not acp:
        return {"error": "ACP 管理器不可用"}

    try:
        success = await acp.remove_group_member(group_id, acp._local_agent_id)

        if success:
            return {"status": "success", "group_id": group_id, "message": f"已离开群组 {group_id}"}
        else:
            return {"error": f"群组 {group_id} 不存在或你不在该群组中"}
    except Exception as e:
        return {"error": f"离开群组失败: {str(e)}"}
