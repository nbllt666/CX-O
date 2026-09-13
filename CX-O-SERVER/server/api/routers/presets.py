"""预设管理端点——per-agent 情感TTS预设与动作预设的 REST 管理（仅 API，无前端界面）。

Spec: .trae/specs/enhance-emotion-tts-and-action-presets/spec.md「管理 API」Scenario。
鉴权与同类管理端点（admin/backup/config 写操作）保持一致：verify_admin_api_key。

端点：
- GET    /presets/{agent_id}                       两类预设全量列表
- POST   /presets/{agent_id}/emotion               新增/覆盖情感TTS预设
- POST   /presets/{agent_id}/action                新增/覆盖动作预设
- DELETE /presets/{agent_id}/emotion/{name}        删除情感TTS预设
- DELETE /presets/{agent_id}/action/{name}         删除动作预设

注册方式: app.include_router(presets.router, prefix="/api")
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from server.api.routers.admin import verify_admin_api_key
from server.core.logging_config import get_contextual_logger
from server.services import preset_service
from server.services.preset_service import PresetValidationError

router = APIRouter()
logger = get_contextual_logger(__name__)


class EmotionPresetUpsertRequest(BaseModel):
    """情感TTS预设新增/覆盖请求体。"""

    name: str
    text: str
    speed: float = 1.0
    volume: float = 1.0
    description: str = ""


class ActionPresetUpsertRequest(BaseModel):
    """动作预设新增/覆盖请求体。"""

    name: str
    tags: List[str]
    description: str = ""


def _validation_error_to_400(e: PresetValidationError) -> HTTPException:
    """校验失败统一映射为 400（含 agent_id 非法/路径穿越与字段校验错误）。"""
    return HTTPException(status_code=400, detail=str(e))


@router.get("/presets/{agent_id}")
async def list_all_presets(agent_id: str, _: bool = Depends(verify_admin_api_key)):
    """返回某 Agent 两类预设的全量清单（各自按 name 升序）。"""
    try:
        presets = await run_in_threadpool(preset_service.list_all_presets, agent_id)
    except PresetValidationError as e:
        raise _validation_error_to_400(e)
    return {
        "agent_id": agent_id,
        "emotion": presets[preset_service.KIND_EMOTION],
        "action": presets[preset_service.KIND_ACTION],
        "emotion_count": len(presets[preset_service.KIND_EMOTION]),
        "action_count": len(presets[preset_service.KIND_ACTION]),
    }


@router.post("/presets/{agent_id}/emotion")
async def upsert_emotion_preset(
    request: EmotionPresetUpsertRequest,
    agent_id: str,
    _: bool = Depends(verify_admin_api_key),
):
    """新增或覆盖（同名原子覆盖）某 Agent 的情感TTS预设。"""
    try:
        preset = await run_in_threadpool(
            preset_service.save_emotion_preset,
            agent_id,
            request.name,
            request.text,
            request.speed,
            request.volume,
            request.description,
        )
    except PresetValidationError as e:
        raise _validation_error_to_400(e)
    logger.info(f"情感预设已保存: agent={agent_id} name={request.name}")
    return {"status": "success", "preset": preset}


@router.post("/presets/{agent_id}/action")
async def upsert_action_preset(
    request: ActionPresetUpsertRequest,
    agent_id: str,
    _: bool = Depends(verify_admin_api_key),
):
    """新增或覆盖（同名原子覆盖）某 Agent 的动作预设。"""
    try:
        preset = await run_in_threadpool(
            preset_service.save_action_preset,
            agent_id,
            request.name,
            request.tags,
            request.description,
        )
    except PresetValidationError as e:
        raise _validation_error_to_400(e)
    logger.info(f"动作预设已保存: agent={agent_id} name={request.name}")
    return {"status": "success", "preset": preset}


@router.delete("/presets/{agent_id}/emotion/{name}")
async def delete_emotion_preset(
    agent_id: str, name: str, _: bool = Depends(verify_admin_api_key)
):
    """删除某 Agent 的情感TTS预设；不存在返回 404。"""
    try:
        removed = await run_in_threadpool(
            preset_service.delete_emotion_preset, agent_id, name
        )
    except PresetValidationError as e:
        raise _validation_error_to_400(e)
    if not removed:
        raise HTTPException(status_code=404, detail=f"情感预设「{name}」不存在")
    return {"status": "success", "deleted": name}


@router.delete("/presets/{agent_id}/action/{name}")
async def delete_action_preset(
    agent_id: str, name: str, _: bool = Depends(verify_admin_api_key)
):
    """删除某 Agent 的动作预设；不存在返回 404。"""
    try:
        removed = await run_in_threadpool(
            preset_service.delete_action_preset, agent_id, name
        )
    except PresetValidationError as e:
        raise _validation_error_to_400(e)
    if not removed:
        raise HTTPException(status_code=404, detail=f"动作预设「{name}」不存在")
    return {"status": "success", "deleted": name}
