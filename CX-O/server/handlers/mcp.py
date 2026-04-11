"""
MCP 处理器
"""
import logging
from typing import TYPE_CHECKING, Optional

from server.protocol.message import create_response, create_error
from server.protocol.actions import MCPActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)


def register_mcp_handlers(manager: "ConnectionManager"):
    _manager = manager

    async def handle_mcp_connect(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            mcp_manager = get_mcp_manager()
            if mcp_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=MCPActions.CONNECT,
                    code="MCP_NOT_AVAILABLE",
                    message="MCP service is not available"
                ))
                return

            result = await mcp_manager.connect(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MCPActions.CONNECT,
                data=result
            ))
        except Exception as e:
            logger.error(f"MCP connect error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MCPActions.CONNECT,
                code="MCP_ERROR",
                message=str(e)
            ))

    async def handle_mcp_tools(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            mcp_manager = get_mcp_manager()
            if mcp_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=MCPActions.TOOLS,
                    code="MCP_NOT_AVAILABLE",
                    message="MCP service is not available"
                ))
                return

            result = await mcp_manager.list_tools(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MCPActions.TOOLS,
                data=result
            ))
        except Exception as e:
            logger.error(f"MCP tools error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MCPActions.TOOLS,
                code="MCP_ERROR",
                message=str(e)
            ))

    async def handle_mcp_call(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            mcp_manager = get_mcp_manager()
            if mcp_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=MCPActions.CALL,
                    code="MCP_NOT_AVAILABLE",
                    message="MCP service is not available"
                ))
                return

            result = await mcp_manager.call_tool(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MCPActions.CALL,
                data=result
            ))
        except Exception as e:
            logger.error(f"MCP call error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MCPActions.CALL,
                code="MCP_ERROR",
                message=str(e)
            ))

    _manager.register_handler(MCPActions.CONNECT, handle_mcp_connect)
    _manager.register_handler(MCPActions.TOOLS, handle_mcp_tools)
    _manager.register_handler(MCPActions.CALL, handle_mcp_call)


class LocalMCPManager:
    def __init__(self):
        self._mcp_service = None

    def _get_mcp_service(self):
        if self._mcp_service is None:
            try:
                from server.core.mcp import get_mcp_service
                self._mcp_service = get_mcp_service()
            except ImportError:
                logger.warning("MCP service not available")
        return self._mcp_service

    async def connect(self, data: dict) -> dict:
        mcp_service = self._get_mcp_service()
        if mcp_service is None:
            return {"success": False, "error": "service_unavailable"}

        try:
            return await mcp_service.connect(data)
        except Exception as e:
            logger.error(f"MCP connect error: {e}")
            return {"success": False, "error": str(e)}

    async def list_tools(self, data: dict) -> dict:
        mcp_service = self._get_mcp_service()
        if mcp_service is None:
            return {"tools": [], "error": "service_unavailable"}

        try:
            return await mcp_service.list_tools(data)
        except Exception as e:
            logger.error(f"MCP list tools error: {e}")
            return {"tools": [], "error": str(e)}

    async def call_tool(self, data: dict) -> dict:
        mcp_service = self._get_mcp_service()
        if mcp_service is None:
            return {"result": None, "error": "service_unavailable"}

        try:
            return await mcp_service.call_tool(data)
        except Exception as e:
            logger.error(f"MCP call tool error: {e}")
            return {"result": None, "error": str(e)}


_mcp_manager: Optional[LocalMCPManager] = None


def get_mcp_manager() -> Optional[LocalMCPManager]:
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = LocalMCPManager()
    return _mcp_manager