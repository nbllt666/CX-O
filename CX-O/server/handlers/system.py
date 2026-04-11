"""
系统处理器
"""
import logging
from typing import TYPE_CHECKING, Optional

from server.protocol.message import create_response, create_error
from server.protocol.actions import SystemActions
from server.gateway.health import health_checker

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)


def register_system_handlers(manager: "ConnectionManager"):
    _manager = manager

    async def handle_system_health(websocket, message, client_id):
        request_id = message.get("request_id", "")

        try:
            status = health_checker.get_all_status()
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=SystemActions.HEALTH,
                data=status
            ))
        except Exception as e:
            logger.error(f"System health error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=SystemActions.HEALTH,
                code="SYSTEM_ERROR",
                message=str(e)
            ))

    async def handle_system_status(websocket, message, client_id):
        request_id = message.get("request_id", "")

        try:
            stats = _manager.get_stats()
            status = {
                "status": "running",
                "stats": stats,
                "connections": len(_manager._connections),
                "handlers": list(_manager._handlers.keys())
            }
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=SystemActions.STATUS,
                data=status
            ))
        except Exception as e:
            logger.error(f"System status error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=SystemActions.STATUS,
                code="SYSTEM_ERROR",
                message=str(e)
            ))

    async def handle_system_info(websocket, message, client_id):
        request_id = message.get("request_id", "")

        try:
            info = {
                "version": "1.0.0",
                "name": "CX-O Gateway",
                "description": "微服务网关 - 统一 WebSocket 和 HTTP API 通讯入口"
            }
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=SystemActions.INFO,
                data=info
            ))
        except Exception as e:
            logger.error(f"System info error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=SystemActions.INFO,
                code="SYSTEM_ERROR",
                message=str(e)
            ))

    _manager.register_handler(SystemActions.HEALTH, handle_system_health)
    _manager.register_handler(SystemActions.STATUS, handle_system_status)
    _manager.register_handler(SystemActions.INFO, handle_system_info)