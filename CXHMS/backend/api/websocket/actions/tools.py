"""
工具 Action 处理器
"""
import logging
from typing import TYPE_CHECKING

from ..protocol import create_response, create_error

if TYPE_CHECKING:
    from ..server import ConnectionManager

logger = logging.getLogger(__name__)


class ToolsActions:
    LIST = "tools.list"
    CALL = "tools.call"
    REGISTER = "tools.register"


_tools: dict = {}


def register_tools_handlers(manager: "ConnectionManager"):
    
    async def handle_tools_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        
        try:
            tools_list = list(_tools.values()) if _tools else [
                {"name": "example_tool", "description": "示例工具", "parameters": {}}
            ]
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ToolsActions.LIST,
                data={"tools": tools_list}
            ))
        except Exception as e:
            logger.error(f"Tools list error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ToolsActions.LIST,
                code="TOOLS_ERROR",
                message=str(e)
            ))

    async def handle_tools_call(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            tool_name = data.get("name", "")
            args = data.get("arguments", {})
            
            result = {"result": f"Tool {tool_name} called with {args}"}
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ToolsActions.CALL,
                data=result
            ))
        except Exception as e:
            logger.error(f"Tools call error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ToolsActions.CALL,
                code="TOOLS_ERROR",
                message=str(e)
            ))

    async def handle_tools_register(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            tool_name = data.get("name", "")
            _tools[tool_name] = data
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ToolsActions.REGISTER,
                data={"success": True, "name": tool_name}
            ))
        except Exception as e:
            logger.error(f"Tools register error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ToolsActions.REGISTER,
                code="TOOLS_ERROR",
                message=str(e)
            ))

    manager.register_handler(ToolsActions.LIST, handle_tools_list)
    manager.register_handler(ToolsActions.CALL, handle_tools_call)
    manager.register_handler(ToolsActions.REGISTER, handle_tools_register)
