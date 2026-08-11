"""CXFC 数据模型——插件、技能与事件的数据结构定义。"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, field_serializer
from enum import Enum


class PluginStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class CXFCPluginInfo(BaseModel):
    plugin_id: str
    host: str
    port: int
    name: str = ""
    version: str = "1.0.0"
    capabilities: List[str] = []
    status: PluginStatus = PluginStatus.DISCONNECTED
    last_seen: Optional[datetime] = None
    tools: List[Dict[str, Any]] = []
    skills: List[Dict[str, Any]] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_serializer("last_seen", "created_at", "updated_at")
    def _ser_dt(self, v: Optional[datetime]) -> Optional[str]:
        return v.isoformat() if v else None


class SkillDefinition(BaseModel):
    name: str
    description: str = ""
    prompt_template: str = ""
    trigger_keywords: List[str] = []
    trigger_events: List[str] = []
    auto_inject: bool = True
    source_plugin_id: str = ""


class CXFCEvent(BaseModel):
    from_port: int
    event_type: str
    data: Dict[str, Any] = {}
    timestamp: Optional[datetime] = None

    @field_serializer("timestamp")
    def _ser_ts(self, v: Optional[datetime]) -> Optional[str]:
        return v.isoformat() if v else None


class CXFCHeartbeatRequest(BaseModel):
    plugin_id: str = ""
    port: int


class CXFCRegisterRequest(BaseModel):
    host: str
    port: int
    name: str = ""
    tools: List[Dict[str, Any]] = []
    capabilities: List[str] = []
    skills: List[Dict[str, Any]] = []


class CXFCConnectRequest(BaseModel):
    host: str
    port: int
