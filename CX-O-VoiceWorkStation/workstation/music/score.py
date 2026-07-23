"""
歌谱数据模型与 JSON Schema 校验模块

歌谱以 dict 为载体（JSON Schema 直接校验），dataclass 提供类型化模型。
规范化后的歌谱 dict 字段：
- title: 歌名
- bpm: 每分钟拍数（>0）
- time_signature: 拍号（默认 "4/4"）
- key: 调号（默认 "C"）
- melody: [{pitch, beats, lyric}]，pitch 为科学音高记谱（如 C4/A#3/Bb5），beats>0，lyric 允许空串
- chords: [{chord, beats}]，允许空数组
- accompaniment_style: 伴奏风格（默认 "piano"）
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from jsonschema import Draft7Validator, validators

# ---------------------------------------------------------------------------
# 数据模型（dataclass，与项目现有风格一致）
# ---------------------------------------------------------------------------


@dataclass
class NoteEvent:
    """旋律音符事件：音高 + 节拍数 + 逐字歌词（空串表示延音）"""

    pitch: str
    beats: float
    lyric: str = ""


@dataclass
class ChordEvent:
    """和弦事件：和弦标记 + 持续节拍数"""

    chord: str
    beats: float


@dataclass
class Score:
    """歌谱模型，字段与 SCORE_SCHEMA 一一对应"""

    title: str
    bpm: float
    melody: list[NoteEvent] = field(default_factory=list)
    time_signature: str = "4/4"
    key: str = "C"
    chords: list[ChordEvent] = field(default_factory=list)
    accompaniment_style: str = "piano"

    @classmethod
    def from_dict(cls, data: dict) -> "Score":
        """由规范化后的歌谱 dict 构造 Score（调用前应先通过 validate_score）"""
        return cls(
            title=data["title"],
            bpm=data["bpm"],
            time_signature=data.get("time_signature", "4/4"),
            key=data.get("key", "C"),
            melody=[
                NoteEvent(pitch=n["pitch"], beats=n["beats"], lyric=n.get("lyric", ""))
                for n in data.get("melody", [])
            ],
            chords=[ChordEvent(chord=c["chord"], beats=c["beats"]) for c in data.get("chords", [])],
            accompaniment_style=data.get("accompaniment_style", "piano"),
        )

    def to_dict(self) -> dict:
        """导出为规范化歌谱 dict"""
        return {
            "title": self.title,
            "bpm": self.bpm,
            "time_signature": self.time_signature,
            "key": self.key,
            "melody": [
                {"pitch": n.pitch, "beats": n.beats, "lyric": n.lyric} for n in self.melody
            ],
            "chords": [{"chord": c.chord, "beats": c.beats} for c in self.chords],
            "accompaniment_style": self.accompaniment_style,
        }


# ---------------------------------------------------------------------------
# 音高换算
# ---------------------------------------------------------------------------

# 音名 → 半音偏移（以 C 为 0）
_PITCH_BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# 科学音高记谱：音名 + 可选升降号(#/b) + 八度（可为负），如 C4 / A#3 / Bb5
_PITCH_PATTERN = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")


def pitch_to_midi(pitch: str) -> int:
    """
    科学音高记谱转 MIDI 音号（约定 C4 = 60）。

    支持写法：C4、A#3、Bb5（# 升半音，b 降半音，八度可为负数）。

    Args:
        pitch: 音高字符串

    Returns:
        MIDI 音号

    Raises:
        ValueError: 音高格式非法时
    """
    if not isinstance(pitch, str):
        raise ValueError(f"非法音高记谱: {pitch!r}（必须是字符串）")
    match = _PITCH_PATTERN.match(pitch.strip())
    if not match:
        raise ValueError(f"非法音高记谱: {pitch!r}（期望形如 C4 / A#3 / Bb5）")
    name, accidental, octave_str = match.groups()
    semitone = _PITCH_BASE[name.upper()]
    if accidental == "#":
        semitone += 1
    elif accidental == "b":
        semitone -= 1
    octave = int(octave_str)
    return (octave + 1) * 12 + semitone


# ---------------------------------------------------------------------------
# JSON Schema 与校验
# ---------------------------------------------------------------------------

# 歌谱 JSON Schema（draft-07）。规范：字段含类型/取值范围/必填性/默认值/描述。
SCORE_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "VoiceWorkStation 歌谱",
    "type": "object",
    "required": ["title", "bpm", "melody"],
    "properties": {
        "title": {"type": "string", "minLength": 1, "description": "歌名"},
        "bpm": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "每分钟拍数，必须大于 0",
        },
        "time_signature": {
            "type": "string",
            "default": "4/4",
            "pattern": "^\\d+/\\d+$",
            "description": "拍号，如 4/4、3/4、6/8",
        },
        "key": {
            "type": "string",
            "minLength": 1,
            "default": "C",
            "description": "调号，如 C、G、Am",
        },
        "melody": {
            "type": "array",
            "minItems": 1,
            "description": "旋律音符序列（至少一个音符）",
            "items": {
                "type": "object",
                "required": ["pitch", "beats"],
                "properties": {
                    "pitch": {
                        "type": "string",
                        "description": "科学音高记谱，如 C4、A#3、Bb5",
                    },
                    "beats": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "description": "节拍数（四分音符=1 拍），必须大于 0",
                    },
                    "lyric": {
                        "type": "string",
                        "default": "",
                        "description": "逐字歌词，空串表示延音",
                    },
                },
                "additionalProperties": False,
            },
        },
        "chords": {
            "type": "array",
            "default": [],
            "description": "和弦轨，允许为空数组（仅主旋律）",
            "items": {
                "type": "object",
                "required": ["chord", "beats"],
                "properties": {
                    "chord": {
                        "type": "string",
                        "minLength": 1,
                        "description": "和弦标记，如 C、G7、Am",
                    },
                    "beats": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "description": "持续节拍数，必须大于 0",
                    },
                },
                "additionalProperties": False,
            },
        },
        "accompaniment_style": {
            "type": "string",
            "default": "piano",
            "description": "伴奏风格",
        },
    },
    "additionalProperties": False,
}


def _extend_with_default(validator_class: type) -> type:
    """扩展 jsonschema 校验器：校验过程中将 schema default 填充进实例（规范化）"""
    validate_properties = validator_class.VALIDATORS["properties"]

    def set_defaults(validator, properties, instance, schema):
        if isinstance(instance, dict):
            for prop, subschema in properties.items():
                if "default" in subschema:
                    instance.setdefault(prop, subschema["default"])
        yield from validate_properties(validator, properties, instance, schema)

    return validators.extend(validator_class, {"properties": set_defaults})


# 带默认值填充能力的 draft-07 校验器（嵌套对象的 default 同样生效）
_DefaultFillingValidator = _extend_with_default(Draft7Validator)


def _format_error_path(err: Any) -> str:
    """将 jsonschema 错误的 absolute_path 格式化为可读字段定位，如 melody[0].beats"""
    parts: list[str] = []
    for node in err.absolute_path:
        if isinstance(node, int):
            parts.append(f"[{node}]")
        elif parts:
            parts.append(f".{node}")
        else:
            parts.append(str(node))
    return "".join(parts) if parts else "$"


def validate_score(data: dict) -> tuple[bool, list[str], Optional[dict]]:
    """
    校验歌谱 JSON 并规范化（填充默认值）。

    Args:
        data: 待校验的歌谱 dict

    Returns:
        (是否合法, 逐条可读错误列表（含字段定位）, 规范化后的歌谱 dict；不合法时为 None)
    """
    if not isinstance(data, dict):
        return False, ["$: 歌谱必须是 JSON 对象"], None

    # 深拷贝后在校验过程中填充默认值，避免污染调用方数据
    normalized = copy.deepcopy(data)
    errors: list[str] = []

    validator = _DefaultFillingValidator(SCORE_SCHEMA)
    raw_errors = sorted(validator.iter_errors(normalized), key=lambda e: list(e.absolute_path))
    for err in raw_errors:
        errors.append(f"{_format_error_path(err)}: {err.message}")

    if errors:
        return False, errors, None

    # 结构合法后再逐音符校验音高（pitch_to_midi 抛 ValueError，由校验层捕获）
    for idx, note in enumerate(normalized.get("melody", [])):
        try:
            pitch_to_midi(note.get("pitch", ""))
        except ValueError as exc:
            errors.append(f"melody[{idx}].pitch: {exc}")

    if errors:
        return False, errors, None
    return True, [], normalized


def total_beats(score: dict) -> float:
    """
    计算歌谱总节拍数（按旋律轨累加，四分音符=1 拍）。

    Args:
        score: 规范化后的歌谱 dict

    Returns:
        旋律总节拍数
    """
    return float(sum(note.get("beats", 0.0) for note in score.get("melody", [])))
