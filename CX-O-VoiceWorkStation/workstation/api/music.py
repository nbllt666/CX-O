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

部署要求与项目整体一致：单 worker 运行（uvicorn --workers 1），
流水线单例与内存注册表不跨进程共享。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field

from workstation.config import get_settings
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
