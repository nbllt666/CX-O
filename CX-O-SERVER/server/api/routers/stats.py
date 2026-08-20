"""系统统计端点——运行状态与指标查询接口。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.api.routers.admin import verify_admin_api_key
from server.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)


@router.get("/stats")
async def get_system_stats():
    from server.dependencies import get_memory_manager

    conn = None
    try:
        memory_mgr = get_memory_manager()
        conn = memory_mgr._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM memories WHERE is_deleted = FALSE")
        total_memories = cursor.fetchone()[0]

        try:
            cursor.execute("SELECT COUNT(*) FROM sessions")
            total_sessions = cursor.fetchone()[0]
        except Exception:
            total_sessions = 0

        try:
            cursor.execute("SELECT COUNT(*) FROM agent_memory_tables")
            total_agents = cursor.fetchone()[0]
        except Exception:
            total_agents = 0

        try:
            cursor.execute("SELECT COUNT(*) FROM memories WHERE archived_at IS NOT NULL AND is_deleted = FALSE")
            archived_memories = cursor.fetchone()[0]
        except Exception:
            archived_memories = 0

        return {
            "status": "success",
            "data": {
                "total_memories": total_memories,
                "total_sessions": total_sessions,
                "total_agents": total_agents,
                "archived_memories": archived_memories,
            },
        }
    except Exception as e:
        logger.error(f"获取系统统计数据失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


class InterruptEnableRequest(BaseModel):
    """AI 插话打断启用配置请求体：enabled 与 speech_end_fallback 均可选，仅更新显式传入的字段。"""
    enabled: Optional[bool] = None
    speech_end_fallback: Optional[bool] = None


@router.get("/stats/interrupt")
async def get_interrupt_stats(_: bool = Depends(verify_admin_api_key)):
    """获取 AI 插话打断判定统计（admin API key 保护）。

    返回 agent_interrupt_user 模块的 get_stats() 结果（总判定数 / 三态 decision 计数 /
    触发打断次数 / 触发回复次数）。
    """
    from server.services.agent_interrupt_user import get_agent_interrupt_module
    return {"status": "success", "data": get_agent_interrupt_module().get_stats()}


@router.post("/stats/interrupt/enable")
async def update_interrupt_enable(
    request: InterruptEnableRequest,
    _: bool = Depends(verify_admin_api_key),
):
    """热更新 AI 插话打断启用状态（admin API key 保护）。

    仅更新请求体中显式传入的字段（enabled / speech_end_fallback），未传入字段保持现状；
    返回热更新后的新状态。set_config 为内存热更新，不落盘。
    """
    from server.services.agent_interrupt_user import get_agent_interrupt_module

    config = {"agent_interrupt": {}}
    if request.enabled is not None:
        config["agent_interrupt"]["enabled"] = request.enabled
    if request.speech_end_fallback is not None:
        config["agent_interrupt"]["speech_end_fallback"] = request.speech_end_fallback

    module = get_agent_interrupt_module()
    module.set_config(config)
    return {
        "status": "success",
        "data": {"enabled": module.enabled, "speech_end_fallback": module.speech_end_fallback},
    }
