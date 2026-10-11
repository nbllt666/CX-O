"""
受控音频上传 API（翻唱音频入口）

对应 spec：split-audio-workstation-cxfc-modelstation「翻唱音频受控上传」。

POST /api/audio-uploads（multipart/form-data，字段 file）：
- 扩展名白名单 .wav/.mp3/.flac/.ogg/.m4a（大小写不敏感），大小上限默认 50MB
  （config.audio_upload.max_size_mb 可配置）；
- 落盘 data/input/（SoVITSSVCInferer allowed_audio_root 白名单根，上传即可推理，
  目录缺失自动创建；不暴露于 audio-files category 服务，不新增 URL 读取面）；
- 文件名服务端重生成 {uuid_hex[:12]}{原扩展名}，防路径穿越与覆盖；
- 非法扩展/超限 → HTTPException 400 可读错误，不落盘；
- 响应 {"status":"success","filename":...,"audio_path":"<落盘文件绝对路径>"}，
  audio_path 可直接作为 POST /api/sovits-svc/infer 的 audio_path 入参
  （绝对路径 resolve 后天然落在 infer 白名单根内，对 CWD 免疫）。
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

import anyio
from fastapi import APIRouter, HTTPException, UploadFile

from workstation.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# 允许的音频扩展名白名单（大小写不敏感；与上传校验一一对应）
_ALLOWED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
_UPLOAD_CHUNK_BYTES = 1024 * 1024


@router.post("")
async def upload_audio(file: UploadFile):
    """受控上传翻唱音频：白名单扩展 + 大小上限校验后落盘 data/input/。"""
    settings = get_settings()
    upload_cfg = settings.audio_upload

    # 1. 扩展名白名单校验（原始文件名仅用于取扩展名，不参与落盘命名）
    original_name = file.filename or ""
    suffix = Path(original_name).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"不支持的音频格式: {suffix or '(无扩展名)'}；"
                f"仅允许: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            ),
        )

    # 2. 只读取限额内的数据及至多一个越界字节，内存不随文件总量增长。
    max_bytes = max(1, int(upload_cfg.max_size_mb)) * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大: {file.size} 字节，超过上限 {upload_cfg.max_size_mb}MB",
        )

    # 3. 服务端重生成文件名（uuid 片段 + 原扩展名），防穿越防覆盖
    input_dir = Path(upload_cfg.input_dir).resolve()
    input_dir.mkdir(parents=True, exist_ok=True)  # auto_init：目录缺失自动创建
    filename = f"{uuid.uuid4().hex[:12]}{suffix}"
    dest = input_dir / filename

    # 防御性校验：resolve 后必须仍位于白名单根内（命名已重生成，此处兜底）
    if not dest.resolve().is_relative_to(input_dir):
        raise HTTPException(status_code=400, detail="非法落盘路径")

    temporary = dest.with_suffix(dest.suffix + ".part")
    size = 0
    output = None
    try:
        # 获取/关闭句柄必须免受取消作用域影响，否则 Windows 无法清理已打开文件。
        with anyio.CancelScope(shield=True):
            output = await anyio.open_file(temporary, "xb")
        while True:
            chunk = await file.read(min(_UPLOAD_CHUNK_BYTES, max_bytes - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件过大，超过上限 {upload_cfg.max_size_mb}MB",
                )
            await output.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="上传文件为空")
        with anyio.CancelScope(shield=True):
            await output.aclose()
        output = None
        await anyio.lowlevel.checkpoint_if_cancelled()
        temporary.replace(dest)
    finally:
        # 包括超限、读取/写入错误与请求取消：不保留不完整的可推理音频。
        with anyio.CancelScope(shield=True):
            if output is not None:
                await output.aclose()
            temporary.unlink(missing_ok=True)

    logger.info(
        "Audio uploaded: %s (%d bytes, original=%r) -> %s",
        filename,
        size,
        original_name,
        dest,
    )
    return {
        "status": "success",
        "filename": filename,
        "audio_path": str(dest.resolve()),
    }
