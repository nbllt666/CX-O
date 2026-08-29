"""Qwen3 参考音频资产管理端点（source=prompt / source=file）。

统一将外部文件上传与提示词生成的参考音频作为可管理资产（对应
public/interface_stub/ref_audio_store.pyi 与 ref_audio_asset.schema.json）。
提供列表、注册（文件/提示词）、详情、试听、注释、删除。

禁止客户端传任意本地路径读取文件；路径安全与元数据校验由 ref_audio_store 承担。
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server.config import get_settings
from server.core.logging_config import get_contextual_logger
from server.qwen3_tts_provider import (
    InvalidRefAudioError,
    RefAudioNotFoundError,
    RuntimeUnavailableError,
)
import server.ref_audio_store as store

logger = get_contextual_logger(__name__)
router = APIRouter()


def _resolve_max_upload_bytes() -> int:
    """启动时从配置读取参考音频单文件大小上限（MB → bytes）。

    与 store 内部校验（get_settings().tts.max_ref_audio_size_mb）同源同口径，
    消除路由硬编码 60MB 与 store 50MB 的双闸门不一致（50-60MB 文件不再进入必失败的泄漏路径）。
    """
    try:
        return int(get_settings().tts.max_ref_audio_size_mb) * 1024 * 1024
    except Exception:  # noqa: BLE001 — 配置不可用时回退内置默认 50MB
        return 50 * 1024 * 1024


_MAX_UPLOAD_BYTES = _resolve_max_upload_bytes()

# 试听 media_type 映射（未列出的扩展名保持现口径 audio/mpeg）
_AUDIO_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}


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
    request: Request,
    file: UploadFile = File(...),
    ref_text: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
):
    """上传外部音频文件并注册为 source=file 资产。"""
    try:
        # 上传防呆：Content-Length 预检（超限直接 413，不整读入内存），读取后复查实际长度
        content_length = request.headers.get("content-length", "")
        if content_length.isdigit() and int(content_length) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="音频文件过大")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="音频文件为空")
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="音频文件过大")
        # 落盘到 store 实际资产目录（含测试覆盖），供 store 注册；store 内部校验格式/大小/时长/采样率/路径安全
        asset_dir = store._resolve_assets_dir()
        asset_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _sanitize_upload_name(file.filename or "ref_audio")
        # 临时名加 uuid：并发上传同名文件不再互相覆盖（safe_name 仅用于最终注册元数据）
        tmp_path = asset_dir / f"_upload_{uuid.uuid4().hex}_{safe_name}"
        tmp_path.write_bytes(content)
        try:
            asset = store.register_from_file(str(tmp_path), ref_text=ref_text or "", note=note or "")
        finally:
            # 注册成功与异常（InvalidRefAudioError 等）路径都清理上传临时文件，杜绝残留
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
        # 错误文案收敛：不透传内部路径/实现细节（详情见上方日志）
        raise HTTPException(status_code=500, detail="音频处理失败，请检查文件格式")


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
        # 错误文案收敛：不透传内部实现细节（详情见上方日志）
        raise HTTPException(status_code=500, detail="参考音频生成失败，请稍后重试")


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
        media_type = _AUDIO_MEDIA_TYPES.get(path.suffix.lower(), "audio/mpeg")
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
    """删除参考音频资产（软删除）。被 Agent 绑定的资产拒绝删除，返回 409。"""
    try:
        store.delete(asset_id)
        return {"status": "success", "asset_id": asset_id}
    except store.AssetBoundError as e:
        raise HTTPException(status_code=409, detail=str(e))
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
