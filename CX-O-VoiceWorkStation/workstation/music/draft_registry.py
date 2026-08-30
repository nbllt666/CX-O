"""
草稿命令总线（模块3_草稿命令总线 · 新增）

实现 voicews_music.pyi 模块4 draft_registry 全部公开签名：
- DraftState TypedDict（内存注册表条目）
- create_draft / execute_command / get_draft / list_drafts
- delete_draft / submit_draft / sweep_expired_drafts
- load_draft（启动恢复 / 测试载入辅助；非 .pyi 公开契约，供注册表冷启动与单测断言）

行为基座（merged.md §3-4 + command-protocol.schema.json x-notes）：
- 原子性：args 校验（按 command 分发 args_<command> schema）→ 应用 → 整谱
  validate_score → undo 入栈 → version+1 → 原子落盘；任一步失败整体回滚，
  草稿状态不变，返回 success=false + 对应错误码
- 串行性：模块级单注册表 _REGISTRY，单进程内按草稿串行（无锁，依赖单时钟）
- undo/redo 双栈：before 片段 = 整谱深拷贝（首版粗粒度，简单正确），上限
  undo_stack_limit（默认 100，内存不落盘，重启清空）；空栈空操作 success=true
  + version 不增；任何新编辑命令清空 redo 栈
- 原子落盘：{drafts_dir}/{draft_id}/draft.json，tempfile + os.replace
- TTL 清扫：按 updated_at 计算，draft_ttl_days 默认 7，0=不清扫

边界（AGENTS.md §2-3）：
- arrange_track 延迟导入 arranger.arrange_events / resolve_style（模块1 并行开发，
  测试用 unittest.mock 桩，不依赖真实 arranger 实现）
- 配置从 workstation.config.get_settings().music 读取；MusicConfig 未含的
  新增字段（drafts_dir / draft_ttl_days / undo_stack_limit / default_vocal_gain
  / default_accompaniment_gain）按 music-config.schema.json 默认值补齐
- submit_draft 物化 auto 轨 + 校验 + 经 SongPipelineService 提交真合成流水线
  （延迟导入 workstation.services.song_pipeline，返回映射保持 task_id/status 契约）
- 严格匹配 voicews_music.pyi 签名（参数名 / 类型 / 返回值 / 异常约定）
- 文件路径用 os.path.dirname(os.path.abspath(__file__)) 解析（rules-2）
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional, TypedDict

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from workstation.music.score import validate_score

# ScoreV2 = dict[str, Any]（voicews_music.pyi 类型别名，运行时等价 dict；不从 score.py 导入）
ScoreV2 = dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 路径解析（rules-2：禁止相对路径字符串拼接，逐层 dirname 定位）
# ---------------------------------------------------------------------------

_MUSIC_DIR = os.path.dirname(os.path.abspath(__file__))
# _MUSIC_DIR = .../CX-O-VoiceWorkStation/workstation/music
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_MUSIC_DIR))  # CX-O-VoiceWorkStation
_CXO_ROOT = os.path.dirname(_PROJECT_ROOT)  # CX-O
_CONTRACTS_DIR = os.path.join(
    _CXO_ROOT, ".trae", "specs", "redesign-composition-staff-editor", "contracts"
)
_COMMAND_PROTOCOL_PATH = os.path.join(_CONTRACTS_DIR, "command-protocol.schema.json")

# ---------------------------------------------------------------------------
# 配置默认值（music-config.schema.json default；MusicConfig 缺字段时补齐）
# ---------------------------------------------------------------------------

_CONFIG_DEFAULTS: dict[str, Any] = {
    "drafts_dir": "data/music/drafts",
    "draft_ttl_days": 7,
    "undo_stack_limit": 100,
    "default_vocal_gain": 1.0,
    "default_accompaniment_gain": 0.8,
}


def _music_config() -> Any:
    """读取 MusicConfig（延迟导入，避免循环依赖）"""
    from workstation.config import get_settings

    return get_settings().music


def _config_value(field: str) -> Any:
    """从 MusicConfig 取字段；缺失或 None 时回退到 music-config.schema.json 默认值"""
    val = getattr(_music_config(), field, None)
    if val is None:
        return _CONFIG_DEFAULTS[field]
    return val


def _drafts_dir_abs() -> str:
    """草稿落盘根目录绝对路径（相对路径相对 CX-O-VoiceWorkStation 项目根解析）"""
    cfg_dir = _config_value("drafts_dir")
    if os.path.isabs(cfg_dir):
        return cfg_dir
    return os.path.join(_PROJECT_ROOT, cfg_dir)


def _ttl_days() -> int:
    return int(_config_value("draft_ttl_days"))


def _undo_limit() -> int:
    return int(_config_value("undo_stack_limit"))


# ---------------------------------------------------------------------------
# 命令清单 + args schema 加载（单一真相源 = 冻结契约 command-protocol.schema.json）
# ---------------------------------------------------------------------------

_COMMANDS: tuple[str, ...] = (
    "create_draft", "get_draft",
    "add_note", "update_note", "move_note", "delete_note", "set_lyric",
    "add_chord", "update_chord", "delete_chord",
    "add_track", "remove_track", "set_track_instrument", "set_track_mode",
    "arrange_track", "set_track_mix",
    "undo", "redo", "validate_draft", "submit_draft",
)

# 编辑类命令（入 undo 栈 + version+1 + 清空 redo 栈）
_EDIT_COMMANDS: frozenset[str] = frozenset({
    "add_note", "update_note", "move_note", "delete_note", "set_lyric",
    "add_chord", "update_chord", "delete_chord",
    "add_track", "remove_track", "set_track_instrument", "set_track_mode",
    "arrange_track", "set_track_mix",
})


def _load_protocol() -> dict:
    """加载冻结契约 command-protocol.schema.json"""
    with open(_COMMAND_PROTOCOL_PATH, "r", encoding="utf-8") as fp:
        return json.load(fp)


# 协议文档与 args 校验器均惰性构建（首次使用时加载并缓存）：
# 1. 契约文件缺失 / 损坏时不在模块导入期崩掉——降级为跳过 args 校验并 log 警告；
# 2. jsonschema>=4.18 已弃用 RefResolver，args 子 schema 的 "#/definitions/..."
#    内部引用改经 referencing Registry 承载协议根文档解析（基座校验器
#    evolve 继承，等价旧 RefResolver.from_schema(_PROTOCOL) 语义）。
_PROTOCOL: Optional[dict] = None
_PROTOCOL_LOAD_FAILED: bool = False
_ARGS_VALIDATORS: Optional[dict[str, Draft7Validator]] = None

# 协议根文档注册 URN（固定锚点，仅作 Registry 内寻址，不参与校验语义）
_PROTOCOL_URN = "urn:cxo:command-protocol"


def _get_protocol() -> dict:
    """惰性加载协议文档并缓存；加载失败降级为空文档（args 校验跳过）并警告"""
    global _PROTOCOL, _PROTOCOL_LOAD_FAILED
    if _PROTOCOL is None and not _PROTOCOL_LOAD_FAILED:
        try:
            _PROTOCOL = _load_protocol()
        except Exception as exc:
            _PROTOCOL_LOAD_FAILED = True
            logger.warning(
                "command-protocol.schema.json 加载失败，args 校验降级为跳过: %s", exc
            )
    return _PROTOCOL if _PROTOCOL is not None else {}


def _get_args_validators() -> dict[str, Draft7Validator]:
    """惰性构建全部命令的 args 校验器（依赖协议加载，单次构建缓存）"""
    global _ARGS_VALIDATORS
    if _ARGS_VALIDATORS is None:
        protocol = _get_protocol()
        # default_specification=DRAFT7：协议加载失败降级为空文档（无 $schema 可
        # 检测）时 from_contents 也能构建，保证降级路径本身不崩
        registry = Registry().with_resource(
            _PROTOCOL_URN,
            Resource.from_contents(protocol, default_specification=DRAFT7),
        )
        base = Draft7Validator(protocol, registry=registry)
        validators: dict[str, Draft7Validator] = {}
        for cmd in _COMMANDS:
            # create_draft/get_draft 等若协议未定义独立 args schema，用空 schema 放行
            schema = protocol.get("definitions", {}).get(f"args_{cmd}")
            if schema is None:
                schema = {"type": "object"}
            # evolve 继承以协议根为基座的 resolver：子 schema 的 "#/definitions/..."
            # 相对协议根解析（等价旧 RefResolver.from_schema 语义）
            validators[cmd] = base.evolve(schema=schema)
        _ARGS_VALIDATORS = validators
    return _ARGS_VALIDATORS


# ---------------------------------------------------------------------------
# DraftState TypedDict（voicews_music.pyi 模块4）
# ---------------------------------------------------------------------------


class DraftState(TypedDict):
    """内存注册表条目（undo/redo 栈不落盘，服务重启后清空）"""

    draft_id: str
    score: ScoreV2
    version: int            # 单调递增，每次成功执行编辑命令 +1
    undo_stack: list[Any]   # 逆操作 before 片段（整谱深拷贝），上限 undo_stack_limit
    redo_stack: list[Any]
    updated_at: str         # ISO 8601


# ---------------------------------------------------------------------------
# 空白草稿占位（merged.md §3 + command-protocol x-notes）
# ---------------------------------------------------------------------------

_PLACEHOLDER_NOTE: dict[str, Any] = {"pitch": "C4", "beats": 4, "lyric": ""}


def _blank_score() -> dict:
    """空白草稿种子：melody 置 C4 全音符占位（满足 score v2 melody minItems=1）"""
    return {
        "title": "未命名",
        "bpm": 120,
        "time_signature": "4/4",
        "key": "C",
        "melody": [copy.deepcopy(_PLACEHOLDER_NOTE)],
        "chords": [],
        "accompaniment_tracks": [],
    }


def _is_placeholder_melody(melody: list) -> bool:
    """检测 melody 是否仍为空白草稿占位（首个 add_note 时替换）"""
    return (
        len(melody) == 1
        and melody[0].get("pitch") == "C4"
        and melody[0].get("beats") == 4
        and melody[0].get("lyric", "") == ""
    )


# ---------------------------------------------------------------------------
# 内存注册表（模块级单例，单进程内按草稿串行）
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, DraftState] = {}


# ---------------------------------------------------------------------------
# 命令内错误（经错误码表达，不抛出 execute_command）
# ---------------------------------------------------------------------------


class _CommandError(Exception):
    """命令应用阶段错误：携带错误码 + payload"""

    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


# ---------------------------------------------------------------------------
# 时间 / 路径辅助
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """本地时区 ISO8601 时间戳（秒级）"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _format_json_path(err: Any) -> str:
    """jsonschema absolute_path → 可读字段定位"""
    parts: list[str] = []
    for node in err.absolute_path:
        if isinstance(node, int):
            parts.append(f"[{node}]")
        elif parts:
            parts.append(f".{node}")
        else:
            parts.append(str(node))
    return "".join(parts) if parts else "$"


def _draft_file_path(draft_id: str) -> str:
    return os.path.join(_drafts_dir_abs(), draft_id, "draft.json")


# ---------------------------------------------------------------------------
# 原子落盘（tempfile + os.replace）
# ---------------------------------------------------------------------------


def _persist(state: DraftState) -> None:
    """将草稿快照原子写入 {drafts_dir}/{draft_id}/draft.json"""
    draft_dir = os.path.dirname(_draft_file_path(state["draft_id"]))
    os.makedirs(draft_dir, exist_ok=True)
    data = {
        "draft_id": state["draft_id"],
        "score": state["score"],
        "version": state["version"],
        "updated_at": state["updated_at"],
    }
    fd, tmp_path = tempfile.mkstemp(dir=draft_dir, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _draft_file_path(state["draft_id"]))
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


# ---------------------------------------------------------------------------
# CommandResult 形状辅助（command-protocol.schema.json definitions.command_result）
# ---------------------------------------------------------------------------


def _ok(state: DraftState, changed_paths: list[str], result: Optional[dict]) -> dict:
    res: dict[str, Any] = {
        "success": True,
        "draft_id": state["draft_id"],
        "version": state["version"],
        "snapshot": copy.deepcopy(state["score"]),
        "changed_paths": changed_paths,
    }
    if result is not None:
        res["result"] = result
    return res


def _fail(
    code: str,
    message: str,
    details: Optional[dict] = None,
    draft_id: str = "",
) -> dict:
    res: dict[str, Any] = {
        "success": False,
        "draft_id": draft_id,
        "error": {"code": code, "message": message},
    }
    if details:
        res["error"]["details"] = details
    return res


# ---------------------------------------------------------------------------
# track / note 寻址辅助（command-protocol x-notes 寻址语义）
# ---------------------------------------------------------------------------


def _find_track(score: dict, track_ref: str) -> tuple[int, dict]:
    """
    track 寻址：返回 (track_idx, track_dict)。
    track_ref="melody" 返回 (-1, {}) 表示主旋律轨（调用方分支处理）。
    非 "melody" 必须命中某伴奏轨 id，否则抛 TRACK_NOT_FOUND。
    """
    if track_ref == "melody":
        return -1, {}
    for idx, track in enumerate(score.get("accompaniment_tracks", [])):
        if track.get("id") == track_ref:
            return idx, track
    raise _CommandError(
        "TRACK_NOT_FOUND",
        f"轨道不存在: {track_ref!r}",
        {"track": track_ref},
    )


def _find_track_by_id(score: dict, track_id: str) -> tuple[int, dict]:
    """伴奏轨 id 寻址（用于 track 类命令，track_id 不可能是 "melody"）"""
    for idx, track in enumerate(score.get("accompaniment_tracks", [])):
        if track.get("id") == track_id:
            return idx, track
    raise _CommandError(
        "TRACK_NOT_FOUND",
        f"轨道不存在: {track_id!r}",
        {"track": track_id},
    )


def _sort_track_events(track: dict) -> None:
    """伴奏轨 events 按 offset 升序（note_id 寻址基准）"""
    track.setdefault("events", []).sort(key=lambda e: e.get("offset", 0))


def _track_path_prefix(track_idx: int) -> str:
    """changed_paths 前缀：melody 轨用 melody，伴奏轨用 accompaniment_tracks[idx]"""
    return "melody" if track_idx < 0 else f"accompaniment_tracks[{track_idx}]"


# ---------------------------------------------------------------------------
# 命令应用（在 state.score 上原地修改；失败由 _execute_edit 回滚）
# ---------------------------------------------------------------------------

# 返回 (changed_paths, result, noop)；noop=True 表示空操作（幂等不增 version）


def _cmd_add_note(state: DraftState, args: dict) -> tuple[list[str], Optional[dict], bool]:
    score = state["score"]
    track_ref = args["track"]
    pitch = args["pitch"]
    beats = args["beats"]
    track_idx, track = _find_track(score, track_ref)

    if track_idx < 0:
        # melody 轨：顺序累加定位，追加到末尾；首音符替换占位
        melody = score.setdefault("melody", [])
        if _is_placeholder_melody(melody):
            melody.clear()
        note = {"pitch": pitch, "beats": beats, "lyric": args.get("lyric", "")}
        melody.append(note)
        changed = [f"melody[{len(melody) - 1}]"]
    else:
        # 伴奏轨：显式 offset 定位（缺省=追加到轨尾 max(offset+beats)）
        events = track.setdefault("events", [])
        if "offset" in args and args["offset"] is not None:
            offset = args["offset"]
        else:
            offset = max((e.get("offset", 0) + e.get("beats", 0) for e in events), default=0)
        note = {"pitch": pitch, "beats": beats, "offset": offset, "velocity": 64}
        events.append(note)
        _sort_track_events(track)
        pos = events.index(note)
        changed = [f"accompaniment_tracks[{track_idx}].events[{pos}]"]
    return changed, None, False


def _cmd_update_note(state: DraftState, args: dict) -> tuple[list[str], Optional[dict], bool]:
    score = state["score"]
    track_ref = args["track"]
    note_id = args["note_id"]
    patch = args["patch"]
    track_idx, track = _find_track(score, track_ref)

    if track_idx < 0:
        melody = score.get("melody", [])
        if note_id < 0 or note_id >= len(melody):
            raise _CommandError(
                "NOTE_NOT_FOUND",
                f"音符不存在: melody[{note_id}]",
                {"track": "melody", "note_id": note_id},
            )
        target = melody[note_id]
        for key in ("pitch", "beats", "lyric"):
            if key in patch:
                target[key] = patch[key]
        # offset 仅伴奏轨有效，melody 轨忽略
        changed = [f"melody[{note_id}]"]
    else:
        events = track.setdefault("events", [])
        if note_id < 0 or note_id >= len(events):
            raise _CommandError(
                "NOTE_NOT_FOUND",
                f"音符不存在: track={track_ref!r} note_id={note_id}",
                {"track": track_ref, "note_id": note_id},
            )
        target = events[note_id]
        for key in ("pitch", "beats", "offset", "velocity"):
            if key in patch:
                target[key] = patch[key]
        _sort_track_events(track)
        changed = [f"accompaniment_tracks[{track_idx}].events[{note_id}]"]
    return changed, None, False


def _cmd_move_note(state: DraftState, args: dict) -> tuple[list[str], Optional[dict], bool]:
    score = state["score"]
    track_ref = args["track"]
    note_id = args["note_id"]
    new_offset = args["new_offset"]
    new_pitch = args.get("new_pitch")
    track_idx, track = _find_track(score, track_ref)

    if track_idx < 0:
        # melody 轨语义：移动到序号位置（重排）
        melody = score.get("melody", [])
        if note_id < 0 or note_id >= len(melody):
            raise _CommandError(
                "NOTE_NOT_FOUND",
                f"音符不存在: melody[{note_id}]",
                {"track": "melody", "note_id": note_id},
            )
        target_pos = max(0, min(int(new_offset), len(melody) - 1))
        note = melody.pop(note_id)
        if new_pitch is not None:
            note["pitch"] = new_pitch
        melody.insert(target_pos, note)
        changed = [f"melody[{target_pos}]"]
    else:
        events = track.setdefault("events", [])
        if note_id < 0 or note_id >= len(events):
            raise _CommandError(
                "NOTE_NOT_FOUND",
                f"音符不存在: track={track_ref!r} note_id={note_id}",
                {"track": track_ref, "note_id": note_id},
            )
        target = events[note_id]
        target["offset"] = new_offset
        if new_pitch is not None:
            target["pitch"] = new_pitch
        _sort_track_events(track)
        pos = events.index(target)
        changed = [f"accompaniment_tracks[{track_idx}].events[{pos}]"]
    return changed, None, False


def _cmd_delete_note(state: DraftState, args: dict) -> tuple[list[str], Optional[dict], bool]:
    """幂等设计：note_id 越界=空操作成功（不报 NOTE_NOT_FOUND）"""
    score = state["score"]
    track_ref = args["track"]
    note_id = args["note_id"]
    track_idx, track = _find_track(score, track_ref)

    if track_idx < 0:
        melody = score.get("melody", [])
        if note_id < 0 or note_id >= len(melody):
            return [], None, True  # 空操作成功
        melody.pop(note_id)
        changed = [f"melody[{note_id}]"]
    else:
        events = track.setdefault("events", [])
        if note_id < 0 or note_id >= len(events):
            return [], None, True  # 空操作成功
        events.pop(note_id)
        changed = [f"accompaniment_tracks[{track_idx}].events[{note_id}]"]
    return changed, None, False


def _cmd_set_lyric(state: DraftState, args: dict) -> tuple[list[str], Optional[dict], bool]:
    """set_lyric 仅作用于 melody 轨（command-protocol args_set_lyric 无 track 字段）"""
    score = state["score"]
    note_id = args["note_id"]
    lyric = args["lyric"]
    melody = score.get("melody", [])
    if note_id < 0 or note_id >= len(melody):
        raise _CommandError(
            "NOTE_NOT_FOUND",
            f"音符不存在: melody[{note_id}]",
            {"track": "melody", "note_id": note_id},
        )
    melody[note_id]["lyric"] = lyric
    return [f"melody[{note_id}]"], None, False


def _cmd_add_chord(state: DraftState, args: dict) -> tuple[list[str], Optional[dict], bool]:
    score = state["score"]
    chords = score.setdefault("chords", [])
    chord = {"chord": args["chord"], "beats": args["beats"]}
    if "index" in args and args["index"] is not None:
        idx = min(max(0, args["index"]), len(chords))
        chords.insert(idx, chord)
    else:
        chords.append(chord)
        idx = len(chords) - 1
    return [f"chords[{idx}]"], None, False


def _cmd_update_chord(state: DraftState, args: dict) -> tuple[list[str], Optional[dict], bool]:
    score = state["score"]
    idx = args["index"]
    patch = args["patch"]
    chords = score.get("chords", [])
    if idx < 0 or idx >= len(chords):
        raise _CommandError(
            "CHORD_NOT_FOUND",
            f"和弦不存在: chords[{idx}]",
            {"index": idx},
        )
    target = chords[idx]
    for key in ("chord", "beats"):
        if key in patch:
            target[key] = patch[key]
    return [f"chords[{idx}]"], None, False


def _cmd_delete_chord(state: DraftState, args: dict) -> tuple[list[str], Optional[dict], bool]:
    score = state["score"]
    idx = args["index"]
    chords = score.get("chords", [])
    if idx < 0 or idx >= len(chords):
        raise _CommandError(
            "CHORD_NOT_FOUND",
            f"和弦不存在: chords[{idx}]",
            {"index": idx},
        )
    chords.pop(idx)
    return [f"chords[{idx}]"], None, False


def _gen_track_id(score: dict) -> str:
    """生成草稿内唯一的伴奏轨 id（trk_<8hex>；冲突重试）"""
    existing = {t.get("id") for t in score.get("accompaniment_tracks", [])}
    while True:
        tid = "trk_" + uuid.uuid4().hex[:8]
        if tid not in existing:
            return tid


def _cmd_add_track(state: DraftState, args: dict) -> tuple[list[str], Optional[dict], bool]:
    score = state["score"]
    tracks = score.setdefault("accompaniment_tracks", [])
    track_id = _gen_track_id(score)
    new_track = {
        "id": track_id,
        "name": args["name"],
        "program": args["program"],
        "mode": args["mode"],
        "style": args.get("style", ""),
        "volume": 100,
        "pan": 64,
        "events": [],
    }
    tracks.append(new_track)
    idx = len(tracks) - 1
    return [f"accompaniment_tracks[{idx}]"], {"track_id": track_id}, False


def _cmd_remove_track(state: DraftState, args: dict) -> tuple[list[str], Optional[dict], bool]:
    """幂等设计：track_id 不存在=空操作成功（对齐 delete_note 范式 + x-notes 幂等性）"""
    score = state["score"]
    track_id = args["track_id"]
    tracks = score.get("accompaniment_tracks", [])
    for idx, track in enumerate(tracks):
        if track.get("id") == track_id:
            tracks.pop(idx)
            return [f"accompaniment_tracks[{idx}]"], None, False
    return [], None, True  # 空操作成功


def _cmd_set_track_instrument(
    state: DraftState, args: dict
) -> tuple[list[str], Optional[dict], bool]:
    score = state["score"]
    track_id = args["track_id"]
    program = args["program"]
    idx, track = _find_track_by_id(score, track_id)
    track["program"] = program
    return [f"accompaniment_tracks[{idx}].program"], None, False


def _cmd_set_track_mode(
    state: DraftState, args: dict
) -> tuple[list[str], Optional[dict], bool]:
    """
    auto/manual 切换：
    - 切 manual 时：若轨为 auto 且 events 为空，先按 chords+style 物化生成结果再切换
    - 切 auto 时：保留 events 作为微调基线，style 不变
    """
    score = state["score"]
    track_id = args["track_id"]
    new_mode = args["mode"]
    idx, track = _find_track_by_id(score, track_id)
    old_mode = track.get("mode", "manual")
    if new_mode == "manual" and old_mode == "auto" and not track.get("events"):
        # 物化 auto 轨（events 空 → 按 chords+style 生成）
        _materialize_track(score, track)
    track["mode"] = new_mode
    return [f"accompaniment_tracks[{idx}].mode"], None, False


def _cmd_arrange_track(
    state: DraftState, args: dict
) -> tuple[list[str], Optional[dict], bool]:
    """
    按和弦骨架重生成 auto 轨 events 并物化写入。
    - 仅 auto 轨可用，manual 轨报 TRACK_MODE_INVALID
    - style 缺省用轨当前 style（含空串回退规则）
    - arranger.ValueError → STYLE_UNKNOWN
    """
    score = state["score"]
    track_id = args["track_id"]
    idx, track = _find_track_by_id(score, track_id)
    if track.get("mode") != "auto":
        raise _CommandError(
            "TRACK_MODE_INVALID",
            f"arrange_track 仅 auto 轨可用: track_id={track_id!r} mode={track.get('mode')!r}",
            {"track_id": track_id, "mode": track.get("mode")},
        )
    style = args.get("style")
    if style is not None:
        track["style"] = style  # 同时更新轨 style 字段
    _materialize_track(score, track)
    return (
        [f"accompaniment_tracks[{idx}].events"],
        {"events": copy.deepcopy(track.get("events", []))},
        False,
    )


def _cmd_set_track_mix(
    state: DraftState, args: dict
) -> tuple[list[str], Optional[dict], bool]:
    score = state["score"]
    track_id = args["track_id"]
    idx, track = _find_track_by_id(score, track_id)
    changed: list[str] = []
    if "volume" in args and args["volume"] is not None:
        track["volume"] = args["volume"]
        changed.append(f"accompaniment_tracks[{idx}].volume")
    if "pan" in args and args["pan"] is not None:
        track["pan"] = args["pan"]
        changed.append(f"accompaniment_tracks[{idx}].pan")
    if not changed:
        changed.append(f"accompaniment_tracks[{idx}]")
    return changed, None, False


# 命令分发表（编辑类命令）
_APPLY_DISPATCH: dict[str, Any] = {
    "add_note": _cmd_add_note,
    "update_note": _cmd_update_note,
    "move_note": _cmd_move_note,
    "delete_note": _cmd_delete_note,
    "set_lyric": _cmd_set_lyric,
    "add_chord": _cmd_add_chord,
    "update_chord": _cmd_update_chord,
    "delete_chord": _cmd_delete_chord,
    "add_track": _cmd_add_track,
    "remove_track": _cmd_remove_track,
    "set_track_instrument": _cmd_set_track_instrument,
    "set_track_mode": _cmd_set_track_mode,
    "arrange_track": _cmd_arrange_track,
    "set_track_mix": _cmd_set_track_mix,
}


# ---------------------------------------------------------------------------
# arranger 延迟导入 + auto 轨物化
# ---------------------------------------------------------------------------


def _import_arranger() -> Any:
    """
    延迟导入 arranger 模块（模块1 并行开发，可能尚未落位）。
    测试用 unittest.mock.patch 住本函数返回的模块的 arrange_events / resolve_style。
    """
    from workstation.music import arranger  # noqa: WPS433（延迟导入，断开加载期依赖）

    return arranger


def _materialize_track(score: dict, track: dict) -> None:
    """
    按和弦骨架 + 节奏型生成 events 并物化写入 track.events（auto 轨专用）。
    arranger.ValueError（style 不合法 / applies_to 冲突）→ 转为 STYLE_UNKNOWN。
    """
    arranger = _import_arranger()
    style = track.get("style", "")
    program = track.get("program", 0)
    try:
        resolved_style = arranger.resolve_style(style, program)
        events = arranger.arrange_events(
            score.get("chords", []),
            resolved_style,
            program,
            score.get("time_signature", "4/4"),
        )
    except ValueError as exc:
        raise _CommandError(
            "STYLE_UNKNOWN",
            f"节奏型不合法或与轨类型不匹配: {exc}",
            {"style": style, "available": _available_styles()},
        ) from exc
    track["events"] = [copy.deepcopy(e) for e in events]
    _sort_track_events(track)


def _available_styles() -> list[str]:
    """节奏型枚举清单（STYLE_UNKNOWN payload）"""
    try:
        from workstation.music.inventory import INVENTORY  # 延迟导入

        return [s["id"] for s in INVENTORY.get("styles", [])]
    except Exception:  # pragma: no cover（inventory 应总是可用）
        return ["block_chords", "arpeggio", "root_eighth", "rock_4beat"]


def _materialize_auto_tracks(score: dict) -> None:
    """submit_draft 前物化所有 auto 空 events 轨（merged.md §7）"""
    for track in score.get("accompaniment_tracks", []):
        if track.get("mode") == "auto" and not track.get("events"):
            _materialize_track(score, track)


# ---------------------------------------------------------------------------
# execute_command 编辑类命令的原子性包装
# ---------------------------------------------------------------------------


def _execute_edit(state: DraftState, command: str, args: dict) -> dict:
    """
    编辑类命令原子执行：args 校验 → 深拷贝 before → 应用 → 整谱 validate_score
    → 入 undo 栈 → version+1 → 原子落盘；任一步失败整体回滚。
    """
    before = copy.deepcopy(state["score"])
    try:
        changed_paths, result, noop = _APPLY_DISPATCH[command](state, args)
    except _CommandError as exc:
        state["score"] = before  # 防御性回滚（应用函数应已保持原状）
        return _fail(exc.code, exc.message, exc.details, draft_id=state["draft_id"])
    except Exception as exc:  # 内部异常统一转 CommandResult
        logger.exception("execute_command 内部异常: command=%s", command)
        state["score"] = before
        return _fail(
            "SCORE_VALIDATION_FAILED",
            f"命令应用内部错误: {exc}",
            {"command": command},
            draft_id=state["draft_id"],
        )

    if noop:
        # 幂等空操作：success=true，不入栈，version 不增，不落盘
        return _ok(state, changed_paths, result)

    # 整谱校验
    ok, errors, normalized = validate_score(state["score"])
    if not ok:
        state["score"] = before  # 回滚
        return _fail(
            "SCORE_VALIDATION_FAILED",
            "应用后整谱校验失败",
            {"errors": errors},
            draft_id=state["draft_id"],
        )
    state["score"] = normalized  # 用规范化后的（填默认值）

    # 入 undo 栈（before 片段 = 整谱深拷贝）
    undo_stack = state["undo_stack"]
    undo_stack.append(before)
    limit = _undo_limit()
    while len(undo_stack) > limit:
        undo_stack.pop(0)

    # 清空 redo 栈（任何新编辑命令）
    state["redo_stack"].clear()

    # version+1
    state["version"] += 1
    state["updated_at"] = _now_iso()

    # 原子落盘
    try:
        _persist(state)
    except Exception as exc:
        state["score"] = before
        undo_stack.pop()
        state["version"] -= 1
        logger.exception("草稿落盘失败: draft_id=%s", state["draft_id"])
        return _fail(
            "SCORE_VALIDATION_FAILED",
            f"草稿落盘失败: {exc}",
            {"draft_id": state["draft_id"]},
            draft_id=state["draft_id"],
        )
    return _ok(state, changed_paths, result)


# ---------------------------------------------------------------------------
# undo / redo
# ---------------------------------------------------------------------------


def _cmd_undo(state: DraftState) -> dict:
    """undo：弹出 undo 栈顶 before，当前 score 压入 redo 栈；空栈空操作 success=true"""
    if not state["undo_stack"]:
        return _ok(state, ["$"], None)  # 空栈空操作，version 不增
    before = state["undo_stack"].pop()
    state["redo_stack"].append(copy.deepcopy(state["score"]))
    state["score"] = before
    state["version"] += 1
    state["updated_at"] = _now_iso()
    try:
        _persist(state)
    except Exception as exc:
        logger.exception("undo 落盘失败: draft_id=%s", state["draft_id"])
        return _fail(
            "SCORE_VALIDATION_FAILED",
            f"undo 落盘失败: {exc}",
            {"draft_id": state["draft_id"]},
            draft_id=state["draft_id"],
        )
    return _ok(state, ["$"], None)


def _cmd_redo(state: DraftState) -> dict:
    """redo：弹出 redo 栈顶，当前 score 压入 undo 栈；空栈空操作 success=true"""
    if not state["redo_stack"]:
        return _ok(state, ["$"], None)  # 空栈空操作，version 不增
    after = state["redo_stack"].pop()
    state["undo_stack"].append(copy.deepcopy(state["score"]))
    state["score"] = after
    state["version"] += 1
    state["updated_at"] = _now_iso()
    try:
        _persist(state)
    except Exception as exc:
        logger.exception("redo 落盘失败: draft_id=%s", state["draft_id"])
        return _fail(
            "SCORE_VALIDATION_FAILED",
            f"redo 落盘失败: {exc}",
            {"draft_id": state["draft_id"]},
            draft_id=state["draft_id"],
        )
    return _ok(state, ["$"], None)


# ---------------------------------------------------------------------------
# 公开 API（voicews_music.pyi 模块4 draft_registry）
# ---------------------------------------------------------------------------


def create_draft(score: Optional[dict] = None) -> dict:
    """
    创建草稿（score 缺省建空白草稿；v1 输入自动迁移）。成功时 result 无附加字段，
    snapshot 为初始歌谱，version=0。

    Raises:
        无（失败走 CommandResult success=false + SCORE_VALIDATION_FAILED）
    """
    if score is None:
        seed = _blank_score()
    else:
        seed = copy.deepcopy(score)
    ok, errors, normalized = validate_score(seed)
    if not ok:
        return _fail(
            "SCORE_VALIDATION_FAILED",
            "种子歌谱校验失败",
            {"errors": errors},
            draft_id="",
        )
    draft_id = uuid.uuid4().hex
    state: DraftState = {
        "draft_id": draft_id,
        "score": normalized,
        "version": 0,
        "undo_stack": [],
        "redo_stack": [],
        "updated_at": _now_iso(),
    }
    _REGISTRY[draft_id] = state
    try:
        _persist(state)
    except Exception as exc:
        del _REGISTRY[draft_id]
        logger.exception("create_draft 落盘失败: draft_id=%s", draft_id)
        return _fail(
            "SCORE_VALIDATION_FAILED",
            f"草稿落盘失败: {exc}",
            {"draft_id": draft_id},
            draft_id="",
        )
    return _ok(state, ["$"], None)


def get_draft(draft_id: str) -> dict:
    """返回当前快照 + version（不增 version）。不存在返回 DRAFT_NOT_FOUND。"""
    state = _REGISTRY.get(draft_id)
    if state is None:
        return _fail(
            "DRAFT_NOT_FOUND",
            f"草稿不存在: {draft_id!r}",
            {"draft_id": draft_id},
            draft_id=draft_id,
        )
    return _ok(state, ["$"], None)


def list_drafts() -> list[dict]:
    """
    草稿摘要列表（按 updated_at 倒序）：{draft_id, title, version, updated_at}。

    Raises:
        无
    """
    items = [
        {
            "draft_id": s["draft_id"],
            "title": s["score"].get("title", ""),
            "version": s["version"],
            "updated_at": s["updated_at"],
        }
        for s in _REGISTRY.values()
    ]
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return items


def delete_draft(draft_id: str) -> bool:
    """删除草稿（内存注册表 + 落盘文件）；不存在返回 False（幂等，不报错）。"""
    existed = draft_id in _REGISTRY
    if existed:
        del _REGISTRY[draft_id]
    draft_dir = os.path.join(_drafts_dir_abs(), draft_id)
    if os.path.isdir(draft_dir):
        shutil.rmtree(draft_dir, ignore_errors=True)
    return existed


def load_draft(draft_id: str) -> Optional[DraftState]:
    """
    从磁盘载入草稿到注册表（启动恢复 / 测试载入辅助）。

    非 voicews_music.pyi 公开契约——.pyi 声明的公开 API 子集不含本函数，
    但 merged.md §4 的"服务重启后从磁盘恢复查询"语义需要载入能力。本函数
    作为公开辅助提供，供启动恢复与单测断言使用。

    Returns:
        载入成功的 DraftState；磁盘无对应文件返回 None
    """
    draft_path = _draft_file_path(draft_id)
    if not os.path.isfile(draft_path):
        return None
    try:
        with open(draft_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None
    state: DraftState = {
        "draft_id": data["draft_id"],
        "score": data["score"],
        "version": data["version"],
        "undo_stack": [],  # 不落盘，重启清空
        "redo_stack": [],
        "updated_at": data["updated_at"],
    }
    _REGISTRY[draft_id] = state
    return state


def execute_command(draft_id: str, command: str, args: dict) -> dict:
    """
    命令执行器唯一入口（REST /drafts/{id}/commands 与 CXFC music_edit_score 共用）。

    原子性：args 校验（按 command 分发 args_<command> schema）→ 应用 → 整谱
    validate_score → 入 undo 栈 → version+1 → 原子落盘；任一步失败整体回滚，
    草稿状态不变，返回 success=false + 对应错误码。

    串行性：服务端单进程内按草稿串行执行（单时钟，无并发漂移）。

    Raises:
        无（一切失败含内部异常统一转 CommandResult success=false）
    """
    # 1. command 是否已知
    if command not in _COMMANDS:
        return _fail(
            "COMMAND_UNKNOWN",
            f"未知命令: {command!r}",
            {"available": list(_COMMANDS)},
            draft_id=draft_id,
        )

    # 2. args 校验（按 command 分发 args_<command> schema）
    validator = _get_args_validators()[command]
    raw_errors = sorted(validator.iter_errors(args), key=lambda e: list(e.absolute_path))
    if raw_errors:
        msgs = [f"{_format_json_path(e)}: {e.message}" for e in raw_errors]
        return _fail(
            "COMMAND_ARGS_INVALID",
            "args 校验失败",
            {"errors": msgs},
            draft_id=draft_id,
        )

    # 3. create_draft 走独立路径（生成新 draft_id，忽略传入的 draft_id 参数）
    if command == "create_draft":
        return create_draft(args.get("score"))

    # 4. 其余命令需要既有草稿
    state = _REGISTRY.get(draft_id)
    if state is None:
        return _fail(
            "DRAFT_NOT_FOUND",
            f"草稿不存在: {draft_id!r}",
            {"draft_id": draft_id},
            draft_id=draft_id,
        )

    # 5. 非编辑类命令分发（draft_id 以 execute_command 第一个参数为准；
    #    args 内 draft_id 仅满足 args_<command> schema 校验，二者应一致）
    if command == "get_draft":
        return get_draft(draft_id)
    if command == "validate_draft":
        return _cmd_validate_draft(state)
    if command == "submit_draft":
        params = {k: v for k, v in args.items() if k != "draft_id"}
        return submit_draft(draft_id, **params)
    if command == "undo":
        return _cmd_undo(state)
    if command == "redo":
        return _cmd_redo(state)

    # 6. 编辑类命令（原子性包装）
    return _execute_edit(state, command, args)


def _cmd_validate_draft(state: DraftState) -> dict:
    """validate_draft：全谱校验，返回 result={valid, errors}；version 不增"""
    ok, errors, _ = validate_score(state["score"])
    return _ok(state, ["$"], {"valid": ok, "errors": errors})


# submit_draft → 流水线提交参数白名单：args_submit_draft 契约允许且
# SongPipelineService.submit 接受的键（draft_id 由命令寻址消费，不透传流水线）
_SUBMIT_PARAM_KEYS: frozenset[str] = frozenset({
    "svc_model", "speaker_id", "transpose", "vocal_gain", "accompaniment_gain",
})


def _submit_to_pipeline(score: dict, params: dict) -> str:
    """
    同步上下文把物化歌谱提交进歌曲流水线，返回 song_id。

    延迟导入 workstation.services.song_pipeline：music 包不在导入期拉起
    services 链（singing_engine 依赖重），也规避 music↔services 循环依赖。

    - 已在事件循环内（FastAPI / CXFC 同步链路）：SongPipelineService.submit
      协程体当前无 await 点（参数校验→任务注册→落盘→create_task 均同步），
      以 coro.send(None) 同步驱动至 StopIteration 取回 song_id；其内部
      create_task 调度的后台流水线挂宿主长驻 loop 存活执行。若未来 submit
      引入 await 点（send 返回非 None），关闭半驱动协程并按 SUBMIT_FAILED 失败。
    - 无事件循环（脚本 / 单测）：asyncio.run 同步完成提交；后台流水线挂临时
      loop，随 loop 关闭被取消（任务停留 pending、metadata 已落盘），该场景
      仅完成受理注册，不携带后台执行。
    """
    from workstation.services.song_pipeline import get_song_pipeline  # 延迟导入

    submit_kwargs = {k: params[k] for k in _SUBMIT_PARAM_KEYS if k in params}
    coro = get_song_pipeline().submit(score=score, **submit_kwargs)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    coro.close()
    raise _CommandError(
        "SUBMIT_FAILED",
        "流水线提交协程含 await 点，同步链路无法驱动（submit 实现已偏离接线假设）",
    )


def submit_draft(draft_id: str, **params: Any) -> dict:
    """
    物化草稿（auto 空 events 轨经 arranger 生成）→ 校验 → 提交歌曲合成流水线，
    返回 result={task_id, song_id, status}。草稿保留可继续编辑。

    task_id/song_id 即流水线 song_id（uuid4 hex，可经 /api/music/tasks/{id} 查询
    进度）；status 固定 "pending"（受理即返回，流水线后台执行）。version 不增
    （submit 非编辑类命令）。

    Raises:
        无（失败走 SUBMIT_FAILED / SCORE_VALIDATION_FAILED 错误码）
    """
    state = _REGISTRY.get(draft_id)
    if state is None:
        return _fail(
            "DRAFT_NOT_FOUND",
            f"草稿不存在: {draft_id!r}",
            {"draft_id": draft_id},
            draft_id=draft_id,
        )
    materialized = copy.deepcopy(state["score"])
    try:
        _materialize_auto_tracks(materialized)
    except _CommandError as exc:
        return _fail(exc.code, exc.message, exc.details, draft_id=draft_id)
    ok, errors, _ = validate_score(materialized)
    if not ok:
        return _fail(
            "SCORE_VALIDATION_FAILED",
            "提交前整谱校验失败",
            {"errors": errors},
            draft_id=draft_id,
        )
    try:
        song_id = _submit_to_pipeline(materialized, params)
    except _CommandError as exc:
        return _fail(exc.code, exc.message, exc.details, draft_id=draft_id)
    except Exception as exc:  # get_settings/落盘等意外异常，按既有错误风格收敛
        logger.exception("submit_draft 流水线提交失败: draft_id=%s", draft_id)
        return _fail(
            "SUBMIT_FAILED",
            f"流水线提交失败: {exc}",
            {"draft_id": draft_id},
            draft_id=draft_id,
        )
    result = {"task_id": song_id, "song_id": song_id, "status": "pending"}
    return _ok(state, ["$"], result)


def sweep_expired_drafts(ttl_days: int) -> int:
    """
    启动时清扫空闲超 TTL 的草稿（按 updated_at 计算）。返回清扫数量。
    ttl_days=0 不清扫返回 0。

    Raises:
        无
    """
    if ttl_days is None or ttl_days <= 0:
        return 0
    now = datetime.now().astimezone()
    threshold = now - timedelta(days=ttl_days)
    to_sweep: list[str] = []
    for draft_id, state in list(_REGISTRY.items()):
        try:
            updated = datetime.fromisoformat(state["updated_at"])
        except (ValueError, TypeError):
            continue
        if updated < threshold:
            to_sweep.append(draft_id)
    for draft_id in to_sweep:
        delete_draft(draft_id)
    return len(to_sweep)
