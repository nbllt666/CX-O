"""
摘要模型工具 - 供摘要模型（summary）调用的工具
"""

from typing import Any, Dict, List, Optional

from .registry import tool_registry
from .graph_tools import (
    user_graph_extract_entities, user_graph_merge_entities, user_graph_get_entity_summary,
    thing_graph_extract_entities, thing_graph_merge_entities, thing_graph_get_entity_summary,
    concept_graph_extract_entities, concept_graph_merge_entities, concept_graph_get_entity_summary,
    event_graph_extract_entities, event_graph_merge_entities, event_graph_get_entity_summary,
)
from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

_MEMORY_MANAGER = None
_MODEL_ROUTER = None
_CONTEXT_MANAGER = None

_TOPIC_SUMMARY_CONFIG = {
    "max_history_topics": None,  # None 表示无限制，数字表示保留的历史话题数量
    "auto_save_memory": True,
    "topic_marker_enabled": True,
}


def set_dependencies(memory_manager=None, model_router=None, context_manager=None):
    """设置依赖的组件"""
    global _MEMORY_MANAGER, _MODEL_ROUTER, _CONTEXT_MANAGER
    _MEMORY_MANAGER = memory_manager
    _MODEL_ROUTER = model_router
    _CONTEXT_MANAGER = context_manager


def get_topic_summary_config() -> Dict[str, Any]:
    """获取话题摘要配置"""
    return _TOPIC_SUMMARY_CONFIG.copy()


def update_topic_summary_config(key: str, value: Any) -> Dict[str, Any]:
    """更新话题摘要配置
    
    Args:
        key: 配置项名称
        value: 配置值
    
    Returns:
        更新后的配置
    """
    if key in _TOPIC_SUMMARY_CONFIG:
        _TOPIC_SUMMARY_CONFIG[key] = value
        return {"status": "success", "config": _TOPIC_SUMMARY_CONFIG}
    return {"error": f"未知的配置项: {key}"}


def set_max_history_topics(max_topics: Optional[int] = None):
    """设置保持在上下文中的历史话题数量

    Args:
        max_topics: 最大历史话题数量，None 表示无限制
    """
    _TOPIC_SUMMARY_CONFIG["max_history_topics"] = max_topics


def get_topic_summary_config_wrapper() -> Dict[str, Any]:
    """获取话题摘要配置的包装函数"""
    return get_topic_summary_config()


def set_max_history_topics_wrapper(max_topics: Optional[int]) -> Dict[str, Any]:
    """设置历史话题数量的包装函数

    Args:
        max_topics: 最大历史话题数量，None 表示无限制

    Returns:
        执行结果
    """
    try:
        set_max_history_topics(max_topics)
        return {
            "status": "success",
            "message": f"历史话题数量已设置为 {max_topics if max_topics else '无限制'}",
            "max_history_topics": _TOPIC_SUMMARY_CONFIG["max_history_topics"],
        }
    except Exception as e:
        return {"error": f"设置失败: {str(e)}"}


def get_summary_client():
    """获取摘要模型客户端"""
    if _MODEL_ROUTER:
        client = _MODEL_ROUTER.get_client("summary")
        if client:
            return client
    return None


def get_context_manager():
    """获取上下文管理器"""
    return _CONTEXT_MANAGER


def register_summary_tools():
    """注册所有摘要模型工具"""

    # 1. summarize_content - 生成摘要
    tool_registry.register(
        name="summarize_content",
        description="使用摘要模型对内容进行摘要，生成简洁的摘要版本。",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要摘要的内容（对话、文本、记忆等）"},
                "max_length": {
                    "type": "integer",
                    "description": "摘要最大长度（字符数）",
                    "default": 200,
                },
            },
            "required": ["content"],
        },
        function=summarize_content,
        category="summary",
        tags=["summary", "summarize", "extract"],
        examples=["摘要这段对话的主要内容", "总结这段文字的核心观点", "提取这段内容的要点"],
    )

    # 2. save_summary_memory - 保存摘要记忆
    tool_registry.register(
        name="save_summary_memory",
        description="将摘要内容保存为长期记忆。可以保存多条记忆，每条包含内容、重要性(1-10)和时间戳(yyyymmddhhmm格式)。",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "记忆内容，简洁明了地描述要点"},
                "importance": {
                    "type": "integer",
                    "description": "重要性等级 (1-10, 10为最重要)",
                    "minimum": 1,
                    "maximum": 10,
                },
                "timestamp": {
                    "type": "string",
                    "description": "时间戳，格式为 yyyymmddhhmm，如 202602112235",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签列表（可选）",
                    "default": ["summary"],
                },
            },
            "required": ["content", "importance", "timestamp"],
        },
        function=save_summary_memory,
        category="summary",
        tags=["summary", "memory", "save", "store"],
        examples=[
            "保存这条记忆：用户喜欢喝咖啡，重要性8，时间202602112300",
            "记录：用户明天要开会，重要性9，时间202602111200",
        ],
    )

    # 3. get_session_messages - 获取会话消息
    tool_registry.register(
        name="get_session_messages",
        description="获取指定会话的消息列表，用于了解当前对话上下文。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID"},
                "limit": {"type": "integer", "description": "获取的消息数量限制", "default": 50},
            },
            "required": ["session_id"],
        },
        function=get_session_messages,
        category="summary",
        tags=["summary", "context", "messages"],
        examples=["获取当前会话的消息", "查看最近的对话内容"],
    )

    # 4. clear_summary_context - 清空摘要助手上下文
    tool_registry.register(
        name="clear_summary_context",
        description="清空摘要助手会话的所有消息，重置对话上下文。",
        parameters={
            "type": "object",
            "properties": {"session_id": {"type": "string", "description": "要清空的会话ID"}},
            "required": ["session_id"],
        },
        function=clear_summary_context,
        category="summary",
        tags=["summary", "context", "clear"],
        examples=["清空当前会话的上下文", "重置对话历史"],
    )

    # 4.1 trigger_topic_summary - 触发话题摘要
    tool_registry.register(
        name="trigger_topic_summary",
        description="触发当前话题的摘要生成。应在判断当前话题已结束时调用，摘要将替换当前话题的上下文并保存为记忆。摘要内容由摘要模型自主生成。",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "会话ID"},
                "topic": {
                    "type": "string",
                    "description": "话题名称/主题（可选，由主模型提供）",
                },
                "end_signal": {
                    "type": "string",
                    "description": "结束信号（可选），主模型判断话题结束的依据",
                },
            },
            "required": ["session_id"],
        },
        function=trigger_topic_summary,
        category="summary",
        tags=["summary", "topic", "trigger", "compress"],
        examples=["触发当前话题摘要", "总结当前讨论的内容"],
    )

    # 4.2 start_topic - 开始新话题
    # 4.2 get_topic_summary_config - 获取话题摘要配置
    tool_registry.register(
        name="get_topic_summary_config",
        description="获取话题摘要系统的当前配置，包括保持在上下文中的历史话题数量等设置。",
        parameters={
            "type": "object",
            "properties": {},
        },
        function=get_topic_summary_config_wrapper,
        category="summary",
        tags=["summary", "config", "topic", "settings"],
        examples=["查看话题摘要配置", "获取当前设置"],
    )

    # 4.4 set_max_history_topics - 设置历史话题数量
    tool_registry.register(
        name="set_max_history_topics",
        description="设置保持在上下文中的历史话题数量。当历史话题超过此数量时，最早的话题摘要将被清理。设置为 null 表示无限制。",
        parameters={
            "type": "object",
            "properties": {
                "max_topics": {
                    "type": "integer",
                    "description": "最大历史话题数量，设置为 null 表示无限制",
                },
            },
            "required": ["max_topics"],
        },
        function=set_max_history_topics_wrapper,
        category="summary",
        tags=["summary", "config", "topic", "limit"],
        examples=["设置历史话题数量为 5", "限制历史话题为 3 个"],
    )

    # 5-16. 图工具注册 (4库 × 3工具 = 12个)
    # 5. user_graph_extract_entities
    tool_registry.register(
        name="user_graph_extract_entities",
        description="从内容中提取用户图实体（使用LLM）。用于从文本中识别和提取用户相关的实体信息。",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "待提取的内容"},
            },
            "required": ["content"],
        },
        function=user_graph_extract_entities,
        category="summary",
        tags=["graph", "user", "extract", "entities"],
        examples=["从这段文字中提取用户实体", "识别文本中的用户相关信息"],
    )

    # 6. user_graph_merge_entities
    tool_registry.register(
        name="user_graph_merge_entities",
        description="合并用户图中的两个实体。当存在重复或相似的用户实体时使用。",
        parameters={
            "type": "object",
            "properties": {
                "entity1_id": {"type": "string", "description": "第一个实体ID（保留）"},
                "entity2_id": {"type": "string", "description": "第二个实体ID（合并到第一个）"},
            },
            "required": ["entity1_id", "entity2_id"],
        },
        function=user_graph_merge_entities,
        category="summary",
        tags=["graph", "user", "merge", "entities"],
        examples=["合并两个重复的用户实体", "将entity2合并到entity1"],
    )

    # 7. user_graph_get_entity_summary
    tool_registry.register(
        name="user_graph_get_entity_summary",
        description="获取用户图实体摘要。查询指定用户实体的详细信息和摘要。",
        parameters={
            "type": "object",
            "properties": {
                "entity_name_or_id": {"type": "string", "description": "实体名称或ID"},
            },
            "required": ["entity_name_or_id"],
        },
        function=user_graph_get_entity_summary,
        category="summary",
        tags=["graph", "user", "summary", "entity"],
        examples=["获取用户'张三'的实体摘要", "查询该用户实体的详细信息"],
    )

    # 8. thing_graph_extract_entities
    tool_registry.register(
        name="thing_graph_extract_entities",
        description="从内容中提取物品图实体（使用LLM）。用于从文本中识别和提取物品相关的实体信息。",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "待提取的内容"},
            },
            "required": ["content"],
        },
        function=thing_graph_extract_entities,
        category="summary",
        tags=["graph", "thing", "extract", "entities"],
        examples=["从这段文字中提取物品实体", "识别文本中的物品相关信息"],
    )

    # 9. thing_graph_merge_entities
    tool_registry.register(
        name="thing_graph_merge_entities",
        description="合并物品图中的两个实体。当存在重复或相似的物品实体时使用。",
        parameters={
            "type": "object",
            "properties": {
                "entity1_id": {"type": "string", "description": "第一个实体ID（保留）"},
                "entity2_id": {"type": "string", "description": "第二个实体ID（合并到第一个）"},
            },
            "required": ["entity1_id", "entity2_id"],
        },
        function=thing_graph_merge_entities,
        category="summary",
        tags=["graph", "thing", "merge", "entities"],
        examples=["合并两个重复的物品实体", "将entity2合并到entity1"],
    )

    # 10. thing_graph_get_entity_summary
    tool_registry.register(
        name="thing_graph_get_entity_summary",
        description="获取物品图实体摘要。查询指定物品实体的详细信息和摘要。",
        parameters={
            "type": "object",
            "properties": {
                "entity_name_or_id": {"type": "string", "description": "实体名称或ID"},
            },
            "required": ["entity_name_or_id"],
        },
        function=thing_graph_get_entity_summary,
        category="summary",
        tags=["graph", "thing", "summary", "entity"],
        examples=["获取物品'电脑'的实体摘要", "查询该物品实体的详细信息"],
    )

    # 11. concept_graph_extract_entities
    tool_registry.register(
        name="concept_graph_extract_entities",
        description="从内容中提取概念图实体（使用LLM）。用于从文本中识别和提取概念相关的实体信息。",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "待提取的内容"},
            },
            "required": ["content"],
        },
        function=concept_graph_extract_entities,
        category="summary",
        tags=["graph", "concept", "extract", "entities"],
        examples=["从这段文字中提取概念实体", "识别文本中的概念相关信息"],
    )

    # 12. concept_graph_merge_entities
    tool_registry.register(
        name="concept_graph_merge_entities",
        description="合并概念图中的两个实体。当存在重复或相似的概念实体时使用。",
        parameters={
            "type": "object",
            "properties": {
                "entity1_id": {"type": "string", "description": "第一个实体ID（保留）"},
                "entity2_id": {"type": "string", "description": "第二个实体ID（合并到第一个）"},
            },
            "required": ["entity1_id", "entity2_id"],
        },
        function=concept_graph_merge_entities,
        category="summary",
        tags=["graph", "concept", "merge", "entities"],
        examples=["合并两个重复的概念实体", "将entity2合并到entity1"],
    )

    # 13. concept_graph_get_entity_summary
    tool_registry.register(
        name="concept_graph_get_entity_summary",
        description="获取概念图实体摘要。查询指定概念实体的详细信息和摘要。",
        parameters={
            "type": "object",
            "properties": {
                "entity_name_or_id": {"type": "string", "description": "实体名称或ID"},
            },
            "required": ["entity_name_or_id"],
        },
        function=concept_graph_get_entity_summary,
        category="summary",
        tags=["graph", "concept", "summary", "entity"],
        examples=["获取概念'人工智能'的实体摘要", "查询该概念实体的详细信息"],
    )

    # 14. event_graph_extract_entities
    tool_registry.register(
        name="event_graph_extract_entities",
        description="从内容中提取事件图实体（使用LLM）。用于从文本中识别和提取事件相关的实体信息。",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "待提取的内容"},
            },
            "required": ["content"],
        },
        function=event_graph_extract_entities,
        category="summary",
        tags=["graph", "event", "extract", "entities"],
        examples=["从这段文字中提取事件实体", "识别文本中的事件相关信息"],
    )

    # 15. event_graph_merge_entities
    tool_registry.register(
        name="event_graph_merge_entities",
        description="合并事件图中的两个实体。当存在重复或相似的事件实体时使用。",
        parameters={
            "type": "object",
            "properties": {
                "entity1_id": {"type": "string", "description": "第一个实体ID（保留）"},
                "entity2_id": {"type": "string", "description": "第二个实体ID（合并到第一个）"},
            },
            "required": ["entity1_id", "entity2_id"],
        },
        function=event_graph_merge_entities,
        category="summary",
        tags=["graph", "event", "merge", "entities"],
        examples=["合并两个重复的事件实体", "将entity2合并到entity1"],
    )

    # 16. event_graph_get_entity_summary
    tool_registry.register(
        name="event_graph_get_entity_summary",
        description="获取事件图实体摘要。查询指定事件实体的详细信息和摘要。",
        parameters={
            "type": "object",
            "properties": {
                "entity_name_or_id": {"type": "string", "description": "实体名称或ID"},
            },
            "required": ["entity_name_or_id"],
        },
        function=event_graph_get_entity_summary,
        category="summary",
        tags=["graph", "event", "summary", "entity"],
        examples=["获取事件'产品发布会'的实体摘要", "查询该事件实体的详细信息"],
    )


async def summarize_content(content: str, max_length: int = 200) -> Dict[str, Any]:
    """生成摘要"""
    summary_client = get_summary_client()
    if not summary_client:
        return {"error": "摘要模型不可用"}

    try:
        prompt = f"""请对以下内容进行摘要，长度不超过{max_length}字：

{content}

要求：
1. 保留核心信息
2. 语言简洁明了
3. 直接返回摘要文本，不要添加额外说明"""

        response = await summary_client.chat(
            messages=[{"role": "user", "content": prompt}], stream=False
        )

        summary = ""
        if hasattr(response, "content") and response.content:
            summary = response.content.strip()
        elif isinstance(response, dict) and response.get("content"):
            summary = response.get("content").strip()
        else:
            summary = str(response)

        return {
            "status": "success",
            "original_length": len(content),
            "summary_length": len(summary),
            "summary": summary,
        }
    except Exception as e:
        return {"error": f"生成摘要失败: {str(e)}"}


async def save_summary_memory(
    content: str, importance: int, timestamp: str, tags: list = None, topic: str = None
) -> Dict[str, Any]:
    """保存摘要记忆

    Args:
        content: 记忆内容
        importance: 重要性 (1-10, 10为最重要)
        timestamp: 时间戳 (格式: yyyymmddhhmm, 如 202602112235)
        tags: 标签列表 (可选)
        topic: 话题名称 (可选)

    Returns:
        保存结果
    """
    if not _MEMORY_MANAGER:
        return {"error": "记忆管理器未初始化"}

    try:
        # 验证参数
        if not content or len(content.strip()) == 0:
            return {"error": "记忆内容不能为空"}

        if not isinstance(importance, int) or importance < 1 or importance > 10:
            return {"error": "重要性必须是 1-10 之间的整数"}

        # 解析时间戳
        from datetime import datetime

        try:
            if len(timestamp) == 12:  # yyyymmddhhmm
                dt = datetime.strptime(timestamp, "%Y%m%d%H%M")
            elif len(timestamp) == 8:  # yyyymmdd
                dt = datetime.strptime(timestamp, "%Y%m%d")
            else:
                return {"error": "时间戳格式错误，应为 yyyymmddhhmm 或 yyyymmdd"}
        except ValueError:
            return {"error": "时间戳格式错误，应为 yyyymmddhhmm 或 yyyymmdd"}

        # 将重要性转换为 0-1 范围
        importance_normalized = importance / 10.0

        # 构建元信息
        metadata = {
            "source": "summary",
            "original_timestamp": timestamp,
            "importance_level": importance,
        }
        if topic:
            metadata["topic"] = topic

        # 构建标签
        final_tags = tags or ["summary"]
        if topic:
            final_tags.append(f"topic:{topic}")

        # 保存记忆
        memory_id = await _MEMORY_MANAGER.write_memory_async(
            content=content,
            memory_type="long_term",
            importance=importance_normalized,
            tags=final_tags,
            metadata=metadata,
        )

        return {
            "status": "success",
            "memory_id": memory_id,
            "content": content,
            "importance": importance,
            "timestamp": timestamp,
            "topic": topic,
            "message": f"记忆已保存 (ID: {memory_id})",
        }

    except Exception as e:
        return {"error": f"保存记忆失败: {str(e)}"}


def get_session_messages(session_id: str, limit: int = 50) -> Dict[str, Any]:
    """获取会话消息"""
    cm = get_context_manager()
    if not cm:
        return {"error": "上下文管理器不可用"}

    try:
        messages = cm.get_messages(session_id, limit=limit)
        return {
            "status": "success",
            "session_id": session_id,
            "count": len(messages),
            "messages": messages,
        }
    except Exception as e:
        return {"error": f"获取会话消息失败: {str(e)}"}


def clear_summary_context(session_id: str) -> Dict[str, Any]:
    """清空摘要助手上下文"""
    cm = get_context_manager()
    if not cm:
        return {"error": "上下文管理器不可用"}

    try:
        cm.clear_session_messages(session_id)
        return {"status": "success", "session_id": session_id, "message": "上下文已清空"}
    except Exception as e:
        return {"error": f"清空上下文失败: {str(e)}"}


async def trigger_topic_summary(
    session_id: str, topic: str = None, end_signal: str = None
) -> Dict[str, Any]:
    """触发当前话题的摘要生成

    流程：
    1. 提取当前话题的所有上下文消息（从最后一个话题摘要之后）
    2. 调用摘要模型生成摘要（摘要模型自主决定内容）
    3. 将当前话题上下文替换为摘要
    4. 保存摘要为长期记忆

    Args:
        session_id: 会话ID
        topic: 话题名称/主题（可选）
        end_signal: 结束信号（可选）

    Returns:
        执行结果
    """
    cm = get_context_manager()
    if not cm:
        return {"error": "上下文管理器不可用"}

    if not _MEMORY_MANAGER:
        return {"error": "记忆管理器未初始化"}

    try:
        messages = cm.get_messages(session_id, limit=1000)

        if not messages:
            return {"error": "没有可摘要的消息"}

        topic_start_idx = 0
        for i, msg in enumerate(messages):
            content = msg.get("content", "")
            content_type = msg.get("content_type", "")
            if content.startswith("[话题摘要]") or content_type == "topic_summary":
                topic_start_idx = i + 1

        if topic_start_idx >= len(messages):
            return {"error": "当前话题没有新消息可摘要"}

        current_topic_messages = messages[topic_start_idx:]

        context_text = "\n".join(
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in current_topic_messages
        )

        summary_prompt = f"""请对以下对话内容进行摘要。

对话内容：
{context_text}

请生成一段简洁的摘要，准确表达本次对话的核心内容。

注意：
- 摘要应包含对话的主要议题、关键决策和重要信息
- 如果有未完成的事项或待办任务，请明确标注
- 格式和长度由你自主决定，以清晰准确为原则"""

        summary_client = get_summary_client()
        if not summary_client:
            return {"error": "摘要模型不可用"}

        response = await summary_client.chat(
            messages=[{"role": "user", "content": summary_prompt}], stream=False
        )

        summary = ""
        if hasattr(response, "content") and response.content:
            summary = response.content.strip()
        elif isinstance(response, dict) and response.get("content"):
            summary = response.get("content").strip()
        else:
            summary = str(response)

        for i in range(len(messages) - 1, topic_start_idx - 1, -1):
            cm.delete_message(messages[i]["id"])

        summary_marker = f"[话题摘要] {summary}"
        cm.add_message(
            session_id=session_id,
            role="topic_summary",
            content=summary_marker,
            content_type="topic_summary",
        )

        max_history = _TOPIC_SUMMARY_CONFIG.get("max_history_topics")
        if max_history is not None:
            all_messages = cm.get_messages(session_id, limit=1000)
            topic_summaries = [
                msg for msg in all_messages
                if msg.get("content_type") == "topic_summary" or
                   (msg.get("content", "").startswith("[话题摘要]"))
            ]
            if len(topic_summaries) > max_history:
                summaries_to_delete = topic_summaries[:-max_history]
                for msg in summaries_to_delete:
                    cm.delete_message(msg["id"])
                logger.info(f"已清理 {len(summaries_to_delete)} 条历史话题摘要")

        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        importance = 7

        tags = ["topic_summary", "conversation_summary"]
        if topic:
            tags.append(f"topic:{topic}")

        memory_id = await _MEMORY_MANAGER.write_memory_async(
            content=summary,
            memory_type="conversation_summary",
            importance=importance / 10.0,
            tags=tags,
            metadata={
                "session_id": session_id,
                "topic": topic or "未知话题",
                "end_signal": end_signal,
                "summarized_at": datetime.now().isoformat(),
                "message_count": len(current_topic_messages),
            },
        )

        logger.info(
            f"话题摘要已生成并保存: session_id={session_id}, memory_id={memory_id}"
        )

        return {
            "status": "success",
            "summary": summary,
            "memory_id": memory_id,
            "message": "话题摘要已生成并保存",
            "topic": topic or "未知话题",
            "summarized_messages": len(current_topic_messages),
        }

    except Exception as e:
        logger.error(f"触发话题摘要失败: {e}")
        return {"error": f"触发话题摘要失败: {str(e)}"}
