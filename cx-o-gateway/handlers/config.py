"""
配置处理器
"""
import logging
from typing import TYPE_CHECKING

from protocol.message import create_error
from protocol.actions import ConfigActions

if TYPE_CHECKING:
    from gateway.server import ConnectionManager
    from services.cxhms_client import CXHMSClient

logger = logging.getLogger(__name__)


def register_config_handlers(manager: "ConnectionManager", cxhms_client: "CXHMSClient"):
    
    async def handle_config_get(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            response = await cxhms_client.request(ConfigActions.GET, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"Config get error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ConfigActions.GET,
                code="CONFIG_ERROR",
                message=str(e)
            ))

    async def handle_config_set(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            response = await cxhms_client.request(ConfigActions.SET, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"Config set error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ConfigActions.SET,
                code="CONFIG_ERROR",
                message=str(e)
            ))

    manager.register_handler(ConfigActions.GET, handle_config_get)
    manager.register_handler(ConfigActions.SET, handle_config_set)
