"""
MCP 处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_error
from server.protocol.actions import MCPActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager
    from server.services.cxhms_client import CXHMSClient

logger = logging.getLogger(__name__)


def register_mcp_handlers(manager: "ConnectionManager", cxhms_client: "CXHMSClient"):

    async def handle_mcp_connect(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(MCPActions.CONNECT, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"MCP connect error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MCPActions.CONNECT,
                code="MCP_ERROR",
                message=str(e)
            ))

    async def handle_mcp_tools(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(MCPActions.TOOLS, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"MCP tools error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MCPActions.TOOLS,
                code="MCP_ERROR",
                message=str(e)
            ))

    async def handle_mcp_call(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(MCPActions.CALL, data)
            await manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"MCP call error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MCPActions.CALL,
                code="MCP_ERROR",
                message=str(e)
            ))

    manager.register_handler(MCPActions.CONNECT, handle_mcp_connect)
    manager.register_handler(MCPActions.TOOLS, handle_mcp_tools)
    manager.register_handler(MCPActions.CALL, handle_mcp_call)
