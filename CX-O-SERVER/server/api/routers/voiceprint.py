"""声纹识别 REST 端点（Task 5/6）。

对外暴露的声纹档案管理与状态查询接口，挂在 /api 前缀下：

  - GET    /api/voiceprint/profiles           声纹档案列表
  - POST   /api/voiceprint/profiles           注册/更新声纹档案（body: {name, audio(base64)}）
  - DELETE /api/voiceprint/profiles/{name}    删除声纹档案
  - GET    /api/voiceprint/status             声纹服务状态

业务逻辑委托给 server.services.voiceprint_service，本模块只做入参校验与
异常 → HTTP 状态码 映射（对齐 server/api/response.py 的错误响应规范）。
"""
from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger
from server.services import voiceprint_service
from server.services.voiceprint_service import (
    VoiceprintUnavailableError,
    VoiceprintServiceError,
)

router = APIRouter(prefix="/voiceprint", tags=["voiceprint"])
logger = get_contextual_logger(__name__)

# 上传防呆：单次请求音频（解码后）大小上限 20MB（与 audio.py ASR 入口同口径）
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class RegisterProfileRequest(BaseModel):
    """注册声纹档案请求：name 为说话人名，audio 为音频文件的 base64 字符串。"""

    name: str = ""
    audio: str = ""


def _decode_audio(payload: RegisterProfileRequest) -> bytes:
    """从 base64 解码音频字节；超限抛 413，解码失败或内容为空抛 400。"""
    if not payload.audio:
        raise HTTPException(status_code=400, detail="audio 不能为空")
    # 上传防呆：base64 编码长度预检（4/3 膨胀 + padding 余量），超限 413
    if len(payload.audio) > _MAX_UPLOAD_BYTES * 4 // 3 + 4:
        raise HTTPException(status_code=413, detail="音频文件过大")
    try:
        audio_bytes = base64.b64decode(payload.audio)
    except (binascii.Error, ValueError) as e:
        # 错误文案收敛：不透传解码器内部报错（详情留日志）
        logger.warning(f"audio base64 解码失败: {e}")
        raise HTTPException(status_code=400, detail="音频解码失败，请检查文件格式")
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio 解码内容为空")
    return audio_bytes


@router.get("/profiles")
def list_profiles():
    """返回全部声纹档案摘要（暴露 embeddings_count，不暴露原始向量）。"""
    return {"profiles": voiceprint_service.list_profiles()}


@router.post("/profiles", status_code=201)
async def register_profile(payload: RegisterProfileRequest):
    """注册/更新声纹档案。name 非法 → 400；容器不可用 → 503。"""
    audio_bytes = _decode_audio(payload)
    try:
        summary = await voiceprint_service.register(payload.name, audio_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except VoiceprintUnavailableError:
        raise HTTPException(status_code=503, detail="voiceprint service unavailable")
    except VoiceprintServiceError as e:
        # 错误文案收敛：不透传内部实现细节（详情留日志）
        logger.error(f"声纹档案注册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="声纹服务处理失败")
    return {"profile": summary}


@router.delete("/profiles/{name}")
async def delete_profile(name: str):
    """删除指定声纹档案；存在删除成功 → 200，不存在 → 404。"""
    try:
        deleted = await voiceprint_service.delete(name)
    except VoiceprintServiceError as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到该声纹档案")
    return {"status": "success", "name": name}


@router.get("/status")
async def status():
    """声纹服务状态：可用性 + 档案数 + 相似度阈值。"""
    return await voiceprint_service.get_status()