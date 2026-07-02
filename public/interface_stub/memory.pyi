"""Memory router 接口契约存根（种子阶段，待 s0201 补全）。

源真理: c:/CX-O/CX-O-SERVER/server/api/routers/memory.py
完成 Skill: s0201
当前状态: 种子——仅含代表性端点签名
"""

from pydantic import BaseModel


class MemoryCreateRequest(BaseModel):
    """记忆创建请求体（种子，待 s0201 补全）。"""
    agent_id: str
    content: str
    # TODO s0201: 补全全部字段（importance/tags/scene 等）


async def list_memories(agent_id: str, limit: int = 100) -> list[dict]:
    """GET /api/memories — 列出记忆。"""
    ...


async def create_memory(request: MemoryCreateRequest) -> dict:
    """POST /api/memories — 创建记忆。

    Raises:
        HTTPException: 400 参数错误 / 404 agent 不存在
    """
    ...


async def get_memory(memory_id: str) -> dict:
    """GET /api/memories/{memory_id} — 获取记忆详情。

    Raises:
        HTTPException: 404 memory 不存在
    """
    ...


async def update_memory(memory_id: str, request: dict) -> dict:
    """PUT /api/memories/{memory_id} — 更新记忆。"""
    ...


async def delete_memory(memory_id: str) -> dict:
    """DELETE /api/memories/{memory_id} — 删除记忆。"""
    ...


async def search_memories(agent_id: str, query: str, limit: int = 10) -> list[dict]:
    """GET /api/memories/search — 搜索记忆（向量+关键词混合搜索）。"""
    ...


async def rag_search(agent_id: str, query: str) -> dict:
    """POST /api/memories/rag — RAG 检索增强生成。"""
    ...


async def batch_write(agent_id: str, memories: list[dict]) -> dict:
    """POST /api/memories/batch/write — 批量写入记忆。"""
    ...


async def recall_memory(memory_id: str) -> dict:
    """POST /api/memories/recall/{id} — 召回记忆。"""
    ...

# TODO s0201: 补全 memory.py 全部端点（permanent/3d/batch_update 等）+ 异常说明
