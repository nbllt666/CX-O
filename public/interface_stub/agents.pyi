"""Agents router 接口契约存根（种子阶段，待 s0201 补全）。

源真理: c:/CX-O/CX-O-SERVER/server/api/routers/agents.py
完成 Skill: s0201
当前状态: 种子——仅含代表性端点签名
"""

from pydantic import BaseModel


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


async def agent_context(agent_id: str) -> dict:
    """GET /api/agents/{agent_id}/context — Agent 上下文。"""
    ...

# TODO s0201: 补全 agents.py 全部端点签名 + 异常说明
