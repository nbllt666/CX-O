from typing import List

from fastapi import APIRouter, HTTPException

from server.core.cxfc.models import (
    CXFCRegisterRequest,
    CXFCHeartbeatRequest,
    CXFCEvent,
    CXFCConnectRequest,
)
from server.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)

_cxfc_manager = None
_discovery = None


def get_cxfc_manager():
    global _cxfc_manager
    return _cxfc_manager


def set_cxfc_manager(manager):
    global _cxfc_manager
    _cxfc_manager = manager


def set_cxfc_discovery(d):
    global _discovery
    _discovery = d


@router.post("/cxfc/register")
async def register_plugin(request: CXFCRegisterRequest):
    cxfc_manager = get_cxfc_manager()
    try:
        plugin = await cxfc_manager.register_plugin(request)
        return {"status": "ok", "plugin_id": plugin.plugin_id}
    except Exception as e:
        logger.error(f"插件注册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/heartbeat")
async def heartbeat(request: CXFCHeartbeatRequest):
    cxfc_manager = get_cxfc_manager()
    try:
        alive = await cxfc_manager.update_heartbeat(request.plugin_id, request.port)
        if not alive:
            raise HTTPException(status_code=404, detail="插件不存在")
        return {"status": "alive"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"心跳处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/event/push")
async def push_event(event: CXFCEvent):
    cxfc_manager = get_cxfc_manager()
    try:
        await cxfc_manager.push_event(event)
        return {"status": "received"}
    except Exception as e:
        logger.error(f"事件推送失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/cxfc/discover")
async def discover_plugins(scan: bool = False):
    cxfc_manager = get_cxfc_manager()
    try:
        plugins = cxfc_manager.get_plugins()
        result = {"plugins": plugins}
        if scan:
            if _discovery:
                network_plugins = await _discovery.scan_network()
                result["network_plugins"] = network_plugins
            else:
                result["network_plugins"] = []
        return result
    except Exception as e:
        logger.error(f"插件发现失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/cxfc/skills")
async def get_skills():
    cxfc_manager = get_cxfc_manager()
    try:
        skills = cxfc_manager.get_skill_registry().get_all_skills()
        return {"skills": skills}
    except Exception as e:
        logger.error(f"获取Skills失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/connect")
async def connect_to_plugin(request: CXFCConnectRequest):
    cxfc_manager = get_cxfc_manager()
    try:
        plugin = await cxfc_manager.connect_to_plugin(request.host, request.port)
        if not plugin:
            raise HTTPException(status_code=503, detail="无法连接到指定插件")
        return {"status": "ok", "plugin": plugin}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"连接插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete("/cxfc/plugins/{plugin_id}")
async def disconnect_plugin(plugin_id: str):
    cxfc_manager = get_cxfc_manager()
    try:
        await cxfc_manager.disconnect_plugin(plugin_id, remove_persistent=True)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"断开插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/cxfc/plugins")
async def list_plugins():
    cxfc_manager = get_cxfc_manager()
    try:
        plugins = cxfc_manager.get_plugins()
        return {"plugins": plugins}
    except Exception as e:
        logger.error(f"列出插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/plugins/{plugin_id}/refresh")
async def refresh_plugin(plugin_id: str):
    cxfc_manager = get_cxfc_manager()
    try:
        plugin = await cxfc_manager.refresh_plugin(plugin_id)
        if not plugin:
            raise HTTPException(status_code=404, detail="插件不存在或未连接")
        return {"status": "ok", "plugin": plugin}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"刷新插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")
