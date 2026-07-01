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
    REQUEST = "request"
    RESPONSE = "response"
    STREAM = "stream"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"


class BaseMessage(BaseModel):
    type: MessageType
    request_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    action: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)


class RequestMessage(BaseMessage):
    type: MessageType = MessageType.REQUEST
    action: str
    data: dict[str, Any] = Field(default_factory=dict)


class ResponseMessage(BaseMessage):
    type: MessageType = MessageType.RESPONSE
    action: str
    status: str = "success"
    data: dict[str, Any] = Field(default_factory=dict)


class StreamMessage(BaseMessage):
    type: MessageType = MessageType.STREAM
    action: str
    chunk_index: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    is_final: bool = False


class ErrorMessage(BaseMessage):
    type: MessageType = MessageType.ERROR
    action: Optional[str] = None
    error: dict[str, Any] = Field(default_factory=dict)


class PingMessage(BaseModel):
    type: MessageType = MessageType.PING
    timestamp: float = Field(default_factory=time.time)


class PongMessage(BaseModel):
    type: MessageType = MessageType.PONG
    timestamp: float = Field(default_factory=time.time)


def create_response(request_id: str, action: str, data: dict[str, Any], status: str = "success") -> dict:
    return ResponseMessage(
        request_id=request_id,
        action=action,
        status=status,
        data=data
    ).model_dump()


def create_stream(request_id: str, action: str, chunk_index: int, data: dict[str, Any], is_final: bool = False) -> dict:
    return StreamMessage(
        request_id=request_id,
        action=action,
        chunk_index=chunk_index,
        data=data,
        is_final=is_final
    ).model_dump()


def create_error(request_id: str, action: str, code: str, message: str) -> dict:
    return ErrorMessage(
        request_id=request_id,
        action=action,
        error={"code": code, "message": message}
    ).model_dump()


def create_pong(timestamp: float) -> dict:
    return PongMessage(timestamp=timestamp).model_dump()
