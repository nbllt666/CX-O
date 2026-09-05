"""
统一数据集批量生成与 SVC 数据集管理 API（三引擎 + manifest v2）

两组路由分别挂载（见 main.py）：
- batch_router    → /api/datasets      ：POST /batch-generate、GET /batch-generate/{task_id}
  （三引擎：voxcpm / cosyvoice3_zero / qwen3_voicedesign；
    原 /api/voxcpm/batch-dataset 端点已移除，消费方仅 ModelStation 自有前端）
- datasets_router → /api/sovits-svc    ：GET /datasets、POST /datasets/import、
                                          DELETE /datasets/{speaker_name}
  （列表响应附每数据集的 manifest 版本与 text 完整率）

安全约定：
- 训练数据目录访问一律经 services/security_utils.validate_training_data_dir()
  集中校验（由 services/dataset_builder 内的 resolve_* 函数承载）；
- cosyvoice3_zero 参考音频路径经 dataset_builder.validate_ref_audio_path 白名单校验
  （training_data_dir ∪ input_dir，与 infer 输入白名单同口径）；
- 导入仅接受 multipart 文件上传（单文件 / 多文件 / zip 包），不接受客户端路径；
- 删除采用严格数据集名白名单校验 + 存在性检查，防路径穿越。

并行时序防御：tts_runtime 配置段由 Task 1 并行落地，非 voxcpm 引擎提交时经
getattr(settings, "tts_runtime", None) 防御，段缺失返回 503「tts_runtime 配置段未就绪」
（Task 5 合跑后该分支不可达）。

部署要求：单 worker 运行（uvicorn --workers 1），任务注册表为进程内存状态。
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from modelstation.services.dataset_builder import AUDIO_EXTENSIONS

logger = logging.getLogger(__name__)

# /api/datasets 前缀下挂载：统一批量生成任务（三引擎）
batch_router = APIRouter()
# /api/sovits-svc 前缀下挂载：数据集管理
datasets_router = APIRouter()


class BatchDatasetTextItem(BaseModel):
    text: str = Field(..., min_length=1)
    control: Optional[str] = None  # 条目级控制描述，覆盖任务级 control（voxcpm）


class EngineParams(BaseModel):
    """运行时引擎专属参数（按 engine 联动；voxcpm 不消费）。

    - cosyvoice3_zero：ref_audio_path（必填，白名单路径：training_data_dir ∪ input_dir）、
      ref_text（可选参考转写，提升克隆质量）；
    - qwen3_voicedesign：voice_description（必填，音色描述自然语言文本）。
    """

    ref_audio_path: Optional[str] = None
    ref_text: Optional[str] = None
    voice_description: Optional[str] = None


class BatchGenerateRequest(BaseModel):
    speaker_name: str = Field(..., min_length=1)
    texts: list[BatchDatasetTextItem] = Field(..., min_length=1)
    engine: Literal["voxcpm", "cosyvoice3_zero", "qwen3_voicedesign"] = Field(
        default="voxcpm",
        description="数据集生成引擎：voxcpm（子进程）/ cosyvoice3_zero（零样本克隆）/ "
        "qwen3_voicedesign（声音设计）；非法值 → 422",
    )
    # ---- voxcpm 专属参数（现状不变）----
    mode: str = Field(default="design", pattern="^(design|controllable_clone|ultimate_clone)$")
    control: str = ""
    reference_audio_path: Optional[str] = None
    prompt_audio_path: Optional[str] = None
    prompt_text: Optional[str] = None
    cfg_value: Optional[float] = None
    inference_timesteps: Optional[int] = None
    # ---- 运行时引擎参数（cosyvoice3_zero / qwen3_voicedesign）----
    engine_params: EngineParams = Field(default_factory=EngineParams)


@batch_router.post("/batch-generate")
async def submit_batch_generate(request: BatchGenerateRequest):
    """提交统一数据集批量生成任务（三引擎），立即返回 task_id，后台逐条生成"""
    from modelstation.config import get_settings
    from modelstation.services.dataset_builder import get_dataset_builder

    if request.engine != "voxcpm":
        # 并行时序防御：tts_runtime 配置段由 Task 1 落地，缺失时明确报错（合跑后不可达）
        if getattr(get_settings(), "tts_runtime", None) is None:
            raise HTTPException(
                status_code=503,
                detail="tts_runtime 配置段未就绪（依赖并行分支 config 落地），"
                "暂时无法使用运行时引擎，请改用 engine=voxcpm 或等待配置就绪",
            )

    try:
        task_id = await get_dataset_builder().submit(
            request.speaker_name,
            [item.model_dump() for item in request.texts],
            mode=request.mode,
            engine=request.engine,
            control=request.control,
            reference_audio_path=request.reference_audio_path,
            prompt_audio_path=request.prompt_audio_path,
            prompt_text=request.prompt_text,
            cfg_value=request.cfg_value,
            inference_timesteps=request.inference_timesteps,
            engine_params=request.engine_params.model_dump(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"批量数据集任务提交失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "task_id": task_id, "total": len(request.texts)}


@batch_router.get("/batch-generate/{task_id}")
async def get_batch_generate_task(task_id: str):
    """查询批量数据集任务进度（done/total/current_text/failed/engine）"""
    from modelstation.services.dataset_builder import get_dataset_builder

    task = get_dataset_builder().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task


@datasets_router.get("/datasets")
async def list_svc_datasets():
    """列出全部 SVC 训练数据集（speaker 目录、音频数量、总大小、创建时间）"""
    from modelstation.services.dataset_builder import list_datasets

    try:
        return {"status": "success", "datasets": list_datasets()}
    except Exception as e:
        logger.error(f"数据集列表查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@datasets_router.post("/datasets/import")
async def import_dataset(
    speaker_name: str = Form(...),
    files: list[UploadFile] = File(...),
):
    """multipart 上传导入数据集：支持多文件直传或单个 zip 包（不接受客户端路径）。

    - 音频扩展名白名单：wav/mp3/flac/ogg；zip 内非音频成员跳过并计数；
    - 文件名仅取 basename，zip 成员剥离目录前缀，杜绝路径穿越。
    """
    from modelstation.services.dataset_builder import (
        ensure_valid_dataset_name,
        resolve_dataset_dir,
        save_import_file,
    )

    try:
        valid_name = ensure_valid_dataset_name(speaker_name)
        dataset_dir = resolve_dataset_dir(valid_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    dataset_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    skipped: list[str] = []
    try:
        for upload in files:
            filename = upload.filename or ""
            data = await upload.read()
            if filename.lower().endswith(".zip"):
                zip_saved, zip_skipped = _extract_zip(dataset_dir, data, save_import_file)
                saved.extend(zip_saved)
                skipped.extend(zip_skipped)
            else:
                target = save_import_file(dataset_dir, filename, data)
                saved.append(target.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info("数据集导入完成: %s imported=%d skipped=%d", valid_name, len(saved), len(skipped))
    return {
        "status": "success",
        "name": valid_name,
        "imported": len(saved),
        "files": saved,
        "skipped": skipped,
    }


@datasets_router.delete("/datasets/{speaker_name}")
async def delete_svc_dataset(speaker_name: str):
    """删除指定数据集：严格名称白名单（防路径穿越）+ 存在性检查"""
    from modelstation.services.dataset_builder import delete_dataset

    try:
        delete_dataset(speaker_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"数据集删除失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "success", "message": f"数据集 {speaker_name} 已删除"}


def _extract_zip(dataset_dir, data: bytes, save_file) -> tuple[list[str], list[str]]:
    """安全解包 zip：成员仅取 basename（防 zip-slip），非音频成员跳过。

    Returns:
        (saved_names, skipped_names)
    """
    saved: list[str] = []
    skipped: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError(f"Invalid zip file: {e}")

    for info in archive.infolist():
        if info.is_dir():
            continue
        # 仅取 basename，剥离任何目录前缀，杜绝 zip-slip 路径穿越
        base = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not base:
            continue
        if Path(base).suffix.lower() not in AUDIO_EXTENSIONS:
            skipped.append(info.filename)
            continue
        target = save_file(dataset_dir, base, archive.read(info))
        saved.append(target.name)
    return saved, skipped
