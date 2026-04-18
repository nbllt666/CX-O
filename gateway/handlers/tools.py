"""
工具处理器
"""
import logging
from typing import TYPE_CHECKING

from protocol.message import create_error
from protocol.actions import ToolsActions

if TYPE_CHECKING:
    from gateway.server import ConnectionManager
    from services.cxhms_client import CXHMSClient

logger = logging.getLogger(__name__)


def register_tools_handlers(manager: "ConnectionManager", cxhms_client: "CXHMSClient"):
    
    async def handle_tools_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            response = await cxhms_client.request(ToolsActions.LIST, data)
            await manager.send_message(client_id, response)
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
            response = await cxhms_client.request(ToolsActions.CALL, data)
            await manager.send_message(client_id, response)
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
            response = await cxhms_client.request(ToolsActions.REGISTER, data)
            await manager.send_message(client_id, response)
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
