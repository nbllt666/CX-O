"""
插件处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_error
from server.protocol.actions import PluginActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager
    from server.services.cxhms_client import CXHMSClient

logger = logging.getLogger(__name__)


def register_plugin_handlers(manager: "ConnectionManager", cxhms_client: "CXHMSClient"):

    async def handle_plugin_register(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(PluginActions.REGISTER, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"Plugin register error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=PluginActions.REGISTER,
                code="PLUGIN_ERROR",
                message=str(e)
            ))

    async def handle_plugin_heartbeat(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(PluginActions.HEARTBEAT, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"Plugin heartbeat error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=PluginActions.HEARTBEAT,
                code="PLUGIN_ERROR",
                message=str(e)
            ))

    async def handle_plugin_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(PluginActions.LIST, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"Plugin list error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=PluginActions.LIST,
                code="PLUGIN_ERROR",
                message=str(e)
            ))

    manager.register_handler(PluginActions.REGISTER, handle_plugin_register)
    manager.register_handler(PluginActions.HEARTBEAT, handle_plugin_heartbeat)
    manager.register_handler(PluginActions.LIST, handle_plugin_list)
