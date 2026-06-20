"""
VoxCPM 参考音频生成 API
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


class VoxCPMGenerateRequest(BaseModel):
    mode: str = Field(default="design", pattern="^(design|controllable_clone|ultimate_clone)$")
    text: str
    control: str = ""
    reference_audio_path: Optional[str] = None
    prompt_audio_path: Optional[str] = None
    prompt_text: Optional[str] = None
    # 注意：output_path 不再接受客户端输入，统一由服务端生成 UUID 路径，避免路径遍历风险。
    output_path: Optional[str] = Field(default=None, exclude=True)
    cfg_value: Optional[float] = None
    inference_timesteps: Optional[int] = None


@router.post("/generate")
async def generate(request: VoxCPMGenerateRequest):
    if request.mode == "design":
        if not request.text:
            raise HTTPException(status_code=400, detail="text is required for design mode")
    elif request.mode == "controllable_clone":
        if not request.reference_audio_path:
            raise HTTPException(status_code=400, detail="reference_audio_path is required for controllable_clone mode")
    elif request.mode == "ultimate_clone":
        if not request.prompt_audio_path:
            raise HTTPException(status_code=400, detail="prompt_audio_path is required for ultimate_clone mode")
        if not request.prompt_text:
            raise HTTPException(status_code=400, detail="prompt_text is required for ultimate_clone mode")

    try:
        from workstation.services.voxcpm_client import get_voxcpm_client
        from workstation.config import get_settings

        settings = get_settings()
        client = get_voxcpm_client(config=settings.voxcpm)

        # output_path 永远由服务端生成，忽略请求体中的 output_path 字段
        output_dir = Path(settings.output.voice_refs_dir) / "voxcpm"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"{uuid.uuid4().hex}.wav")

        kwargs = {}
        if request.cfg_value is not None:
            kwargs["cfg_value"] = request.cfg_value
        if request.inference_timesteps is not None:
            kwargs["inference_timesteps"] = request.inference_timesteps

        if request.mode == "design":
            result_path = await client.design(
                text=request.text,
                control=request.control,
                output_path=output_path,
                **kwargs,
            )
        elif request.mode == "controllable_clone":
            result_path = await client.controllable_clone(
                text=request.text,
                control=request.control,
                reference_audio=request.reference_audio_path,
                output_path=output_path,
                **kwargs,
            )
        elif request.mode == "ultimate_clone":
            result_path = await client.ultimate_clone(
                text=request.text,
                prompt_audio=request.prompt_audio_path,
                prompt_text=request.prompt_text,
                output_path=output_path,
                **kwargs,
            )

        return {"status": "success", "output_filename": result_path.name}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"VoxCPM generate failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_status():
    try:
        from workstation.services.voxcpm_client import get_voxcpm_client
        from workstation.config import get_settings

        settings = get_settings()
        client = get_voxcpm_client(config=settings.voxcpm)
        healthy = await client.health_check()

        return {"status": "healthy" if healthy else "unhealthy", "model_path": settings.voxcpm.model_path}
    except Exception as e:
        logger.error(f"VoxCPM status check failed: {e}")
        return {"status": "unhealthy", "model_path": ""}
