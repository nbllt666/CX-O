"""Memory router 接口契约存根（种子阶段，待 s0201 补全）。

源真理: c:/CX-O/CX-O-SERVER/server/api/routers/memory.py
完成 Skill: s0201
当前状态: 种子——仅含代表性端点签名

@version 1.1.0
@changelog v1.1.0 按实现对齐 5 处签名漂移（对照 memory.py 实码，已获人类显式授权）：
    get_memory(memory_id: int, agent_id)、list_memories 对齐 :122-129 实参、
    search_memories 改 POST + MemorySearchRequest 请求体、
    batch_write_memories(memories, raise_on_error=False)、
    recall_memory(memory_id: int, emotion_intensity=0.0, agent_id)
"""

from typing import Dict, List, Optional

from pydantic import BaseModel


class MemoryCreateRequest(BaseModel):
    """记忆创建请求体（种子，待 s0201 补全）。"""
    agent_id: str
    content: str
    # TODO s0201: 补全全部字段（importance/tags/scene 等）


class MemorySearchRequest(BaseModel):
    """搜索记忆请求体（POST /api/memories/search，对齐实码 memory.py:100-113）。"""
    query: Optional[str] = None
    type: Optional[str] = None
    memory_type: Optional[str] = None
    tags: Optional[List[str]] = None
    time_range: Optional[str] = None
    limit: int = 10   # 实码 Field(ge=1, le=200)
    offset: int = 0   # 实码 Field(ge=0)
    include_deleted: bool = False
    workspace_id: str = "default"
    agent_id: str = "default"


async def list_memories(
    workspace_id: str = "default",
    type: Optional[str] = None,
    memory_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    agent_id: str = "default",
) -> dict:
    """GET /api/memories — 列出记忆（对齐实码 memory.py:130-138 实参）。

    Returns:
        {"status": "success", "memories": [...], "total": int}

    Raises:
        HTTPException: 400 MemoryOperationError / 500 内部服务器错误
    """
    ...


async def create_memory(request: MemoryCreateRequest) -> dict:
    """POST /api/memories — 创建记忆。

    Raises:
        HTTPException: 400 参数错误 / 404 agent 不存在
    """
    ...


async def get_memory(memory_id: int, agent_id: str = "default") -> dict:
    """GET /api/memories/{memory_id} — 获取记忆详情（对齐实码 memory.py:347）。

    Returns:
        {"status": "success", "memory": {...}}

    Raises:
        HTTPException: 404 memory 不存在 / 500 内部服务器错误
    """
    ...


async def update_memory(memory_id: str, request: dict) -> dict:
    """PUT /api/memories/{memory_id} — 更新记忆。"""
    ...


async def delete_memory(memory_id: str) -> dict:
    """DELETE /api/memories/{memory_id} — 删除记忆。"""
    ...


async def search_memories(request: MemorySearchRequest) -> dict:
    """POST /api/memories/search — 搜索记忆（对齐实码 memory.py:418-419）。

    请求体 MemorySearchRequest（query/type/memory_type/tags/time_range/分页/
    workspace_id/agent_id）；返回 {"status", "memories", "total"}。

    Raises:
        HTTPException: 500 内部服务器错误
    """
    ...


async def rag_search(agent_id: str, query: str) -> dict:
    """POST /api/memories/rag — RAG 检索增强生成。"""
    ...


async def batch_write_memories(memories: List[Dict], raise_on_error: bool = False) -> dict:
    """POST /api/memories/batch/write — 批量写入记忆（对齐实码 memory.py:637-638）。

    Args:
        memories: 记忆字典列表
        raise_on_error: 单条失败是否中断抛错（默认 False，失败计入结果统计）

    Returns:
        {"status": "success", "result": {...写入统计...}}

    Raises:
        HTTPException: 500 内部服务器错误
    """
    ...


async def recall_memory(memory_id: int, emotion_intensity: float = 0.0, agent_id: str = "default") -> dict:
    """POST /api/memories/recall/{memory_id} — 召回记忆（对齐实码 memory.py:616-617）。

    Args:
        memory_id: 记忆 ID
        emotion_intensity: 情感强度参数（默认 0.0）
        agent_id: agent 隔离标识（默认 "default"）

    Returns:
        {"status": "success", "memory": {...}, "message": "记忆召回成功"}

    Raises:
        HTTPException: 404 记忆不存在 / 500 内部服务器错误
    """
    ...

# TODO s0201: 补全 memory.py 全部端点（permanent/3d/batch_update 等）+ 异常说明
