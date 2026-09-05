"""系统统计端点——运行状态与指标查询接口。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.api.routers.admin import verify_admin_api_key
from server.core.logging_config import get_contextual_logger
from server.core.utils import run_io

router = APIRouter()
logger = get_contextual_logger(__name__)


def _collect_system_stats(memory_mgr) -> dict:
    """同步收集系统统计（sqlite 直连），在 async 热路径中经 run_io 移入 IO 线程池。"""
    conn = None
    try:
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
            "total_memories": total_memories,
            "total_sessions": total_sessions,
            "total_agents": total_agents,
            "archived_memories": archived_memories,
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@router.get("/stats")
async def get_system_stats():
    from server.dependencies import get_memory_manager

    try:
        memory_mgr = get_memory_manager()
        data = await run_io(_collect_system_stats, memory_mgr)
        return {"status": "success", "data": data}
    except Exception as e:
        logger.error(f"获取系统统计数据失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class InterruptEnableRequest(BaseModel):
    """AI 插话打断启用配置请求体：enabled 与 speech_end_fallback 均可选，仅更新显式传入的字段。"""
    enabled: Optional[bool] = None
    speech_end_fallback: Optional[bool] = None


@router.get("/stats/interrupt")
async def get_interrupt_stats(_: bool = Depends(verify_admin_api_key)):
    """获取 AI 插话打断判定统计（admin API key 保护）。

    返回 agent_interrupt_user 模块的 get_stats() 结果（总判定数 / 三态 decision 计数 /
    触发打断次数 / 触发回复次数）。模块未初始化时返回可控 503，而非裸 500。
    """
    try:
        from server.services.agent_interrupt_user import get_agent_interrupt_module
    except Exception as e:
        logger.error(f"AI 插话打断模块不可用: {e}")
        raise HTTPException(status_code=503, detail=f"AI 插话打断模块不可用: {e}")
    try:
        return {"status": "success", "data": get_agent_interrupt_module().get_stats()}
    except Exception as e:
        logger.error(f"获取 AI 插话打断统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/stats/interrupt/enable")
async def update_interrupt_enable(
    request: InterruptEnableRequest,
    _: bool = Depends(verify_admin_api_key),
):
    """热更新 AI 插话打断启用状态（admin API key 保护）。

    仅更新请求体中显式传入的字段（enabled / speech_end_fallback），未传入字段保持现状；
    返回热更新后的新状态。set_config 为内存热更新，不落盘。
    """
    try:
        from server.services.agent_interrupt_user import get_agent_interrupt_module
    except Exception as e:
        logger.error(f"AI 插话打断模块不可用: {e}")
        raise HTTPException(status_code=503, detail=f"AI 插话打断模块不可用: {e}")

    config = {"agent_interrupt": {}}
    if request.enabled is not None:
        config["agent_interrupt"]["enabled"] = request.enabled
    if request.speech_end_fallback is not None:
        config["agent_interrupt"]["speech_end_fallback"] = request.speech_end_fallback

    try:
        module = get_agent_interrupt_module()
        module.set_config(config)
    except Exception as e:
        logger.error(f"更新 AI 插话打断配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=str(e))
    return {
        "status": "success",
        "data": {"enabled": module.enabled, "speech_end_fallback": module.speech_end_fallback},
    }


@router.get("/stats/voice-latency")
async def get_voice_latency_stats():
    """获取语音链路延迟统计（spec Task 4，仪表盘性能指标卡片数据源）。

    返回 {summary, recent, buffer_size}：
    - summary: 各段延迟 {asr/ttft/tts_first/e2e: {p50, p95, max, count}}（ms）
    - recent: 最近 N 轮明细（client_id / settled_at / segments / events）
    - buffer_size: 缓冲内已结算轮次样本数
    无样本时各段 p50/p95/max 为 null、count=0（前端显示"暂无样本"而非报错）。
    采集器查询内部吞异常，本端点不阻断。
    """
    try:
        from server.core.metrics.voice_latency import get_voice_latency_tracker

        tracker = get_voice_latency_tracker()
        return {
            "status": "success",
            "data": {
                "summary": tracker.summary(),
                "recent": tracker.recent(20),
                "buffer_size": tracker.buffer_size(),
            },
        }
    except Exception as e:
        logger.error(f"获取语音链路延迟统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail=str(e))
