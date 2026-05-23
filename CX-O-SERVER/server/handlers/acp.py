"""
ACP 处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error
from server.protocol.actions import ACPActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def register_acp_handlers(manager: "WebSocketManager"):

    async def handle_acp_connect(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.dependencies import get_acp_manager
            from server.core.acp.manager import ACPAgentInfo, ACPConnectionInfo

            acp_mgr = get_acp_manager()

            agent = ACPAgentInfo(
                id=data.get("agent_id", ""),
                name=data.get("agent_name", ""),
                host=data.get("host", ""),
                port=data.get("port", 0),
                capabilities=data.get("capabilities", []),
            )
            await acp_mgr.register_agent(agent)

            connection = ACPConnectionInfo(
                id=data.get("connection_id", ""),
                local_agent_id=acp_mgr._local_agent_id,
                remote_agent_id=data.get("agent_id", ""),
                remote_agent_name=data.get("agent_name", ""),
                host=data.get("host", ""),
                port=data.get("port", 0),
                status="connected",
            )
            await acp_mgr.create_connection(connection)

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ACPActions.CONNECT,
                data={"connection_id": connection.id, "status": "connected"}
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
            from server.dependencies import get_acp_manager

            acp_mgr = get_acp_manager()
            connection_id = data.get("connection_id", "")

            success = await acp_mgr.delete_connection(connection_id)

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ACPActions.DISCONNECT,
                data={"success": success}
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
        data = message.get("data", {})

        try:
            from server.dependencies import get_acp_manager

            acp_mgr = get_acp_manager()
            connections = await acp_mgr.list_connections(local_only=data.get("local_only", True))

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ACPActions.CONNECTIONS,
                data={"connections": connections}
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
