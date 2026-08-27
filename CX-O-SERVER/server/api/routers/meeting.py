"""多 Agent 语音会议协调器 REST 端点。

- POST /api/meeting/start                             开启会议
- POST /api/meeting/{room_id}/end                     结束会议（沉淀记忆）
- GET  /api/meeting/{room_id}/state                   查询房间状态
- POST /api/meeting/{room_id}/join                    并入 Agent
- POST /api/meeting/{room_id}/leave                   移除 Agent
- POST /api/meeting/{room_id}/speak                   用户发言触发仲裁
- POST /api/meeting/{room_id}/audience/toggle         开/关观众席

装配方式对齐 cxfc.py / autonomy.py 模式：模块级 ``_coordinator`` 全局 +
``set_meeting_coordinator()`` 注入，由 server/main.py 装配时调用。

``meeting.enabled=false`` 时整体跳过装配：start 返回 400「未启用」，
其余房间型端点因无 coordinator 返回 404「未装配」，零侵入。

响应对齐 server/api/response.py：统一 APIResponse 封装；错误走 exceptions/HTTPException。
"""
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.api.response import APIResponse
from server.config import get_settings
from server.core.meeting.coordinator import MeetingRoomConflictError

router = APIRouter()

_coordinator = None


# ================================================================ 装配注入
def get_meeting_coordinator():
    """返回模块级 MeetingCoordinator 实例（未装配时为 None）。"""
    return _coordinator


def set_meeting_coordinator(coordinator):
    """注入 MeetingCoordinator 实例（server/main.py 装配时调用）。"""
    global _coordinator
    _coordinator = coordinator


def _require_enabled():
    """meeting.enabled=false 时抛 400「未启用」。"""
    settings = get_settings()
    cfg = getattr(settings.config, "meeting", None)
    if cfg is None or not cfg.enabled:
        raise HTTPException(status_code=400, detail="Meeting 模块未启用")


def _require_coordinator():
    """获取 coordinator，未装配抛 404。"""
    if _coordinator is None:
        raise HTTPException(status_code=404, detail="Meeting 协调器未装配")
    return _coordinator


def _room_or_404(coord, room_id: str):
    """按房间号取房间，不存在抛 404。"""
    room = coord.get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail=f"会议房间不存在: {room_id}")
    return room


# ================================================================ 请求体
class AgentSpec(BaseModel):
    """参会 Agent 描述。"""

    agent_id: str = Field(..., min_length=1)
    name: str = ""
    persona: str = ""
    # M 修复：relevance / desire_to_speak 取值域收敛到 [0, 1]（语义即相关度/发言欲）
    relevance: float = Field(0.5, ge=0, le=1)
    desire_to_speak: float = Field(0.5, ge=0, le=1)
    voice: Optional[str] = None


class StartRequest(BaseModel):
    """开会请求体。"""

    user: str = Field(..., min_length=1)
    agents: List[AgentSpec] = Field(default_factory=list)
    room_id: Optional[str] = None
    # M 修复：max_agents 下界保护（>=1），防止 0/负数导致上限判断形同虚设
    max_agents: Optional[int] = Field(None, ge=1)
    audience_enabled: bool = False


class AgentIdRequest(BaseModel):
    """join/leave 请求体。"""

    agent_id: str = Field(..., min_length=1)
    name: str = ""
    persona: str = ""
    relevance: float = 0.5
    desire_to_speak: float = 0.5
    voice: Optional[str] = None


class SpeakRequest(BaseModel):
    """用户/观众发言请求体。"""

    text: str = Field(..., min_length=1)
    # M 修复：role 收敛为字面量枚举——此前非法值会静默落入"用户发言"分支
    role: Literal["user", "audience"] = "user"
    userid: str = ""
    username: str = ""
    mention: str = ""


class AudienceToggleRequest(BaseModel):
    """观众席开关请求体。"""

    enabled: bool = False


# ================================================================ 端点
@router.post("/meeting/start", response_model=APIResponse)
async def start_meeting(body: StartRequest):
    """开启一场多 Agent 语音会议。

    Args:
        body: StartRequest（user 必填，agents 可空）。

    Returns:
        APIResponse: data=房间状态快照（含 room_id / agents / state）。
    """
    _require_enabled()
    coord = _require_coordinator()
    try:
        room = await coord.start_meeting(
            user=body.user,
            agents=[a.model_dump() for a in body.agents],
            room_id=body.room_id,
            max_agents=body.max_agents,
            audience_enabled=body.audience_enabled,
        )
    except MeetingRoomConflictError as e:
        # H5 修复：同名房间仍进行中 → 业务冲突 409（缺省随机 room_id 不受影响）
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return APIResponse.ok(data=room.to_dict(), message="会议已开启")


@router.post("/meeting/{room_id}/end", response_model=APIResponse)
async def end_meeting(room_id: str):
    """结束会议并沉淀会议记忆。"""
    coord = _require_coordinator()
    room = _room_or_404(coord, room_id)
    try:
        summary = await coord.end_meeting(room.room_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return APIResponse.ok(data={"summary": summary}, message="会议已结束")


@router.get("/meeting/{room_id}/state", response_model=APIResponse)
async def get_state(room_id: str):
    """查询房间状态快照。"""
    coord = _require_coordinator()
    room = _room_or_404(coord, room_id)
    return APIResponse.ok(data=room.to_dict())


@router.post("/meeting/{room_id}/join", response_model=APIResponse)
async def join_meeting(room_id: str, body: AgentIdRequest):
    """向会议并入一个 Agent。"""
    coord = _require_coordinator()
    room = _room_or_404(coord, room_id)
    ok = await coord.join(
        room.room_id,
        body.agent_id,
        name=body.name,
        persona=body.persona,
        relevance=body.relevance,
        desire_to_speak=body.desire_to_speak,
        voice=body.voice,
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Agent 已在场或房间已达上限")
    return APIResponse.ok(data=room.to_dict(), message="已并入")


@router.post("/meeting/{room_id}/leave", response_model=APIResponse)
async def leave_meeting(room_id: str, body: AgentIdRequest):
    """将 Agent 移出会议。"""
    coord = _require_coordinator()
    room = _room_or_404(coord, room_id)
    ok = await coord.leave(room.room_id, body.agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent 不在会场")
    return APIResponse.ok(data=room.to_dict(), message="已离开")


@router.post("/meeting/{room_id}/speak", response_model=APIResponse)
async def speak(room_id: str, body: SpeakRequest):
    """用户/观众发言，触发仲裁 → 令牌 → 转录 → TTS 全流程。

    role="audience" 时按观众身份进入互动空间消息流（meta 带 userid/username），
    否则视为用户发言（保持既有行为）。
    """
    coord = _require_coordinator()
    room = _room_or_404(coord, room_id)
    if body.role == "audience":
        result: Dict[str, Any] = await coord.process_message(
            room.room_id,
            body.text,
            role="audience",
            meta={
                "userid": body.userid,
                "username": body.username,
                "mention": body.mention,
            },
        )
    else:
        result = await coord.process_user_speech(room.room_id, body.text)
    return APIResponse.ok(data=result, message="已处理发言")


@router.post("/meeting/{room_id}/audience/toggle", response_model=APIResponse)
async def toggle_audience(room_id: str, body: AudienceToggleRequest):
    """开启/关闭观众席（互动空间弹幕通道）。"""
    coord = _require_coordinator()
    room = _room_or_404(coord, room_id)
    await coord.toggle_audience(room.room_id, body.enabled)
    return APIResponse.ok(data=room.to_dict(), message="观众席已切换")