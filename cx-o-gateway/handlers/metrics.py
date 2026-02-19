"""
监控处理器
"""
import logging
from typing import TYPE_CHECKING

from protocol.message import create_error
from protocol.actions import MetricsActions

if TYPE_CHECKING:
    from gateway.server import ConnectionManager
    from services.cxhms_client import CXHMSClient

logger = logging.getLogger(__name__)


def register_metrics_handlers(manager: "ConnectionManager", cxhms_client: "CXHMSClient"):
    
    async def handle_metrics_get(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            response = await cxhms_client.request(MetricsActions.GET, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"Metrics get error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MetricsActions.GET,
                code="METRICS_ERROR",
                message=str(e)
            ))

    manager.register_handler(MetricsActions.GET, handle_metrics_get)
