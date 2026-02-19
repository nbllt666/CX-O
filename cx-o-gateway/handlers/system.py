"""
系统处理器
"""
import logging
from typing import TYPE_CHECKING

from protocol.message import create_response, create_error
from protocol.actions import SystemActions
from gateway.health import health_checker

if TYPE_CHECKING:
    from gateway.server import ConnectionManager
    from services.cxhms_client import CXHMSClient

logger = logging.getLogger(__name__)


def register_system_handlers(manager: "ConnectionManager", cxhms_client: "CXHMSClient"):
    
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
            response = await cxhms_client.request(SystemActions.STATUS, {})
            await manager.send_message(client_id, response)
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
