"""
ACP 处理器
"""
import logging
from typing import TYPE_CHECKING, Optional

from server.protocol.message import create_response, create_error
from server.protocol.actions import ACPActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)


def register_acp_handlers(manager: "ConnectionManager"):
    _manager = manager

    async def handle_acp_connect(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            acp_manager = get_acp_manager()
            if acp_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ACPActions.CONNECT,
                    code="ACP_NOT_AVAILABLE",
                    message="ACP service is not available"
                ))
                return

            result = await acp_manager.connect(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ACPActions.CONNECT,
                data=result
            ))
        except Exception as e:
            logger.error(f"ACP connect error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ACPActions.CONNECT,
                code="ACP_ERROR",
                message=str(e)
            ))

    async def handle_acp_disconnect(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            acp_manager = get_acp_manager()
            if acp_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ACPActions.DISCONNECT,
                    code="ACP_NOT_AVAILABLE",
                    message="ACP service is not available"
                ))
                return

            result = await acp_manager.disconnect(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ACPActions.DISCONNECT,
                data=result
            ))
        except Exception as e:
            logger.error(f"ACP disconnect error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ACPActions.DISCONNECT,
                code="ACP_ERROR",
                message=str(e)
            ))

    async def handle_acp_connections(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            acp_manager = get_acp_manager()
            if acp_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ACPActions.CONNECTIONS,
                    code="ACP_NOT_AVAILABLE",
                    message="ACP service is not available"
                ))
                return

            result = await acp_manager.list_connections(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ACPActions.CONNECTIONS,
                data=result
            ))
        except Exception as e:
            logger.error(f"ACP connections error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ACPActions.CONNECTIONS,
                code="ACP_ERROR",
                message=str(e)
            ))

    _manager.register_handler(ACPActions.CONNECT, handle_acp_connect)
    _manager.register_handler(ACPActions.DISCONNECT, handle_acp_disconnect)
    _manager.register_handler(ACPActions.CONNECTIONS, handle_acp_connections)


class LocalACPManager:
    def __init__(self):
        self._acp_service = None

    def _get_acp_service(self):
        if self._acp_service is None:
            try:
                from server.core.acp import get_acp_service
                self._acp_service = get_acp_service()
            except ImportError:
                logger.warning("ACP service not available")
        return self._acp_service

    async def connect(self, data: dict) -> dict:
        acp_service = self._get_acp_service()
        if acp_service is None:
            return {"success": False, "error": "service_unavailable"}

        try:
            return await acp_service.connect(data)
        except Exception as e:
            logger.error(f"ACP connect error: {e}")
            return {"success": False, "error": str(e)}

    async def disconnect(self, data: dict) -> dict:
        acp_service = self._get_acp_service()
        if acp_service is None:
            return {"success": False, "error": "service_unavailable"}

        try:
            return await acp_service.disconnect(data)
        except Exception as e:
            logger.error(f"ACP disconnect error: {e}")
            return {"success": False, "error": str(e)}

    async def list_connections(self, data: dict) -> dict:
        acp_service = self._get_acp_service()
        if acp_service is None:
            return {"connections": [], "error": "service_unavailable"}

        try:
            return await acp_service.list_connections(data)
        except Exception as e:
            logger.error(f"ACP list connections error: {e}")
            return {"connections": [], "error": str(e)}


_acp_manager: Optional[LocalACPManager] = None


def get_acp_manager() -> Optional[LocalACPManager]:
    global _acp_manager
    if _acp_manager is None:
        _acp_manager = LocalACPManager()
    return _acp_manager