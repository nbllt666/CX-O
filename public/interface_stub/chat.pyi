"""Chat router 接口契约存根（种子阶段，待 s0201 补全）。

源真理: c:/CX-O/CX-O-SERVER/server/api/routers/chat.py
完成 Skill: s0201
当前状态: 种子——含代表性端点签名；G2 契约修订对齐 POST /chat / history / summary-agent 端点
契约版本: 1.1.0（MINOR：POST /chat 改为 Request 直收无 Pydantic 体；GET history 补 limit
参数；补 POST /summary-agent/chat/stream 及 SummaryAgentChatRequest 模型）
"""

from typing import Any, AsyncIterator, List, Optional

from fastapi import Request

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


class SummaryAgentChatRequest(BaseModel):
    """摘要助手聊天请求（对齐 chat.py:620-632）。

    target_session_id 是摘要助手扩展字段（指定待摘要的目标会话）；
    CX-O 简化实现：接受但仅用于日志，不进行上下文替换。
    """
    message: str
    agent_id: str = "summary-agent"
    images: Optional[List[str]] = None  # base64 encoded images
    target_session_id: Optional[str] = None


async def chat(request: Request) -> ChatResponse:
    """POST /api/chat — 同步聊天（对齐 chat.py:74-75）。

    实现直收 fastapi.Request（无 Pydantic 请求体模型）：内部按 content-type
    分流处理 multipart/form-data（text/agent_id/image/audio 表单字段）与 JSON 体。

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


async def chat_history(session_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """GET /api/chat/history/{session_id} — 获取会话历史（对齐 chat.py:372-373）。

    Args:
        session_id: 会话 ID
        limit: 返回的最大消息数量（默认 50）

    Raises:
        HTTPException: 500 查询失败（session 不存在时返回空历史，不抛 404）
    """
    ...


async def memory_agent_chat_stream(request: ChatRequest) -> AsyncIterator[str]:
    """POST /api/memory-agent/chat/stream — 记忆代理 SSE 流式聊天。"""
    ...


async def summary_agent_stream_chat(request: SummaryAgentChatRequest) -> AsyncIterator[str]:
    """POST /api/summary-agent/chat/stream — 摘要助手 SSE 流式聊天（对齐 chat.py:635-636）。

    使用 summary 模型，仅提供 summary 类工具（save_diary_entry 等）；
    固定会话 summary-agent-default。

    Yields: SSE 格式的流式响应片段
    Raises:
        HTTPException: 500 流式处理失败
    """
    ...

# TODO s0201: 补全 chat.py 全部端点签名 + 异常说明 + 请求/响应模型
