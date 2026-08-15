"""Qwen3 参考音频资产管理端点（source=prompt / source=file）。

统一将外部文件上传与提示词生成的参考音频作为可管理资产（对应
public/interface_stub/ref_audio_store.pyi 与 ref_audio_asset.schema.json）。
提供列表、注册（文件/提示词）、详情、试听、注释、删除。

禁止客户端传任意本地路径读取文件；路径安全与元数据校验由 ref_audio_store 承担。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server.core.logging_config import get_contextual_logger
from server.qwen3_tts_provider import (
    InvalidRefAudioError,
    RefAudioNotFoundError,
    RuntimeUnavailableError,
)
import server.ref_audio_store as store

logger = get_contextual_logger(__name__)
router = APIRouter()

# 外部文件上传大小上限（与配置 max_ref_audio_size_mb 对齐，默认 50MB）
_MAX_UPLOAD_BYTES = 60 * 1024 * 1024


class SetCurrentAssetRequest(BaseModel):
    """设置当前默认参考音频请求。"""

    asset_id: str = Field(..., min_length=1)


class RegisterFromPromptRequest(BaseModel):
    """提示词生成参考音频请求。"""

    prompt: str = Field(..., min_length=1)
    language: Optional[str] = None


class UpdateNoteRequest(BaseModel):
    """更新资产注释请求。"""

    note: str = ""


def _to_public(asset: store.RefAudioAsset) -> dict:
    """资产对象序列化为公开形状（仅非空字段）。"""
    return asset.to_dict()


@router.get("/ref-audio-assets", summary="参考音频资产列表")
async def list_assets():
    """列出全部可用参考音频资产（排除已删除），并返回当前默认资产 ID。"""
    try:
        assets = store.list()
        current = store.get_current()
        return {
            "assets": [_to_public(a) for a in assets],
            "current_asset_id": current.id if current is not None else None,
        }
    except Exception as e:  # noqa: BLE001
        logger.error(f"列出参考音频资产失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/ref-audio-assets/current", summary="当前默认参考音频资产")
async def get_current_asset():
    """返回当前默认参考音频资产；未设置返回 {"asset": null}。"""
    try:
        asset = store.get_current()
        return {"asset": _to_public(asset) if asset is not None else None}
    except Exception as e:  # noqa: BLE001
        logger.error(f"获取当前参考音频资产失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.put("/ref-audio-assets/current", summary="设为当前默认参考音频")
async def set_current_asset(payload: SetCurrentAssetRequest):
    """将指定资产设为当前默认参考音频（TTS 编排默认使用，合成请求可覆盖）。"""
    try:
        asset = store.set_current(payload.asset_id)
        return {"asset": _to_public(asset), "current_asset_id": asset.id}
    except RefAudioNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidRefAudioError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.error(f"设置当前参考音频资产失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete("/ref-audio-assets/current", summary="清除当前默认参考音频")
async def clear_current_asset():
    """清除当前默认参考音频设置（不删除资产本身）。"""
    try:
        store.clear_current()
        return {"status": "success", "current_asset_id": None}
    except Exception as e:  # noqa: BLE001
        logger.error(f"清除当前参考音频资产失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/ref-audio-assets/from-file", summary="注册外部音频文件资产")
async def register_from_file(
    file: UploadFile = File(...),
    ref_text: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
):
    """上传外部音频文件并注册为 source=file 资产。"""
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="音频文件为空")
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="音频文件过大")
        # 落盘到 store 实际资产目录（含测试覆盖），供 store 注册；store 内部校验格式/大小/时长/采样率/路径安全
        asset_dir = store._resolve_assets_dir()
        asset_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _sanitize_upload_name(file.filename or "ref_audio")
        tmp_path = asset_dir / f"_upload_{safe_name}"
        tmp_path.write_bytes(content)
        asset = store.register_from_file(str(tmp_path), ref_text=ref_text or "", note=note or "")
        # 注册成功后清理上传临时文件（store 已复制到资产文件）
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"asset": _to_public(asset)}
    except InvalidRefAudioError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"注册外部文件资产失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ref-audio-assets/from-prompt", summary="提示词生成参考音频资产")
async def register_from_prompt(payload: RegisterFromPromptRequest):
    """根据自然语言提示词调用 Qwen3 VoiceDesign 生成并注册 source=prompt 资产。"""
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt 提示词不能为空")
    try:
        asset = await store.register_from_prompt(prompt=payload.prompt, language=payload.language)
        return {"asset": _to_public(asset)}
    except RuntimeUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except InvalidRefAudioError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.error(f"提示词生成参考音频失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ref-audio-assets/{asset_id}", summary="参考音频资产详情")
async def get_asset(asset_id: str):
    """按 ID 获取资产详情。"""
    try:
        asset = store.get(asset_id)
        if asset is None or asset.is_deleted:
            raise RefAudioNotFoundError(f"参考音频资产不存在: {asset_id}")
        return _to_public(asset)
    except RefAudioNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.error(f"获取参考音频资产失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/ref-audio-assets/{asset_id}/audio", summary="试听参考音频")
async def get_asset_audio(asset_id: str):
    """返回资产音频文件供前端试听。"""
    try:
        path = store.get_audio_path(asset_id)
        media_type = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
        return FileResponse(path=path, media_type=media_type)
    except (RefAudioNotFoundError, InvalidRefAudioError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.error(f"试听参考音频失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.patch("/ref-audio-assets/{asset_id}/note", summary="更新资产注释")
async def update_note(asset_id: str, payload: UpdateNoteRequest):
    """更新资产注释。"""
    try:
        asset = store.update_note(asset_id, payload.note)
        return _to_public(asset)
    except RefAudioNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.error(f"更新参考音频注释失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete("/ref-audio-assets/{asset_id}", summary="删除参考音频资产")
async def delete_asset(asset_id: str):
    """删除参考音频资产（软删除）。"""
    try:
        store.delete(asset_id)
        return {"status": "success", "asset_id": asset_id}
    except RefAudioNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.error(f"删除参考音频资产失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


def _sanitize_upload_name(name: str) -> str:
    """清洗上传文件名，仅保留安全字符，防止路径穿越。"""
    import re

    base = name.replace("\\", "/").split("/")[-1]
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
    return safe or "ref_audio"
