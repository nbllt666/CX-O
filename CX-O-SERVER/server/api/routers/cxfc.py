"""CXFC 端点——插件注册、心跳与事件分发接口。"""
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.core.cxfc.models import (
    CXFCRegisterRequest,
    CXFCHeartbeatRequest,
    CXFCEvent,
    CXFCConnectRequest,
    CXFCRelayRegisterRequest,
    CXFCRelayResultRequest,
    CXFCEmbeddedRegisterRequest,
)
from server.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)


class CXFCCallToolRequest(BaseModel):
    """CXFC 插件工具调用请求"""

    tool: str
    arguments: Dict[str, Any] = {}

_cxfc_manager = None
_discovery = None


def get_cxfc_manager():
    """返回模块级 CXFC 管理器单例（未设置时为 None）。"""
    return _cxfc_manager


def set_cxfc_manager(manager):
    """设置 CXFC 管理器实例。"""
    global _cxfc_manager
    _cxfc_manager = manager


def set_cxfc_discovery(d):
    """设置网络发现器实例，用于局域网插件发现扫描。"""
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
    """推送一个 CXFC 事件。"""
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


@router.post("/cxfc/plugins/{plugin_id}/disconnect")
async def disconnect_plugin_keep_registration(plugin_id: str):
    """断开插件连接但保留注册记录（可重新连接）。"""
    cxfc_manager = get_cxfc_manager()
    try:
        await cxfc_manager.disconnect_plugin(plugin_id, remove_persistent=False)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"断开插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/cxfc/plugins")
async def list_plugins():
    """列出已注册的 CXFC 插件。"""
    cxfc_manager = get_cxfc_manager()
    try:
        plugins = cxfc_manager.get_plugins()
        return {"plugins": plugins}
    except Exception as e:
        logger.error(f"列出插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/plugins/{plugin_id}/refresh")
async def refresh_plugin(plugin_id: str):
    """刷新指定插件的信息。"""
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


@router.post("/cxfc/plugins/{plugin_id}/call")
async def call_plugin_tool(plugin_id: str, request: CXFCCallToolRequest):
    """调用指定插件的工具

    通过主系统转发到插件侧的 POST /call 端点，实现工具调用。
    用于测试工具验证端到端调用链路。
    """
    cxfc_manager = get_cxfc_manager()
    try:
        result = await cxfc_manager.call_tool(plugin_id, request.tool, request.arguments)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"调用插件工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/relay/register")
async def relay_register(request: CXFCRelayRegisterRequest):
    """注册一个 relay（前端转接）插件目标。

    前端（或经前端代理的远端插件）登记插件描述与令牌；后端随后需为该 plugin_id
    注入活跃通道（register_relay_dispatcher）才能投递调用。
    """
    cxfc_manager = get_cxfc_manager()
    try:
        plugin = await cxfc_manager.register_relay_plugin(
            plugin_id=request.plugin_id or request.name,
            name=request.name,
            tools=request.tools,
            skills=request.skills,
            capabilities=request.capabilities,
            token=request.token,
        )
        return {"status": "ok", "plugin_id": plugin.plugin_id}
    except Exception as e:
        logger.error(f"relay 注册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/cxfc/relay/targets")
async def relay_targets():
    """列出已注册并注入通道的 relay 插件目标。"""
    cxfc_manager = get_cxfc_manager()
    try:
        return {"targets": cxfc_manager.get_relay_targets()}
    except Exception as e:
        logger.error(f"获取 relay 目标失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/relay/result")
async def relay_result(request: CXFCRelayResultRequest):
    """前端回报一次被转发的工具调用结果，回填给后端等待中的调用方。"""
    cxfc_manager = get_cxfc_manager()
    try:
        payload = {
            "success": request.success,
            "result": request.result,
            "error": request.error,
        }
        resolved = cxfc_manager.complete_relay_result(request.plugin_id, request.request_id, payload)
        if not resolved:
            raise HTTPException(status_code=404, detail="未找到对应待回报调用")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"relay 结果回报失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/embedded")
async def embedded_register(request: CXFCEmbeddedRegisterRequest):
    """登记后端进程内嵌入式工具描述（transport=embedded，不走网络）。

    实际 handler 由 register_embedded_plugin() 以 Callable 在进程内注入；此处登记
    描述供列出与管理时展示传输类型。handler 由调用方注入后，调用走进程内分发。
    """
    cxfc_manager = get_cxfc_manager()
    try:
        tools = [t.model_dump() for t in request.tools]
        plugin = await cxfc_manager.register_embedded_plugin(
            plugin_id=request.plugin_id,
            name=request.name,
            tools=tools,
            skills=request.skills,
            capabilities=request.capabilities,
        )
        return {"status": "ok", "plugin_id": plugin.plugin_id}
    except Exception as e:
        logger.error(f"嵌入式插件注册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")
