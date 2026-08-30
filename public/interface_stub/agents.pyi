"""Agents router 接口契约存根（种子阶段，待 s0201 补全）。

源真理: c:/CX-O/CX-O-SERVER/server/api/routers/agents.py
完成 Skill: s0201
当前状态: 种子——含代表性端点签名；G2 契约修订补齐 default/context/ref-audio 端点
契约版本: 1.1.0（MINOR：补齐 GET/POST default、DELETE context、GET/PUT/DELETE ref-audio
端点及 SetAgentRefAudioRequest 模型；get_agent_context 补 limit 参数）
"""

from typing import Optional

from pydantic import BaseModel, Field


class AgentCreateRequest(BaseModel):
    """Agent 创建请求体（种子，待 s0201 补全全部字段）。"""
    name: str
    description: str
    system_prompt: str
    model: str
    temperature: float = 0.7
    # TODO s0201: 补全全部字段（max_tokens/use_memory/use_tools/memory_scene/decay_model/vision_enabled/is_default）


class AgentUpdateRequest(BaseModel):
    """Agent 更新请求体（种子，待 s0201 补全）。"""
    # TODO s0201: 补全全部可选更新字段


class SetAgentRefAudioRequest(BaseModel):
    """设置 Agent 参考音频绑定请求（A2，对齐 agents.py:213）。"""
    asset_id: str = Field(..., min_length=1)
    tts_voice: Optional[str] = None


async def list_agents() -> list[dict]:
    """GET /api/agents — 列出所有 Agent。"""
    ...


async def create_agent(request: AgentCreateRequest) -> dict:
    """POST /api/agents — 创建 Agent。

    Raises:
        HTTPException: 400 参数错误 / 409 名称冲突
    """
    ...


async def get_agent(agent_id: str) -> dict:
    """GET /api/agents/{agent_id} — 获取 Agent 详情。

    Raises:
        HTTPException: 404 agent 不存在
    """
    ...


async def update_agent(agent_id: str, request: AgentUpdateRequest) -> dict:
    """PUT /api/agents/{agent_id} — 更新 Agent。

    Raises:
        HTTPException: 404 agent 不存在 / 400 参数错误
    """
    ...


async def delete_agent(agent_id: str) -> dict:
    """DELETE /api/agents/{agent_id} — 删除 Agent。

    Raises:
        HTTPException: 404 agent 不存在
    """
    ...


async def clone_agent(agent_id: str) -> dict:
    """POST /api/agents/{agent_id}/clone — 克隆 Agent。"""
    ...


async def agent_stats(agent_id: str) -> dict:
    """GET /api/agents/{agent_id}/stats — Agent 统计。"""
    ...


async def agent_context(agent_id: str, limit: int = 20) -> dict:
    """GET /api/agents/{agent_id}/context — Agent 上下文。

    Args:
        agent_id: Agent 唯一标识
        limit: 返回的最大消息数量（默认 20，对齐 agents.py:675）

    Raises:
        HTTPException: 404 agent 不存在 / 500 获取失败
    """
    ...


async def get_default_agent() -> dict:
    """GET /api/agents/default — 获取默认 Agent（对齐 agents.py:296-300）。

    优先返回 is_default=True 的 Agent；若无回退 id="default"；均无抛 404。

    Returns:
        {"status": "success", "agent": dict}

    Raises:
        HTTPException: 404 未配置默认 Agent / 500 内部错误
    """
    ...


async def set_default_agent(agent_id: str) -> dict:
    """POST /api/agents/{agent_id}/default — 设为默认 Agent（对齐 agents.py:560-561）。

    全局唯一：同事务清除其他 Agent 的 is_default；不删除数据，仅转移标记。

    Returns:
        {"status": "success", "agent": dict, "message": str}

    Raises:
        HTTPException: 404 agent 不存在 / 500 内部错误
    """
    ...


async def clear_agent_context(agent_id: str) -> dict:
    """DELETE /api/agents/{agent_id}/context — 清空 Agent 上下文（对齐 agents.py:714-715）。

    Returns:
        {"status": "success", "message": str}

    Raises:
        HTTPException: 404 agent 不存在 / 500 清空失败
    """
    ...


async def get_agent_ref_audio(agent_id: str) -> dict:
    """GET /api/agents/{agent_id}/ref-audio — 查询 Agent 参考音频绑定（对齐 agents.py:767-768）。

    Returns:
        {"status": "success", "agent_id": str, "asset_id": Optional[str], "tts_voice": Optional[str]}

    Raises:
        HTTPException: 404 agent 不存在 / 500 内部错误
    """
    ...


async def set_agent_ref_audio(agent_id: str, request: SetAgentRefAudioRequest) -> dict:
    """PUT /api/agents/{agent_id}/ref-audio — 设置 Agent 参考音频绑定（对齐 agents.py:780-781）。

    asset 必须存在；成功返回更新后的绑定。

    Raises:
        HTTPException: 404 agent 不存在或资产不存在（RefAudioNotFoundError）/ 500 内部错误
    """
    ...


async def clear_agent_ref_audio(agent_id: str) -> dict:
    """DELETE /api/agents/{agent_id}/ref-audio — 清除 Agent 参考音频绑定（对齐 agents.py:810-811）。

    不删除资产本身。

    Returns:
        {"status": "success", "agent_id": str, "asset_id": None, "tts_voice": None}

    Raises:
        HTTPException: 404 agent 不存在 / 500 内部错误
    """
    ...

# TODO s0201: 补全 agents.py 全部端点签名 + 异常说明
