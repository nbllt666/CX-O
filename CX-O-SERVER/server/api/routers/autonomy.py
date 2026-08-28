"""CX-O-Autonomy 自主系统 REST 端点（前端 Agent 生活控制页依赖，P4 前置）。

- GET  /autonomy/status   状态快照（未装配/未启用返回 {"status": "disabled"}，不抛错）
- POST /autonomy/control  控制指令（enable/disable/pause/resume/emergency_stop）
- GET  /autonomy/audit    审计日志分页 {items, total}
- GET  /autonomy/config   当前配置（对齐 autonomy_config.schema.json）
- PUT  /autonomy/config   局部更新配置并保存（非法字段/枚举/时间格式返回 422）

依赖注入对齐 cxfc.py 模式：模块级 `_manager` / `_audit_store` 全局 + `set_*` 注入函数，
由 server/main.py 装配成功后注入。
"""
import asyncio
import logging
import threading
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from server.api.routers.admin import verify_admin_api_key
from server.autonomy.config import AutonomyConfig, save_config
from server.autonomy.manager import AutonomyDisabledError

logger = logging.getLogger(__name__)

router = APIRouter()

# 控制指令枚举（对齐 public/interface_stub/cxo_autonomy.pyi control() 契约）
CONTROL_ACTIONS = ("enable", "disable", "pause", "resume", "emergency_stop")

# 配置写锁（R3）：串行化 PUT /autonomy/config 读改写与 control enable/disable
# 持久化两条写路径，消除双入口并发写交错损坏文件。async 上下文经
# asyncio.to_thread 在工作线程内持锁执行，事件循环内不做阻塞文件 IO。
_CONFIG_WRITE_LOCK = threading.Lock()


def _save_config_locked(cfg: AutonomyConfig) -> None:
    """持 _CONFIG_WRITE_LOCK 写配置（供工作线程内执行）。"""
    with _CONFIG_WRITE_LOCK:
        save_config(cfg)


_manager = None
_audit_store = None


def get_autonomy_manager():
    """返回模块级 AutonomyManager 单例（未设置时为 None）。"""
    return _manager


def set_autonomy_manager(manager):
    """设置 AutonomyManager 实例。"""
    global _manager
    _manager = manager


def get_audit_store():
    """返回模块级 AuditStore 单例（未设置时为 None）。"""
    return _audit_store


def set_audit_store(store):
    """设置 AuditStore 实例。"""
    global _audit_store
    _audit_store = store


class ControlRequest(BaseModel):
    """控制指令请求体：{"action": str}。"""

    action: str


def _manager_state(manager) -> Dict[str, Any]:
    """返回控制后的轻量状态快照（enabled/running/status）。

    不调用 get_status()——它在未启用/紧急停止后会抛 AutonomyDisabledError，
    而 control 返回的 state 需要在任何动作后都可读。
    """
    return {
        "enabled": manager.enabled,
        "running": manager.running,
        "status": manager.status,
    }


def _try_bootstrap_manager():
    """尝试从装配入口获取已装配的 AutonomyManager。

    manager 为 None 且收到 enable 时调用：若自主系统已在启动流程中装配
    （server.autonomy.main.setup_autonomy 成功，模块级单例存在），则回填模块级
    引用；否则返回 None。
    """
    global _manager
    if _manager is not None:
        return _manager
    try:
        from server.autonomy.main import get_autonomy_manager as _get_assembled

        mgr = _get_assembled()
    except Exception:
        mgr = None
    if mgr is not None:
        _manager = mgr
    return mgr


async def _try_ensure_manager(request: Request):
    """获取可用 AutonomyManager；未装配时对 enable 尝试运行时装配。

    优先复用已装配单例（`_try_bootstrap_manager`）；仍为 None 且 app 已装配
    services 时，将配置 enabled 持久化后调用 setup_autonomy 完成运行时装配，
    并回填模块级 `_manager` / `_audit_store`。任何失败返回 None（调用方降级 400）。
    """
    global _manager, _audit_store
    if _manager is not None:
        return _manager
    mgr = _try_bootstrap_manager()
    if mgr is not None:
        return mgr
    services = getattr(getattr(request.app, "state", None), "services", None)
    if services is None:
        return None
    try:
        from server.autonomy.config import load_config
        from server.autonomy.main import (
            get_audit_store as _get_assembled_audit,
            setup_autonomy,
        )

        def _enable_and_save_locked() -> None:
            """持锁读改写：读取当前配置置 enabled=True 后落盘（线程内执行）。"""
            with _CONFIG_WRITE_LOCK:
                cfg = load_config()
                cfg.enabled = True
                save_config(cfg)

        await asyncio.to_thread(_enable_and_save_locked)
        mgr = await setup_autonomy(services)
        if mgr is not None:
            _manager = mgr
            _audit_store = _get_assembled_audit()
        return mgr
    except Exception as e:
        logger.error("自主系统运行时装配失败: %s", e)
        return None


async def _persist_enabled(action: str, manager: Any) -> None:
    """enable/disable 开关状态持久化到配置存储（其余动作不持久化）。

    使用 manager.config 的 store_path 落盘，保证跨重启保持；写盘经
    asyncio.to_thread 在工作线程中执行且持 _CONFIG_WRITE_LOCK，事件循环内
    不做阻塞文件 IO（R3）。配置缺失或写入失败仅告警，不影响控制指令执行。
    """
    if action not in ("enable", "disable"):
        return
    cfg = getattr(manager, "config", None)
    if cfg is None:
        return
    try:
        cfg.enabled = action == "enable"
        await asyncio.to_thread(_save_config_locked, cfg)
    except Exception as e:
        logger.warning("自主系统开关状态持久化失败: %s", e)


@router.get("/autonomy/status")
def get_status():
    """返回自主系统状态快照（对齐 autonomy_state.schema.json）。

    未装配（manager 为 None）或未启用（get_status 抛 AutonomyDisabledError）时
    返回 {"status": "disabled"}，HTTP 200，不抛错。
    """
    manager = _manager
    if manager is None:
        return {"status": "disabled"}
    try:
        return manager.get_status()
    except AutonomyDisabledError:
        return {"status": "disabled"}


@router.post("/autonomy/control")
async def control(
    body: ControlRequest,
    request: Request,
    _: bool = Depends(verify_admin_api_key),
):
    """下发控制指令：enable / disable / pause / resume / emergency_stop。

    C5: 控制类端点补管理员鉴权（GET 状态端点保持开放）。
    非法 action 返回 400；manager 为 None 时对 enable 尝试从装配入口获取已装配
    单例，仍不可用则尝试运行时装配（services 可用时），均不可用则返回 400。
    enable/disable 会持久化开关状态，保证跨重启保持。
    """
    action = body.action
    if action not in CONTROL_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"非法 action {action!r}，可选 {list(CONTROL_ACTIONS)}",
        )

    manager = _manager
    if manager is None:
        if action == "enable":
            manager = await _try_ensure_manager(request)
        if manager is None:
            raise HTTPException(status_code=400, detail="自主系统未装配，无法执行控制指令")

    method = getattr(manager, action)
    method()
    await _persist_enabled(action, manager)
    return {"status": "ok", "state": _manager_state(manager)}


@router.get("/autonomy/audit")
def list_audit(limit: int = 50, offset: int = 0):
    """返回审计日志分页列表 {"items": [...], "total": int}。

    AuditStore 未装配时返回空列表与 total=0。
    """
    # R9: 分页参数钳制（对齐 tuner.py:252 惯例）
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    store = _audit_store
    if store is None:
        return {"items": [], "total": 0}
    return store.list(limit=limit, offset=offset)


@router.get("/autonomy/config")
def get_config():
    """返回当前自主系统配置（对齐 autonomy_config.schema.json）。未装配返回 404。"""
    manager = _manager
    if manager is None or manager.config is None:
        raise HTTPException(status_code=404, detail="自主系统未装配")
    return manager.config.model_dump()


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并：patch 中的 dict 与 base 中同名 dict 深度合并，其余键整体覆盖。

    用于局部更新配置时保留嵌套子对象（search/schedule/budget/permissions/safety）
    未被提交的字段，配合 model_validate 自动补齐缺失字段。
    """
    result = dict(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@router.put("/autonomy/config")
def update_config(partial: Dict[str, Any], _: bool = Depends(verify_admin_api_key)):
    """局部更新自主系统配置并保存（自动补齐缺失字段）。

    C5: 写路径端点补管理员鉴权。
    以当前配置为基础做深度合并后经 AutonomyConfig.model_validate 校验；非法字段
    （extra="forbid"）、非法枚举/非法时间格式返回 422。未装配返回 404。
    读改写（读 manager.config → _deep_merge → save_config）整体持
    _CONFIG_WRITE_LOCK（sync 线程池上下文直接 with）：与 control 持久化路径
    串行化，消除双入口并发写交错损坏文件与丢更新（R3）。
    """
    manager = _manager
    if manager is None or manager.config is None:
        raise HTTPException(status_code=404, detail="自主系统未装配")

    with _CONFIG_WRITE_LOCK:
        current = manager.config.model_dump()
        merged = _deep_merge(current, partial)
        try:
            updated = AutonomyConfig.model_validate(merged)
        except (ValidationError, ValueError) as e:
            raise HTTPException(status_code=422, detail=f"配置字段非法: {e}") from e

        save_config(updated)
        manager.config = updated
    return updated.model_dump()
