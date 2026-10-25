"""
一键成模 API（参考音频上传 / 一键运行 / 分阶段进度查询）

change-id: add-one-click-voice-model-pipeline（spec「一键成模」Task 1/4）。

三端点（响应形状冻结，前端并行开发依赖，不得偏离）：
- POST /reference     multipart 单文件（字段名 file）：扩展名白名单 wav/mp3/flac/ogg，
  文件名仅取 basename（防穿越），落 settings.sovits_svc.input_dir 白名单根
  （cosyvoice 参考音频白名单根，spec 冻结），返回服务端受控绝对路径；非法 → 400
- POST /run           一键启动自动全流程：model_type 必选（melotts|sovits，非法 422），
  输入三选一（提示词 / 上传参考 / 自带数据集目录，同时提供/都缺 → 400），
  自带数据集仅 sovits（melotts 组合 → 400），参考音频须位于 data/input 白名单根
  （不存在 → 400）；同一时间仅一个运行（重复提交 → 409）；立即返回 run_id 与初始阶段清单
- GET  /run/{run_id}  分阶段进度（reference→corpus→preprocess→training→collect，
  含 skipped 语义、语料计数、训练进度、失败原因与最终产物）；未知 run_id → 404

注意：HTTPException 不得被外层 except Exception 吞成 500（需要处加
``except HTTPException: raise``）。

部署要求：单 worker（uvicorn --workers 1），运行注册表为进程内存状态。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from modelstation.services.auto_model_pipeline import (
    PipelineRunConflictError,
    get_auto_model_pipeline,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 参考音频扩展名白名单（spec 冻结：wav/mp3/flac/ogg）
_REFERENCE_AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg")


class PipelineTextItem(BaseModel):
    text: str = Field(..., min_length=1)


class PipelineRunRequest(BaseModel):
    """一键成模运行请求（model_type 必选；提示词/参考音频二选一）。"""

    model_type: Literal["melotts", "sovits"]
    voice_description: Optional[str] = Field(
        None, description="音色描述（自然语言提示词）；与 ref_audio_path 二选一"
    )
    ref_audio_path: Optional[str] = Field(
        None, description="上传参考音频的受控路径（/api/pipeline/reference 返回）；与 voice_description 二选一"
    )
    dataset_dir: Optional[str] = Field(
        None,
        description=(
            "自带数据集目录（本地绝对路径，递归扫描 wav/mp3/flac/ogg，统一转码 44.1kHz 单声道）；"
            "仅 model_type=sovits 支持；与 voice_description / ref_audio_path 三选一"
        ),
    )
    texts: Optional[list[PipelineTextItem]] = Field(
        None, description="语料文本清单；缺省用服务端内置默认语料"
    )
    output_name: Optional[str] = Field(
        None, description="输出模型名（缺省 auto_<DS编号>_<模型类型>；仅字母/数字/下划线/连字符）"
    )
    max_epochs: int = Field(
        10000,
        ge=1,
        description="本次训练 epoch 上限（默认 10000，判停器在拟合/过拟合时自动提前停止）",
    )
    corpus_target_clips: int = Field(
        50,
        ge=1,
        le=10000,
        description=(
            "语料目标切片条数（提示词/参考模式生效；自带数据集模式忽略）："
            "合成后按句子边界组装为 5~15s 标准切片"
        ),
    )


@router.post("/reference")
async def upload_reference(file: UploadFile = File(...)):
    """上传参考音频：扩展名白名单 + basename 防穿越，落 data/input 白名单根"""
    try:
        from modelstation.config import get_settings

        filename = file.filename or ""
        # 仅取 basename（统一正反斜杠分隔符），剥离任何目录前缀，杜绝路径穿越
        base = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not base or base in (".", ".."):
            raise HTTPException(
                status_code=400, detail=f"Invalid upload filename: {filename!r}"
            )
        if Path(base).suffix.lower() not in _REFERENCE_AUDIO_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported audio file type: {base!r} "
                    "(allowed: wav/mp3/flac/ogg)"
                ),
            )
        # 落盘根 = cosyvoice 参考音频白名单根（settings.sovits_svc.input_dir，
        # 默认仓库 data/input），保证后续 corpus 阶段白名单校验可接受
        input_dir = Path(get_settings().sovits_svc.input_dir)
        input_dir.mkdir(parents=True, exist_ok=True)
        target = input_dir / base
        data = await file.read()
        target.write_bytes(data)
        logger.info("参考音频已上传: %s (%d bytes)", target, len(data))
        return {"status": "success", "ref_audio_path": str(target.resolve())}
    except HTTPException:
        # 语义化错误（扩展名白名单 400 等）原样透传，不吞为 500
        raise
    except Exception as e:
        logger.error(f"参考音频上传失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run")
async def start_run(request: PipelineRunRequest):
    """一键启动自动全流程，立即返回 run_id 与初始阶段清单"""
    try:
        snapshot = await get_auto_model_pipeline().submit_run(
            request.model_type,
            voice_description=request.voice_description,
            ref_audio_path=request.ref_audio_path,
            texts=[item.model_dump() for item in request.texts] if request.texts else None,
            output_name=request.output_name,
            max_epochs=request.max_epochs,
            dataset_dir=request.dataset_dir,
            corpus_target_clips=request.corpus_target_clips,
        )
    except ValueError as e:
        # 二选一校验失败 / 参考音频白名单外或不存在 / 名称白名单等 → 400
        raise HTTPException(status_code=400, detail=str(e))
    except PipelineRunConflictError as e:
        # 同一时间仅一个运行 → 409
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"一键成模运行提交失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "status": "success",
        "run_id": snapshot["run_id"],
        "stages": snapshot["stages"],
    }


@router.get("/run/{run_id}")
async def get_run(run_id: str):
    """查询一键成模运行分阶段进度（阶段状态/语料计数/训练进度/失败原因/产物）"""
    snapshot = get_auto_model_pipeline().get_run(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return snapshot
