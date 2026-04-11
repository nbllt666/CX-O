from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel, Field


class HookType(str, Enum):
    MEMORY_CREATED = "memory_created"
    MEMORY_UPDATED = "memory_updated"
    MEMORY_DELETED = "memory_deleted"
    MEMORY_SEARCH = "memory_search"
    MEMORY_DECAY = "memory_decay"
    CHAT_BEFORE = "chat_before"
    CHAT_AFTER = "chat_after"
    CHAT_STREAM = "chat_stream"
    SESSION_CREATED = "session_created"
    SESSION_UPDATED = "session_updated"
    SESSION_DELETED = "session_deleted"
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"
    SYSTEM_HEALTH_CHECK = "system_health_check"
    TOOL_BEFORE_EXECUTE = "tool_before_execute"
    TOOL_AFTER_EXECUTE = "tool_after_execute"
    CUSTOM = "custom"


class PluginMetadata(BaseModel):
    id: str = Field(..., description="插件唯一ID")
    name: str = Field(..., description="插件名称")
    version: str = Field(default="1.0.0", description="版本号")
    description: str = Field(default="", description="插件描述")
    author: str = Field(default="", description="作者")
    author_email: Optional[str] = Field(default=None, description="作者邮箱")
    url: Optional[str] = Field(default=None, description="插件主页")
    license: str = Field(default="MIT", description="许可证")
    requires: List[str] = Field(default_factory=list, description="依赖的其他插件")
    conflicts: List[str] = Field(default_factory=list, description="冲突的插件")
    hooks: List[HookType] = Field(default_factory=list, description="注册的钩子")
    provides: List[str] = Field(default_factory=list, description="提供的功能")
    config_schema: Optional[Dict[str, Any]] = Field(default=None, description="配置项Schema")
    default_config: Dict[str, Any] = Field(default_factory=dict, description="默认配置")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class PluginHook(BaseModel):
    type: HookType = Field(..., description="钩子类型")
    handler: Callable = Field(..., description="处理函数")
    priority: int = Field(default=100, description="优先级，数字越小优先级越高")
    plugin_id: str = Field(..., description="所属插件ID")

    class Config:
        arbitrary_types_allowed = True


class Plugin(BaseModel):
    metadata: PluginMetadata = Field(..., description="插件元数据")
    enabled: bool = Field(default=False, description="是否启用")
    config: Dict[str, Any] = Field(default_factory=dict, description="当前配置")
    loaded_at: Optional[datetime] = Field(default=None, description="加载时间")
    module: Optional[Any] = Field(default=None, description="插件模块")
    instance: Optional[Any] = Field(default=None, description="插件实例")
    hook_calls: int = Field(default=0, description="钩子调用次数")
    errors: int = Field(default=0, description="错误次数")

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}

    def to_dict(self) -> Dict[str, Any]:
        return {"metadata": self.metadata.dict(), "enabled": self.enabled, "config": self.config,
                "loaded_at": self.loaded_at.isoformat() if self.loaded_at else None,
                "hook_calls": self.hook_calls, "errors": self.errors}


class PluginEvent(BaseModel):
    type: HookType = Field(..., description="事件类型")
    data: Dict[str, Any] = Field(default_factory=dict, description="事件数据")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    source: Optional[str] = Field(default=None, description="事件来源")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class PluginResult(BaseModel):
    success: bool = Field(default=True, description="是否成功")
    data: Optional[Any] = Field(default=None, description="返回数据")
    error: Optional[str] = Field(default=None, description="错误信息")
    modified: bool = Field(default=False, description="是否修改了数据")
    stop_propagation: bool = Field(default=False, description="是否阻止后续处理")