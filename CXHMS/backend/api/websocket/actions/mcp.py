"""
MCP Action 处理器
"""
import logging
from typing import TYPE_CHECKING

from ..protocol import create_response, create_error

if TYPE_CHECKING:
    from ..server import ConnectionManager

logger = logging.getLogger(__name__)


class MCPActions:
    CONNECT = "mcp.connect"
    DISCONNECT = "mcp.disconnect"
    TOOLS = "mcp.tools"
    CALL = "mcp.call"
    STATUS = "mcp.status"


_mcp_connections: dict = {}


def register_mcp_handlers(manager: "ConnectionManager"):
    
    async def handle_mcp_connect(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            server_name = data.get("server", "default")
            _mcp_connections[server_name] = {
                "server": server_name,
                "status": "connected",
                "config": data.get("config", {})
            }
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MCPActions.CONNECT,
                data={"success": True, "server": server_name}
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
        
        try:
            tools = [{"name": "example_mcp_tool", "description": "示例 MCP 工具"}]
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
            tool_name = data.get("name", "")
            args = data.get("arguments", {})
            result = {"result": f"MCP tool {tool_name} called with {args}"}
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
