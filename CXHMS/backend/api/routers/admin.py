import os
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Header, HTTPException

from backend.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "chenxi-admin-default-key-change-in-production")


def verify_admin_key(x_api_key: Optional[str] = Header(None)) -> bool:
    """验证管理员 API Key"""
    if not x_api_key:
        return False
    return x_api_key == ADMIN_API_KEY


@router.get("/admin/dashboard")
async def get_dashboard(x_api_key: Optional[str] = Header(None)):
    if not verify_admin_key(x_api_key):
        raise HTTPException(status_code=401, detail="未授权访问")

    from backend.api.app import get_acp_manager, get_context_manager, get_memory_manager

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
    if not verify_admin_key(x_api_key):
        raise HTTPException(status_code=401, detail="未授权访问")

    from backend.api.app import get_context_manager, get_memory_manager
    from backend.core.tools.registry import tool_registry

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
    from backend.api.app import get_acp_manager, get_context_manager, get_memory_manager

    health = {"memory": "unknown", "context": "unknown", "acp": "unknown"}

    try:
        memory_mgr = get_memory_manager()
        health["memory"] = "healthy"
    except Exception:
        health["memory"] = "unhealthy"

    try:
        context_mgr = get_context_manager()
        health["context"] = "healthy"
    except Exception:
        health["context"] = "unhealthy"

    try:
        acp_mgr = get_acp_manager()
        acp_stats = await acp_mgr.get_statistics()
        health["acp"] = "healthy" if acp_stats.get("total_agents", 0) >= 0 else "unhealthy"
    except Exception:
        health["acp"] = "unhealthy"

    overall = "healthy" if all(h == "healthy" for h in health.values()) else "degraded"

    return {"status": overall, "components": health}


@router.get("/admin/config")
async def get_config(x_api_key: Optional[str] = Header(None)):
    if not verify_admin_key(x_api_key):
        raise HTTPException(status_code=401, detail="未授权访问")

    from config.settings import settings

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
async def update_config(config: Dict, x_api_key: Optional[str] = Header(None)):
    if not verify_admin_key(x_api_key):
        raise HTTPException(status_code=401, detail="未授权访问")

    from config.settings import settings

    try:
        if not isinstance(config, dict):
            raise HTTPException(status_code=400, detail="配置必须是对象格式")

        if "llm" in config:
            if "provider" in config["llm"]:
                provider = config["llm"]["provider"]
                if provider not in ["ollama", "vllm"]:
                    raise HTTPException(status_code=400, detail=f"不支持的LLM提供商: {provider}")
                settings.config.llm.provider = provider
            if "model" in config["llm"]:
                settings.config.llm.model = config["llm"]["model"]

        if "vector" in config:
            if "enabled" in config["vector"]:
                settings.config.vector.enabled = bool(config["vector"]["enabled"])

        if "acp" in config:
            if "enabled" in config["acp"]:
                settings.config.acp.enabled = bool(config["acp"]["enabled"])
            if "agent_name" in config["acp"]:
                settings.config.acp.agent_name = str(config["acp"]["agent_name"])

        if "system" in config:
            if "debug" in config["system"]:
                settings.config.system.debug = bool(config["system"]["debug"])

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
    if not verify_admin_key(x_api_key):
        raise HTTPException(status_code=401, detail="未授权访问")

    import logging

    if lines > 1000:
        lines = 1000
    if lines < 1:
        lines = 50

    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if level.upper() not in valid_levels:
        level = "INFO"

    return {
        "status": "success",
        "logs": ["日志功能通过服务端日志文件查看", f"当前日志级别: {level}", f"请求行数: {lines}"],
        "total": 3,
        "level": level,
        "lines": lines,
    }


@router.post("/admin/backup")
async def create_backup(x_api_key: Optional[str] = Header(None)):
    if not verify_admin_key(x_api_key):
        raise HTTPException(status_code=401, detail="未授权访问")

    import os
    import shutil

    try:
        data_dir = "data"
        backup_dir = "data/backups"

        if not os.path.exists(data_dir):
            raise HTTPException(status_code=400, detail="数据目录不存在")

        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{timestamp}"
        backup_path = f"{backup_dir}/{backup_name}"

        shutil.make_archive(backup_path, "zip", data_dir)

        logger.info(f"创建备份: {backup_path}.zip")

        return {
            "status": "success",
            "path": f"{backup_path}.zip",
            "message": f"备份已创建: {backup_name}.zip",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建备份失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="创建备份失败")
