"""
MCP 处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error
from server.protocol.actions import MCPActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def register_mcp_handlers(manager: "WebSocketManager"):

    async def handle_mcp_connect(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.dependencies import get_mcp_manager

            mcp_mgr = get_mcp_manager()
            server_info = await mcp_mgr.add_server(
                name=data.get("name", ""),
                command=data.get("command", ""),
                args=data.get("args", []),
                env=data.get("env"),
                endpoint_url=data.get("endpoint_url"),
            )

            if data.get("auto_start", False):
                await mcp_mgr.start_server(data.get("name", ""))

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MCPActions.CONNECT,
                data=server_info
            ))
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
            from server.dependencies import get_mcp_manager

            mcp_mgr = get_mcp_manager()
            server_name = data.get("server_name", "")

            if server_name:
                tools = await mcp_mgr.get_tools(server_name)
            else:
                servers = await mcp_mgr.list_servers()
                tools = []
                for server in servers:
                    server_tools = await mcp_mgr.get_tools(server["name"])
                    tools.extend(server_tools)

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MCPActions.TOOLS,
                data={"tools": tools}
            ))
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
            from server.dependencies import get_mcp_manager

            mcp_mgr = get_mcp_manager()
            result = await mcp_mgr.call_tool(
                server_name=data.get("server_name", ""),
                tool_name=data.get("tool_name", ""),
                arguments=data.get("arguments"),
            )

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MCPActions.CALL,
                data=result
            ))
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
