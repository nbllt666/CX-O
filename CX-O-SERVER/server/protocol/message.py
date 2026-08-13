"""
WebSocket 消息协议定义
统一前端-网关-后端消息格式
"""
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid
import time


class MessageType(str, Enum):
    """消息类型枚举：请求/响应/流/错误/心跳。"""
    REQUEST = "request"
    RESPONSE = "response"
    STREAM = "stream"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"


class BaseMessage(BaseModel):
    """消息基类——定义所有消息共有的类型、请求 ID、动作与时间戳字段。"""
    type: MessageType
    request_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    action: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)


class RequestMessage(BaseMessage):
    """请求消息。"""
    type: MessageType = MessageType.REQUEST
    action: str
    data: dict[str, Any] = Field(default_factory=dict)


class ResponseMessage(BaseMessage):
    """响应消息，携带处理状态与结果数据。"""
    type: MessageType = MessageType.RESPONSE
    action: str
    status: str = "success"
    data: dict[str, Any] = Field(default_factory=dict)


class StreamMessage(BaseMessage):
    """流式消息，携带分块序号与是否结束标记。"""
    type: MessageType = MessageType.STREAM
    action: str
    chunk_index: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    is_final: bool = False


class ErrorMessage(BaseMessage):
    """错误消息，携带错误码与错误描述。"""
    type: MessageType = MessageType.ERROR
    action: Optional[str] = None
    error: dict[str, Any] = Field(default_factory=dict)


class PingMessage(BaseModel):
    """心跳请求消息。"""
    type: MessageType = MessageType.PING
    timestamp: float = Field(default_factory=time.time)


class PongMessage(BaseModel):
    """心跳响应消息。"""
    type: MessageType = MessageType.PONG
    timestamp: float = Field(default_factory=time.time)


def create_response(request_id: str, action: str, data: dict[str, Any], status: str = "success") -> dict:
    """构造并返回响应消息字典。"""
    return ResponseMessage(
        request_id=request_id,
        action=action,
        status=status,
        data=data
    ).model_dump()


def create_request(action: str, data: dict[str, Any], request_id: Optional[str] = None) -> dict:
    """构造并返回请求消息字典。"""
    return RequestMessage(
        request_id=request_id,
        action=action,
        data=data
    ).model_dump()


def create_stream(request_id: str, action: str, chunk_index: int, data: dict[str, Any], is_final: bool = False) -> dict:
    """构造并返回流式消息字典。"""
    return StreamMessage(
        request_id=request_id,
        action=action,
        chunk_index=chunk_index,
        data=data,
        is_final=is_final
    ).model_dump()


def create_error(request_id: str, action: str, code: str, message: str) -> dict:
    """构造并返回错误消息字典。"""
    return ErrorMessage(
        request_id=request_id,
        action=action,
        error={"code": code, "message": message}
    ).model_dump()


def create_pong(timestamp: float) -> dict:
    """构造并返回心跳响应消息字典。"""
    return PongMessage(timestamp=timestamp).model_dump()