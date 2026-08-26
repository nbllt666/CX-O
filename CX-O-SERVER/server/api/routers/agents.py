"""Agent 配置端点——Agent 的增删改查与配置管理接口。"""
import json
import os
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.core.cache import agent_config_cache
from server.core.logging_config import get_contextual_logger
from server.core.utils import run_io

router = APIRouter()
logger = get_contextual_logger(__name__)

# Agent 配置文件路径
AGENTS_CONFIG_PATH = "data/agents.json"

# --------------------------------------------------------------------------- #
# system_prompt 单源常量
# 默认助手 / 记忆管理助手 的 system_prompt 在此单源定义，seed 与 secondary_router
# 共同引用，避免多处重复导致漂移（rules-0 提示词去重收敛）。
# --------------------------------------------------------------------------- #
DEFAULT_AGENT_SYSTEM_PROMPT = """你是默认助手，一位热情、可靠、随和的AI伙伴。请始终用中文、以自然亲切的口吻回答用户的问题，语气贴近日常交流，避免生硬。

你可以使用以下工具帮助用户：

### 基础工具
1. calculator - 数学计算工具，支持基本运算、三角函数、对数等
2. datetime - 获取当前日期和时间
3. random - 生成随机数
4. json_format - 格式化JSON字符串

### 记忆与上下文工具
5. write_long_term_memory - 写入长期记忆，保存用户的重要信息、偏好、事件等
6. search_all_memories - 搜索所有记忆，检索与当前话题相关的历史信息
7. call_assistant - 调用记忆管理模型，获取专业处理结果
8. set_alarm - 设置定时提醒，在指定时间后提醒用户
9. mono - 保持信息在上下文中，跨多轮对话记住重要信息

使用原则：
- 需要计算/时间/日期/随机数/JSON格式化时，首选对应工具，不要自己心算或编造
- 用户提到的重要偏好、事实、事件，主动调用 write_long_term_memory 保存
- 用户问及之前聊过的事情时，先 search_all_memories 检索
- 用户要求定闹钟/提醒时，调用 set_alarm
- 回答清晰直接，先给结论再给补充；不确定时坦诚说明，不编造"""

MEMORY_AGENT_SYSTEM_PROMPT = """你是记忆管理助手，专门负责帮助用户管理和维护记忆库。你可以通过自然语言理解用户的需求，并调用相应的工具来执行记忆管理操作。

你可以使用以下9个记忆管理工具：

1. update_memory_node - 更新记忆节点内容
2. search_memories - 搜索记忆（关键词搜索）
3. delete_memory - 删除记忆（软删除，7天后自动清理）
4. get_memory_stats - 获取记忆库统计信息
5. search_by_tag - 按标签搜索记忆
6. bulk_delete - 批量删除记忆
7. restore_memory - 恢复软删除的记忆
8. get_chat_history - 获取指定会话的聊天历史
9. get_available_commands - 获取所有可用命令列表

工具选用建议：用户想找某条记忆时先用 search_memories 或 search_by_tag；想删除/清理时用 delete_memory 或 bulk_delete；想恢复误删时用 restore_memory；想了解记忆库概况时用 get_memory_stats 或 get_available_commands。执行操作前先确认用户意图；删除类操作需先与用户确认再执行。用中文回答用户的问题。"""


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
    # per-agent 参考音频绑定（A1.1 请求接受与响应透传；真源在 ref_audio_store，不持久化到 agents.json）
    ref_audio_asset_id: Optional[str] = None
    tts_voice: Optional[str] = None


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
    # per-agent 参考音频绑定（请求接受；持久化走专用绑定端点，不落盘 agents.json）
    ref_audio_asset_id: Optional[str] = None
    tts_voice: Optional[str] = None


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
    # per-agent 参考音频绑定（请求接受；持久化走专用绑定端点，不落盘 agents.json）
    ref_audio_asset_id: Optional[str] = None
    tts_voice: Optional[str] = None


def _ensure_data_dir():
    """确保数据目录存在"""
    os.makedirs(os.path.dirname(AGENTS_CONFIG_PATH), exist_ok=True)


def _seed_agents() -> List[dict]:
    """生成并持久化默认 Agent 种子（缺文件 / 置空 / 解析失败时兜底）。

    #15（CX-O问题汇总报告）: 旧实现仅在文件缺失时注入种子，文件存在但内容
    为空/非列表时静默返回空列表 → 系统无任何默认 Agent 可用。
    """
    now = datetime.now().isoformat()

    default_agent = {
        "id": "default",
        "name": "默认助手",
        "description": "通用AI助手，支持数学计算、记忆管理、提醒设置等多种工具（128k上下文）",
        "system_prompt": DEFAULT_AGENT_SYSTEM_PROMPT,
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
        "system_prompt": MEMORY_AGENT_SYSTEM_PROMPT,
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


def _load_agents() -> List[dict]:
    """加载所有 Agent 配置（带缓存）"""
    cached = agent_config_cache.get("all_agents")
    if cached is not None:
        return cached
    
    _ensure_data_dir()
    if not os.path.exists(AGENTS_CONFIG_PATH):
        return _seed_agents()

    try:
        with open(AGENTS_CONFIG_PATH, "r", encoding="utf-8") as f:
            parsed = json.load(f)
        # #15: 文件存在但内容为空/非列表 → 种子兜底（曾静默返回空，系统无默认 Agent）
        if isinstance(parsed, list) and parsed:
            agent_config_cache.set("all_agents", parsed)
            return parsed
        logger.warning("Agent 配置为空或格式异常，注入种子兜底")
        return _seed_agents()
    except Exception:
        return _seed_agents()


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


def _merge_ref_audio_binding(agent: dict) -> dict:
    """读透传：把 ref_audio_store 中该 Agent 的参考音频绑定合并进 agent 对象展示。

    从不写入 data/agents.json（持久化走专用绑定端点）。返回浅拷贝，不污染原始配置。
    """
    from server import ref_audio_store

    out = dict(agent)
    binding = {}
    agent_id = agent.get("id")
    if agent_id:
        b = ref_audio_store.get_for_agent(agent_id) or {}
        binding = {
            "ref_audio_asset_id": b.get("asset_id"),
            "tts_voice": b.get("tts_voice"),
        }
    out.update(binding)
    return out


class SetAgentRefAudioRequest(BaseModel):
    """设置 Agent 参考音频绑定请求（A2）。"""

    asset_id: str = Field(..., min_length=1)
    tts_voice: Optional[str] = None


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
        agents = [_merge_ref_audio_binding(a) for a in agents]
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


@router.get(
    "/agents/default",
    summary="获取默认 Agent",
    description="获取系统中标记为 is_default 的 Agent 配置。",
)
async def get_default_agent():
    """获取默认 Agent 配置。

    迁移自 CXHMS: backend/api/routers/agents.py:L280-L311

    对齐 public/interface_stub/agent_service.pyi 的 get_default_agent() 契约。
    优先返回 is_default=True 的 Agent；若无则回退到 id="default"；
    均无则抛 404。

    Returns:
        dict: 包含 status 和 default agent 配置
    """
    try:
        agents = _load_agents()
        # 优先 is_default=True
        default_agent = next((a for a in agents if a.get("is_default", False)), None)
        # 回退到 id="default"
        if default_agent is None:
            default_agent = next((a for a in agents if a.get("id") == "default"), None)

        if not default_agent:
            raise HTTPException(status_code=404, detail="未配置默认 Agent")

        return {"status": "success", "agent": default_agent}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取默认Agent失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    """获取单个 Agent"""
    try:
        agents = _load_agents()
        agent = next((a for a in agents if a["id"] == agent_id), None)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        return {"status": "success", "agent": _merge_ref_audio_binding(agent)}
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
        update_data = request.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            # per-agent 参考音频绑定不落盘 agents.json（走专用绑定端点）
            if key in ("ref_audio_asset_id", "tts_voice"):
                continue
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


def _cleanup_agent_graph_db(agent_id: str) -> None:
    """清理指定助手的图数据库实例及 db 文件。

    迁移自 CXHMS: backend/api/routers/agents.py:L365-L382
    """
    # 从注册表移除并关闭实例（内部会调用 server.core.graph.database.remove_database）
    try:
        from server.dependencies import remove_graph_database
        remove_graph_database(agent_id)
    except Exception as e:
        logger.warning(f"清理图数据库实例失败 (agent_id={agent_id}): {e}")

    # 删除 per-agent db 文件
    try:
        from server.core.graph.config import get_graph_config
        db_path = get_graph_config(agent_id=agent_id).database_path
        if db_path and os.path.exists(db_path):
            os.remove(db_path)
            logger.info(f"已删除图数据库文件: {db_path}")
    except Exception as e:
        logger.warning(f"删除图数据库文件失败 (agent_id={agent_id}): {e}")


def _cleanup_agent_weaviate_collection(agent_id: str) -> None:
    """清理指定助手的 Weaviate per-agent collection。

    迁移自 CXHMS: backend/api/routers/agents.py:L385-L416

    通过 memory_manager._vector_store 获取 WeaviateVectorStore 实例，
    调用 delete_agent_collection(agent_id) 删除 per-agent collection。
    若向量存储未启用或不是 WeaviateVectorStore，则跳过（幂等）。
    """
    try:
        from server.dependencies import _resolve_state

        state = _resolve_state()
        memory_manager = state.memory_manager
        if memory_manager is None:
            logger.debug(f"memory_manager 未就绪，跳过 Weaviate collection 清理 (agent_id={agent_id})")
            return

        vector_store = getattr(memory_manager, "_vector_store", None)
        if vector_store is None:
            logger.debug(f"向量存储未启用，跳过 Weaviate collection 清理 (agent_id={agent_id})")
            return

        # 仅 WeaviateVectorStore 支持 per-agent collection
        delete_fn = getattr(vector_store, "delete_agent_collection", None)
        if delete_fn is None:
            logger.debug(
                f"向量存储 {type(vector_store).__name__} 不支持 per-agent collection，跳过清理 (agent_id={agent_id})"
            )
            return

        delete_fn(agent_id)
    except Exception as e:
        logger.warning(f"清理 Weaviate per-agent collection 失败 (agent_id={agent_id}): {e}")


def _cleanup_agent_memory_tables(agent_id: str) -> None:
    """清理指定助手的 per-agent 记忆表及映射记录。

    迁移自 CXHMS: backend/api/routers/agents.py:L419-L485

    - DROP TABLE memories_{safe_agent_id}（如果存在）
    - DELETE FROM agent_memory_tables WHERE agent_id = ?
    - DELETE FROM rejected_content WHERE session_id LIKE 'agent-{agent_id}%'
    """
    try:
        from server.dependencies import _resolve_state

        state = _resolve_state()
        memory_manager = state.memory_manager
        if memory_manager is None:
            logger.debug(f"memory_manager 未就绪，跳过记忆表清理 (agent_id={agent_id})")
            return

        # 复用 MemoryManager 的表名生成逻辑，确保命名一致
        table_name = memory_manager._get_table_name(agent_id)
        if table_name == "memories":
            # default agent 不清理主表
            logger.debug(f"默认 agent 不清理主表 (agent_id={agent_id})")
            return

        conn = memory_manager._get_connection()
        try:
            cursor = conn.cursor()

            # 1. 检查表是否存在，存在则 DROP
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            if cursor.fetchone():
                cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
                logger.info(f"已删除 agent 记忆表: {table_name} (agent_id={agent_id})")
            else:
                logger.debug(f"agent 记忆表不存在，跳过 DROP (agent_id={agent_id}, table={table_name})")

            # 2. 删除 agent_memory_tables 中的映射记录
            cursor.execute(
                "DELETE FROM agent_memory_tables WHERE agent_id = ?",
                (agent_id,),
            )
            deleted_rows = cursor.rowcount
            if deleted_rows > 0:
                logger.info(
                    f"已删除 agent_memory_tables 映射记录: {deleted_rows} 条 (agent_id={agent_id})"
                )

            # 3. 删除 rejected_content 中该 agent 的记录（通过 session_id 前缀匹配）
            cursor.execute(
                "DELETE FROM rejected_content WHERE session_id LIKE ?",
                (f"{agent_id}%",),
            )
            rejected_deleted = cursor.rowcount
            if rejected_deleted > 0:
                logger.info(
                    f"已删除 rejected_content 记录: {rejected_deleted} 条 (agent_id={agent_id})"
                )

            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"清理 agent 记忆表失败 (agent_id={agent_id}): {e}")


def _cleanup_agent_resources(agent_id: str) -> None:
    """清理指定助手的全部 per-agent 资源（图数据库 + Weaviate collection + 记忆表）。

    迁移自 CXHMS: backend/api/routers/agents.py:L488-L492
    """
    _cleanup_agent_graph_db(agent_id)
    _cleanup_agent_weaviate_collection(agent_id)
    _cleanup_agent_memory_tables(agent_id)


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """删除 Agent"""
    try:
        agents = _load_agents()
        agent = next((a for a in agents if a["id"] == agent_id), None)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        if agent.get("is_default", False) or agent_id == "default":
            # #17（CX-O问题汇总报告）: is_default 标记可自由转移，仅凭标记
            # 保护会被绕过——先转移标记再删旧默认。id="default" 是共享资源
            # 锚点（记忆/图/会话兜底），无条件禁删。
            raise HTTPException(status_code=400, detail="不能删除默认 Agent 或系统锚点 Agent")

        agents = [a for a in agents if a["id"] != agent_id]
        _save_agents(agents)

        # 清理该助手的全部 per-agent 资源（图数据库 + Weaviate collection + 记忆表）
        await run_io(_cleanup_agent_resources, agent_id)

        return {"status": "success", "message": f"Agent '{agent_id}' 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除Agent失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/agents/{agent_id}/default")
async def set_default_agent(agent_id: str):
    """将指定 Agent 设为默认 Agent（全局唯一：同事务清除其他 Agent 的 is_default）。

    目标 Agent 不存在返回 404；不删除任何数据，仅转移 is_default 标记。
    保留 id="default" Agent 作为共享资源锚点（记忆/图/会话兜底），其 is_default
    标记可被转移，但该 Agent 实体仍存在。
    """
    try:
        agents = _load_agents()
        target = next((a for a in agents if a["id"] == agent_id), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        for agent in agents:
            agent["is_default"] = agent["id"] == agent_id
            agent["updated_at"] = datetime.now().isoformat()
        _save_agents(agents)

        return {"status": "success", "agent": target, "message": f"已设为默认 Agent：{target.get('name', agent_id)}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置默认Agent失败: {e}", exc_info=True)
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
    from server.dependencies import get_context_manager

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
    from server.core.context.agent_context_manager import get_agent_context_manager

    try:
        agents = _load_agents()
        agent = next((a for a in agents if a["id"] == agent_id), None)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        context_mgr = get_agent_context_manager()
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
    from server.core.context.agent_context_manager import get_agent_context_manager

    try:
        agents = _load_agents()
        agent = next((a for a in agents if a["id"] == agent_id), None)

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")

        context_mgr = get_agent_context_manager()
        context_mgr.clear_context(agent_id)

        return {"status": "success", "message": f"Agent '{agent_id}' 的上下文已清空"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清空Agent上下文失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清空Agent上下文失败: {str(e)}")


# --------------------------------------------------------------------------- #
# A2. per-agent 参考音频绑定端点（运行真源在 ref_audio_store，不落盘 agents.json）
# --------------------------------------------------------------------------- #

def _get_agent_or_404(agent_id: str) -> dict:
    """按 agent_id 取 Agent 配置，不存在抛 404。"""
    agents = _load_agents()
    agent = next((a for a in agents if a["id"] == agent_id), None)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")
    return agent


def _ref_binding_body(agent_id: str) -> dict:
    """组装绑定返回体 {status, agent_id, asset_id, tts_voice}。"""
    from server import ref_audio_store

    b = ref_audio_store.get_for_agent(agent_id) or {}
    return {
        "status": "success",
        "agent_id": agent_id,
        "asset_id": b.get("asset_id"),
        "tts_voice": b.get("tts_voice"),
    }


@router.get("/agents/{agent_id}/ref-audio", summary="查询 Agent 参考音频绑定")
async def get_agent_ref_audio(agent_id: str):
    """返回 Agent 绑定的参考音频 {asset_id, tts_voice}。"""
    try:
        _get_agent_or_404(agent_id)
        return _ref_binding_body(agent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询Agent参考音频绑定失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.put("/agents/{agent_id}/ref-audio", summary="设置 Agent 参考音频绑定")
async def set_agent_ref_audio(agent_id: str, request: SetAgentRefAudioRequest):
    """为 Agent 绑定参考音频资产。

    - asset 必须存在（不存在/已删除返回 404 + 错误提示）。
    - 成功返回更新后的绑定。
    """
    from server import ref_audio_store
    from server.qwen3_tts_provider import RefAudioNotFoundError

    try:
        _get_agent_or_404(agent_id)
        b = ref_audio_store.set_for_agent(
            agent_id, request.asset_id, tts_voice=request.tts_voice
        )
        return {
            "status": "success",
            "agent_id": agent_id,
            "asset_id": b.get("asset_id"),
            "tts_voice": b.get("tts_voice"),
        }
    except RefAudioNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"设置Agent参考音频绑定失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete("/agents/{agent_id}/ref-audio", summary="清除 Agent 参考音频绑定")
async def clear_agent_ref_audio(agent_id: str):
    """清除 Agent 的参考音频绑定（不删除资产本身）。"""
    from server import ref_audio_store

    try:
        _get_agent_or_404(agent_id)
        ref_audio_store.clear_for_agent(agent_id)
        return {
            "status": "success",
            "agent_id": agent_id,
            "asset_id": None,
            "tts_voice": None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清除Agent参考音频绑定失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")
