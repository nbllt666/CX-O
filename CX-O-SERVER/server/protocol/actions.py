"""
Action 常量定义
统一 Action 命名规范
"""


class ChatActions:
    MESSAGE = "chat.message"
    STREAM = "chat.stream"
    MULTIMODAL = "chat.multimodal"


class MemoryActions:
    """记忆相关 action 常量。"""

    LIST = "memory.list"
    CREATE = "memory.create"
    DELETE = "memory.delete"
    SEARCH = "memory.search"
    GET = "memory.get"
    UPDATE = "memory.update"


class ToolsActions:
    LIST = "tools.list"
    CALL = "tools.call"
    REGISTER = "tools.register"


class PluginActions:
    """插件生命周期相关 action 常量。"""

    REGISTER = "plugin.register"
    HEARTBEAT = "plugin.heartbeat"
    LIST = "plugin.list"
    UNREGISTER = "plugin.unregister"


class ContextActions:
    GET = "context.get"
    APPEND = "context.append"
    CLEAR = "context.clear"
    SET = "context.set"


class ACPActions:
    """ACP 连接管理相关 action 常量。"""
    CONNECT = "acp.connect"
    DISCONNECT = "acp.disconnect"
    CONNECTIONS = "acp.connections"
    STATUS = "acp.status"


class MCPActions:
    """MCP 服务器管理相关 action 常量。"""

    CONNECT = "mcp.connect"
    DISCONNECT = "mcp.disconnect"
    TOOLS = "mcp.tools"
    CALL = "mcp.call"
    STATUS = "mcp.status"


class ConfigActions:
    GET = "config.get"
    SET = "config.set"
    RESET = "config.reset"


class MetricsActions:
    GET = "metrics.get"
    REQUESTS = "metrics.requests"
    HISTORY = "metrics.history"


class SystemActions:
    """系统健康与状态相关 action 常量。"""

    HEALTH = "system.health"
    STATUS = "system.status"
    INFO = "system.info"


class ASRActions:
    RECOGNIZE = "asr.recognize"
    RECOGNIZE_BASE64 = "asr.recognize_base64"
    STREAM = "asr_stream"
    STATUS = "asr_stream_status"
    RESULT = "asr_stream_result"


class VoiceActions:
    """双流式语音 action 常量

    双流式模式核心：ASR Partial Result 是主驱动器，VAD 仅作兜底。
    这些 action 用于 voice.dual_stream handler 与前端的双向通信：
    - DUAL_STREAM: 前端发起双流式会话（init/audio/end 三类消息复用此 action）
    - PARTIAL: 后端 → 前端，推送 ASR Partial 识别文本（实时显示）
    - TTS_CHUNK: 后端 → 前端，流式推送 TTS 音频块（不等整句）
    - PREFILL_STARTED: 后端 → 前端，通知 LLM Speculative Prefill 已启动
    """
    DUAL_STREAM = "voice.dual_stream"
    PARTIAL = "voice.partial"
    TTS_CHUNK = "voice.tts_chunk"
    PREFILL_STARTED = "voice.prefill_started"


class TTSActions:
    """语音合成相关 action 常量。"""

    SYNTHESIZE = "tts.synthesize"
    SYNTHESIZE_STREAM = "tts.synthesize_stream"
    VOICES = "tts.voices"


class EmotionActions:
    """情感识别相关 action 常量。"""
    LIST = "emotions.list"
    PARSE = "emotions.parse"


class EffectActions:
    LIST = "effects.list"
    PARSE = "effects.parse"


class DanmakuActions:
    """弹幕相关 action 常量。"""

    LIST = "danmaku.list"
    ADD = "danmaku.add"
    CLEAR = "danmaku.clear"


class EventsActions:
    """事件订阅相关 action 常量。"""

    SUBSCRIBE = "events.subscribe"
    UNSUBSCRIBE = "events.unsubscribe"


ACTION_HANDLERS = {
    ChatActions.MESSAGE: "chat",
    ChatActions.STREAM: "chat",
    ChatActions.MULTIMODAL: "chat",
    MemoryActions.LIST: "memory",
    MemoryActions.CREATE: "memory",
    MemoryActions.DELETE: "memory",
    MemoryActions.SEARCH: "memory",
    MemoryActions.GET: "memory",
    MemoryActions.UPDATE: "memory",
    ToolsActions.LIST: "tools",
    ToolsActions.CALL: "tools",
    ToolsActions.REGISTER: "tools",
    PluginActions.REGISTER: "plugin",
    PluginActions.HEARTBEAT: "plugin",
    PluginActions.LIST: "plugin",
    PluginActions.UNREGISTER: "plugin",
    ContextActions.GET: "context",
    ContextActions.APPEND: "context",
    ContextActions.CLEAR: "context",
    ContextActions.SET: "context",
    ACPActions.CONNECT: "acp",
    ACPActions.DISCONNECT: "acp",
    ACPActions.CONNECTIONS: "acp",
    ACPActions.STATUS: "acp",
    MCPActions.CONNECT: "mcp",
    MCPActions.DISCONNECT: "mcp",
    MCPActions.TOOLS: "mcp",
    MCPActions.CALL: "mcp",
    MCPActions.STATUS: "mcp",
    ConfigActions.GET: "config",
    ConfigActions.SET: "config",
    ConfigActions.RESET: "config",
    MetricsActions.GET: "metrics",
    MetricsActions.REQUESTS: "metrics",
    MetricsActions.HISTORY: "metrics",
    SystemActions.HEALTH: "system",
    SystemActions.STATUS: "system",
    SystemActions.INFO: "system",
    ASRActions.RECOGNIZE: "audio",
    ASRActions.RECOGNIZE_BASE64: "audio",
    ASRActions.STREAM: "audio",
    VoiceActions.DUAL_STREAM: "audio",
    TTSActions.SYNTHESIZE: "audio",
    TTSActions.SYNTHESIZE_STREAM: "audio",
    TTSActions.VOICES: "audio",
    EmotionActions.LIST: "audio",
    EmotionActions.PARSE: "audio",
    EffectActions.LIST: "audio",
    EffectActions.PARSE: "audio",
    DanmakuActions.LIST: "danmaku",
    DanmakuActions.ADD: "danmaku",
    DanmakuActions.CLEAR: "danmaku",
    EventsActions.SUBSCRIBE: "events",
    EventsActions.UNSUBSCRIBE: "events",
}


def get_handler_name(action: str) -> str | None:
    """根据 action 返回对应的处理器名称，未注册时返回 None。"""
    return ACTION_HANDLERS.get(action)
