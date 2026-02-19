"""
ACP Action 处理器
"""
import logging
from typing import TYPE_CHECKING

from ..protocol import create_response, create_error

if TYPE_CHECKING:
    from ..server import ConnectionManager

logger = logging.getLogger(__name__)


class ACPActions:
    CONNECT = "acp.connect"
    DISCONNECT = "acp.disconnect"
    CONNECTIONS = "acp.connections"
    STATUS = "acp.status"


_acp_connections: dict = {}


def register_acp_handlers(manager: "ConnectionManager"):
    
    async def handle_acp_connect(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            alias = data.get("alias", "default")
            _acp_connections[alias] = {
                "alias": alias,
                "status": "connected",
                "config": data.get("config", {})
            }
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ACPActions.CONNECT,
                data={"success": True, "alias": alias}
            ))
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
            alias = data.get("alias", "")
            if alias in _acp_connections:
                del _acp_connections[alias]
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ACPActions.DISCONNECT,
                data={"success": True}
            ))
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
        
        try:
            connections_list = list(_acp_connections.values())
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ACPActions.CONNECTIONS,
                data={"connections": connections_list}
            ))
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
