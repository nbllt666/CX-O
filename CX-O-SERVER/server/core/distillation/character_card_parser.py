"""SillyTavern 角色卡解析器（CX-O 迁移版，无改动）。

支持 PNG（tEXt chunk 隐写）和 JSON（V1/V2/V3 规范）两种格式，
兼容非标准角色卡（字段不完整或含额外字段）。

规范参考:
    - V3: spec="chara_card_v3", data 嵌套
    - V2: spec="chara_card_v2", data 嵌套
    - V1: 扁平化 JSON，无 spec/data
    - PNG: tEXt chunk 关键字 "chara_card_v3"（V3）或 "chara"（V2），V3 优先

从 CXHMS modules/模块9_蒸馏服务/character_card_parser.py 迁移，
纯解析逻辑无外部依赖，保持原实现。

@version 1.0.0
"""

import base64
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 标准字段定义（SillyTavern V2/V3 规范）
# --------------------------------------------------------------------------- #

# 角色卡标准字段（V2/V3 data 内的合法字段）
_STANDARD_FIELDS: Dict[str, str] = {
    "name": "角色名",
    "description": "描述",
    "personality": "性格",
    "scenario": "场景",
    "first_mes": "开场白",
    "mes_example": "对话示例",
    "alternate_greetings": "备选问候语",
    "creator_notes": "创作者备注",
    "system_prompt": "系统提示",
    "post_history_instructions": "历史后指令",
    "character_book": "角色书",
    "extensions": "扩展",
}

# spec/spec_version 为元数据字段，不算标准内容字段
_META_FIELDS = {"spec", "spec_version"}

# PNG tEXt chunk 关键字（按优先级排序，V3 优先）
_PNG_TEXT_KEYS = ("chara_card_v3", "chara")


# --------------------------------------------------------------------------- #
# PNG 角色卡解析
# --------------------------------------------------------------------------- #


def parse_png_character_card(file_bytes: bytes) -> Dict[str, Any]:
    """解析 PNG 角色卡，从 tEXt chunk 提取角色卡 JSON 数据。

    SillyTavern 角色卡 PNG 使用 tEXt chunk 嵌入 JSON：
    - V3 关键字: "chara_card_v3"
    - V2 关键字: "chara"
    V3 优先于 V2。

    Args:
        file_bytes: PNG 文件二进制数据

    Returns:
        Dict[str, Any]: 角色卡原始数据（未规范化）

    Raises:
        ValueError: PNG 解析失败或未找到角色卡数据
    """
    try:
        from PIL import Image
        import io
    except ImportError as e:
        raise ValueError(f"Pillow 未安装: {e}") from e

    try:
        img = Image.open(io.BytesIO(file_bytes))
    except Exception as e:
        raise ValueError(f"PNG 文件解析失败: {e}") from e

    # Pillow 的 img.info 包含 tEXt chunk 数据
    text_chunks: Dict[str, str] = dict(img.info or {})

    # 按优先级查找角色卡数据
    raw_json: Optional[str] = None
    used_key: Optional[str] = None
    for key in _PNG_TEXT_KEYS:
        if key in text_chunks:
            raw_json = text_chunks[key]
            used_key = key
            break

    if raw_json is None:
        raise ValueError(
            "PNG 文件中未找到角色卡数据（tEXt chunk 无 chara/chara_card_v3 关键字）"
        )

    logger.info(f"PNG 角色卡使用 tEXt 关键字: {used_key}")

    # JSON 数据可能是 UTF-8 字符串或 base64 编码
    card_data = _decode_card_json(raw_json)
    return card_data


def _decode_card_json(raw: str) -> Dict[str, Any]:
    """解码角色卡 JSON 数据（兼容 UTF-8 字符串和 base64 编码）。

    Args:
        raw: 原始字符串

    Returns:
        Dict[str, Any]: 解析后的 JSON 数据

    Raises:
        ValueError: JSON 解析失败
    """
    # 先尝试直接解析（UTF-8 字符串）
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # 尝试 base64 解码
    try:
        decoded = base64.b64decode(raw, validate=True)
        data = json.loads(decoded.decode("utf-8"))
        if isinstance(data, dict):
            return data
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        pass

    raise ValueError(
        "角色卡 JSON 解析失败（既不是有效 JSON 也不是 base64 编码的 JSON）"
    )


# --------------------------------------------------------------------------- #
# JSON 角色卡解析
# --------------------------------------------------------------------------- #


def parse_json_character_card(json_str: str) -> Dict[str, Any]:
    """解析 JSON 格式角色卡，适配 V1/V2/V3 规范。

    Args:
        json_str: JSON 字符串

    Returns:
        Dict[str, Any]: 角色卡原始数据（未规范化）

    Raises:
        ValueError: JSON 解析失败
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层应为对象，实际为 {type(data).__name__}")

    return data


# --------------------------------------------------------------------------- #
# 规范化（统一结构 + 非标准字段保留）
# --------------------------------------------------------------------------- #


def normalize_character_card(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """将角色卡原始数据规范化为统一结构。

    适配 V1（扁平化）、V2/V3（data 嵌套）格式，提取标准字段到顶层，
    非标准字段保留到 extra_fields。

    Args:
        raw_data: 角色卡原始数据

    Returns:
        Dict[str, Any]: 规范化后的角色卡数据，结构:
            {
                "spec": "chara_card_v3" | "chara_card_v2" | "v1_legacy",
                "spec_version": str,
                "name": str,  # 必填，缺失时默认 "未命名角色"
                "description": str,
                "personality": str,
                "scenario": str,
                "first_mes": str,
                "mes_example": str,
                "alternate_greetings": List[str],
                "creator_notes": str,
                "system_prompt": str,
                "post_history_instructions": str,
                "character_book": Optional[Dict],
                "extensions": Dict,
                "extra_fields": Dict[str, Any],  # 非标准字段
            }
    """
    # 判断版本：V2/V3 有 spec 字段且 data 嵌套；V1 无 spec，扁平化
    spec = raw_data.get("spec", "")
    has_data = isinstance(raw_data.get("data"), dict)

    if spec in ("chara_card_v3", "chara_card_v2") and has_data:
        # V2/V3 格式：从 data 提取字段
        source = raw_data["data"]
        spec_version = raw_data.get("spec_version", "2.0" if spec == "chara_card_v2" else "3.0")
    elif has_data and not spec:
        # 无 spec 但有 data（部分非标准卡）：从 data 提取
        source = raw_data["data"]
        spec = "unknown"
        spec_version = "unknown"
    else:
        # V1 格式（扁平化）或非标准格式：直接从顶层提取
        source = raw_data
        spec = spec or "v1_legacy"
        spec_version = raw_data.get("spec_version", "1.0")

    # 提取标准字段
    result: Dict[str, Any] = {
        "spec": spec,
        "spec_version": spec_version,
        "name": str(source.get("name") or "未命名角色").strip(),
        "description": str(source.get("description") or "").strip(),
        "personality": str(source.get("personality") or "").strip(),
        "scenario": str(source.get("scenario") or "").strip(),
        "first_mes": str(source.get("first_mes") or "").strip(),
        "mes_example": str(source.get("mes_example") or "").strip(),
        "alternate_greetings": list(source.get("alternate_greetings") or []),
        "creator_notes": str(source.get("creator_notes") or "").strip(),
        "system_prompt": str(source.get("system_prompt") or "").strip(),
        "post_history_instructions": str(source.get("post_history_instructions") or "").strip(),
        "character_book": source.get("character_book"),
        "extensions": dict(source.get("extensions") or {}),
        "extra_fields": {},
    }

    # 收集非标准字段（不在标准字段列表和元数据字段中的字段）
    standard_keys = set(_STANDARD_FIELDS.keys()) | _META_FIELDS
    for key, value in source.items():
        if key not in standard_keys:
            result["extra_fields"][key] = value

    # V2/V3 的 data 外层也可能有非标准字段
    if has_data:
        for key, value in raw_data.items():
            if key not in standard_keys and key != "data":
                result["extra_fields"][f"_top_{key}"] = value

    logger.info(
        f"角色卡规范化完成: name={result['name']}, spec={spec}, "
        f"extra_fields_count={len(result['extra_fields'])}"
    )

    return result


# --------------------------------------------------------------------------- #
# 角色卡 → source_ref 转换
# --------------------------------------------------------------------------- #


def character_card_to_source_ref(card_data: Dict[str, Any]) -> str:
    """将规范化角色卡数据转换为带标签文本（source_ref）。

    转换规则：
    - 标准字段用 "中文字段名: 内容" 格式
    - alternate_greetings 用 "备选问候语 N: ..." 格式
    - character_book 摘要为 "角色书: N 条目"
    - extensions 摘要为 "扩展: key1, key2, ..."
    - extra_fields 用 "额外字段 - 字段名: 内容" 格式
    - 空字段跳过

    Args:
        card_data: 规范化后的角色卡数据

    Returns:
        str: 带标签文本，供蒸馏服务作为 source_ref 使用
    """
    lines: List[str] = []

    # 标准字段（按 SillyTavern 规范顺序）
    field_order = [
        ("name", "角色名"),
        ("description", "描述"),
        ("personality", "性格"),
        ("scenario", "场景"),
        ("first_mes", "开场白"),
        ("mes_example", "对话示例"),
        ("creator_notes", "创作者备注"),
        ("system_prompt", "系统提示"),
        ("post_history_instructions", "历史后指令"),
    ]

    for field_key, label in field_order:
        value = card_data.get(field_key, "")
        if isinstance(value, str):
            value = value.strip()
        if value:
            lines.append(f"{label}: {value}")

    # 备选问候语
    greetings = card_data.get("alternate_greetings") or []
    for i, greeting in enumerate(greetings):
        if greeting and isinstance(greeting, str):
            lines.append(f"备选问候语 {i + 1}: {greeting.strip()}")

    # 角色书（摘要）
    character_book = card_data.get("character_book")
    if character_book and isinstance(character_book, dict):
        entries = character_book.get("entries") or []
        if isinstance(entries, list):
            lines.append(f"角色书: {len(entries)} 条目")
        elif isinstance(entries, dict):
            lines.append(f"角色书: {len(entries)} 条目")

    # 扩展（摘要）
    extensions = card_data.get("extensions") or {}
    if extensions:
        ext_keys = list(extensions.keys())
        lines.append(f"扩展: {', '.join(ext_keys)}")

    # 非标准字段（完整保留）
    extra_fields = card_data.get("extra_fields") or {}
    for key, value in extra_fields.items():
        if value is not None:
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, ensure_ascii=False)
            else:
                value_str = str(value)
            lines.append(f"额外字段 - {key}: {value_str}")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 便捷入口
# --------------------------------------------------------------------------- #


def parse_character_card_from_bytes(file_bytes: bytes, filename: str = "") -> Dict[str, Any]:
    """从文件字节解析角色卡（自动判断 PNG/JSON 格式）。

    Args:
        file_bytes: 文件二进制数据
        filename: 文件名（用于判断格式，可选）

    Returns:
        Dict[str, Any]: 规范化后的角色卡数据

    Raises:
        ValueError: 解析失败
    """
    # 根据文件名后缀判断
    lower_name = filename.lower()
    is_png = lower_name.endswith(".png") or file_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    if is_png:
        raw_data = parse_png_character_card(file_bytes)
    else:
        # 尝试 JSON
        try:
            json_str = file_bytes.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"文件既不是 PNG 也不是有效 UTF-8 文本: {e}") from e
        raw_data = parse_json_character_card(json_str)

    return normalize_character_card(raw_data)


def parse_character_card_from_json_str(json_str: str) -> Dict[str, Any]:
    """从 JSON 字符串解析角色卡。

    Args:
        json_str: JSON 字符串

    Returns:
        Dict[str, Any]: 规范化后的角色卡数据

    Raises:
        ValueError: 解析失败
    """
    raw_data = parse_json_character_card(json_str)
    return normalize_character_card(raw_data)
