"""
音乐 API 路由：歌谱校验 / MusicXML 导入 / 歌曲合成 / 任务查询 / 歌曲历史

对应 spec：add-voicews-music-cxfc-suite（Task 6）。

- POST /score/validate     歌谱校验，返回 {valid, errors, score?}（HTTP 200，非法歌谱不走 4xx）
- POST /import-musicxml    multipart 上传 MusicXML，返回转换后的歌谱 JSON；非法文件 400
- POST /synthesize         提交歌曲合成任务，202 Accepted 返回 {song_id, status}
- GET  /tasks/{song_id}    任务状态查询（status/stage/progress/error/audio_url/steps）
- GET  /songs              歌曲历史列表（metadata 摘要 + audio_url）
- GET  /songs/{song_id}    单曲详情（完整 metadata）；不存在 404
- DELETE /songs/{song_id}  删除歌曲目录与元数据；运行中任务 409，不存在 404

成品音频经 Task 1 的 /api/audio-files/songs/{song_id}/final.wav 访问，
metadata 中的 audio_url 已含该路径。song_id 合法性复用流水线层的
_SONG_ID_PATTERN 白名单正则（防路径穿越），非法 id 一律 404。

草稿命令总线（spec redesign-composition-staff-editor §5 REST 端点冻结项）：
- POST   /drafts                      创建草稿（空白或种子），返回 CommandResult
- GET    /drafts                      列出草稿摘要（list_drafts() 原样返回）
- GET    /drafts/{draft_id}           获取草稿快照，返回 CommandResult；不存在 404
- DELETE /drafts/{draft_id}           删除草稿，返回 {success: bool}（幂等）
- POST   /drafts/{draft_id}/commands  执行命令，返回 CommandResult
请求/响应形状严格按 command-protocol.schema.json definitions.command_result；
失败时响应体仍为 CommandResult（success=false + error），HTTP 状态码按
x-error-codes 映射（DRAFT_NOT_FOUND→404、COMMAND_*→400、SUBMIT_FAILED→500）。

部署要求与项目整体一致：单 worker 运行（uvicorn --workers 1），
流水线单例与内存注册表不跨进程共享。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from workstation.config import get_settings
from workstation.music import draft_registry
from workstation.music.musicxml_import import MusicXMLImportError, musicxml_to_score
from workstation.music.score import validate_score
from workstation.services.song_pipeline import (
    DEFAULT_ACCOMPANIMENT_GAIN,
    DEFAULT_VOCAL_GAIN,
    get_song_pipeline,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# multipart 上传大小上限（MusicXML 为文本格式，10MB 已非常宽裕）
_MAX_MUSICXML_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class SynthesizeRequest(BaseModel):
    """歌曲合成请求：歌谱 + 可选声库/SVC 模型 + 混音增益"""

    score: dict = Field(..., description="歌谱 JSON（结构由流水线 validate 阶段校验）")
    voice_bank: Optional[str] = Field(None, description="声库标识（Mock 引擎忽略）")
    svc_model: Optional[str] = Field(None, description="SVC 模型路径；空表示不变声")
    speaker_id: int = Field(0, description="SVC 说话人 id")
    transpose: int = Field(0, description="SVC 变调（半音数）")
    vocal_gain: float = Field(DEFAULT_VOCAL_GAIN, description="歌声增益（≥0）")
    accompaniment_gain: float = Field(DEFAULT_ACCOMPANIMENT_GAIN, description="伴奏增益（≥0）")


# ---------------------------------------------------------------------------
# 歌谱校验与 MusicXML 导入
# ---------------------------------------------------------------------------


@router.post("/score/validate")
async def validate_score_endpoint(payload: dict):
    """
    校验歌谱 JSON 并规范化（填充默认值）。

    契约（spec「歌谱模型与校验」）：合法 → {valid: true, errors: [], score: 规范化歌谱}；
    非法 → {valid: false, errors: [逐条可读错误]}，HTTP 均为 200。
    """
    ok, errors, normalized = validate_score(payload)
    if not ok:
        return {"valid": False, "errors": errors}
    return {"valid": True, "errors": [], "score": normalized}


@router.post("/import-musicxml")
async def import_musicxml(file: UploadFile):
    """
    上传 MusicXML 文件并转换为内部歌谱 JSON（music21 解析）。

    契约（spec「MusicXML 导入」）：合法 → 200 返回歌谱 JSON（可直接进入合成流程）；
    损坏/不支持 → 400 + 可读错误。
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="MusicXML 内容为空")
    if len(content) > _MAX_MUSICXML_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"MusicXML 文件过大（{len(content)} 字节，上限 {_MAX_MUSICXML_BYTES}）",
        )
    try:
        score = musicxml_to_score(content)
    except MusicXMLImportError as exc:
        logger.info("MusicXML 导入被拒: filename=%r error=%s", file.filename, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # music21 未预期的解析异常，统一转为可读 400
        logger.warning("MusicXML 导入异常: filename=%r error=%s", file.filename, exc)
        raise HTTPException(status_code=400, detail=f"MusicXML 解析失败: {exc}")
    return score


# ---------------------------------------------------------------------------
# 歌曲合成与任务/历史查询
# ---------------------------------------------------------------------------


@router.post("/synthesize", status_code=202)
async def synthesize(request: SynthesizeRequest):
    """
    提交歌曲合成任务：立即返回 {song_id, status}，流水线后台执行。

    歌谱合法性不在此拦截（任务进入 validate 阶段判定，非法歌谱使任务 failed
    且错误可读）；增益等标量参数非法（负数/NaN）在提交时 400 快速失败。
    """
    pipeline = get_song_pipeline()
    try:
        song_id = await pipeline.submit(
            request.score,
            svc_model=request.svc_model,
            speaker_id=request.speaker_id,
            transpose=request.transpose,
            vocal_gain=request.vocal_gain,
            accompaniment_gain=request.accompaniment_gain,
            voice_bank=request.voice_bank or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info("歌曲合成任务已受理: song_id=%s", song_id)
    return {"song_id": song_id, "status": "pending"}


@router.get("/tasks/{song_id}")
async def get_task(song_id: str):
    """查询任务状态：status / stage / progress / error / steps / audio_url 等；不存在 404。"""
    info = get_song_pipeline().get_task(song_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"歌曲任务不存在: {song_id}")
    return info


@router.get("/songs")
async def list_songs():
    """歌曲历史列表：metadata 摘要 + audio_url，按创建时间倒序。"""
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
    return {"songs": summaries}


@router.get("/songs/{song_id}")
async def get_song(song_id: str):
    """单曲详情：完整 metadata（含歌谱快照、参数、文件清单）；不存在 404。"""
    info = get_song_pipeline().get_task(song_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"歌曲不存在: {song_id}")
    return info


@router.delete("/songs/{song_id}")
async def delete_song(song_id: str):
    """
    删除歌曲：移除歌曲目录（含成品音频与 metadata）并弹出内存注册。

    - song_id 非法（路径穿越尝试）或不存在 → 404（复用流水线白名单正则）；
    - 任务 pending/running → 409（运行中任务不可删除，避免后台流水线写半截文件）；
    - 目录删除前做 resolve + is_relative_to 防穿越双保险。
    """
    pipeline = get_song_pipeline()
    info = pipeline.get_task(song_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"歌曲不存在: {song_id}")

    if info.get("status") in ("pending", "running"):
        raise HTTPException(status_code=409, detail=f"歌曲任务进行中，不可删除: {song_id}")

    songs_dir = Path(get_settings().music.songs_dir).resolve()
    song_dir = (songs_dir / song_id).resolve()
    if not song_dir.is_relative_to(songs_dir):
        # 理论上被 _SONG_ID_PATTERN 拦截，防御性双保险
        logger.warning("歌曲删除路径穿越拦截: %s -> %s", song_id, song_dir)
        raise HTTPException(status_code=403, detail="非法歌曲路径")

    if song_dir.is_dir():
        shutil.rmtree(song_dir)
    # 内存注册表同步弹出（磁盘记录已随目录删除）
    pipeline._tasks.pop(song_id, None)  # noqa: SLF001 - 流水线未提供删除接口，API 层同步清理
    logger.info("歌曲已删除: song_id=%s", song_id)
    return {"status": "success", "song_id": song_id}


# ---------------------------------------------------------------------------
# 草稿命令总线（spec redesign-composition-staff-editor §5 REST 端点冻结项）
#
# 对接 workstation.music.draft_registry 公开函数，不绕过 execute_command
# 直接改草稿。请求/响应形状严格按 command-protocol.schema.json
# definitions.command_result；失败时响应体仍为 CommandResult（success=false
# + error），HTTP 状态码按 x-error-codes 映射。
# ---------------------------------------------------------------------------

# command-protocol.schema.json x-error-codes → HTTP 状态码
_DRAFT_ERROR_STATUS: dict[str, int] = {
    "DRAFT_NOT_FOUND": 404,
    "COMMAND_UNKNOWN": 400,
    "COMMAND_ARGS_INVALID": 400,
    "SCORE_VALIDATION_FAILED": 400,
    "NOTE_NOT_FOUND": 400,
    "TRACK_NOT_FOUND": 400,
    "CHORD_NOT_FOUND": 400,
    "STYLE_UNKNOWN": 400,
    "TRACK_MODE_INVALID": 400,
    "SUBMIT_FAILED": 500,
}


class CreateDraftRequest(BaseModel):
    """POST /drafts 请求体：score 缺省建空白草稿（C4 全音符占位）。

    draft_id 字段为兼容预留——当前由服务端生成（draft_registry.create_draft
    总返回新 uuid），传入将被忽略。契约 args_create_draft 仅声明 score。
    """

    score: Optional[dict] = Field(
        None,
        description="初始歌谱（v1 或 v2，v1 自动迁移）；缺省创建空白草稿",
    )
    draft_id: Optional[str] = Field(
        None,
        description="可选；当前由服务端生成，传入将被忽略",
    )


class CommandRequest(BaseModel):
    """POST /drafts/{draft_id}/commands 请求体。

    args 内需含 draft_id 字段（command-protocol x-notes：args_<command> schema
    多数 required draft_id）。路径 draft_id 为寻址真源；args 内 draft_id 仅
    满足 schema 校验，二者应一致。缺 draft_id 时 schema 校验失败 → 400。
    """

    command: str = Field(
        ...,
        description="命令名（command-protocol.schema.json properties.command.enum）",
    )
    args: dict = Field(
        default_factory=dict,
        description="命令参数（形状随 command 而变，见 definitions.args_<command>）",
    )


def _draft_failure_response(result: dict) -> JSONResponse:
    """将 draft_registry success=false 结果转为 HTTP 错误响应。

    响应体保持 CommandResult 形状（success=false + error{code, message, details?}），
    HTTP 状态码按错误码映射；未知错误码兜底 400。
    """
    code = result.get("error", {}).get("code", "")
    status = _DRAFT_ERROR_STATUS.get(code, 400)
    return JSONResponse(status_code=status, content=result)


@router.post("/drafts")
async def create_draft_endpoint(request: CreateDraftRequest):
    """
    创建草稿。

    - score 缺省 → 空白草稿（title=未命名、bpm=120、melody 置 C4 全音符占位）
    - score 提供 → v1 输入自动迁移到 v2，校验失败 → 400（SCORE_VALIDATION_FAILED）
    - 响应：CommandResult（success=true → 200；success=false → 映射状态码）
    """
    result = draft_registry.create_draft(request.score)
    if not result.get("success"):
        return _draft_failure_response(result)
    return result


@router.get("/drafts")
async def list_drafts_endpoint():
    """
    列出草稿摘要（按 updated_at 倒序）。

    响应：list[{draft_id, title, version, updated_at}]（list_drafts() 原样返回）。
    """
    return draft_registry.list_drafts()


@router.get("/drafts/{draft_id}")
async def get_draft_endpoint(draft_id: str):
    """
    获取草稿快照（不增 version）。

    - 存在 → 200 + CommandResult（snapshot + version）
    - 不存在 → 404 + CommandResult（DRAFT_NOT_FOUND）
    """
    result = draft_registry.get_draft(draft_id)
    if not result.get("success"):
        return _draft_failure_response(result)
    return result


@router.delete("/drafts/{draft_id}")
async def delete_draft_endpoint(draft_id: str):
    """
    删除草稿（内存注册表 + 落盘文件）。

    幂等：不存在返回 {success: false}（草稿本就不存在），HTTP 200。
    存在则返回 {success: true}。
    """
    existed = draft_registry.delete_draft(draft_id)
    return {"success": existed}


@router.post("/drafts/{draft_id}/commands")
async def execute_command_endpoint(draft_id: str, request: CommandRequest):
    """
    执行命令（命令执行器唯一入口，与 CXFC music_edit_score 共用）。

    - 路径 draft_id 为寻址真源；args 原样传入 execute_command
    - args 缺 draft_id（或其它必需字段）→ schema 校验失败 → 400（COMMAND_ARGS_INVALID）
    - 未知命令 → 400（COMMAND_UNKNOWN）；草稿不存在 → 404（DRAFT_NOT_FOUND）
    - 响应：CommandResult（success=true → 200；success=false → 映射状态码）
    """
    result = draft_registry.execute_command(draft_id, request.command, request.args)
    if not result.get("success"):
        return _draft_failure_response(result)
    return result
