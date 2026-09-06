"""
翻唱音域分析 API（change-id: enhance-cover-pitch-analysis-duet Task 1 骨架 + Task 2 端点）

- POST /analyze       ：源音频音域分析 + 推荐 transpose（最终 URL /api/cover/analyze）
- GET  /model-profiles：模型音域画像列表（最终 URL /api/cover/model-profiles）
- GET  /status        ：能力就绪状态（Task 1 骨架）

analyze 行为（spec「源音频音域分析与自动升降 key」）：
- audio_path 白名单 = data/input（audio-uploads 落盘点），越界/不存在 → 400
- 无声帧不达标时先经 VocalSeparator 分离人声再分析（separation_used 标记）；
  分离引擎错误 → 503（含 setup 指引）；分析失败（voiced 仍不足等）→ 400 可读错误
- 给 model_name 时对照目标画像：recommended_transpose =
  clamp(round(源中位数MIDI − 目标中位数MIDI), ±12)；源跨度 > 目标跨度时附
  range_warning；目标画像不可算（无训练数据/为空）→ 200 + profile_unavailable
  说明（不报错，spec 明确定义）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from workstation.config import get_settings
from workstation.services.vocal_analysis import (
    VoiceAnalysisError,
    analyze_with_separation,
)
from workstation.services.vocal_separator import SeparationError, VocalSeparator
from workstation.services.voice_profile_store import get_profile, list_profiles

logger = logging.getLogger(__name__)
router = APIRouter()

# 推荐转调钳制范围（±12 半音，spec 冻结）
_TRANSPOSE_CLAMP = 12


class AnalyzeRequest(BaseModel):
    """POST /api/cover/analyze 请求体。"""

    audio_path: str
    model_name: Optional[str] = None


def separation_ready() -> bool:
    """分离引擎就绪判定（守卫逻辑，Task 2/3 端点复用）。

    enabled=true 且两引擎目录均存在才算就绪；
    引擎缺失时端点应返回含 tools/setup_separation.py --clone 指引的错误。
    """
    settings = get_settings()
    separation = settings.separation
    if not separation.enabled:
        return False
    return (
        Path(separation.demucs_engine_dir).exists()
        and Path(separation.audiosep_engine_dir).exists()
    )


def separation_unavailable_detail() -> str:
    """引擎未就绪时的统一错误提示（含 setup 指引）。"""
    settings = get_settings()
    if not settings.separation.enabled:
        return "分离引擎未启用（separation.enabled=false），如需使用请在配置中开启"
    return (
        "分离引擎未就绪（engines/demucs 或 engines/AudioSep 缺失）。"
        "请执行 python tools/setup_separation.py --clone 克隆引擎，"
        "并按 DEPLOY-SEPARATION.md 安装依赖与权重"
    )


@router.get("/status")
async def status():
    """骨架状态端点：分离/音域分析能力就绪情况（守卫逻辑预建）。"""
    settings = get_settings()
    return {
        "status": "success",
        "separation_ready": separation_ready(),
        "separation": {
            "enabled": settings.separation.enabled,
            "demucs_engine_dir": settings.separation.demucs_engine_dir,
            "audiosep_engine_dir": settings.separation.audiosep_engine_dir,
            "demucs_model": settings.separation.demucs_model,
        },
        "cover_analysis": {
            "training_data_dir": settings.cover_analysis.training_data_dir,
            "voice_profiles_dir": settings.cover_analysis.voice_profiles_dir,
            "f0_confidence": settings.cover_analysis.f0_confidence,
        },
    }


def _validate_input_path(audio_path: str) -> Path:
    """analyze 输入白名单校验：audio_path 必须 resolve 后位于 data/input 内。

    白名单口径对齐 audio_uploads 落盘点（spec 冻结：上传即可分析）。
    越界 / 路径非法 / 文件不存在 → HTTPException 400。
    """
    input_root = Path(get_settings().audio_upload.input_dir).resolve()
    try:
        resolved = Path(audio_path).resolve()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"非法 audio_path: {audio_path} ({e})")
    if not resolved.is_relative_to(input_root):
        raise HTTPException(
            status_code=400,
            detail=(
                f"audio_path 不在白名单目录内（仅允许 data/input 上传产物）: {audio_path}"
            ),
        )
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail=f"audio_path 文件不存在: {resolved}")
    return resolved


def _build_transpose_advice(body: dict, profile, model_name: str) -> None:
    """对照目标模型画像填充推荐转调（原地修改 body）。

    目标画像不可算 → 附 profile_unavailable（HTTP 200，spec 明确不报错）；
    可算 → recommended_transpose（clamp ±12）+ 源跨度超目标时的 range_warning。
    """
    body["model_name"] = model_name
    target = get_profile(model_name)
    if target is None:
        body["profile_unavailable"] = "模型训练数据不可得，无法推荐 transpose"
        return
    delta = profile.f0_median_midi - float(target["f0_median_midi"])
    recommended = int(min(max(round(delta), -_TRANSPOSE_CLAMP), _TRANSPOSE_CLAMP))
    body["target_profile"] = target
    body["recommended_transpose"] = recommended
    source_span = float(profile.range_span_semitones)
    target_span = float(target["range_span_semitones"])
    if source_span > target_span:
        body["range_warning"] = (
            f"源音频音域跨度 {source_span:.1f} 半音，超过目标模型音域跨度 "
            f"{target_span:.1f} 半音，翻唱后音区覆盖可能不足"
        )


@router.post("/analyze")
async def analyze(request: AnalyzeRequest):
    """源音频人声音域分析 + 对照目标模型的推荐转调。"""
    settings = get_settings()
    audio = _validate_input_path(request.audio_path)

    separator = VocalSeparator()
    try:
        profile, separation_used = await analyze_with_separation(
            audio, separator, settings.cover_analysis.f0_confidence
        )
    except SeparationError as e:
        # 分离引擎缺失/失败 → 503 含 setup 指引（守卫消息已带指引时不重复拼接）
        detail = str(e)
        if "setup_separation.py" not in detail:
            detail = f"{detail}；{separation_unavailable_detail()}"
        logger.warning("analyze separation unavailable: %s", detail)
        raise HTTPException(status_code=503, detail=detail)
    except VoiceAnalysisError as e:
        # 直析与分离后均无法分析（voiced 不达标等）→ 400 可读错误
        logger.warning("analyze failed for %s: %s", audio, e)
        raise HTTPException(status_code=400, detail=f"音域分析失败：{e}")

    body: dict = {
        "status": "success",
        "audio_path": str(audio),
        "separation_used": separation_used,
        "profile": profile.to_dict(),
    }
    model_name = (request.model_name or "").strip()
    if model_name:
        _build_transpose_advice(body, profile, model_name)
    return body


@router.get("/model-profiles")
async def model_profiles():
    """全部模型音域画像列表（含数据集 MD5 与计算时间）。"""
    return {"status": "success", "profiles": list_profiles()}
