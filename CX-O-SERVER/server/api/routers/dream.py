"""CX-O-Dream 梦境引擎 REST 端点（前端 DreamPage 管理页依赖）。

- GET    /dream/status       状态（未装配/未启用返回 {"status": "disabled"}，不抛错）
- POST   /dream/trigger      手动触发一轮梦境会话
- GET    /dream/list         分页列出缓冲候选（按 state 过滤）
- POST   /dream/{id}/confirm 确认 → 固化（红线 R5 前置：写主库）
- POST   /dream/{id}/reject  否定 → 清除（不写主库，保留 30 天审计）
- DELETE /dream/session/{session_id}  按会话回滚（红线 R5）
- POST   /dream/purge        手动触发清除任务
- GET/PUT /dream/config      读取 / 深度合并更新配置（非法字段 422）

依赖注入对齐 autonomy.py / cxfc.py 模式：模块级 `_engine` 全局 + `set_dream_engine`
注入函数，由 server/main.py 装配成功后注入。engine 为 None（未装配/未启用）时所有
引擎端点以 disabled 口径响应（不抛 500）。配置读写走独立 config 模块
（load_config/save_config），不依赖引擎实例，始终可用。
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from server.autonomy.dream.config import DreamConfig, load_config, save_config

logger = logging.getLogger(__name__)

router = APIRouter()

_engine = None


def get_dream_engine():
    """返回模块级 DreamEngine 单例（未设置时为 None）。"""
    return _engine


def set_dream_engine(engine):
    """设置 DreamEngine 实例。"""
    global _engine
    _engine = engine


class RejectRequest(BaseModel):
    """否定请求体：{"reason": str}。"""

    reason: str = ""


def _engine_ready() -> bool:
    """返回引擎是否已装配且启用（config.enabled）。"""
    engine = _engine
    return engine is not None and bool(
        getattr(engine, "config", None) and engine.config.enabled
    )


@router.get("/dream/status")
def get_status():
    """返回梦境引擎状态快照。

    引擎未装配或未启用（config.enabled=False）时返回 {"status": "disabled"}，
    HTTP 200，不抛错。
    """
    engine = _engine
    if not _engine_ready():
        return {"status": "disabled"}
    return engine.get_status()


@router.post("/dream/trigger")
async def trigger(agent_id: str = "default"):
    """手动触发一轮梦境会话（采集 → 生成 → D7 过滤 → 缓冲）。

    未启用时返回 {"status": "disabled"}（HTTP 200），不抛错。
    """
    engine = _engine
    if not _engine_ready():
        return {"status": "disabled"}
    return await engine.run_session(agent_id=agent_id)


@router.get("/dream/list")
def list_candidates(
    agent_id: str = "default",
    state: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """分页列出缓冲候选（按 agent / decision(state) 过滤）。

    未启用时返回空列表 {"items": [], "total": 0}。
    """
    engine = _engine
    if not _engine_ready():
        return {"items": [], "total": 0}
    items = engine.buffer.list(
        agent_id=agent_id, decision=state, limit=limit, offset=offset
    )
    return {"items": items, "total": len(items)}


@router.post("/dream/{buffer_id}/confirm")
def confirm(buffer_id: int, agent_id: str = "default"):
    """确认一条梦境候选 → 固化为主库梦境记忆（红线 R5 前置）。

    候选不存在或已决策（rejected/approved）返回 404。
    """
    engine = _engine
    if not _engine_ready():
        raise HTTPException(status_code=404, detail="梦境引擎未启用")
    memory_id = engine.consolidator.consolidate(buffer_id, agent_id=agent_id)
    if memory_id is None:
        raise HTTPException(status_code=404, detail=f"候选 {buffer_id} 不存在或已决策")
    return {"memory_id": memory_id}


@router.post("/dream/{buffer_id}/reject")
def reject(
    buffer_id: int,
    body: Optional[RejectRequest] = None,
    agent_id: str = "default",
):
    """否定一条梦境候选 → 缓冲置 rejected（保留 30 天审计），不写主库。

    候选不存在或已否定返回 404。reason 可选（请求体 {"reason": str}）。
    """
    engine = _engine
    if not _engine_ready():
        raise HTTPException(status_code=404, detail="梦境引擎未启用")
    reason = body.reason if body is not None else ""
    ok = engine.consolidator.reject(buffer_id, agent_id=agent_id, reason=reason)
    if not ok:
        raise HTTPException(status_code=404, detail=f"候选 {buffer_id} 不存在或已否定")
    return {"status": "ok", "buffer_id": buffer_id}


@router.delete("/dream/session/{session_id}")
def purge_session(session_id: str, agent_id: str = "default"):
    """按会话回滚：软删该会话全部 type='dream' 记忆（红线 R5）。

    返回 {"purged": n}。
    """
    engine = _engine
    if not _engine_ready():
        raise HTTPException(status_code=404, detail="梦境引擎未启用")
    purged = engine.consolidator.memory_manager.purge_dream_session(
        session_id, agent_id=agent_id
    )
    return {"purged": purged}


@router.post("/dream/purge")
async def purge(agent_id: str = "default"):
    """手动触发清除任务（超 TTL 未确认 / 低重要性 / 缓冲过期）。

    返回 {"purged_memories": n, "purged_buffer": n}。
    """
    engine = _engine
    if not _engine_ready():
        raise HTTPException(status_code=404, detail="梦境引擎未启用")
    return await engine.purge_job.run(agent_id=agent_id)


@router.get("/dream/config")
def get_config():
    """返回当前梦境配置（DreamConfig.model_dump）。

    独立配置模块（load_config），不依赖引擎实例，未启用也可读。
    """
    return load_config().model_dump()


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并：patch 中的 dict 与 base 中同名 dict 深度合并，其余键整体覆盖。

    用于局部更新配置时保留嵌套子对象（schedule 等）未被提交的字段，
    配合 model_validate 自动补齐缺失字段。
    """
    result = dict(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _sync_engine_runtime(engine, updated: DreamConfig) -> None:
    """将更新后的配置应用到运行中引擎（enabled 开关尽力而为）。

    - enabled=true  且引擎未运行 → engine.start()（已运行则内部 no-op）
    - enabled=false → engine.stop()
    引擎实例已装配时才执行；任何异常被捕获隔离，不影响配置保存与返回。
    """
    if engine is None:
        return
    engine.config = updated
    try:
        if updated.enabled:
            engine.start()
        else:
            engine.stop()
    except Exception as e:
        logger.warning("梦境引擎运行期 enabled 变更应用失败（尽力而为）: %s", e)


@router.put("/dream/config")
async def update_config(partial: Dict[str, Any]):
    """局部更新梦境配置并保存（自动补齐缺失字段）。

    以当前配置为基础做深度合并后经 DreamConfig.model_validate 校验；非法字段
    （extra="forbid"）、非法枚举/非法时间格式返回 422。运行期 enabled 变更尽力
    应用到已装配引擎（start/stop）。
    """
    current = load_config().model_dump()
    merged = _deep_merge(current, partial)
    try:
        updated = DreamConfig.model_validate(merged)
    except (ValidationError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"配置字段非法: {e}") from e

    save_config(updated)
    _sync_engine_runtime(_engine, updated)
    return updated.model_dump()
