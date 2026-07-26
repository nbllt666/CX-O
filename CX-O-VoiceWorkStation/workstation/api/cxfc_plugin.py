"""
CXFC 插件端点：GET /tools、GET /skills、POST /call

对应 spec：redesign-composition-staff-editor（S4-D2 模块5_CXFC工具面）。
VoiceWorkStation 自身即 CX-O 主系统的 CXFC 插件，agent 经主系统
POST /cxfc/plugins/{plugin_id}/call 转发到本模块的 POST /call 完成作曲演唱。

工具面 v2（merged.md §8 冻结项）：
- music_edit_score：命令门面单一入口 {draft_id?, command, args} → CommandResult，
  透传 draft_registry.execute_command 的 10 错误码；draft_id 仅 create_draft 可缺省
- music_list_instruments：GM 128 音色 + 节奏型枚举 + 鼓键，返回 music-inventory 形状
- music_validate_score：v2，v1 输入自动迁移，返回 {valid, errors, normalized_score?}
- music_sing：增 draft_id 参数（与 score 二选一，draft_id 优先走 submit_draft）
- music_get_task / music_list_songs：零改动保留

协议形状（以 CX-O-SERVER server/core/cxfc/manager.py 与
server/api/routers/cxfc.py 的实际代码为准）：
- GET  /tools  → {"tools": [{name, description, parameters(JSON Schema)}]}
- GET  /skills → {"skills": [{name, description, prompt_template,
                 trigger_keywords, trigger_events, auto_inject}]}
- POST /call   → 请求 {"tool": <name>, "arguments": {...}}；
                 响应 {"success": bool, "result": ..., "error": ...}，
                 HTTP 恒为 200，业务失败（未知工具/参数非法/任务不存在）
                 走 success=false（与 tests/test_tools/cxfc/mock_plugin_server.py
                 及 CXFCManager.call_tool 的失败约定一致）。
- GET  /health → 由 main.py 既有路由提供（含 name/version，
                 供主系统 connect_to_plugin 读取），本模块不重复挂载。

工具与技能定义通过 get_tool_definitions()/get_skill_definitions() 暴露，
注册服务（services/cxfc_registration.py）复用同一份定义作为注册载荷，
避免 /tools 响应与注册内容两处漂移。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Awaitable, Callable

from fastapi import APIRouter
from pydantic import BaseModel, Field

from workstation.music import draft_registry, inventory
from workstation.music.score import SCORE_SCHEMA_V2, validate_score
from workstation.services.song_pipeline import (
    DEFAULT_ACCOMPANIMENT_GAIN,
    DEFAULT_VOCAL_GAIN,
    get_song_pipeline,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# 契约加载（rules-2：路径用 os.path.dirname 解析；直接引用契约不手写漂移副本）
# ---------------------------------------------------------------------------

# 逐层 dirname 定位 CX-O 根：workstation/api → workstation → CX-O-VoiceWorkStation → CX-O
_API_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKSTATION_DIR = os.path.dirname(_API_DIR)
_PROJECT_ROOT = os.path.dirname(_WORKSTATION_DIR)
_CXO_ROOT = os.path.dirname(_PROJECT_ROOT)
_CONTRACTS_DIR = os.path.join(
    _CXO_ROOT, ".trae", "specs", "redesign-composition-staff-editor", "contracts"
)
_COMMAND_PROTOCOL_PATH = os.path.join(_CONTRACTS_DIR, "command-protocol.schema.json")


def _load_command_protocol() -> dict:
    """加载 command-protocol.schema.json，提取 command enum 供工具参数引用。

    失败即 raise ImportError（与 inventory.py import 期自检一致，防漂移）。
    """
    try:
        with open(_COMMAND_PROTOCOL_PATH, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except OSError as exc:
        raise ImportError(
            f"command-protocol 契约文件缺失或不可读: {_COMMAND_PROTOCOL_PATH} ({exc})"
        ) from exc


_COMMAND_PROTOCOL = _load_command_protocol()
# 命令枚举直接来自契约（新增命令时契约更新即同步，不漂移）
_COMMAND_ENUM: list[str] = _COMMAND_PROTOCOL["properties"]["command"]["enum"]


# ---------------------------------------------------------------------------
# 工具与技能清单（/tools、/skills 响应与 CXFC 注册载荷共用的唯一定义源）
# ---------------------------------------------------------------------------


def get_tool_definitions() -> list[dict]:
    """
    CXFC 工具清单：name/description/parameters（parameters 为 JSON Schema）。

    工具参数直接引用冻结契约（SCORE_SCHEMA_V2 / command-protocol / music-inventory），
    不手写漂移副本；与 spec「通过 GET /tools 的 parameters 字段向 agent 发布」一致。
    """
    return [
        {
            "name": "music_edit_score",
            "description": (
                "歌谱编辑命令门面单一入口（merged.md §8）：经 draft_registry.execute_command "
                "执行 20 命令之一，原子应用并返回 CommandResult（含 draft_id/version/snapshot/"
                "changed_paths/result/error）。draft_id 仅 create_draft 可缺省（新建草稿），"
                "其余命令缺省 draft_id 报 COMMAND_ARGS_INVALID；错误码透传 draft_registry 的 "
                "10 错误码（SCORE_VALIDATION_FAILED/DRAFT_NOT_FOUND/COMMAND_UNKNOWN/"
                "COMMAND_ARGS_INVALID/TRACK_NOT_FOUND/NOTE_NOT_FOUND/CHORD_NOT_FOUND/"
                "STYLE_UNKNOWN/TRACK_MODE_INVALID/SUBMIT_FAILED）。命令清单（args 形状见 "
                "command-protocol.schema.json definitions.args_<command>）：\n"
                "- create_draft(score?)：新建草稿（score 缺省建空白草稿；v1 自动迁移）\n"
                "- get_draft/validate_draft：查询快照 / 全谱校验\n"
                "- add_note/update_note/move_note/delete_note/set_lyric：音符与歌词编辑\n"
                "- add_chord/update_chord/delete_chord：和弦骨架编辑\n"
                "- add_track/remove_track/set_track_instrument/set_track_mode/arrange_track/"
                "set_track_mix：伴奏轨编辑与编排（arrange_track 仅 auto 轨）\n"
                "- undo/redo：撤销重做（空栈空操作）\n"
                "- submit_draft：物化 auto 轨 + 校验 + 提交合成，返回 {task_id, song_id, status}"
            ),
            "parameters": {
                "type": "object",
                "required": ["command", "args"],
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": (
                            "草稿 id（create_draft 返回）。仅 command=create_draft 时可缺省"
                            "（新建草稿，忽略本字段）；其余命令必填，缺省报 COMMAND_ARGS_INVALID"
                        ),
                    },
                    "command": {
                        "type": "string",
                        "enum": _COMMAND_ENUM,
                        "description": "命令名（枚举来自 command-protocol.schema.json）",
                    },
                    "args": {
                        "type": "object",
                        "description": (
                            "命令参数，形状随 command 而变，见 command-protocol.schema.json "
                            "definitions.args_<command>"
                        ),
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "music_list_instruments",
            "description": (
                "列出音乐枚举清单（GM 128 音色按 16 组分组 + 编排节奏型枚举 + GM 鼓键映射）。"
                "返回 music-inventory.schema.json 形状 {instrument_groups, styles, drum_keys}。"
                "用于选择音色/节奏型、解析打击乐鼓键名（add_track/set_track_instrument 的 program、"
                "arrange_track 的 style、打击乐轨 events.pitch 的鼓键名均以此清单为合法取值真源）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "music_validate_score",
            "description": (
                "校验歌谱 JSON 是否符合 VoiceWorkStation 歌谱规范 v2。"
                "返回 {valid, errors, normalized_score?}：valid 为是否合法，errors 为逐条可读错误"
                "（含字段定位），合法时附带默认值填充后的规范化 v2 歌谱（normalized_score）。"
                "v1 输入（含 accompaniment_style）自动迁移为 v2。作曲后、演唱前必须先校验。"
            ),
            "parameters": {
                "type": "object",
                "required": ["score"],
                "properties": {
                    "score": SCORE_SCHEMA_V2,
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "music_sing",
            "description": (
                "提交歌曲合成任务：歌谱 → 伴奏渲染 → 歌声合成 → （可选）SVC 变声 → 混音。"
                "立即返回 {song_id, task_id, status}（task_id 即 song_id）；"
                "用 music_get_task 轮询直至 status=completed，取 audio_url 播放成品。"
                "支持两种输入：① draft_id（从草稿取 score，经 submit_draft 提交，草稿保留可继续编辑）；"
                "② score（直接提交）。draft_id 与 score 二选一，draft_id 优先。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "string",
                        "description": (
                            "草稿 id。提供时从草稿取 score 走 submit_draft 路径"
                            "（与 score 二选一，draft_id 优先）"
                        ),
                    },
                    "score": SCORE_SCHEMA_V2,
                    "svc_model": {
                        "type": "string",
                        "default": "",
                        "description": "SVC 模型路径；空串表示不变声，直接使用原始歌声",
                    },
                    "speaker_id": {
                        "type": "integer",
                        "default": 0,
                        "description": "SVC 说话人 id（不变声时忽略）",
                    },
                    "transpose": {
                        "type": "integer",
                        "default": 0,
                        "description": "SVC 变调（半音数，可为负）",
                    },
                    "vocal_gain": {
                        "type": "number",
                        "default": DEFAULT_VOCAL_GAIN,
                        "minimum": 0,
                        "description": "歌声增益（≥0）",
                    },
                    "accompaniment_gain": {
                        "type": "number",
                        "default": DEFAULT_ACCOMPANIMENT_GAIN,
                        "minimum": 0,
                        "description": "伴奏增益（≥0）",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "music_get_task",
            "description": (
                "查询歌曲合成任务：status（pending/running/completed/failed）、stage"
                "（当前步骤）、progress（0~1）、error（失败原因）、steps（逐步状态）"
                "与 audio_url（成品音频，完成后可用）。"
            ),
            "parameters": {
                "type": "object",
                "required": ["task_id"],
                "properties": {
                    "task_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "music_sing 返回的任务 id（即 song_id）",
                    },
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "music_list_songs",
            "description": (
                "列出历史歌曲：metadata 摘要（song_id/title/status/progress/audio_url 等），"
                "按创建时间倒序。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]


_COMPOSE_PROMPT_TEMPLATE = """你是虚拟歌手作曲与演唱助手。当用户要求作曲、写歌、唱歌或演唱时，严格按以下命令流完成（命令式编辑总线，merged.md §8）：

【完整命令流】
1. 调用 music_edit_score(command="create_draft", args={score?}) 新建草稿（score 可缺省建空白草稿；也可传入初始歌谱 v1/v2，v1 自动迁移）。记下返回的 draft_id
2. 用 music_edit_score 逐命令编辑草稿（每命令传 draft_id）：
   - add_note：旋律/伴奏轨加音符（args: {draft_id, track, pitch, beats, lyric?, offset?}）
   - add_chord：加和弦骨架（args: {draft_id, chord, beats, index?}）
   - add_track：加伴奏轨（args: {draft_id, name, program, mode, style?}）；program 见 music_list_instruments
   - arrange_track：编排 auto 轨（args: {draft_id, track_id, style?}；仅 auto 轨可用，style 见 music_list_instruments）
   - set_lyric/update_note/move_note/delete_note/update_chord/delete_chord/set_track_instrument/set_track_mode/set_track_mix/remove_track：细节编辑
3. 调用 music_edit_score(command="validate_draft", args={draft_id}) 全谱校验；若 result.valid=false，按 errors 修正后重新校验直至通过
4. 提交合成（等价 submit_draft 命令：物化 auto 轨 + 校验 + 提交流水线）：调用 music_sing(draft_id=<草稿id>)（可选 svc_model 变声、transpose 变调、vocal_gain/accompaniment_gain 增益）。记下返回的 task_id
5. 用 music_get_task(task_id) 轮询任务，直至 status 为 completed 或 failed
6. completed 时将结果中的 audio_url 交给用户播放；failed 时读取 error 向用户说明原因

【辅助工具】
- music_list_instruments()：列出 GM 128 音色（16 组）、节奏型枚举、鼓键映射，用于选 program/style
- music_validate_score(score)：独立校验一份歌谱 JSON（不经草稿，直接校验）

【命令流示例（小星星）】
music_edit_score(command="create_draft", args={"score": {"title": "小星星", "bpm": 100, "key": "C", "melody": [], "chords": [{"chord": "C", "beats": 4}]}})
  → draft_id
music_edit_score(command="add_note", args={"draft_id": <draft_id>, "track": "melody", "pitch": "C4", "beats": 1, "lyric": "一"})
music_edit_score(command="add_note", args={"draft_id": <draft_id>, "track": "melody", "pitch": "G4", "beats": 1, "lyric": "闪"})
# ... 继续加音符 ...
music_edit_score(command="add_track", args={"draft_id": <draft_id>, "name": "钢琴", "program": 0, "mode": "auto", "style": "block_chords"})
music_edit_score(command="arrange_track", args={"draft_id": <draft_id>, "track_id": "trk_1"})
music_edit_score(command="validate_draft", args={"draft_id": <draft_id>})  → valid=true
music_sing(draft_id=<draft_id>)  → {task_id, song_id, status}
music_get_task(task_id=<task_id>)  轮询至 completed → audio_url

【字段约束】
- 草稿 score：必填 title（歌名）、bpm（>0）、melody（≥1 音符）；chords 可空
- melody[] 音符：pitch 科学音高记谱（如 C4、A#3、Bb5），beats>0，lyric 逐字歌词（空串=延音）
- chords[] 和弦：chord 标记（如 C、G7、Am）+ beats>0
- 伴奏轨 program：GM 音色号 0–127（-1=打击乐轨，pitch 用鼓键名如 kick/snare）；style 节奏型 id 见 music_list_instruments
- 命令 args 形状详见 command-protocol.schema.json definitions.args_<command>
"""


def get_skill_definitions() -> list[dict]:
    """
    CXFC 技能清单：virtual-singer-compose（agent 作曲+演唱的完整流程指引）。

    字段与 CX-O-SERVER SkillDefinition 模型对齐
    （name/description/prompt_template/trigger_keywords/trigger_events/auto_inject）。
    """
    return [
        {
            "name": "virtual-singer-compose",
            "description": (
                "虚拟歌手作曲与演唱：根据用户要求生成歌谱 JSON，校验后提交歌曲合成，"
                "轮询任务直至产出可播放的成品音频（歌谱→validate→sing→轮询→audio_url）。"
            ),
            "prompt_template": _COMPOSE_PROMPT_TEMPLATE,
            "trigger_keywords": ["唱歌", "作曲", "写歌", "演唱"],
            "trigger_events": [],
            "auto_inject": True,
        }
    ]


# ---------------------------------------------------------------------------
# /tools、/skills 端点
# ---------------------------------------------------------------------------


@router.get("/tools")
async def list_tools():
    """CXFC 工具清单（主系统注册/刷新时抓取，响应包裹 {"tools": [...]}）"""
    return {"tools": get_tool_definitions()}


@router.get("/skills")
async def list_skills():
    """CXFC 技能清单（响应包裹 {"skills": [...]}）"""
    return {"skills": get_skill_definitions()}


# ---------------------------------------------------------------------------
# /call 工具调用分发
# ---------------------------------------------------------------------------


class CXFCCallRequest(BaseModel):
    """CXFC 工具调用请求（与主系统 CXFCManager.call_tool 的 POST 体一致）"""

    tool: str = Field(..., description="工具名（见 GET /tools）")
    arguments: dict = Field(default_factory=dict, description="工具参数")


async def _handle_edit_score(args: dict) -> dict:
    """
    music_edit_score：命令门面 → CommandResult。

    draft_id 缺省语义：仅 create_draft 允许缺省（新建草稿，忽略 draft_id）；
    其余命令缺省 draft_id 报 COMMAND_ARGS_INVALID。错误码透传 draft_registry。
    """
    command = args.get("command")
    if not isinstance(command, str) or not command:
        return {
            "success": False,
            "error": {
                "code": "COMMAND_ARGS_INVALID",
                "message": "参数 command 缺失或不是字符串",
                "details": {"missing": "command"},
            },
        }
    command_args = args.get("args")
    if not isinstance(command_args, dict):
        return {
            "success": False,
            "error": {
                "code": "COMMAND_ARGS_INVALID",
                "message": "参数 args 缺失或不是 JSON 对象",
                "details": {"missing": "args"},
            },
        }
    # draft_id 按契约是 command_args 的子字段（见 command-protocol.schema.json
    # args_<command>.required: ["draft_id"]，仅 create_draft 允许缺省）
    draft_id = command_args.get("draft_id")
    if command == "create_draft":
        # create_draft 忽略 draft_id（execute_command 内部走独立路径）
        effective_draft_id = draft_id if isinstance(draft_id, str) and draft_id else ""
    else:
        if not (isinstance(draft_id, str) and draft_id):
            return {
                "success": False,
                "error": {
                    "code": "COMMAND_ARGS_INVALID",
                    "message": f"命令 {command!r} 需要 draft_id（仅 create_draft 可缺省）",
                    "details": {"missing": "draft_id"},
                },
            }
        effective_draft_id = draft_id
    result = draft_registry.execute_command(effective_draft_id, command, command_args)
    if result.get("success"):
        return {"success": True, "result": result}
    return {
        "success": False,
        "error": result.get("error", {"code": "SUBMIT_FAILED", "message": "命令执行失败"}),
    }


async def _handle_list_instruments(args: dict) -> dict:
    """music_list_instruments：→ music-inventory 形状 {instrument_groups, styles, drum_keys}"""
    return {"success": True, "result": inventory.get_inventory()}


async def _handle_validate_score(args: dict) -> dict:
    """music_validate_score：歌谱 → {valid, errors, normalized_score?}（v1 自动迁移 v2）"""
    score = args.get("score")
    if not isinstance(score, dict):
        return {"success": False, "error": "参数 score 缺失或不是 JSON 对象"}
    ok, errors, normalized = validate_score(score)
    result: dict[str, Any] = {"valid": ok, "errors": errors}
    if ok:
        result["normalized_score"] = normalized
    return {"success": True, "result": result}


async def _handle_sing(args: dict) -> dict:
    """
    music_sing：draft_id（走 submit_draft）或 score（走原流水线）→ {song_id, task_id, status}。

    draft_id 优先：调 draft_registry.submit_draft（物化 auto 轨 + 校验 + 提交），
    透传 CommandResult；草稿保留可继续编辑。
    score 路径：提交前快速校验（非法歌谱快速失败，不产生 failed 任务）。
    """
    draft_id = args.get("draft_id")
    if isinstance(draft_id, str) and draft_id:
        # draft_id 路径：草稿 → submit_draft
        params: dict[str, Any] = {}
        for key in ("svc_model", "speaker_id", "transpose", "vocal_gain", "accompaniment_gain"):
            if key in args:
                params[key] = args[key]
        cr = draft_registry.submit_draft(draft_id, **params)
        if cr.get("success"):
            logger.info("CXFC music_sing(draft_id) 已受理: draft_id=%s", draft_id)
            return {"success": True, "result": cr.get("result", {})}
        return {
            "success": False,
            "error": cr.get("error", {"code": "SUBMIT_FAILED", "message": "提交失败"}),
        }
    # score 路径：原合成流水线
    score = args.get("score")
    if not isinstance(score, dict):
        return {"success": False, "error": "参数 draft_id 或 score 至少提供一个"}
    ok, errors, _ = validate_score(score)
    if not ok:
        return {"success": False, "error": "歌谱校验失败: " + "; ".join(errors)}
    try:
        song_id = await get_song_pipeline().submit(
            score,
            svc_model=(args.get("svc_model") or "").strip() or None,
            speaker_id=int(args.get("speaker_id", 0)),
            transpose=int(args.get("transpose", 0)),
            vocal_gain=float(args.get("vocal_gain", DEFAULT_VOCAL_GAIN)),
            accompaniment_gain=float(args.get("accompaniment_gain", DEFAULT_ACCOMPANIMENT_GAIN)),
        )
    except (TypeError, ValueError) as exc:
        return {"success": False, "error": f"参数非法: {exc}"}
    logger.info("CXFC music_sing 已受理: song_id=%s", song_id)
    return {
        "success": True,
        "result": {"song_id": song_id, "task_id": song_id, "status": "pending"},
    }


async def _handle_get_task(args: dict) -> dict:
    """music_get_task：task_id → 任务元数据（status/stage/progress/error/audio_url/steps）"""
    task_id = args.get("task_id") or args.get("song_id")
    if not isinstance(task_id, str) or not task_id:
        return {"success": False, "error": "参数 task_id 缺失或不是字符串"}
    info = get_song_pipeline().get_task(task_id)
    if info is None:
        return {"success": False, "error": f"任务不存在: {task_id}"}
    return {"success": True, "result": info}


async def _handle_list_songs(args: dict) -> dict:
    """music_list_songs：→ {songs: [metadata 摘要]}（与 /api/music/songs 摘要口径一致）"""
    songs = get_song_pipeline().list_songs()
    summaries = [
        {
            "song_id": s.get("song_id"),
            "title": s.get("title"),
            "status": s.get("status"),
            "stage": s.get("stage"),
            "progress": s.get("progress"),
            "error": s.get("error"),
            "created_at": s.get("created_at"),
            "finished_at": s.get("finished_at"),
            "audio_url": s.get("audio_url"),
        }
        for s in songs
    ]
    return {"success": True, "result": {"songs": summaries}}


# 工具名 → 处理器（新增工具须同时在 get_tool_definitions() 中登记）
_TOOL_HANDLERS: dict[str, Callable[[dict], Awaitable[dict]]] = {
    "music_edit_score": _handle_edit_score,
    "music_list_instruments": _handle_list_instruments,
    "music_validate_score": _handle_validate_score,
    "music_sing": _handle_sing,
    "music_get_task": _handle_get_task,
    "music_list_songs": _handle_list_songs,
}


@router.post("/call")
async def call_tool(request: CXFCCallRequest):
    """
    CXFC 工具调用入口：按 tool 分发到对应处理器。

    响应形状 {"success", "result"|"error"}，HTTP 恒 200：
    未知工具 / 参数非法 / 任务不存在均走 success=false（协议约定，
    主系统 call_tool 原样透传本响应给调用方）。
    """
    handler = _TOOL_HANDLERS.get(request.tool)
    if handler is None:
        available = ", ".join(sorted(_TOOL_HANDLERS))
        logger.info("CXFC /call 拒绝未知工具: %r", request.tool)
        return {
            "success": False,
            "error": f"未知工具: {request.tool}（可用工具: {available}）",
        }
    try:
        return await handler(request.arguments or {})
    except Exception as exc:  # 处理器未预期的内部错误，统一转为 success=false
        logger.error("CXFC /call 工具执行异常: tool=%s error=%s", request.tool, exc)
        return {"success": False, "error": f"工具执行失败: {type(exc).__name__}: {exc}"}
