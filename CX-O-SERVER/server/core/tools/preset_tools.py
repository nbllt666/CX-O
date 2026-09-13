"""per-agent 预设工具 - 供主模型注册/查询/删除情感TTS预设与动作预设。

Spec: .trae/specs/enhance-emotion-tts-and-action-presets/spec.md「per-agent 预设」。
与 master_tools.py 的「写记忆」类工具同一注册方式（tool_registry.register +
register_*_tools()），agent_id 复用 graph_tools 的 contextvar 机制
（chat 路由/ACP 在请求开始时 set_current_agent_id，工具经 get_current_agent_id 读取）。

引用写法（Task 4 在服务端展开，工具描述中向 LLM 说明）：
- 情感预设：在回复最前面输出 ``<tts_instruction>{"preset":"预设名"}</tts_instruction>``
- 动作预设：在回复中输出 ``[action:预设名]``
"""

from typing import Any, Dict, List

from server.core.logging_config import get_contextual_logger
from server.core.tools.graph_tools import get_current_agent_id
from server.services import preset_service
from .registry import tool_registry

logger = get_contextual_logger(__name__)

# 预设工具名称（同步加入 registry.BUILTIN_TOOL_NAMES 与 chat_helpers 主模型白名单）
PRESET_TOOL_NAMES = (
    "save_emotion_preset",
    "save_action_preset",
    "list_presets",
    "delete_preset",
)

# 引用写法提示（注入工具 description，降低 LLM 使用门槛）
_EMOTION_USAGE_HINT = (
    "引用方式：在回复【最前面】输出 <tts_instruction>{\"preset\":\"预设名\"}</tts_instruction>，"
    "服务端会展开为完整情感TTS指令（语气/语速/音量）。"
)
_ACTION_USAGE_HINT = (
    "引用方式：在回复中输出 [action:预设名]，服务端会展开为该预设的原始标签序列。"
)


def _agent_id() -> str:
    """获取当前请求上下文的 agent_id（contextvar 默认 'default'）。"""
    return get_current_agent_id()


def save_emotion_preset(
    name: str = None,
    text: str = None,
    speed: float = None,
    volume: float = None,
    description: str = "",
    # 别名参数（兼容模型不同调用方式）
    tone: str = None,
) -> Dict[str, Any]:
    """保存情感TTS预设（语气描述 + 语速 + 音量），name 重复时原子覆盖。"""
    text = text or tone
    if not name:
        return {"error": "预设名 name 不能为空"}
    if not text:
        return {"error": "语气描述 text 不能为空"}

    agent_id = _agent_id()
    try:
        preset = preset_service.save_emotion_preset(
            agent_id=agent_id,
            name=name,
            text=text,
            speed=speed,
            volume=volume,
            description=description or "",
        )
        return {
            "status": "success",
            "message": f"情感预设「{name}」已保存",
            "preset": preset,
            "usage": _EMOTION_USAGE_HINT,
        }
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        logger.error(f"保存情感预设失败: {e}")
        return {"error": f"保存情感预设失败: {str(e)}"}


def save_action_preset(
    name: str = None,
    tags: List[str] = None,
    description: str = "",
) -> Dict[str, Any]:
    """保存动作预设（标签序列），name 重复时原子覆盖。"""
    if not name:
        return {"error": "预设名 name 不能为空"}
    if not tags:
        return {"error": "tags 不能为空（须为 [\"[emotion:happy]\", ...] 形式的标签数组）"}

    agent_id = _agent_id()
    try:
        preset = preset_service.save_action_preset(
            agent_id=agent_id,
            name=name,
            tags=tags,
            description=description or "",
        )
        return {
            "status": "success",
            "message": f"动作预设「{name}」已保存",
            "preset": preset,
            "usage": _ACTION_USAGE_HINT,
        }
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        logger.error(f"保存动作预设失败: {e}")
        return {"error": f"保存动作预设失败: {str(e)}"}


def list_presets(kind: str = None) -> Dict[str, Any]:
    """列出当前 Agent 的预设清单（name + 描述 + 引用写法）。

    Args:
        kind: 可选筛选 "emotion"（情感TTS预设）或 "action"（动作预设），缺省返回两类。
    """
    agent_id = _agent_id()
    try:
        if kind == preset_service.KIND_EMOTION:
            emotion = preset_service.list_emotion_presets(agent_id)
            action = None
        elif kind == preset_service.KIND_ACTION:
            emotion = None
            action = preset_service.list_action_presets(agent_id)
        elif kind in (None, ""):
            both = preset_service.list_all_presets(agent_id)
            emotion, action = both[preset_service.KIND_EMOTION], both[preset_service.KIND_ACTION]
        else:
            return {"error": f"非法 kind: {kind!r}（须为 'emotion' / 'action' / 缺省）"}

        def _brief(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return [
                {
                    "name": p.get("name", ""),
                    "description": p.get("description", ""),
                }
                for p in items
            ]

        result: Dict[str, Any] = {"status": "success", "agent_id": agent_id}
        if emotion is not None:
            result["emotion_presets"] = _brief(emotion)
            result["emotion_usage"] = _EMOTION_USAGE_HINT
        if action is not None:
            result["action_presets"] = _brief(action)
            result["action_usage"] = _ACTION_USAGE_HINT
        return result
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        logger.error(f"列出预设失败: {e}")
        return {"error": f"列出预设失败: {str(e)}"}


def delete_preset(kind: str = None, name: str = None) -> Dict[str, Any]:
    """删除当前 Agent 的指定预设。

    Args:
        kind: "emotion"（情感TTS预设）或 "action"（动作预设）。
        name: 要删除的预设名。
    """
    if kind not in (preset_service.KIND_EMOTION, preset_service.KIND_ACTION):
        return {"error": f"非法 kind: {kind!r}（须为 'emotion' 或 'action'）"}
    if not name:
        return {"error": "预设名 name 不能为空"}

    agent_id = _agent_id()
    try:
        if kind == preset_service.KIND_EMOTION:
            removed = preset_service.delete_emotion_preset(agent_id, name)
        else:
            removed = preset_service.delete_action_preset(agent_id, name)
        if removed:
            return {"status": "success", "message": f"{kind} 预设「{name}」已删除"}
        return {"status": "not_found", "error": f"{kind} 预设「{name}」不存在"}
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001
        logger.error(f"删除预设失败: {e}")
        return {"error": f"删除预设失败: {str(e)}"}


def register_preset_tools():
    """注册所有预设工具（主模型可用；在 main.py lifespan 中调用）。"""

    # 1. save_emotion_preset - 保存情感TTS预设
    tool_registry.register(
        name="save_emotion_preset",
        description=(
            "保存一个情感TTS预设（快捷指令）：语气描述 text + 可选语速 speed(0.5~2.0) 与"
            "音量 volume(0.1~2.0)。同名预设会被覆盖。"
            + _EMOTION_USAGE_HINT
            + "适合把你常用的语气组合（如『元气满满、语速稍快』）沉淀为可复用预设。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "预设名（唯一，≤50字符，如「元气满满」）"},
                "text": {
                    "type": "string",
                    "description": "语气描述（≤200字符，如「元气满满、活泼开朗、语速稍快」）",
                },
                "speed": {
                    "type": "number",
                    "description": "语速（0.5~2.0，缺省 1.0）",
                    "default": 1.0,
                },
                "volume": {
                    "type": "number",
                    "description": "音量（0.1~2.0，缺省 1.0）",
                    "default": 1.0,
                },
                "description": {"type": "string", "description": "一句话描述（帮助日后挑选）"},
            },
            "required": ["name", "text"],
        },
        function=save_emotion_preset,
        category="preset",
        tags=["preset", "tts", "emotion", "save"],
        examples=[
            "保存一个叫「元气满满」的情感预设：语气元气活泼，语速1.2",
            "把「温柔低语」存为预设，方便以后用",
        ],
    )

    # 2. save_action_preset - 保存动作预设
    tool_registry.register(
        name="save_action_preset",
        description=(
            "保存一个动作预设（快捷指令）：一组标签的序列 tags，每项须为 \"[...]\" 标签形式"
            "（如 [\"[emotion:happy]\", \"[action:wave]\"]）。同名预设会被覆盖。"
            + _ACTION_USAGE_HINT
            + "适合把常用动作组合（如『开心挥手打招呼』）沉淀为可复用预设。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "预设名（唯一，≤50字符，如「打招呼」）"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签序列数组，每项须为 \"[...]\" 形式（如 \"[emotion:happy]\"）",
                },
                "description": {"type": "string", "description": "一句话描述（帮助日后挑选）"},
            },
            "required": ["name", "tags"],
        },
        function=save_action_preset,
        category="preset",
        tags=["preset", "action", "save"],
        examples=[
            "保存一个叫「打招呼」的动作预设：开心并挥手",
            "把「开心挥手」组合存为动作预设",
        ],
    )

    # 3. list_presets - 查询预设清单
    tool_registry.register(
        name="list_presets",
        description=(
            "查询当前 Agent 已保存的预设清单（名称+描述+引用写法提示）。"
            "kind 缺省返回两类：emotion=情感TTS预设（用 <tts_instruction>{\"preset\":\"名\"}"
            "</tts_instruction> 在回复最前面引用），action=动作预设（用 [action:名] 在回复中引用）。"
            "回复用户『你有哪些预设』或挑选预设前先调用本工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["emotion", "action"],
                    "description": "预设类别筛选（缺省返回两类）",
                    "default": None,
                },
            },
            "required": [],
        },
        function=list_presets,
        category="preset",
        tags=["preset", "list", "query"],
        examples=["我有哪些预设？", "列出动作预设", "看看可用的快捷指令"],
    )

    # 4. delete_preset - 删除预设
    tool_registry.register(
        name="delete_preset",
        description=(
            "删除当前 Agent 的一个预设。kind 须为 'emotion'（情感TTS预设）或"
            " 'action'（动作预设），name 为预设名。删除前建议先用 list_presets 确认存在。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["emotion", "action"],
                    "description": "预设类别",
                },
                "name": {"type": "string", "description": "要删除的预设名"},
            },
            "required": ["kind", "name"],
        },
        function=delete_preset,
        category="preset",
        tags=["preset", "delete"],
        examples=["删除「打招呼」这个动作预设", "把「温柔低语」预设删掉"],
    )
