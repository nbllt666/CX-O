"""
Orpheus TTS 合成 API

提供三种端点：
- POST /synthesize：非流式合成，落盘 WAV，返回 audio_url
- POST /synthesize-stream：流式合成，返回 audio/wav stream（PCM chunks）
- GET /status：健康检查

合成结果落盘到 voice_refs_dir/orpheus 目录，通过 /api/audio-files/orpheus/<filename> 服务。
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


# ----------------------------------------------------------------------
# 请求模型
# ----------------------------------------------------------------------

class OrpheusSynthesizeRequest(BaseModel):
    """Orpheus 合成请求。

    text 中的 <laugh>/<giggle> 等 emotion 标签原样透传到 Orpheus 模型。
    """
    text: str = Field(..., min_length=1, description="待合成文本（含可选 emotion 标签）")
    voice: Optional[str] = Field(default=None, description="Orpheus 预设音色（如 tara/leo），None 用配置默认值")
    stream: bool = Field(default=False, description="是否流式合成（此字段在 /synthesize 端点忽略，仅 /synthesize-stream 流式）")


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------

def _get_orpheus_output_dir() -> Path:
    """获取 orpheus 合成结果输出目录（voice_refs_dir/orpheus），确保目录存在。"""
    from workstation.config import get_settings
    settings = get_settings()
    output_dir = Path(settings.output.voice_refs_dir) / "orpheus"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _get_client():
    """从全局配置构造 OrpheusClient 单例。"""
    from workstation.config import get_settings
    from workstation.services.orpheus_client import get_orpheus_client

    settings = get_settings()
    return get_orpheus_client(
        url=settings.orpheus.url,
        voice=settings.orpheus.voice,
        timeout=settings.orpheus.timeout,
    )


# ----------------------------------------------------------------------
# 路由
# ----------------------------------------------------------------------

@router.post("/synthesize")
async def synthesize(request: OrpheusSynthesizeRequest):
    """
    非流式合成：调用 Orpheus vLLM 服务，返回完整 WAV bytes，
    落盘后返回 audio_url 供前端播放。

    emotion 标签（<laugh> 等）原样透传。
    """
    from workstation.services.orpheus_client import OrpheusError

    client = _get_client()
    try:
        wav_bytes = await client.synthesize(text=request.text, voice=request.voice)

        # 落盘到 orpheus 输出目录
        output_dir = _get_orpheus_output_dir()
        filename = f"{uuid.uuid4().hex}.wav"
        output_path = output_dir / filename
        output_path.write_bytes(wav_bytes)

        logger.info(f"Orpheus 非流式合成完成: {filename} ({len(wav_bytes)} bytes)")

        return {
            "status": "success",
            "audio_url": f"/api/audio-files/orpheus/{filename}",
            "format": "wav",
        }
    except OrpheusError as e:
        logger.error(f"Orpheus 合成失败: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"Orpheus 合成异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/synthesize-stream")
async def synthesize_stream(request: OrpheusSynthesizeRequest):
    """
    流式合成：调用 Orpheus vLLM 服务，逐块 yield PCM chunks，
    返回 audio/wav StreamingResponse。

    emotion 标签（<laugh> 等）原样透传。
    流式响应跳过 44 字节 WAV header，仅返回 PCM 数据。
    """
    from workstation.services.orpheus_client import OrpheusError

    client = _get_client()

    async def _stream_generator():
        try:
            async for chunk in client.synthesize_stream(text=request.text, voice=request.voice):
                yield chunk
        except OrpheusError as e:
            logger.error(f"Orpheus 流式合成失败: {e}")
            # 流式响应已开始，无法改 HTTP 状态码，仅记录错误
            # 前端检测到流中断即知服务异常

    return StreamingResponse(
        _stream_generator(),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲，确保真流式
        },
    )


@router.get("/status")
async def get_status():
    """
    Orpheus 服务健康检查。

    返回 {status: healthy/unhealthy, url, voice}。
    不可达时返回 unhealthy，不影响其他功能。
    """
    client = _get_client()
    healthy = await client.health_check()

    from workstation.config import get_settings
    settings = get_settings()

    return {
        "status": "healthy" if healthy else "unhealthy",
        "url": settings.orpheus.url,
        "voice": settings.orpheus.voice,
    }
