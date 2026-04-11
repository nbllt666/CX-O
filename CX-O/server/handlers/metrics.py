"""
监控处理器
"""
import logging
from typing import TYPE_CHECKING, Optional

from server.protocol.message import create_response, create_error
from server.protocol.actions import MetricsActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)


def register_metrics_handlers(manager: "ConnectionManager"):
    _manager = manager

    async def handle_metrics_get(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            metrics = _manager.get_stats()

            try:
                from server.gateway.health import health_checker
                health_status = health_checker.get_all_status()
                metrics["health"] = health_status
            except Exception as e:
                logger.warning(f"Could not get health status: {e}")

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MetricsActions.GET,
                data=metrics
            ))
        except Exception as e:
            logger.error(f"Metrics get error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MetricsActions.GET,
                code="METRICS_ERROR",
                message=str(e)
            ))

    _manager.register_handler(MetricsActions.GET, handle_metrics_get)