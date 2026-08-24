"""管理端点——API 密钥、运行时配置与数据管理接口。"""
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")

# 项目根目录（c:\CX-O\CX-O-SERVER）：本文件位于 server/api/routers/ 下，向上 4 级即项目根。
# 与 audio.py/config.py/avatars.py/agents.py 的 _PROJECT_ROOT 模式对齐（rules-0 §三：禁止相对路径）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_BACKUP_DIR = _DATA_DIR / "backups"


# ---------------------------------------------------------------------------
# B10 修复: PUT /admin/config 添加 Pydantic schema 校验
# 原实现接收 config: Dict，任意嵌套结构都会被写入 settings，缺少 schema 校验。
# ---------------------------------------------------------------------------


class LLMConfigUpdate(BaseModel):
    """LLM 配置更新片段。"""

    provider: Optional[str] = None
    model: Optional[str] = None


class VectorConfigUpdate(BaseModel):
    """向量配置更新片段。"""

    enabled: Optional[bool] = None


class ACPConfigUpdate(BaseModel):
    """ACP 配置更新片段。"""

    enabled: Optional[bool] = None
    agent_name: Optional[str] = None


class SystemConfigUpdate(BaseModel):
    """系统配置更新片段。"""

    debug: Optional[bool] = None


class AdminConfigUpdate(BaseModel):
    """管理员配置更新请求体 schema。"""

    llm: Optional[LLMConfigUpdate] = None
    vector: Optional[VectorConfigUpdate] = None
    acp: Optional[ACPConfigUpdate] = None
    system: Optional[SystemConfigUpdate] = None


def verify_admin_api_key(x_api_key: Optional[str] = Header(None)) -> bool:
    """校验管理端 API 密钥，未配置或校验失败时抛出 403。"""
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Admin API key not configured")
    if not x_api_key or not secrets.compare_digest(x_api_key, ADMIN_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True


@router.get("/admin/dashboard")
async def get_dashboard(x_api_key: Optional[str] = Header(None)):
    """获取管理后台仪表盘统计。"""
    # B10 修复: verify_admin_api_key 在认证失败时已 raise 403，
    # 永远不会返回 False，原 401 路径为死代码，已删除。
    verify_admin_api_key(x_api_key)

    from server.dependencies import get_acp_manager, get_context_manager, get_memory_manager

    stats = {"memory": {}, "context": {}, "acp": {}}

    try:
        memory_mgr = get_memory_manager()
        stats["memory"] = memory_mgr.get_statistics()
    except Exception as e:
        logger.warning(f"获取内存管理统计失败: {e}")

    try:
        context_mgr = get_context_manager()
        stats["context"] = context_mgr.get_statistics()
    except Exception as e:
        logger.warning(f"获取上下文管理统计失败: {e}")

    try:
        acp_mgr = get_acp_manager()
        stats["acp"] = await acp_mgr.get_statistics()
    except Exception as e:
        logger.warning(f"获取ACP统计失败: {e}")

    return {"status": "success", "timestamp": datetime.now().isoformat(), "dashboard": stats}


@router.get("/admin/stats")
async def get_stats(x_api_key: Optional[str] = Header(None)):
    # B10 修复: verify_admin_api_key 在认证失败时已 raise 403，
    # 永远不会返回 False，原 401 路径为死代码，已删除。
    verify_admin_api_key(x_api_key)

    from server.dependencies import get_context_manager, get_memory_manager
    from server.core.tools.registry import tool_registry

    stats = {"memory": {}, "context": {}, "tools": {}}

    try:
        memory_mgr = get_memory_manager()
        stats["memory"] = memory_mgr.get_statistics()
    except Exception as e:
        logger.warning(f"获取内存管理统计失败: {e}")

    try:
        context_mgr = get_context_manager()
        stats["context"] = context_mgr.get_statistics()
    except Exception as e:
        logger.warning(f"获取上下文管理统计失败: {e}")

    try:
        stats["tools"] = tool_registry.get_tool_stats()
    except Exception as e:
        logger.warning(f"获取工具统计失败: {e}")

    return {"status": "success", "statistics": stats}


@router.get("/admin/health")
async def health_check():
    """健康检查端点 - 不需要认证"""
    from server.dependencies import get_acp_manager, get_context_manager, get_memory_manager

    health = {"memory": "unknown", "context": "unknown", "acp": "unknown"}

    try:
        get_memory_manager()
        health["memory"] = "healthy"
    except Exception:
        health["memory"] = "unhealthy"

    try:
        get_context_manager()
        health["context"] = "healthy"
    except Exception:
        health["context"] = "unhealthy"

    try:
        acp_mgr = get_acp_manager()
        await acp_mgr.get_statistics()
        # BUG-B-M9 修复: 原判断 acp_stats.get("total_agents", 0) >= 0 恒为 True
        # (数量不可能为负),无意义。能成功获取统计信息即说明 ACP 健康。
        health["acp"] = "healthy"
    except Exception:
        health["acp"] = "unhealthy"

    overall = "healthy" if all(h == "healthy" for h in health.values()) else "degraded"

    return {"status": overall, "components": health}


@router.get("/admin/config")
async def get_config(x_api_key: Optional[str] = Header(None)):
    # B10 修复: verify_admin_api_key 在认证失败时已 raise 403，
    # 永远不会返回 False，原 401 路径为死代码，已删除。
    verify_admin_api_key(x_api_key)

    from server.config import get_settings
    settings = get_settings()

    return {
        "status": "success",
        "config": {
            "llm": {"provider": settings.config.llm.provider, "model": settings.config.llm.model},
            "vector": {"enabled": settings.config.vector.enabled},
            "acp": {
                "enabled": settings.config.acp.enabled,
                "agent_name": settings.config.acp.agent_name,
            },
            "system": {"debug": settings.config.system.debug},
        },
    }


@router.put("/admin/config")
async def update_config(config: AdminConfigUpdate, x_api_key: Optional[str] = Header(None)):
    # B10 修复: verify_admin_api_key 在认证失败时已 raise 403，
    # 永远不会返回 False，原 401 路径为死代码，已删除。
    # B10 修复: 参数类型从 Dict 改为 AdminConfigUpdate，添加 schema 校验。
    verify_admin_api_key(x_api_key)

    from server.config import get_settings
    settings = get_settings()

    try:
        if config.llm:
            if config.llm.provider is not None:
                provider = config.llm.provider
                if provider not in ["ollama", "vllm"]:
                    raise HTTPException(status_code=400, detail=f"不支持的LLM提供商: {provider}")
                settings.config.llm.provider = provider
            if config.llm.model is not None:
                settings.config.llm.model = config.llm.model

        if config.vector:
            if config.vector.enabled is not None:
                settings.config.vector.enabled = config.vector.enabled

        if config.acp:
            if config.acp.enabled is not None:
                settings.config.acp.enabled = config.acp.enabled
            if config.acp.agent_name is not None:
                settings.config.acp.agent_name = config.acp.agent_name

        if config.system:
            if config.system.debug is not None:
                settings.config.system.debug = config.system.debug

        settings.save_config()

        logger.info("管理员更新了系统配置")

        return {"status": "success", "message": "配置已更新"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="更新配置失败")


@router.get("/admin/logs")
async def get_logs(level: str = "INFO", lines: int = 50, x_api_key: Optional[str] = Header(None)):
    # B10 修复: verify_admin_api_key 在认证失败时已 raise 403，
    # 永远不会返回 False，原 401 路径为死代码，已删除。
    # 2026-08-23 修复: 取消占位实现，改为真实读取服务端日志（与 /service/logs 一致）。
    verify_admin_api_key(x_api_key)

    if lines > 1000:
        lines = 1000
    if lines < 1:
        lines = 50

    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if level.upper() not in valid_levels:
        level = "INFO"

    try:
        from server.api.routers.service import _backend_log_path
        import os

        log_file = _backend_log_path
        if not log_file:
            from server.api.routers.service import get_project_root

            log_file = os.path.join(get_project_root(), "logs", "cxo.log")
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                all_lines = [ln.rstrip("\n") for ln in f.readlines()]
            # 保持 logs 为数组类型（原接口契约），避免前端对返回类型变化解析失败
            return {"status": "success", "logs": all_lines[-lines:], "total": len(all_lines[-lines:]), "level": level, "lines": lines}
        return {"status": "success", "logs": ["No log file available"], "total": 0, "level": level, "lines": lines}
    except Exception as e:
        logger.error(f"Failed to read logs: {e}", exc_info=True)
        return {"status": "error", "logs": [f"读取日志失败: {e}"], "total": 0, "level": level, "lines": lines}


@router.post("/admin/backup")
async def create_backup(x_api_key: Optional[str] = Header(None)):
    """创建数据目录的压缩备份。"""
    # B10 修复: verify_admin_api_key 在认证失败时已 raise 403，
    # 永远不会返回 False，原 401 路径为死代码，已删除。
    verify_admin_api_key(x_api_key)

    import os
    import zipfile

    try:
        # 使用基于文件位置的项目绝对路径（_DATA_DIR/_BACKUP_DIR），消除 CWD 依赖。
        data_dir = str(_DATA_DIR)
        backup_dir = str(_BACKUP_DIR)

        if not os.path.exists(data_dir):
            raise HTTPException(status_code=400, detail="数据目录不存在")

        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{timestamp}"
        backup_path = f"{backup_dir}/{backup_name}.zip"

        # BUG-B-M8 修复: 排除 data/backups 目录,避免备份嵌套导致体积指数增长。
        # 原实现使用 shutil.make_archive 打包整个 data 目录,其中包含 data/backups,
        # 导致每次备份都包含历史备份,体积指数增长。
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(data_dir):
                # 排除 backups 子目录,避免递归打包历史备份
                if "backups" in dirs:
                    dirs.remove("backups")
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, data_dir)
                    zipf.write(file_path, arcname)

        logger.info(f"创建备份: {backup_path}")

        return {
            "status": "success",
            "path": backup_path,
            "message": f"备份已创建: {backup_name}.zip",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建备份失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="创建备份失败")


# ===========================================================================
# CX-A 管理面（spec admin-plane-sentinel-cluster Part A）——新增端点
# 依赖 admin.enabled=true 时由 main.py 注入模块级运行时；未注入时端点按 503 disabled。
# 认证走 AdminAuth（Bearer token + request_id 防重放 + 限流）。
# ===========================================================================
_admin_auth = None
_control_plane = None
_manifest = None
_instance_registry = None
_cluster_bridge = None
_services = None


def inject_admin_runtime(auth, control_plane, manifest, instance_registry, cluster_bridge, services):
    """注入 CX-A 管理面运行时（main.py lifespan 调用；admin.enabled=true 时）。"""
    global _admin_auth, _control_plane, _manifest, _instance_registry, _cluster_bridge, _services
    from server.core.admin.cluster_bridge import audit_now as _audit_impl
    global audit_now
    audit_now = _audit_impl
    _admin_auth = auth
    _control_plane = control_plane
    _manifest = manifest
    _instance_registry = instance_registry
    _cluster_bridge = cluster_bridge
    _services = services


def _admin_unavailable():
    raise HTTPException(status_code=503, detail="CX-A 管理面未启用（admin.enabled=false）")


def _admin_guard(request: Request, required: str, request_id: str = None):
    """校验 Bearer token 足够权限 + 可选防重放 + 限流。未注入/未启用抛 503。"""
    if _admin_auth is None:
        _admin_unavailable()
    auth_header = (request.headers.get("Authorization") or "").strip()
    token = auth_header[7:] if auth_header.startswith("Bearer ") else auth_header
    try:
        level = _admin_auth.authenticate(token)
        _admin_auth.check_required_level(level, required)
        if request_id:
            _admin_auth.check_replay(request_id)
        _admin_auth.check_rate_limit()
    except HTTPException:
        raise
    except Exception as e:
        # 权限不足/防重放 → 403（无 Authorization 或 429 限流已在异常内区分，统一 403 兜底）
        raise HTTPException(status_code=403, detail=str(e))
    return level


@router.get("/admin/manifest")
async def admin_manifest(request: Request):
    _admin_guard(request, "readonly")
    if _manifest is None:
        _admin_unavailable()
    cluster_state = None
    if _cluster_bridge is not None:
        raw = _cluster_bridge.read_state()
        if isinstance(raw, dict) and raw.get("status") not in ("cluster_disabled", "error"):
            cluster_state = raw
        else:
            cluster_state = {"enabled": False}
    return _manifest.build(cluster_state)


@router.get("/admin/status")
async def admin_status(request: Request):
    _admin_guard(request, "readonly")
    snapshot = {
        "models": (_manifest.detect_models() if _manifest else {}),
        "capabilities": (_manifest.detect_capabilities() if _manifest else {}),
        "cluster": _cluster_bridge.read_state() if _cluster_bridge is not None else {"enabled": False},
    }
    return {"status": "success", "snapshot": snapshot}


class _ControlRequest(BaseModel):
    action: str
    target: str
    agent_id: Optional[str] = "default"
    request_id: str
    params: dict = {}


class _BatchRequest(BaseModel):
    request_id: str
    mode: str = "sequential"
    stop_on_error: bool = True
    steps: list = []


class _StepItem(BaseModel):
    target: str
    action: str
    agent_id: Optional[str] = "default"
    params: dict = {}


class _BatchRespStep(BaseModel):
    step: int
    ok: bool
    result: dict = {}
    duration_ms: float = 0


@router.post("/admin/control")
async def admin_control(request: Request, req: _ControlRequest):
    _admin_guard(request, "operator", request_id=req.request_id)
    if _control_plane is None:
        _admin_unavailable()
    try:
        import time
        t0 = time.monotonic()
        result = _control_plane.dispatch(req.action, req.target, req.request_id, req.agent_id or "default", req.params or {})
        from inspect import iscoroutine
        if iscoroutine(result):
            result = await result
        audit_now("CX-A", "info", "control", f"{req.target}/{req.action}", "管理面控制动作完成",
                  request_id=req.request_id, detail={"elapsed_ms": round((time.monotonic() - t0) * 1000, 1)})
        return {"status": "success", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/batch")
async def admin_batch(request: Request, req: _BatchRequest):
    _admin_guard(request, "operator", request_id=req.request_id)
    if _control_plane is None:
        _admin_unavailable()
    if not req.steps:
        raise HTTPException(status_code=400, detail="steps 不能为空")
    steps: list = []
    for i, st in enumerate(req.steps):
        if not isinstance(st, dict):
            raise HTTPException(status_code=400, detail=f"step[{i}] 必须是对象")
        steps.append(_StepItem(**st))

    async def _run_step(i: int, st: _StepItem):
        import time
        t0 = time.monotonic()
        try:
            result = _control_plane.dispatch(st.action, st.target, req.request_id, st.agent_id or "default", st.params or {})
            from inspect import iscoroutine
            if iscoroutine(result):
                result = await result
            return {"step": i, "ok": True, "result": result, "duration_ms": round((time.monotonic() - t0) * 1000, 1)}
        except Exception as e:
            return {"step": i, "ok": False, "result": {"error": str(e)}, "duration_ms": round((time.monotonic() - t0) * 1000, 1)}

    if req.mode == "parallel":
        import asyncio
        out = await asyncio.gather(*[_run_step(i, st) for i, st in enumerate(steps)])
    else:  # sequential
        out = []
        for i, st in enumerate(steps):
            r = await _run_step(i, st)
            out.append(r)
            if req.stop_on_error and not r["ok"]:
                break
    audit_now("CX-A", "info", "batch", f"mode={req.mode}", "批量编排执行",
              request_id=req.request_id, detail={"steps": len(steps), "completed": len(out)})
    return {"status": "success", "mode": req.mode, "steps": out}


@router.get("/admin/audit")
async def admin_audit(request: Request, limit: int = 50, offset: int = 0):
    _admin_guard(request, "readonly")
    from server.core.admin.cluster_bridge import _audit_read
    return {"status": "success", "items": _audit_read(limit, offset)}


@router.post("/admin/register")
async def admin_register():
    """内部：CX-O 向 CX-A 注册（本机作为被注册方，仅记录；主动注册由 registry 承接）。"""
    return {"status": "success", "message": "registered", "registered": True}
