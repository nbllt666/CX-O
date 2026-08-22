"""CXFC 数据模型——插件、技能与事件的数据结构定义。"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, field_serializer
from enum import Enum


class PluginStatus(str, Enum):
    """插件连接状态枚举，表示插件当前为已连接或已断开。"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class PluginTransport(str, Enum):
    """CXFC 插件的传输方式：

    - direct: 插件自带 HTTP(S) 服务，后端按 host:port 直接调用（既有默认行为）。
    - relay: 前端转接——后端不直连 host:port，把调用投递到前端 relay 通道，由前端
      执行或在转发后回报结果；覆盖"前端作为中转代理转发外部插件"与"前端自身承载
      工具后回报"两种语义，统一收敛为一种传输。
    - embedded: 后端进程内嵌入式——工具以 Python Callable 直接登记于后端进程内，
      不走网络、无需 host/port。
    """
    DIRECT = "direct"
    RELAY = "relay"
    EMBEDDED = "embedded"


class CXFCPluginInfo(BaseModel):
    """CXFC 插件信息模型，描述已注册插件的主机端口、能力、工具与技能清单及连接状态。"""
    plugin_id: str
    host: str = ""
    port: int = 0
    name: str = ""
    version: str = "1.0.0"
    capabilities: List[str] = []
    status: PluginStatus = PluginStatus.DISCONNECTED
    # transport 判别：direct / relay / embedded。默认 direct，保持既有行为。
    transport: PluginTransport = PluginTransport.DIRECT
    last_seen: Optional[datetime] = None
    tools: List[Dict[str, Any]] = []
    skills: List[Dict[str, Any]] = []
    # Task3 电脑控制接入：注册令牌、TLS 证书指纹与自签名证书 PEM 原文（仅带 TLS 插件使用）。
    # token 仅用于后端转发 /call 时携带 Authorization: Bearer <token>，不回传插件元数据接口。
    # tls_cert_pem 为插件注册时上报的自签名证书 PEM，后端据此做 TOFU 首次信任（证书固定）。
    token: Optional[str] = None
    tls_cert_fingerprint: Optional[str] = None
    tls_cert_pem: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_serializer("last_seen", "created_at", "updated_at")
    def _ser_dt(self, v: Optional[datetime]) -> Optional[str]:
        return v.isoformat() if v else None


class SkillDefinition(BaseModel):
    """技能定义模型，描述技能名称、说明、提示模板、触发条件与来源插件。"""
    name: str
    description: str = ""
    prompt_template: str = ""
    trigger_keywords: List[str] = []
    trigger_events: List[str] = []
    auto_inject: bool = True
    source_plugin_id: str = ""


class CXFCEvent(BaseModel):
    """CXFC 事件模型，描述来自插件端口的事件类型、数据载荷与时间戳。"""
    from_port: int
    event_type: str
    data: Dict[str, Any] = {}
    timestamp: Optional[datetime] = None

    @field_serializer("timestamp")
    def _ser_ts(self, v: Optional[datetime]) -> Optional[str]:
        return v.isoformat() if v else None


class CXFCHeartbeatRequest(BaseModel):
    """插件心跳请求模型，向主服务上报插件 ID 与监听端口以维持连接。"""
    plugin_id: str = ""
    port: int


class CXFCRegisterRequest(BaseModel):
    """插件注册请求模型，上报主机端口、能力、工具与技能清单以完成注册。

    Task3 新增可选字段 token 与 tls_cert_fingerprint，供电脑控制插件（Electron
    客户端）注册时携带注册令牌与自签名证书指纹；非令牌插件不传，保持既有兼容。
    B-1 修复：新增 tls_cert_pem 可选字段，携带插件自签名证书 PEM 原文，后端据此
    进行 TOFU 首次信任（证书固定）并以 https 访问。
    扩展：新增可选 transport 字段（direct/relay/embedded，默认 direct），供 relay
    插件经前端注册时声明；host/port 对非 direct 插件可留空。
    """
    host: str = ""
    port: int = 0
    name: str = ""
    tools: List[Dict[str, Any]] = []
    capabilities: List[str] = []
    skills: List[Dict[str, Any]] = []
    token: Optional[str] = None
    tls_cert_fingerprint: Optional[str] = None
    tls_cert_pem: Optional[str] = None
    transport: PluginTransport = PluginTransport.DIRECT


class CXFCConnectRequest(BaseModel):
    """插件连接请求模型，指定目标插件的主机与端口发起连接。"""
    host: str
    port: int


class CXFCRelayRegisterRequest(BaseModel):
    """relay 插件注册请求模型——前端（或经前端代理的远端插件）注册 relay 目标。

    前端作中转代理时上报其承载/代理插件的描述与令牌；request_id 在调用投递与
    结果回报间保持一致，配合令牌沿用既有防重放语义。
    """
    plugin_id: Optional[str] = None
    name: str = ""
    tools: List[Dict[str, Any]] = []
    capabilities: List[str] = []
    skills: List[Dict[str, Any]] = []
    token: Optional[str] = None
    transport: PluginTransport = PluginTransport.RELAY


class CXFCRelayDispatchMessage(BaseModel):
    """relay 调用投递载荷——后端把一次工具调用投递给前端 relay 通道。"""
    plugin_id: str
    tool: str
    arguments: Dict[str, Any] = {}
    request_id: str
    token: Optional[str] = None


class CXFCRelayResultRequest(BaseModel):
    """relay 结果回报请求模型——前端在执行/转发完成后回报调用结果。"""
    plugin_id: str
    request_id: str
    success: bool = True
    result: Any = None
    error: Optional[str] = None


class CXFCEmbeddedTool(BaseModel):
    """嵌入式工具登记结构——名称、描述、参数 schema 与可调用 handler 名称。"""
    name: str
    description: str = ""
    parameters: Dict[str, Any] = {}
    handler: str = ""


class CXFCEmbeddedRegisterRequest(BaseModel):
    """嵌入式工具登记请求模型——供管理端/后端登记嵌入式工具描述。

    实际 handler 由 register_embedded_plugin() 以进程内 Callable 注入，此处只承载
    描述字段（名称/参数/handler 标识），用于列出与管理。
    """
    plugin_id: str
    name: str = ""
    tools: List[CXFCEmbeddedTool] = []
    capabilities: List[str] = []
    skills: List[Dict[str, Any]] = []
    transport: PluginTransport = PluginTransport.EMBEDDED