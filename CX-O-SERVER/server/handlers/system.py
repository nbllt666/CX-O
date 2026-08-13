"""
系统处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error
from server.protocol.actions import SystemActions
from server.gateway.health import health_checker

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def register_system_handlers(manager: "WebSocketManager"):
    """将系统（健康/状态）处理器注册到 WebSocket 管理器。"""

    async def handle_system_health(websocket, message, client_id):
        request_id = message.get("request_id", "")

        try:
            status = health_checker.get_all_status()
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=SystemActions.HEALTH,
                data=status
            ))
        except Exception as e:
            logger.error(f"System health error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=SystemActions.HEALTH,
                code="SYSTEM_ERROR",
                message=str(e)
            ))

    async def handle_system_status(websocket, message, client_id):
        request_id = message.get("request_id", "")

        try:
            status = {
                "gateway": manager.get_stats(),
                "services": {},
            }

            try:
                from server.dependencies import get_memory_manager
                memory_mgr = get_memory_manager()
                status["services"]["memory"] = {"available": True, "stats": memory_mgr.get_statistics()}
            except Exception as e:
                logger.warning("获取memory管理器状态失败: %s", e, exc_info=True)
                status["services"]["memory"] = {"available": False}

            try:
                from server.dependencies import get_acp_manager
                acp_mgr = get_acp_manager()
                status["services"]["acp"] = {"available": True, "stats": await acp_mgr.get_statistics()}
            except Exception as e:
                logger.warning("获取acp管理器状态失败: %s", e, exc_info=True)
                status["services"]["acp"] = {"available": False}

            try:
                from server.dependencies import get_mcp_manager
                mcp_mgr = get_mcp_manager()
                status["services"]["mcp"] = {"available": True, "stats": mcp_mgr.get_stats()}
            except Exception as e:
                logger.warning("获取mcp管理器状态失败: %s", e, exc_info=True)
                status["services"]["mcp"] = {"available": False}

            try:
                from server.dependencies import get_llm_client
                llm = get_llm_client()
                # 防御性访问 model_name，避免 llm 对象无此属性时 AttributeError
                status["services"]["llm"] = {"available": True, "model": getattr(llm, "model_name", "unknown")}
            except Exception as e:
                logger.warning("获取llm客户端状态失败: %s", e, exc_info=True)
                status["services"]["llm"] = {"available": False}

            try:
                from server.dependencies import get_model_router
                mr = get_model_router()
                status["services"]["model_router"] = {"available": True, "stats": mr.get_all_models_info()}
            except Exception as e:
                logger.warning("获取model router状态失败: %s", e, exc_info=True)
                status["services"]["model_router"] = {"available": False}

            try:
                from server.core.tools import tool_registry
                status["services"]["tools"] = {"available": True, "stats": tool_registry.get_tool_stats()}
            except Exception as e:
                logger.warning("获取tools状态失败: %s", e, exc_info=True)
                status["services"]["tools"] = {"available": False}

            try:
                from server.core.plugins.manager import get_plugin_manager
                plugin_mgr = get_plugin_manager()
                status["services"]["plugins"] = {"available": True, "stats": plugin_mgr.get_stats()}
            except Exception as e:
                logger.warning("获取plugins状态失败: %s", e, exc_info=True)
                status["services"]["plugins"] = {"available": False}

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=SystemActions.STATUS,
                data=status
            ))
        except Exception as e:
            logger.error(f"System status error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=SystemActions.STATUS,
                code="SYSTEM_ERROR",
                message=str(e)
            ))

    manager.register_handler(SystemActions.HEALTH, handle_system_health)
    manager.register_handler(SystemActions.STATUS, handle_system_status)
