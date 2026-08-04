from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SessionType(str, Enum):
    """会话类型"""

    CHAT = "chat"
    MEMORY = "memory"
    TOOL = "tool"
    SYSTEM = "system"


class Session(BaseModel):
    """会话模型"""

    id: str = Field(..., description="会话ID")
    workspace_id: str = Field(default="default", description="工作区ID")
    title: str = Field(default="新对话", description="会话标题")
    user_id: Optional[str] = Field(default=None, description="用户ID")
    session_type: SessionType = Field(default=SessionType.CHAT, description="会话类型")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    last_accessed_at: datetime = Field(default_factory=datetime.now, description="最后访问时间")
    message_count: int = Field(default=0, description="消息数量")
    summary: Optional[str] = Field(default=None, description="会话摘要")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")
    is_active: bool = Field(default=True, description="是否激活")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class SessionMessage(BaseModel):
    """会话消息模型"""

    id: str = Field(..., description="消息ID")
    session_id: str = Field(..., description="会话ID")
    role: str = Field(..., description="角色 (user/assistant/system/mono)")
    content: str = Field(..., description="内容")
    content_type: str = Field(default="text", description="内容类型")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")
    tokens: int = Field(default=0, description="Token数量")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    is_deleted: bool = Field(default=False, description="是否删除")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class SessionStats(BaseModel):
    """会话统计"""

    total_sessions: int = Field(default=0, description="总会话数")
    active_sessions: int = Field(default=0, description="激活会话数")
    expired_sessions: int = Field(default=0, description="过期会话数")
    total_messages: int = Field(default=0, description="总消息数")
    avg_messages_per_session: float = Field(default=0.0, description="平均每会话消息数")
