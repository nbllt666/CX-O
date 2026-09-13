"""头像清单上报 REST 端点（spec enhance-emotion-tts-and-action-presets Task 5.1）。

对外暴露的前端运行时上报/查询接口，挂在 /api 前缀下：

  - POST /api/avatar-manifest                上报可用动作/表情清单（覆盖式更新）
  - GET  /api/avatar-manifest/{agent_id}     查询该 agent 的清单缓存

鉴权口径：与 chat.py 等前端运行时路由一致——不加管理端鉴权依赖
（verify_admin_api_key 仅用于管理操作，上报为前端桌宠窗运行时行为）。

错误映射：
  - 字段缺失 / 类型非法 → 422（Pydantic 校验）
  - 其余内部异常       → 500（错误文案收敛，详情留日志）

业务逻辑委托 server.services.avatar_manifest_registry（进程级内存缓存，
不持久化；服务重启后前端重新上报）。提示词注入（查询消费方）归 Task 4。
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.core.logging_config import get_contextual_logger

router = APIRouter(prefix="/avatar-manifest", tags=["avatar-manifest"])
logger = get_contextual_logger(__name__)


class AvatarManifestReport(BaseModel):
    """上报请求体：agent_id 为目标 agent，actions 为可用动作名（motions keys）清单。"""

    agent_id: str = Field(min_length=1, max_length=128, description="目标 Agent id")
    actions: List[str] = Field(default_factory=list, description="可用动作名清单（motions keys）")
    expressions: Optional[List[str]] = Field(default=None, description="可用表情 id 清单（可省略）")


@router.post("")
async def report_manifest(payload: AvatarManifestReport):
    """上报该 agent 的可用动作/表情清单（覆盖式更新）。"""
    from server.services.avatar_manifest_registry import get_avatar_manifest_registry

    try:
        snapshot = get_avatar_manifest_registry().upsert(
            payload.agent_id, payload.actions, payload.expressions
        )
    except Exception as e:  # noqa: BLE001 错误文案收敛：详情留日志
        logger.error(f"头像清单上报失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="头像清单上报处理失败")
    return {
        "status": "success",
        "agent_id": payload.agent_id,
        "actions_count": len(snapshot["actions"]),
        "expressions_count": len(snapshot["expressions"]),
        "updated_at": snapshot["updated_at"],
    }


@router.get("/{agent_id}")
async def get_manifest(agent_id: str):
    """查询该 agent 的清单缓存；未上报时返回空清单与 reported=False（不报错）。"""
    from server.services.avatar_manifest_registry import get_avatar_manifest_registry

    try:
        snapshot = get_avatar_manifest_registry().get(agent_id)
    except Exception as e:  # noqa: BLE001 错误文案收敛：详情留日志
        logger.error(f"头像清单查询失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="头像清单查询处理失败")
    return {
        "agent_id": agent_id,
        "actions": snapshot["actions"],
        "expressions": snapshot["expressions"],
        "updated_at": snapshot["updated_at"],
        "reported": snapshot["updated_at"] is not None,
    }
