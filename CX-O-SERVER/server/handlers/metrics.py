"""
监控处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error
from server.protocol.actions import MetricsActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def register_metrics_handlers(manager: "WebSocketManager"):

    async def handle_metrics_get(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.dependencies import get_memory_manager, get_acp_manager, get_mcp_manager

            metrics = {}

            try:
                memory_mgr = get_memory_manager()
                metrics["memory"] = memory_mgr.get_statistics()
            except Exception as e:
                logger.warning("获取memory metrics失败: %s", e, exc_info=True)
                metrics["memory"] = {"error": "unavailable"}

            try:
                acp_mgr = get_acp_manager()
                metrics["acp"] = await acp_mgr.get_statistics()
            except Exception as e:
                logger.warning("获取acp metrics失败: %s", e, exc_info=True)
                metrics["acp"] = {"error": "unavailable"}

            try:
                mcp_mgr = get_mcp_manager()
                metrics["mcp"] = mcp_mgr.get_stats()
            except Exception as e:
                logger.warning("获取mcp metrics失败: %s", e, exc_info=True)
                metrics["mcp"] = {"error": "unavailable"}

            try:
                from server.core.tools import tool_registry
                metrics["tools"] = tool_registry.get_tool_stats()
            except Exception as e:
                logger.warning("获取tools metrics失败: %s", e, exc_info=True)
                metrics["tools"] = {"error": "unavailable"}

            try:
                from server.core.plugins.manager import get_plugin_manager
                plugin_mgr = get_plugin_manager()
                metrics["plugins"] = plugin_mgr.get_stats()
            except Exception as e:
                logger.warning("获取plugins metrics失败: %s", e, exc_info=True)
                metrics["plugins"] = {"error": "unavailable"}

            metrics["gateway"] = manager.get_stats()

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MetricsActions.GET,
                data=metrics
            ))
        except Exception as e:
            logger.error(f"Metrics get error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MetricsActions.GET,
                code="METRICS_ERROR",
                message=str(e)
            ))

    manager.register_handler(MetricsActions.GET, handle_metrics_get)
