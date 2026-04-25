"""
Action 常量定义
统一 Action 命名规范
"""


class ChatActions:
    MESSAGE = "chat.message"
    STREAM = "chat.stream"
    MULTIMODAL = "chat.multimodal"


class MemoryActions:
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
    CONNECT = "acp.connect"
    DISCONNECT = "acp.disconnect"
    CONNECTIONS = "acp.connections"
    STATUS = "acp.status"


class MCPActions:
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
    HEALTH = "system.health"
    STATUS = "system.status"
    INFO = "system.info"


class ASRActions:
    RECOGNIZE = "asr.recognize"
    RECOGNIZE_BASE64 = "asr.recognize_base64"
    STREAM = "asr.stream"


class TTSActions:
    SYNTHESIZE = "tts.synthesize"
    SYNTHESIZE_STREAM = "tts.synthesize_stream"
    VOICES = "tts.voices"


class EmotionActions:
    LIST = "emotions.list"
    PARSE = "emotions.parse"


class EffectActions:
    LIST = "effects.list"
    PARSE = "effects.parse"


class DanmakuActions:
    LIST = "danmaku.list"
    ADD = "danmaku.add"
    CLEAR = "danmaku.clear"


class EventsActions:
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
    return ACTION_HANDLERS.get(action)
