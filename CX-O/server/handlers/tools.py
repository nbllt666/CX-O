"""
工具处理器
"""
import logging
from typing import TYPE_CHECKING, Optional

from server.protocol.message import create_response, create_error
from server.protocol.actions import ToolsActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)


def register_tools_handlers(manager: "ConnectionManager"):
    _manager = manager

    async def handle_tools_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            tools_manager = get_tools_manager()
            if tools_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ToolsActions.LIST,
                    code="TOOLS_NOT_AVAILABLE",
                    message="Tools service is not available"
                ))
                return

            result = await tools_manager.list_tools(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ToolsActions.LIST,
                data=result
            ))
        except Exception as e:
            logger.error(f"Tools list error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ToolsActions.LIST,
                code="TOOLS_ERROR",
                message=str(e)
            ))

    async def handle_tools_call(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            tools_manager = get_tools_manager()
            if tools_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ToolsActions.CALL,
                    code="TOOLS_NOT_AVAILABLE",
                    message="Tools service is not available"
                ))
                return

            result = await tools_manager.call_tool(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ToolsActions.CALL,
                data=result
            ))
        except Exception as e:
            logger.error(f"Tools call error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ToolsActions.CALL,
                code="TOOLS_ERROR",
                message=str(e)
            ))

    async def handle_tools_register(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            tools_manager = get_tools_manager()
            if tools_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ToolsActions.REGISTER,
                    code="TOOLS_NOT_AVAILABLE",
                    message="Tools service is not available"
                ))
                return

            result = await tools_manager.register_tool(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ToolsActions.REGISTER,
                data=result
            ))
        except Exception as e:
            logger.error(f"Tools register error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ToolsActions.REGISTER,
                code="TOOLS_ERROR",
                message=str(e)
            ))

    _manager.register_handler(ToolsActions.LIST, handle_tools_list)
    _manager.register_handler(ToolsActions.CALL, handle_tools_call)
    _manager.register_handler(ToolsActions.REGISTER, handle_tools_register)


class LocalToolsManager:
    def __init__(self):
        self._tools_service = None

    def _get_tools_service(self):
        if self._tools_service is None:
            try:
                from server.core.tools import get_tools_service
                self._tools_service = get_tools_service()
            except ImportError:
                logger.warning("Tools service not available")
        return self._tools_service

    async def list_tools(self, data: dict) -> dict:
        tools_service = self._get_tools_service()
        if tools_service is None:
            return {"tools": [], "error": "service_unavailable"}

        try:
            return await tools_service.list_tools(data)
        except Exception as e:
            logger.error(f"List tools error: {e}")
            return {"tools": [], "error": str(e)}

    async def call_tool(self, data: dict) -> dict:
        tools_service = self._get_tools_service()
        if tools_service is None:
            return {"result": None, "error": "service_unavailable"}

        try:
            return await tools_service.call_tool(data)
        except Exception as e:
            logger.error(f"Call tool error: {e}")
            return {"result": None, "error": str(e)}

    async def register_tool(self, data: dict) -> dict:
        tools_service = self._get_tools_service()
        if tools_service is None:
            return {"success": False, "error": "service_unavailable"}

        try:
            return await tools_service.register_tool(data)
        except Exception as e:
            logger.error(f"Register tool error: {e}")
            return {"success": False, "error": str(e)}


_tools_manager: Optional[LocalToolsManager] = None


def get_tools_manager() -> Optional[LocalToolsManager]:
    global _tools_manager
    if _tools_manager is None:
        _tools_manager = LocalToolsManager()
    return _tools_manager