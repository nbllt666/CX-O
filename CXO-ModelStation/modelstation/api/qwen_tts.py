"""Qwen3-TTS 本地试音 API（参考音频克隆 / 音色描述设计）。

不依赖外部 vLLM 运行时：合成链路走 ``engines/Qwen3TTS`` 本地引擎
（模型常驻，见 services/qwen3tts_local.py）。
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modelstation.config import get_settings
from modelstation.services.qwen3tts_local import (
    LocalQwen3TTSError,
    get_local_qwen3tts_client,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_TEXT_MAX = 500


class QwenTTSInferRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=_TEXT_MAX)
    mode: Literal["clone", "design"] = "clone"
    # clone：参考音频（data/input 白名单内）与可选转写
    ref_audio_path: Optional[str] = None
    ref_text: Optional[str] = None
    # design：音色描述（自然语言）
    voice_description: Optional[str] = None


def _input_dir() -> Path:
    return Path(get_settings().sovits_svc.input_dir).resolve()


def _audition_dir() -> Path:
    return Path(get_settings().sovits_svc.audition_dir).resolve()


def _validate_ref(path: str) -> Path:
    p = Path(path).resolve()
    root = _input_dir()
    if not p.is_file() or not p.is_relative_to(root):
        raise HTTPException(status_code=400, detail=f"参考音频不在允许目录内: {path}")
    return p


@router.get("/references")
async def list_references():
    """列出 data/input 下的参考音频（试音下拉用）。"""
    root = _input_dir()
    items = []
    if root.is_dir():
        for p in sorted(root.glob("*.wav")):
            items.append({"name": p.name, "path": str(p), "size": p.stat().st_size})
    return {"references": items}


@router.post("/infer")
async def infer(request: QwenTTSInferRequest):
    """本地 Qwen3-TTS 合成：clone=参考音频克隆，design=音色描述设计。"""
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    out_dir = _audition_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = uuid.uuid4().hex[:8]
    out_path = out_dir / f"qwen_{request.mode}_{suffix}.wav"
    client = get_local_qwen3tts_client()
    try:
        if request.mode == "clone":
            if not request.ref_audio_path:
                raise HTTPException(status_code=400, detail="clone 模式需要 ref_audio_path")
            ref = _validate_ref(request.ref_audio_path)
            await client.synthesize_cosyvoice_zero(
                text=text,
                ref_audio_path=ref,
                ref_text=request.ref_text or "",
                output_path=out_path,
            )
        else:
            desc = (request.voice_description or "").strip()
            if not desc:
                raise HTTPException(status_code=400, detail="design 模式需要 voice_description")
            await client.synthesize_voicedesign(
                text=text, voice_description=desc, output_path=out_path
            )
    except HTTPException:
        raise
    except LocalQwen3TTSError as exc:
        logger.error("Qwen3-TTS 本地合成失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Qwen3-TTS 本地合成异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not out_path.is_file():
        raise HTTPException(status_code=500, detail="合成完成但输出文件不存在")
    return {
        "status": "success",
        "output_filename": out_path.name,
        "audio_url": f"/api/audio-files/audition/{out_path.name}",
    }
