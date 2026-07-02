"""Chat router 接口契约存根（种子阶段，待 s0201 补全）。

源真理: c:/CX-O/CX-O-SERVER/server/api/routers/chat.py
完成 Skill: s0201
当前状态: 种子——仅含代表性端点签名，待 s0201 补全全部端点 + 异常说明
"""

from typing import Any, AsyncIterator
from pydantic import BaseModel


class ChatRequest(BaseModel):
    """聊天请求体（种子，待 s0201 补全全部字段）。"""
    message: str
    agent_id: str
    session_id: str | None = None
    # TODO s0201: 补全全部字段（stream/use_memory/use_tools/context 等）


class ChatResponse(BaseModel):
    """聊天响应体（种子，待 s0201 补全）。"""
    response: str
    session_id: str
    # TODO s0201: 补全全部字段


async def chat(request: ChatRequest) -> ChatResponse:
    """POST /api/chat — 同步聊天。

    Raises:
        HTTPException: 400 参数错误 / 404 agent 不存在 / 500 服务内部错误
    """
    ...


async def chat_stream(request: ChatRequest) -> AsyncIterator[str]:
    """POST /api/chat/stream — SSE 流式聊天。

    Yields: SSE 格式的流式响应片段
    Raises:
        HTTPException: 400 参数错误 / 404 agent 不存在
    """
    ...


async def chat_history(session_id: str) -> list[dict[str, Any]]:
    """GET /api/chat/history/{session_id} — 获取会话历史。

    Raises:
        HTTPException: 404 session 不存在
    """
    ...


async def memory_agent_chat_stream(request: ChatRequest) -> AsyncIterator[str]:
    """POST /api/memory-agent/chat/stream — 记忆代理 SSE 流式聊天。"""
    ...

# TODO s0201: 补全 chat.py 全部端点签名 + 异常说明 + 请求/响应模型
