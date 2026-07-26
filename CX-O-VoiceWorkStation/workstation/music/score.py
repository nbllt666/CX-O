"""
歌谱数据模型与 JSON Schema 校验模块（歌谱契约 v2，MAJOR 2.0.0）

歌谱以 dict 为载体（JSON Schema 直接校验），dataclass 提供类型化模型。
规范化后的歌谱 v2 dict 字段：
- title: 歌名
- bpm: 每分钟拍数（>0）
- time_signature: 拍号（默认 "4/4"）
- key: 调号（默认 "C"）
- melody: [{pitch, beats, lyric}]，pitch 为科学音高记谱（如 C4/A#3/Bb5），beats>0，lyric 允许空串
- chords: [{chord, beats}]，允许空数组
- accompaniment_tracks: [{id, name, program, mode, style, volume, pan, events}]，允许空数组；
  program=-1 表示打击乐轨（events.pitch 为 GM 鼓键名，解析见 inventory.resolve_drum_key）

v1 → v2 迁移（score-v2.schema.json x-migration）：
- 触发：输入含 accompaniment_style 且不含 accompaniment_tracks（判定为 v1）
- 规则：生成首条 auto 钢琴轨（style 映射：piano→block_chords，其余原样保留），
  随后删除 accompaniment_style；chords/melody 原样保留
- OBS-3 边界（GN-004 复审注记）：v1 裸 dict 缺 accompaniment_style 时不触发迁移——
  此时按 v2 校验，accompaniment_tracks 落默认值 []；与 v1 默认填充 "piano" 的行为差异
  属预期契约演进，在本模块测试与 docstring 中显式锚定
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from jsonschema import Draft7Validator, validators

from workstation.music.inventory import resolve_drum_key

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
class TrackNoteEvent:
    """伴奏轨音符事件：音高（科学音高记谱或 GM 鼓键名）+ 节拍 + 显式定位 + 力度"""

    pitch: str
    beats: float
    offset: float
    velocity: int = 64


@dataclass
class AccompanimentTrack:
    """伴奏轨模型，字段与 score v2 accompaniment_tracks[] 元素一一对应"""

    id: str
    name: str
    program: int  # GM 音色号 0–127；-1=打击乐轨
    mode: str  # "auto" | "manual"
    style: str = ""
    volume: int = 100
    pan: int = 64
    events: list[TrackNoteEvent] = field(default_factory=list)


@dataclass
class Score:
    """歌谱 v2 模型，字段与 SCORE_SCHEMA_V2 一一对应"""

    title: str
    bpm: float
    melody: list[NoteEvent] = field(default_factory=list)
    time_signature: str = "4/4"
    key: str = "C"
    chords: list[ChordEvent] = field(default_factory=list)
    accompaniment_tracks: list[AccompanimentTrack] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Score":
        """
        由歌谱 dict 构造 Score（调用前应先通过 validate_score）。

        v1 输入兼容：内部先经 migrate_v1_to_v2 迁移再按 v2 构造。
        """
        migrated = migrate_v1_to_v2(data)
        return cls(
            title=migrated["title"],
            bpm=migrated["bpm"],
            time_signature=migrated.get("time_signature", "4/4"),
            key=migrated.get("key", "C"),
            melody=[
                NoteEvent(pitch=n["pitch"], beats=n["beats"], lyric=n.get("lyric", ""))
                for n in migrated.get("melody", [])
            ],
            chords=[
                ChordEvent(chord=c["chord"], beats=c["beats"])
                for c in migrated.get("chords", [])
            ],
            accompaniment_tracks=[
                AccompanimentTrack(
                    id=t["id"],
                    name=t["name"],
                    program=t.get("program", 0),
                    mode=t.get("mode", "manual"),
                    style=t.get("style", ""),
                    volume=t.get("volume", 100),
                    pan=t.get("pan", 64),
                    events=[
                        TrackNoteEvent(
                            pitch=e["pitch"],
                            beats=e["beats"],
                            offset=e["offset"],
                            velocity=e.get("velocity", 64),
                        )
                        for e in t.get("events", [])
                    ],
                )
                for t in migrated.get("accompaniment_tracks", [])
            ],
        )

    def to_dict(self) -> dict:
        """导出为规范化歌谱 v2 dict（v1 字段 accompaniment_style 不再出现）"""
        return {
            "title": self.title,
            "bpm": self.bpm,
            "time_signature": self.time_signature,
            "key": self.key,
            "melody": [
                {"pitch": n.pitch, "beats": n.beats, "lyric": n.lyric} for n in self.melody
            ],
            "chords": [{"chord": c.chord, "beats": c.beats} for c in self.chords],
            "accompaniment_tracks": [
                {
                    "id": t.id,
                    "name": t.name,
                    "program": t.program,
                    "mode": t.mode,
                    "style": t.style,
                    "volume": t.volume,
                    "pan": t.pan,
                    "events": [
                        {
                            "pitch": e.pitch,
                            "beats": e.beats,
                            "offset": e.offset,
                            "velocity": e.velocity,
                        }
                        for e in t.events
                    ],
                }
                for t in self.accompaniment_tracks
            ],
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

# 歌谱 v2 JSON Schema（draft-07，MAJOR 2.0.0）。
# 内容与冻结契约 .trae/specs/redesign-composition-staff-editor/contracts/score-v2.schema.json
# 逐字节一致（含 x-version/x-changelog/x-migration 注解字段）；契约冻结，禁止手改，
# 变更走 s0601。tests/test_score.py 以契约文件加载比对防漂移。
SCORE_SCHEMA_V2: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "VoiceWorkStation 歌谱契约 v2",
    "x-version": "2.0.0",
    "x-changelog": "MAJOR 2.0.0：新增 accompaniment_tracks[]（多乐器伴奏轨）；移除 accompaniment_style（v1 读取时自动迁移，迁移后该字段不再出现）。迁移规则见 x-migration 与 contracts/README.md。",
    "x-migration": {
        "from": "1.0.0",
        "trigger": "输入含 accompaniment_style 且不含 accompaniment_tracks 时判定为 v1",
        "rule": "生成首条 auto 模式钢琴轨 {id: \"trk_0\", name: \"钢琴\", program: 0, mode: \"auto\", style: <accompaniment_style 映射，piano→block_chords，其余原样保留>, volume: 100, pan: 64, events: []}，随后删除 accompaniment_style 字段；chords/melody 原样保留",
        "executor": "validate_score 前置执行（幂等纯函数，对调用方透明）；已含 accompaniment_tracks 的输入不触发迁移",
        "submission": "合成提交路径只接受 v2（经迁移规范化后的结果）",
    },
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
            "description": "主旋律音符序列（至少一个音符）。旋律轨为逐字歌词轨，事件按顺序累加定位（无 offset 字段），与伴奏轨事件的显式 offset 定位不同",
            "items": {
                "type": "object",
                "required": ["pitch", "beats"],
                "properties": {
                    "pitch": {
                        "type": "string",
                        "description": "科学音高记谱，如 C4、A#3、Bb5（C4=60）",
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
            "description": "和弦骨架（和声进行），允许为空数组。用途：①auto 模式伴奏轨的生成源；②谱面上排的和弦标记",
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
        "accompaniment_tracks": {
            "type": "array",
            "default": [],
            "description": "多乐器伴奏轨列表，允许为空数组（纯主旋律）。同一歌谱内各轨 id 必须唯一（JSON Schema 无法表达数组内字段唯一性，由 validate_score 在结构校验后追加唯一性检查）",
            "items": {
                "type": "object",
                "required": ["id", "name", "program", "mode"],
                "properties": {
                    "id": {
                        "type": "string",
                        "pattern": "^[a-z0-9_]+$",
                        "description": "轨道稳定标识，草稿内唯一，小写字母/数字/下划线；编辑命令按 id 寻址",
                    },
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "轨道显示名（谱表左侧标签）",
                    },
                    "program": {
                        "type": "integer",
                        "minimum": -1,
                        "maximum": 127,
                        "default": 0,
                        "description": "General MIDI 音色号 0–127；特殊值 -1 表示打击乐轨（渲染时全部事件强制走通道 9，不写 program change，events.pitch 使用 GM 鼓键名，鼓键名枚举见 music-inventory.schema.json）",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "manual"],
                        "default": "manual",
                        "description": "auto=按和弦骨架+节奏型自动生成音符（生成结果可物化后逐音符微调）；manual=逐音符编辑",
                    },
                    "style": {
                        "type": "string",
                        "default": "",
                        "description": "编排节奏型 id，仅 auto 模式有效（manual 模式忽略）。当前枚举：block_chords（柱式和弦）/arpeggio（八分分解）/root_eighth（根音八分）/rock_4beat（鼓组四拍型），枚举真源见 music-inventory.schema.json，可扩展（扩展属数据层变更，不改本 schema）。auto 模式下 style 为空串时回退默认：program=-1 → rock_4beat，其余 → block_chords",
                    },
                    "volume": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 127,
                        "default": 100,
                        "description": "轨道音量，GM 原生量纲 0–127，渲染时直写 MIDI CC7",
                    },
                    "pan": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 127,
                        "default": 64,
                        "description": "轨道声像，GM 原生量纲 0–127（64=中央），渲染时直写 MIDI CC10",
                    },
                    "events": {
                        "type": "array",
                        "default": [],
                        "description": "轨道音符事件列表，按 offset 升序排列，重叠事件即同度和音。auto 模式下为空数组（合成/编排时由 arranger 按 chords+style 生成；arrange_track 命令可将生成结果物化写入本字段以便逐音符微调）",
                        "items": {
                            "type": "object",
                            "required": ["pitch", "beats", "offset"],
                            "properties": {
                                "pitch": {
                                    "type": "string",
                                    "description": "音高。program≥0 时为科学音高记谱（如 C2、G2）；program=-1（打击乐轨）时为 GM 鼓键名（如 kick、snare，枚举别名见 music-inventory.schema.json，底层映射 MIDI 音号）",
                                },
                                "beats": {
                                    "type": "number",
                                    "exclusiveMinimum": 0,
                                    "description": "持续节拍数（四分音符=1 拍），必须大于 0",
                                },
                                "offset": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "相对轨道起点的拍数位置（显式定位，允许休止与对位空隙）",
                                },
                                "velocity": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 127,
                                    "default": 64,
                                    "description": "力度（MIDI velocity 1–127）",
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}

# 向后兼容别名（v1 常量不再单独保留；v1 输入由 migrate_v1_to_v2 处理）。
# 注意：cxfc_plugin.py 的 music_validate_score / music_sing 工具 parameters.score
# 经本别名引用，SCORE_SCHEMA 升级为 v2 后工具参数面即变为 v2——这是冻结契约的预期行为。
SCORE_SCHEMA = SCORE_SCHEMA_V2


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


# ---------------------------------------------------------------------------
# v1 → v2 迁移
# ---------------------------------------------------------------------------

# v1 accompaniment_style → v2 style 映射：piano→block_chords，其余原样保留
_V1_STYLE_MAP = {"piano": "block_chords"}


def migrate_v1_to_v2(data: dict) -> dict:
    """
    v1 → v2 迁移（幂等纯函数，深拷贝，不污染入参）。

    触发条件：含 accompaniment_style 且不含 accompaniment_tracks。
    规则：生成首条 auto 模式钢琴轨 {id: "trk_0", name: "钢琴", program: 0,
    mode: "auto", style: <accompaniment_style 映射，piano→block_chords，其余原样保留>,
    volume: 100, pan: 64, events: []}，随后删除 accompaniment_style 字段；
    chords/melody 原样保留。

    OBS-3 边界：v1 裸 dict 缺 accompaniment_style 时不触发迁移——该输入按 v2
    校验处理，accompaniment_tracks 由结构校验填充默认值 []（与 v1 默认填充
    accompaniment_style="piano" 不同，属预期契约演进）。

    Args:
        data: 待迁移歌谱 dict（v1 或 v2）

    Returns:
        迁移后的 v2 歌谱 dict；v2 输入（含 accompaniment_tracks）原样深拷贝返回

    Raises:
        无（纯字段变换，不校验结构合法性——校验由 validate_score 负责）
    """
    result = copy.deepcopy(data)
    if not isinstance(result, dict):
        return result
    if "accompaniment_style" in result and "accompaniment_tracks" not in result:
        style = result.pop("accompaniment_style")
        result["accompaniment_tracks"] = [
            {
                "id": "trk_0",
                "name": "钢琴",
                "program": 0,
                "mode": "auto",
                "style": _V1_STYLE_MAP.get(style, style),
                "volume": 100,
                "pan": 64,
                "events": [],
            }
        ]
    return result


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def validate_score(data: dict) -> tuple[bool, list[str], Optional[dict]]:
    """
    校验歌谱并规范化（v1 输入自动迁移 → v2，填充默认值）。

    流程：migrate_v1_to_v2（幂等，v2 输入原样通过）→ 深拷贝 + default 填充的
    Draft7 结构校验 → 追加校验：
      ① melody 与每轨 events 逐音符 pitch 合法性（program≥0 轨用 pitch_to_midi；
         program=-1 打击乐轨用 inventory.resolve_drum_key 鼓键名解析）
      ② accompaniment_tracks 各轨 id 草稿内唯一性
      ③ 打击乐轨 events.pitch 必须是合法鼓键名（或别名）

    Args:
        data: 待校验的歌谱 dict（v1 或 v2）

    Returns:
        (是否合法, 逐条可读错误列表（含字段定位）, 规范化后的 v2 歌谱；不合法时为 None)
    """
    if not isinstance(data, dict):
        return False, ["$: 歌谱必须是 JSON 对象"], None

    # v1 → v2 迁移（migrate 内部已深拷贝，不污染调用方数据）
    normalized = migrate_v1_to_v2(data)
    errors: list[str] = []

    validator = _DefaultFillingValidator(SCORE_SCHEMA_V2)
    raw_errors = sorted(validator.iter_errors(normalized), key=lambda e: list(e.absolute_path))
    for err in raw_errors:
        errors.append(f"{_format_error_path(err)}: {err.message}")

    if errors:
        return False, errors, None

    # 追加校验①：melody 逐音符音高（pitch_to_midi 抛 ValueError，由校验层捕获）
    for idx, note in enumerate(normalized.get("melody", [])):
        try:
            pitch_to_midi(note.get("pitch", ""))
        except ValueError as exc:
            errors.append(f"melody[{idx}].pitch: {exc}")

    # 追加校验②③：轨 id 唯一性 + 轨 events 逐音符音高/鼓键名合法性
    seen_track_ids: set[str] = set()
    for track_idx, track in enumerate(normalized.get("accompaniment_tracks", [])):
        track_id = track.get("id", "")
        if track_id in seen_track_ids:
            errors.append(
                f"accompaniment_tracks[{track_idx}].id: 轨道 id 重复: {track_id!r}"
                "（同一歌谱内各轨 id 必须唯一）"
            )
        seen_track_ids.add(track_id)

        is_drum_track = track.get("program", 0) == -1
        for event_idx, event in enumerate(track.get("events", [])):
            pitch = event.get("pitch", "")
            try:
                if is_drum_track:
                    resolve_drum_key(pitch)
                else:
                    pitch_to_midi(pitch)
            except ValueError as exc:
                errors.append(
                    f"accompaniment_tracks[{track_idx}].events[{event_idx}].pitch: {exc}"
                )

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
