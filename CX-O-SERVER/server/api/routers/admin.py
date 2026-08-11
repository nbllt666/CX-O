"""管理端点——API 密钥、运行时配置与数据管理接口。"""
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
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
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Admin API key not configured")
    if not x_api_key or not secrets.compare_digest(x_api_key, ADMIN_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return True


@router.get("/admin/dashboard")
async def get_dashboard(x_api_key: Optional[str] = Header(None)):
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
    # B10 修复: 原返回占位字符串（"日志功能通过服务端日志文件查看"），
    # 前端误以为日志功能可用。改为明确提示"暂未实现"。
    verify_admin_api_key(x_api_key)

    if lines > 1000:
        lines = 1000
    if lines < 1:
        lines = 50

    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if level.upper() not in valid_levels:
        level = "INFO"

    return {
        "status": "success",
        "logs": [
            f"[{level}] 日志查看功能暂未实现，请通过 logs/cxo.log 文件查看服务端日志",
        ],
        "total": 1,
        "level": level,
        "lines": lines,
    }


@router.post("/admin/backup")
async def create_backup(x_api_key: Optional[str] = Header(None)):
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
