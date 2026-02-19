"""
系统 Action 处理器
"""
import logging
import time
from typing import TYPE_CHECKING

from ..protocol import create_response, create_error

if TYPE_CHECKING:
    from ..server import ConnectionManager

logger = logging.getLogger(__name__)


class SystemActions:
    HEALTH = "system.health"
    STATUS = "system.status"
    INFO = "system.info"


_start_time = time.time()


def register_system_handlers(manager: "ConnectionManager"):
    
    async def handle_system_health(websocket, message, client_id):
        request_id = message.get("request_id", "")
        
        try:
            health = {
                "status": "healthy",
                "uptime": time.time() - _start_time,
                "timestamp": time.time()
            }
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=SystemActions.HEALTH,
                data=health
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
                "status": "running",
                "uptime": time.time() - _start_time,
                "version": "1.0.0"
            }
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
