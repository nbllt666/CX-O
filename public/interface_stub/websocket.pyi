"""WebSocket 接口契约存根（种子阶段，待 s0201 补全）。

源真理:
  - c:/CX-O/CX-O-SERVER/server/api/routers/websocket.py
  - c:/CX-O/CX-O-SERVER/server/protocol/message.py（6 消息类型 + 4 工厂函数）
  - c:/CX-O/CX-O-SERVER/server/protocol/actions.py（18 Actions 类）

完成 Skill: s0201
当前状态: 种子——仅含 WS 信封 + Actions 枚举签名
"""

from enum import Enum
from typing import Any
from pydantic import BaseModel


class MessageType(str, Enum):
    """WS 消息类型（源真理: server/protocol/message.py）。"""
    REQUEST = "request"
    RESPONSE = "response"
    STREAM = "stream"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"


class BaseMessage(BaseModel):
    """WS 消息基类（种子，待 s0201 补全全部字段）。"""
    type: MessageType
    # TODO s0201: 补全 id/timestamp/action/data 等字段


class RequestMessage(BaseMessage):
    """请求消息。"""
    type: MessageType = MessageType.REQUEST


class ResponseMessage(BaseMessage):
    """响应消息。"""
    type: MessageType = MessageType.RESPONSE


class StreamMessage(BaseMessage):
    """流式消息。"""
    type: MessageType = MessageType.STREAM


class ErrorMessage(BaseMessage):
    """错误消息。"""
    type: MessageType = MessageType.ERROR
    # TODO s0201: 补全 error_code/error_message 字段


class Ping(BaseMessage):
    """心跳请求。"""
    type: MessageType = MessageType.PING


class Pong(BaseMessage):
    """心跳响应。"""
    type: MessageType = MessageType.PONG


class Actions(str, Enum):
    """WS Actions 枚举（18 类，源真理: server/protocol/actions.py）。

    待 s0201 补全全部 action 值与对应 payload schema：
    - Chat / Memory / Tools / Plugin / Context
    - ACP / MCP / Config / Metrics / System
    - ASR / Voice / TTS / Emotion / Effect
    - Danmaku / Events / ExternalEvents
    """
    CHAT = "chat"
    MEMORY = "memory"
    TOOLS = "tools"
    # TODO s0201: 补全全部 18 个 Actions 枚举值
    ...


async def websocket_endpoint(agent_id: str, websocket: Any) -> None:
    """WS /api/ws/{agent_id} — WebSocket 主端点。

    接收 RequestMessage，分发到对应 Action handler，返回 ResponseMessage/StreamMessage。

    Raises:
        WebSocketDisconnect: 客户端断开
        ValueError: 未知 action 或 payload 不合法
    """
    ...


def create_request(action: Actions, data: dict) -> RequestMessage:
    """工厂：创建请求消息（源真理: server/protocol/message.py 4 工厂函数之一）。"""
    ...


def create_response(request_id: str, data: dict) -> ResponseMessage:
    """工厂：创建响应消息。"""
    ...


def create_error(request_id: str, error_code: str, error_message: str) -> ErrorMessage:
    """工厂：创建错误消息。"""
    ...


def create_stream(request_id: str, chunk: str, done: bool = False) -> StreamMessage:
    """工厂：创建流式消息。"""
    ...

# TODO s0201: 补全全部 18 Actions 的 payload schema + handler 签名 + 异常说明
