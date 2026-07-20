# CXFC 测试工具预置工具定义与执行处理器
"""预置工具集：提供计算器、字符串反转、时间查询、回声四个基础测试工具，
以及 video_summary / audio_transcribe 两个多模态测试工具（CX-O 扩展）。

每个工具包含：
- 定义（name / description / parameters JSON Schema）：暴露给主系统
- 处理器（handler）：当主系统通过 POST /call 调用时实际执行

多模态工具字段对齐 CX-O CXFC 扩展点（server/core/cxfc/models.py 中
tools 为 List[Dict[str, Any]]，多模态属性由工具定义内部的 modality /
type 字段承载）：
- modality: "video" | "audio" 标识媒体模态
- type: "multimodal" 标识工具类别（与 CX-O tools.py 前端兼容字段一致）
"""
import datetime
import math
from typing import Any, Dict, List


def _tool_calculator(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """简易计算器：支持加减乘除、幂运算、开方。"""
    op = str(arguments.get("operation", "")).strip()
    a = arguments.get("a")
    b = arguments.get("b")

    try:
        a = float(a) if a is not None else None
        b = float(b) if b is not None else None
    except (TypeError, ValueError) as e:
        return {"success": False, "error": f"参数类型错误: {e}"}

    if op == "add":
        if a is None or b is None:
            return {"success": False, "error": "add 操作需要 a 和 b 两个参数"}
        return {"success": True, "result": a + b}
    if op == "subtract":
        if a is None or b is None:
            return {"success": False, "error": "subtract 操作需要 a 和 b 两个参数"}
        return {"success": True, "result": a - b}
    if op == "multiply":
        if a is None or b is None:
            return {"success": False, "error": "multiply 操作需要 a 和 b 两个参数"}
        return {"success": True, "result": a * b}
    if op == "divide":
        if a is None or b is None:
            return {"success": False, "error": "divide 操作需要 a 和 b 两个参数"}
        if b == 0:
            return {"success": False, "error": "除数不能为 0"}
        return {"success": True, "result": a / b}
    if op == "power":
        if a is None or b is None:
            return {"success": False, "error": "power 操作需要 a 和 b 两个参数"}
        return {"success": True, "result": math.pow(a, b)}
    if op == "sqrt":
        if a is None:
            return {"success": False, "error": "sqrt 操作需要 a 参数"}
        if a < 0:
            return {"success": False, "error": "不能对负数开平方"}
        return {"success": True, "result": math.sqrt(a)}

    return {"success": False, "error": f"不支持的操作: {op}"}


def _tool_string_reverse(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """字符串反转：返回输入字符串的逆序。"""
    text = arguments.get("text", "")
    if not isinstance(text, str):
        return {"success": False, "error": "text 参数必须是字符串"}
    return {"success": True, "result": text[::-1], "length": len(text)}


def _tool_time_query(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """时间查询：返回当前时间或格式化指定时间。"""
    fmt = arguments.get("format", "%Y-%m-%d %H:%M:%S")
    if not isinstance(fmt, str):
        return {"success": False, "error": "format 参数必须是字符串"}
    now = datetime.datetime.now()
    try:
        return {
            "success": True,
            "result": now.strftime(fmt),
            "iso8601": now.isoformat(),
            "timestamp": now.timestamp(),
            "weekday": now.strftime("%A"),
        }
    except Exception as e:
        return {"success": False, "error": f"时间格式化失败: {e}"}


def _tool_echo(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """回声工具：原样返回输入内容，用于验证调用链路。"""
    message = arguments.get("message", "")
    return {
        "success": True,
        "result": message,
        "received_at": datetime.datetime.now().isoformat(),
        "echo_type": type(message).__name__,
    }


def _tool_video_summary(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """视频摘要工具：输入视频 URL，返回内容摘要文本（测试模拟实现）。

    对齐 CX-O CXFC 多模态工具契约：modality=video。
    真实场景应由多模态模型处理；此处返回模拟摘要用于端到端链路验证。
    """
    video_url = str(arguments.get("video_url", "")).strip()
    if not video_url:
        return {"success": False, "error": "video_url 参数不能为空"}

    max_length = arguments.get("max_length", 200)
    try:
        max_length = int(max_length)
        if max_length <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return {"success": False, "error": "max_length 必须是正整数"}

    summary = (
        "[模拟视频摘要] 已分析视频 " + video_url + "，时长约 00:01:30。"
        "主要内容包括：场景切换 5 次，人物出现 2 名，关键事件为开场与结尾对话。"
    )
    if len(summary) > max_length:
        summary = summary[:max_length] + "..."

    return {
        "success": True,
        "result": summary,
        "modality": "video",
        "source_url": video_url,
        "summary_length": len(summary),
        "processed_at": datetime.datetime.now().isoformat(),
    }


def _tool_audio_transcribe(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """音频转写工具：输入音频 URL，返回转写文本（测试模拟实现）。

    对齐 CX-O CXFC 多模态工具契约：modality=audio。
    真实场景应由 ASR 模型处理；此处返回模拟转写用于端到端链路验证。
    """
    audio_url = str(arguments.get("audio_url", "")).strip()
    if not audio_url:
        return {"success": False, "error": "audio_url 参数不能为空"}

    language = str(arguments.get("language", "auto")).strip() or "auto"

    transcript = (
        "[模拟转写] 音频 " + audio_url + " 的转写结果："
        "大家好，这是一段测试音频，用于验证 CXFC 多模态工具调用链路。"
    )

    return {
        "success": True,
        "result": transcript,
        "modality": "audio",
        "source_url": audio_url,
        "language": language,
        "transcript_length": len(transcript),
        "processed_at": datetime.datetime.now().isoformat(),
    }


# 工具定义（JSON Schema 格式，供主系统注册时使用）
PRESET_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "calculator",
        "description": "简易计算器，支持 add/subtract/multiply/divide/power/sqrt 操作",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide", "power", "sqrt"],
                    "description": "要执行的运算",
                },
                "a": {"type": "number", "description": "第一个操作数"},
                "b": {"type": "number", "description": "第二个操作数（sqrt 不需要）"},
            },
            "required": ["operation", "a"],
        },
    },
    {
        "name": "string_reverse",
        "description": "字符串反转工具，返回输入字符串的逆序",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要反转的字符串"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "time_query",
        "description": "时间查询工具，返回当前时间，支持自定义格式化",
        "parameters": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "strftime 格式字符串，默认 '%Y-%m-%d %H:%M:%S'",
                    "default": "%Y-%m-%d %H:%M:%S",
                },
            },
            "required": [],
        },
    },
    {
        "name": "echo",
        "description": "回声工具，原样返回输入内容，用于验证调用链路",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "要回声的内容",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "video_summary",
        "description": "视频摘要工具，输入视频 URL 返回内容摘要文本（多模态）",
        "type": "multimodal",
        "modality": "video",
        "parameters": {
            "type": "object",
            "properties": {
                "video_url": {
                    "type": "string",
                    "description": "待摘要的视频资源 URL",
                },
                "max_length": {
                    "type": "integer",
                    "description": "摘要文本最大长度",
                    "default": 200,
                },
            },
            "required": ["video_url"],
        },
    },
    {
        "name": "audio_transcribe",
        "description": "音频转写工具，输入音频 URL 返回转写文本（多模态）",
        "type": "multimodal",
        "modality": "audio",
        "parameters": {
            "type": "object",
            "properties": {
                "audio_url": {
                    "type": "string",
                    "description": "待转写的音频资源 URL",
                },
                "language": {
                    "type": "string",
                    "description": "音频语言，默认 auto 自动识别",
                    "default": "auto",
                },
            },
            "required": ["audio_url"],
        },
    },
]

# 预置 Skills 定义（JSON Schema 格式，供主系统注册时使用）
# 与 tools 定义格式一致：name / description / parameters
PRESET_SKILL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "text_summary",
        "description": "文本摘要：将长文本总结为要点",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要摘要的文本"},
                "max_length": {
                    "type": "integer",
                    "description": "最大摘要长度",
                    "default": 100,
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "translation",
        "description": "翻译：多语言翻译",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要翻译的文本"},
                "target_language": {
                    "type": "string",
                    "description": "目标语言，例如 en/zh/ja/fr",
                },
                "source_language": {
                    "type": "string",
                    "description": "源语言，默认 auto 自动识别",
                    "default": "auto",
                },
            },
            "required": ["text", "target_language"],
        },
    },
    {
        "name": "code_generation",
        "description": "代码生成：根据描述生成代码",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "代码需求描述",
                },
                "language": {
                    "type": "string",
                    "description": "编程语言，例如 python/javascript/java",
                    "default": "python",
                },
                "framework": {
                    "type": "string",
                    "description": "目标框架，可选，例如 flask/react",
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "sentiment_analysis",
        "description": "情感分析：分析文本情感倾向",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要分析的文本"},
                "detail_level": {
                    "type": "string",
                    "enum": ["brief", "detailed"],
                    "description": "分析详细程度，brief 仅给出倾向，detailed 给出分数与理由",
                    "default": "brief",
                },
            },
            "required": ["text"],
        },
    },
]

# 工具名 → 处理器映射
TOOL_HANDLERS = {
    "calculator": _tool_calculator,
    "string_reverse": _tool_string_reverse,
    "time_query": _tool_time_query,
    "echo": _tool_echo,
    "video_summary": _tool_video_summary,
    "audio_transcribe": _tool_audio_transcribe,
}


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """执行指定工具，返回结果字典。

    Args:
        tool_name: 工具名称
        arguments: 工具参数

    Returns:
        包含 success 字段的结果字典
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {"success": False, "error": f"未知工具: {tool_name}"}
    try:
        return handler(arguments or {})
    except Exception as e:
        return {"success": False, "error": f"工具执行异常: {e}"}


def get_preset_definitions() -> List[Dict[str, Any]]:
    """返回预置工具定义的深拷贝，避免外部修改污染。"""
    import copy

    return copy.deepcopy(PRESET_TOOL_DEFINITIONS)


def list_tool_names() -> List[str]:
    """返回所有预置工具名列表。"""
    return [t["name"] for t in PRESET_TOOL_DEFINITIONS]


def get_preset_skills() -> List[Dict[str, Any]]:
    """返回预置 skills 定义的深拷贝，避免外部修改污染。"""
    import copy

    return copy.deepcopy(PRESET_SKILL_DEFINITIONS)


def list_skill_names() -> List[str]:
    """返回所有预置 skill 名列表。"""
    return [s["name"] for s in PRESET_SKILL_DEFINITIONS]


# ===== 多模态工具辅助函数（CX-O 扩展）=====

MULTIMODAL_MODALITIES = ("video", "audio")


def get_multimodal_definitions() -> List[Dict[str, Any]]:
    """返回多模态工具定义的深拷贝（modality 字段非空的工具）。"""
    import copy

    return copy.deepcopy([
        t for t in PRESET_TOOL_DEFINITIONS
        if t.get("modality") in MULTIMODAL_MODALITIES
    ])


def list_multimodal_tool_names() -> List[str]:
    """返回所有多模态工具名列表。"""
    return [t["name"] for t in PRESET_TOOL_DEFINITIONS
            if t.get("modality") in MULTIMODAL_MODALITIES]


def get_modality(tool_name: str) -> str:
    """根据工具名返回其 modality（video/audio）；非多模态工具返回空串。"""
    for t in PRESET_TOOL_DEFINITIONS:
        if t.get("name") == tool_name:
            return t.get("modality", "")
    return ""
