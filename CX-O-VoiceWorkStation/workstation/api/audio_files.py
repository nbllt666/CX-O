"""
受控音频文件服务 API

提供 GET /api/audio-files/{category}/{filename}，将生成/推理/合成产物
以 URL 形式暴露给前端播放。category 白名单映射到受控目录，
filename 允许一层子路径（如 songs/<song_id>/final.wav），
解析后路径必须位于对应目录内，否则拒绝访问（防路径穿越）。

校验风格复用 services/security_utils.py：resolve() + is_relative_to()。
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from workstation.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# 允许的音频扩展名 → media_type；不在表内的扩展名一律 404，避免暴露任意文件类型
_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}


def _category_dirs() -> dict[str, Path]:
    """category 白名单 → 受控目录映射（每次请求取最新配置）。

    - voxcpm:      VoxCPM 生成结果目录 <voice_refs_dir>/voxcpm
    - svc-results: So-VITS-SVC 推理结果目录（sovits_svc_infer 直接落盘在
                   output_dir 根目录，文件名为 converted_<stem>.wav，无子目录）
    - songs:       歌曲流水线成品目录 data/songs（允许 <song_id>/final.wav 子路径）
    """
    settings = get_settings()
    return {
        "voxcpm": Path(settings.output.voice_refs_dir) / "voxcpm",
        "svc-results": Path(settings.sovits_svc.output_dir),
        "songs": Path(settings.music.songs_dir),
    }


@router.get("/{category}/{filename:path}")
async def serve_audio_file(category: str, filename: str):
    """按 category/filename 返回受控目录内的音频文件。"""
    base_dir = _category_dirs().get(category)
    if base_dir is None:
        raise HTTPException(status_code=404, detail=f"Unknown audio category: {category}")

    media_type = _MEDIA_TYPES.get(Path(filename).suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=404, detail="Unsupported audio file type")

    base_resolved = base_dir.resolve()
    try:
        resolved = (base_resolved / filename).resolve()
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid file path")

    # 防路径穿越：解析后路径必须位于受控目录之内
    if not resolved.is_relative_to(base_resolved):
        logger.warning(f"Audio file path traversal blocked: {category}/{filename} -> {resolved}")
        raise HTTPException(status_code=403, detail="Access outside the controlled directory is forbidden")

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(path=str(resolved), media_type=media_type, filename=resolved.name)
