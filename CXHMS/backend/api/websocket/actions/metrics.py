"""
监控 Action 处理器
"""
import logging
import time
from typing import TYPE_CHECKING

from ..protocol import create_response, create_error

if TYPE_CHECKING:
    from ..server import ConnectionManager

logger = logging.getLogger(__name__)


class MetricsActions:
    GET = "metrics.get"
    REQUESTS = "metrics.requests"
    HISTORY = "metrics.history"


_request_count = 0


def register_metrics_handlers(manager: "ConnectionManager"):
    
    async def handle_metrics_get(websocket, message, client_id):
        global _request_count
        request_id = message.get("request_id", "")
        
        try:
            _request_count += 1
            metrics = {
                "request_count": _request_count,
                "uptime": time.time(),
                "connections": 1
            }
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MetricsActions.GET,
                data={"metrics": metrics}
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
