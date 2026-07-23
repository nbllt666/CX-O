"""
CXFC 插件端点：GET /tools、GET /skills、POST /call

对应 spec：add-voicews-music-cxfc-suite（Task 7.1）。
VoiceWorkStation 自身即 CX-O 主系统的 CXFC 插件，agent 经主系统
POST /cxfc/plugins/{plugin_id}/call 转发到本模块的 POST /call 完成作曲演唱。

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

import logging
from typing import Any, Awaitable, Callable

from fastapi import APIRouter
from pydantic import BaseModel, Field

from workstation.music.score import SCORE_SCHEMA, validate_score
from workstation.services.song_pipeline import (
    DEFAULT_ACCOMPANIMENT_GAIN,
    DEFAULT_VOCAL_GAIN,
    get_song_pipeline,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# 工具与技能清单（/tools、/skills 响应与 CXFC 注册载荷共用的唯一定义源）
# ---------------------------------------------------------------------------


def get_tool_definitions() -> list[dict]:
    """
    CXFC 工具清单：name/description/parameters（parameters 为 JSON Schema）。

    歌谱结构直接引用 music.score.SCORE_SCHEMA（Task 2 的契约），
    与 spec「通过 GET /tools 的 parameters 字段向 agent 发布」一致。
    """
    return [
        {
            "name": "music_validate_score",
            "description": (
                "校验歌谱 JSON 是否符合 VoiceWorkStation 歌谱规范。"
                "返回 {valid, errors, score?}：valid 为是否合法，errors 为逐条可读错误"
                "（含字段定位），合法时附带默认值填充后的规范化歌谱。作曲后、演唱前必须先校验。"
            ),
            "parameters": {
                "type": "object",
                "required": ["score"],
                "properties": {
                    "score": SCORE_SCHEMA,
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
            ),
            "parameters": {
                "type": "object",
                "required": ["score"],
                "properties": {
                    "score": SCORE_SCHEMA,
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


_COMPOSE_PROMPT_TEMPLATE = """你是虚拟歌手作曲与演唱助手。当用户要求作曲、写歌、唱歌或演唱时，严格按以下流程完成：

【完整流程】
1. 根据用户要求（主题、风格、情绪、速度、歌词）创作歌谱 JSON
2. 调用 music_validate_score 校验歌谱；若 valid=false，按 errors 逐条修正后重新校验，直至通过
3. 调用 music_sing 提交合成（可选 svc_model 变声、transpose 变调、vocal_gain/accompaniment_gain 增益）
4. 用 music_get_task 轮询任务（task_id 即 music_sing 返回的 song_id），直至 status 为 completed 或 failed
5. completed 时将结果中的 audio_url 交给用户播放；failed 时读取 error 向用户说明原因

【歌谱 JSON 示例】
{
  "title": "小星星",
  "bpm": 100,
  "time_signature": "4/4",
  "key": "C",
  "melody": [
    {"pitch": "C4", "beats": 1.0, "lyric": "一"},
    {"pitch": "C4", "beats": 1.0, "lyric": "闪"},
    {"pitch": "G4", "beats": 1.0, "lyric": "一"},
    {"pitch": "G4", "beats": 1.0, "lyric": "闪"}
  ],
  "chords": [{"chord": "C", "beats": 4}],
  "accompaniment_style": "piano"
}

【字段约束】
- 必填：title（歌名）、bpm（每分钟拍数，>0）、melody（至少 1 个音符）
- melody[] 音符：pitch 为科学音高记谱（如 C4、A#3、Bb5），beats 拍数（>0，四分音符=1），lyric 逐字歌词（空串表示延音）
- chords[] 和弦：chord 和弦标记（如 C、G7、Am）+ beats 持续拍数；允许为空数组（仅主旋律，伴奏为静音）
- time_signature 拍号默认 4/4；key 调号默认 C；accompaniment_style 伴奏风格默认 piano
- 完整 JSON Schema 见 music_validate_score 工具 parameters.score 的定义
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


async def _handle_validate_score(args: dict) -> dict:
    """music_validate_score：歌谱 → {valid, errors, score?}"""
    score = args.get("score")
    if not isinstance(score, dict):
        return {"success": False, "error": "参数 score 缺失或不是 JSON 对象"}
    ok, errors, normalized = validate_score(score)
    result: dict[str, Any] = {"valid": ok, "errors": errors}
    if ok:
        result["score"] = normalized
    return {"success": True, "result": result}


async def _handle_sing(args: dict) -> dict:
    """
    music_sing：歌谱 + 可选参数 → {song_id, task_id, status}。

    提交前先做快速校验：非法歌谱直接 success=false 返回逐条可读错误，
    不产生 failed 任务（agent 可立即按错误修正重试，无需轮询失败任务）。
    """
    score = args.get("score")
    if not isinstance(score, dict):
        return {"success": False, "error": "参数 score 缺失或不是 JSON 对象"}
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
