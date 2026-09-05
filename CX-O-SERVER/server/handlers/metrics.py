"""
监控处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error
from server.protocol.actions import MetricsActions
from server.core.utils import run_io

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def register_metrics_handlers(manager: "WebSocketManager"):
    """将监控统计处理器注册到 WebSocket 管理器。"""

    async def handle_metrics_get(websocket, message, client_id):
        request_id = message.get("request_id", "")

        try:
            from server.dependencies import get_memory_manager, get_acp_manager, get_mcp_manager

            metrics = {}

            try:
                memory_mgr = get_memory_manager()
                # get_statistics 为同步主库读，移入线程池避免阻塞事件循环
                # （对齐下方 acp 的 await 形态）
                metrics["memory"] = await run_io(memory_mgr.get_statistics)
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

            # 语音链路延迟（spec Task 4，ADDITIVE 追加键，既有键不动）
            try:
                from server.core.metrics.voice_latency import get_voice_latency_tracker
                metrics["voice_latency"] = get_voice_latency_tracker().summary()
            except Exception as e:
                logger.warning("获取voice_latency metrics失败: %s", e, exc_info=True)
                metrics["voice_latency"] = {"error": "unavailable"}

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
