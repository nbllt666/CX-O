import json
import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.cache import agent_config_cache
from backend.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)

# Agent 配置文件路径
AGENTS_CONFIG_PATH = "data/agents.json"


class AgentConfig(BaseModel):
    """Agent 配置模型"""

    id: str
    name: str
    description: str = ""
    system_prompt: str = "你是一个有帮助的AI助手。"
    model: str = "main"  # main/summary/memory 或具体模型名
    temperature: float = 0.7
    max_tokens: int = 0  # 0 表示不限制
    use_memory: bool = True
    use_tools: bool = True
    memory_scene: str = "chat"  # chat/task/first_interaction
    decay_model: str = "exponential"  # exponential/ebbinghaus
    vision_enabled: bool = False
    is_default: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentCreateRequest(BaseModel):
    """创建 Agent 请求"""

    name: str
    description: str = ""
    system_prompt: str = "你是一个有帮助的AI助手。"
    model: str = "main"
    temperature: float = 0.7
    max_tokens: int = 0  # 0 表示不限制
    use_memory: bool = True
    use_tools: bool = True
    memory_scene: str = "chat"
    decay_model: str = "exponential"
    vision_enabled: bool = False


class AgentUpdateRequest(BaseModel):
    """更新 Agent 请求"""

    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    use_memory: Optional[bool] = None
    use_tools: Optional[bool] = None
    memory_scene: Optional[str] = None
    decay_model: Optional[str] = None
    vision_enabled: Optional[bool] = None


def _ensure_data_dir():
    """确保数据目录存在"""
    os.makedirs(os.path.dirname(AGENTS_CONFIG_PATH), exist_ok=True)


def _load_agents() -> List[dict]:
    """加载所有 Agent 配置（带缓存）"""
    cached = agent_config_cache.get("all_agents")
    if cached is not None:
        return cached
    
    _ensure_data_dir()
    if not os.path.exists(AGENTS_CONFIG_PATH):
        now = datetime.now().isoformat()

        default_agent = {
            "id": "default",
            "name": "默认助手",
            "description": "通用AI助手，支持数学计算、记忆管理、提醒设置等多种工具（128k上下文）",
            "system_prompt": "你是一个有帮助的AI助手。请用中文回答用户的问题。\n\n你可以使用以下工具来帮助用户：\n\n### 基础工具\n1. calculator - 数学计算工具，支持基本运算、三角函数、对数等\n2. datetime - 获取当前日期和时间\n3. random - 生成随机数\n4. json_format - 格式化JSON字符串\n\n### 记忆与上下文工具\n5. write_long_term_memory - 写入长期记忆，保存用户的重要信息、偏好、事件等\n6. search_all_memories - 搜索所有记忆，检索与当前话题相关的历史信息\n7. call_assistant - 调用记忆管理模型，获取专业处理结果\n8. set_alarm - 设置定时提醒，在指定时间后提醒用户\n9. mono - 保持信息在上下文中，跨多轮对话记住重要信息\n\n当用户需要进行计算、获取时间、生成随机数、处理JSON、保存记忆、搜索记忆或设置提醒时，请主动使用这些工具。",
            "model": "main",
            "temperature": 0.7,
            "max_tokens": 131072,
            "use_memory": True,
            "use_tools": True,
            "memory_scene": "chat",
            "decay_model": "exponential",
            "vision_enabled": False,
            "is_default": True,
            "created_at": now,
            "updated_at": now,
        }

        memory_agent = {
            "id": "memory-agent",
            "name": "记忆管理助手",
            "description": "专业的记忆管理助手，可以通过自然语言管理记忆库（128k上下文）",
            "system_prompt": "你是记忆管理助手，专门负责帮助用户管理和维护记忆库。你可以通过自然语言理解用户的需求，并调用相应的工具来执行记忆管理操作。\n\n你可以使用以下16个记忆管理工具：\n\n1. update_memory_node - 更新记忆节点内容\n2. search_memories - 搜索记忆（关键词搜索）\n3. delete_memory - 删除记忆（软删除，7天后自动清理）\n4. merge_memories - 合并多个相似记忆\n5. clean_expired - 清理已软删除超过7天的记忆\n6. export_memories - 导出记忆数据（JSON/CSV格式）\n7. get_memory_stats - 获取记忆库统计信息\n8. search_by_time - 按时间范围搜索记忆\n9. search_by_tag - 按标签搜索记忆\n10. bulk_delete - 批量删除记忆\n11. restore_memory - 恢复软删除的记忆\n12. search_similar_memories - 搜索与指定记忆相似的其他记忆\n13. get_chat_history - 获取指定会话的聊天历史\n14. get_similar_memories - 获取与给定内容相似的记忆\n15. get_memory_logs - 获取记忆管理操作日志\n16. get_available_commands - 获取所有可用命令列表\n\n当用户需要管理记忆时，请主动使用这些工具。用中文回答用户的问题。",
            "model": "memory",
            "temperature": 0.3,
            "max_tokens": 131072,
            "use_memory": False,
            "use_tools": True,
            "memory_scene": "task",
            "decay_model": "exponential",
            "vision_enabled": False,
            "is_default": False,
            "created_at": now,
            "updated_at": now,
        }

        _save_agents([default_agent, memory_agent])
        agent_config_cache.set("all_agents", [default_agent, memory_agent])
        return [default_agent, memory_agent]

    try:
        with open(AGENTS_CONFIG_PATH, "r", encoding="utf-8") as f:
            agents = json.load(f)
            agent_config_cache.set("all_agents", agents)
            return agents
    except Exception:
        return []


def _save_agents(agents: List[dict]):
    """保存所有 Agent 配置"""
    _ensure_data_dir()
    with open(AGENTS_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(agents, f, ensure_ascii=False, indent=2)
    agent_config_cache.delete("all_agents")


def _generate_agent_id() -> str:
    """生成 Agent ID"""
    import uuid

    return f"agent-{uuid.uuid4().hex[:8]}"


@router.get(
    "/agents",
    summary="获取所有 Agent",
    description="获取系统中所有 Agent 的配置列表，包括默认 Agent 和自定义 Agent。",
    response_description="返回 Agent 列表和总数",
)
async def get_agents():
    """获取所有 Agent
    
    Returns:
        dict: 包含 status, agents 列表和 total 总数
    """
    try:
        agents = _load_agents()
        return {"status": "success", "agents": agents, "total": len(agents)}
    except Exception as e:
        logger.error(f"获取Agent列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post(
    "/agents",
    summary="创建新 Agent",
    description="创建一个新的自定义 Agent，可以配置模型、系统提示、记忆和工具使用等参数。",
    response_description="返回创建的 Agent 配置",
)
async def create_agent(request: AgentCreateRequest):
    """创建新 Agent
    
    Args:
        request: Agent 创建请求，包含名称、描述、系统提示等配置
        
    Returns:
        dict: 包含 status 和新创建的 agent 配置
    """
    try:
        agents = _load_agents()

        # 检查名称是否重复
        if any(a["name"] == request.name for a in agents):
            raise HTTPException(status_code=400, detail=f"Agent 名称 '{request.name}' 已存在")

        now = datetime.now().isoformat()

        # 处理空模型字符串 - 空字符串表示使用默认模型
        model = request.model if request.model and request.model.strip() else "main"

        new_agent = {
            "id": _generate_agent_id(),
            "name": request.name,
            "description": request.description,
            "system_prompt": request.system_prompt,
            "model": model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "use_memory": request.use_memory,
            "use_tools": request.use_tools,
            "memory_scene": request.memory_scene,
            "decay_model": request.decay_model,
            "is_default": False,
            "created_at": now,
            "updated_at": now,
        }

        agents.append(new_agent)
        _save_agents(agents)

        return {"status": "success", "agent": new_agent, "message": "Agent 创建成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建Agent失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    """获取单个 Agent"""
    try:
        agents = _load_agents()
        agent = next((a for a in agents if a["id"] == agent_id), None)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        return {"status": "success", "agent": agent}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取Agent失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, request: AgentUpdateRequest):
    """更新 Agent"""
    try:
        agents = _load_agents()
        agent_index = next((i for i, a in enumerate(agents) if a["id"] == agent_id), None)

        if agent_index is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        agent = agents[agent_index]

        # 更新字段
        update_data = request.dict(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                # 处理空模型字符串 - 空字符串表示使用默认模型
                if key == "model" and value and isinstance(value, str) and not value.strip():
                    value = "main"
                agent[key] = value

        agent["updated_at"] = datetime.now().isoformat()
        _save_agents(agents)

        return {"status": "success", "agent": agent, "message": "Agent 更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新Agent失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """删除 Agent"""
    try:
        agents = _load_agents()
        agent = next((a for a in agents if a["id"] == agent_id), None)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        if agent.get("is_default", False):
            raise HTTPException(status_code=400, detail="不能删除默认 Agent")

        agents = [a for a in agents if a["id"] != agent_id]
        _save_agents(agents)

        return {"status": "success", "message": f"Agent '{agent_id}' 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除Agent失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/agents/{agent_id}/clone")
async def clone_agent(agent_id: str):
    """克隆 Agent"""
    try:
        agents = _load_agents()
        source_agent = next((a for a in agents if a["id"] == agent_id), None)

        if not source_agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        now = datetime.now().isoformat()
        new_agent = {
            **source_agent,
            "id": _generate_agent_id(),
            "name": f"{source_agent['name']} (副本)",
            "is_default": False,
            "created_at": now,
            "updated_at": now,
        }

        agents.append(new_agent)
        _save_agents(agents)

        return {"status": "success", "agent": new_agent, "message": "Agent 克隆成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"克隆Agent失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/agents/{agent_id}/stats")
async def get_agent_stats(agent_id: str):
    """获取 Agent 统计信息"""
    from backend.api.app import get_context_manager

    try:
        agents = _load_agents()
        agent = next((a for a in agents if a["id"] == agent_id), None)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        context_mgr = get_context_manager()
        # 获取使用该 Agent 的会话数量
        sessions = context_mgr.list_sessions()
        agent_sessions = [s for s in sessions if s.get("agent_id") == agent_id]

        return {
            "status": "success",
            "agent_id": agent_id,
            "session_count": len(agent_sessions),
            "total_messages": sum(s.get("message_count", 0) for s in agent_sessions),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取Agent统计失败: {e}", exc_info=True)
        return {
            "status": "success",
            "agent_id": agent_id,
            "session_count": 0,
            "total_messages": 0,
            "error": str(e),
        }


@router.get("/agents/{agent_id}/context")
async def get_agent_context(agent_id: str, limit: int = 20):
    """获取Agent上下文

    Args:
        agent_id: Agent唯一标识
        limit: 返回的最大消息数量
    """
    from backend.core.context.agent_context_manager import AgentContextManager

    try:
        agents = _load_agents()
        agent = next((a for a in agents if a["id"] == agent_id), None)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        context_mgr = AgentContextManager()
        summary = context_mgr.get_context_summary(agent_id)
        messages = context_mgr.get_message_history(agent_id, limit=limit)

        return {
            "status": "success",
            "agent_id": agent_id,
            "has_context": summary.get("has_context", False),
            "session_id": summary.get("session_id"),
            "last_active": summary.get("last_active"),
            "created_at": summary.get("created_at"),
            "updated_at": summary.get("updated_at"),
            "total_messages": summary.get("total_messages", 0),
            "role_counts": summary.get("role_counts", {}),
            "recent_messages": messages,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取Agent上下文失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取Agent上下文失败: {str(e)}")


@router.delete("/agents/{agent_id}/context")
async def clear_agent_context(agent_id: str):
    """清空Agent上下文

    Args:
        agent_id: Agent唯一标识
    """
    from backend.core.context.agent_context_manager import AgentContextManager

    try:
        agents = _load_agents()
        agent = next((a for a in agents if a["id"] == agent_id), None)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        context_mgr = AgentContextManager()
        context_mgr.clear_context(agent_id)

        return {"status": "success", "message": f"Agent '{agent_id}' 的上下文已清空"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清空Agent上下文失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清空Agent上下文失败: {str(e)}")
