"""
ACP 处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_error
from server.protocol.actions import ACPActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager
    from server.services.cxhms_client import CXHMSClient

logger = logging.getLogger(__name__)


def register_acp_handlers(manager: "ConnectionManager", cxhms_client: "CXHMSClient"):

    async def handle_acp_connect(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(ACPActions.CONNECT, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"ACP connect error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ACPActions.CONNECT,
                code="ACP_ERROR",
                message=str(e)
            ))

    async def handle_acp_disconnect(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(ACPActions.DISCONNECT, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"ACP disconnect error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ACPActions.DISCONNECT,
                code="ACP_ERROR",
                message=str(e)
            ))

    async def handle_acp_connections(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(ACPActions.CONNECTIONS, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"ACP connections error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ACPActions.CONNECTIONS,
                code="ACP_ERROR",
                message=str(e)
            ))

    manager.register_handler(ACPActions.CONNECT, handle_acp_connect)
    manager.register_handler(ACPActions.DISCONNECT, handle_acp_disconnect)
    manager.register_handler(ACPActions.CONNECTIONS, handle_acp_connections)
