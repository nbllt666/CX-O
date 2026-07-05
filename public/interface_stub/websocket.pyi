"""WebSocket 接口契约存根（s0601/A7 补全版，18 个独立 Action 类镜像）。

源真理:
  - c:/CX-O/CX-O-SERVER/server/api/routers/websocket.py
  - c:/CX-O/CX-O-SERVER/server/protocol/message.py（7 消息类型 + 5 工厂函数）
  - c:/CX-O/CX-O-SERVER/server/protocol/actions.py（18 个 Action 类，共 ~60 个 action 常量）

完成 Skill: s0601（A6+A7+A8）
版本: 1.0.0
"""

from typing import Any, Optional
from enum import Enum
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# MessageType 枚举
# ---------------------------------------------------------------------------
class MessageType(str, Enum):
    """WS 消息类型（源真理: server/protocol/message.py:MessageType）。"""
    REQUEST = "request"
    RESPONSE = "response"
    STREAM = "stream"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"


# ---------------------------------------------------------------------------
# 消息模型（镜像 server/protocol/message.py 的 7 个 BaseModel）
# ---------------------------------------------------------------------------
class BaseMessage(BaseModel):
    """WS 消息基类。"""
    type: MessageType
    request_id: Optional[str] = None
    action: Optional[str] = None
    timestamp: float = None


class RequestMessage(BaseMessage):
    """请求消息。前端 → 网关 → 后端。"""
    type: MessageType = MessageType.REQUEST
    action: str
    data: dict = {}


class ResponseMessage(BaseMessage):
    """响应消息。后端 → 前端。"""
    type: MessageType = MessageType.RESPONSE
    action: str
    status: str = "success"
    data: dict = {}


class StreamMessage(BaseMessage):
    """流式消息。用于流式响应。"""
    type: MessageType = MessageType.STREAM
    action: str
    chunk_index: int = 0
    data: dict = {}
    is_final: bool = False


class ErrorMessage(BaseMessage):
    """错误消息。"""
    type: MessageType = MessageType.ERROR
    action: Optional[str] = None
    error: dict = {}


class PingMessage(BaseModel):
    """心跳请求。"""
    type: MessageType = MessageType.PING
    timestamp: float = None


class PongMessage(BaseModel):
    """心跳响应。"""
    type: MessageType = MessageType.PONG
    timestamp: float = None


# ---------------------------------------------------------------------------
# 18 个独立 Action 类（镜像 server/protocol/actions.py）
# ---------------------------------------------------------------------------
class ChatActions:
    """Chat 相关 actions。"""
    MESSAGE: str = "chat.message"
    STREAM: str = "chat.stream"
    MULTIMODAL: str = "chat.multimodal"


class MemoryActions:
    """Memory 相关 actions。"""
    LIST: str = "memory.list"
    CREATE: str = "memory.create"
    DELETE: str = "memory.delete"
    SEARCH: str = "memory.search"
    GET: str = "memory.get"
    UPDATE: str = "memory.update"


class ToolsActions:
    """Tools 相关 actions。"""
    LIST: str = "tools.list"
    CALL: str = "tools.call"
    REGISTER: str = "tools.register"


class PluginActions:
    """Plugin 相关 actions。"""
    REGISTER: str = "plugin.register"
    HEARTBEAT: str = "plugin.heartbeat"
    LIST: str = "plugin.list"
    UNREGISTER: str = "plugin.unregister"


class ContextActions:
    """Context 相关 actions。"""
    GET: str = "context.get"
    APPEND: str = "context.append"
    CLEAR: str = "context.clear"
    SET: str = "context.set"


class ACPActions:
    """ACP（Agent Communication Protocol）相关 actions。"""
    CONNECT: str = "acp.connect"
    DISCONNECT: str = "acp.disconnect"
    CONNECTIONS: str = "acp.connections"
    STATUS: str = "acp.status"


class MCPActions:
    """MCP（Model Context Protocol）相关 actions。"""
    CONNECT: str = "mcp.connect"
    DISCONNECT: str = "mcp.disconnect"
    TOOLS: str = "mcp.tools"
    CALL: str = "mcp.call"
    STATUS: str = "mcp.status"


class ConfigActions:
    """Config 相关 actions。"""
    GET: str = "config.get"
    SET: str = "config.set"
    RESET: str = "config.reset"


class MetricsActions:
    """Metrics 相关 actions。"""
    GET: str = "metrics.get"
    REQUESTS: str = "metrics.requests"
    HISTORY: str = "metrics.history"


class SystemActions:
    """System 相关 actions。"""
    HEALTH: str = "system.health"
    STATUS: str = "system.status"
    INFO: str = "system.info"


class ASRActions:
    """ASR（语音识别）相关 actions。"""
    RECOGNIZE: str = "asr.recognize"
    RECOGNIZE_BASE64: str = "asr.recognize_base64"
    STREAM: str = "asr_stream"
    STATUS: str = "asr_stream_status"
    RESULT: str = "asr_stream_result"


class VoiceActions:
    """双流式语音 actions。"""
    DUAL_STREAM: str = "voice.dual_stream"
    PARTIAL: str = "voice.partial"
    TTS_CHUNK: str = "voice.tts_chunk"
    PREFILL_STARTED: str = "voice.prefill_started"


class TTSActions:
    """TTS（语音合成）相关 actions。"""
    SYNTHESIZE: str = "tts.synthesize"
    SYNTHESIZE_STREAM: str = "tts.synthesize_stream"
    VOICES: str = "tts.voices"


class EmotionActions:
    """Emotion 相关 actions。"""
    LIST: str = "emotions.list"
    PARSE: str = "emotions.parse"


class EffectActions:
    """Effect 相关 actions。"""
    LIST: str = "effects.list"
    PARSE: str = "effects.parse"


class DanmakuActions:
    """Danmaku（弹幕）相关 actions。"""
    LIST: str = "danmaku.list"
    ADD: str = "danmaku.add"
    CLEAR: str = "danmaku.clear"


class EventsActions:
    """Events 相关 actions。"""
    SUBSCRIBE: str = "events.subscribe"
    UNSUBSCRIBE: str = "events.unsubscribe"


class ExternalEventsActions:
    """ExternalEvents 相关 actions。"""
    EXTERNAL_EVENT: str = "external_event"
    SUBSCRIBE: str = "events.subscribe"
    UNSUBSCRIBE: str = "events.unsubscribe"


# ---------------------------------------------------------------------------
# Action handler 映射（镜像 server/protocol/actions.py:ACTION_HANDLERS）
# ---------------------------------------------------------------------------
ACTION_HANDLERS: dict[str, str] = ...
def get_handler_name(action: str) -> Optional[str]: ...


# ---------------------------------------------------------------------------
# WebSocket 端点签名（镜像 server/api/routers/websocket.py 的 4 个 WS 路由）
# ---------------------------------------------------------------------------
async def websocket_agent_endpoint(websocket: Any, agent_id: str, timeout: int = 60) -> None:
    """WS /api/ws/{agent_id} — Agent 专用 WebSocket 端点。

    接收 RequestMessage，分发到对应 Action handler，返回 ResponseMessage/StreamMessage。

    Raises:
        WebSocketDisconnect: 客户端断开
        ValueError: 未知 action 或 payload 不合法
    """
    ...


async def websocket_endpoint(websocket: Any, client_id: Optional[str] = None, token: Optional[str] = None) -> None:
    """WS /api/ws — WebSocket 主端点（无 agent_id 路径）。

    支持实时聊天、消息订阅、心跳检测等功能。

    Raises:
        WebSocketDisconnect: 客户端断开
    """
    ...


async def websocket_chat_endpoint(websocket: Any, session_id: Optional[str] = None, agent_id: Optional[str] = "default") -> None:
    """WS /api/ws/chat — 聊天频道订阅端点。

    Raises:
        WebSocketDisconnect: 客户端断开
    """
    ...


async def websocket_live_endpoint(websocket: Any, session_id: Optional[str] = None) -> None:
    """WS /api/ws/live — 实时消息分发端点。

    Raises:
        WebSocketDisconnect: 客户端断开
    """
    ...


# ---------------------------------------------------------------------------
# 5 个工厂函数（镜像 server/protocol/message.py 的实现签名）
# ---------------------------------------------------------------------------
def create_request(action: str, data: dict, request_id: Optional[str] = None) -> dict:
    """工厂：创建请求消息。返回 dict（model_dump 后的序列化形式）。

    s0601/A6 已实现。源真理：server/protocol/message.py:create_request
    """
    ...


def create_response(request_id: str, action: str, data: dict, status: str = "success") -> dict:
    """工厂：创建响应消息。返回 dict。"""
    ...


def create_stream(request_id: str, action: str, chunk_index: int, data: dict, is_final: bool = False) -> dict:
    """工厂：创建流式消息。返回 dict。"""
    ...


def create_error(request_id: str, action: str, code: str, message: str) -> dict:
    """工厂：创建错误消息。返回 dict。error 字段结构 {code, message}。"""
    ...


def create_pong(timestamp: float) -> dict:
    """工厂：创建心跳响应。返回 dict。"""
    ...
