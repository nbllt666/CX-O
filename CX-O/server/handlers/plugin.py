"""
插件处理器
"""
import logging
from typing import TYPE_CHECKING, Optional

from server.protocol.message import create_response, create_error
from server.protocol.actions import PluginActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)


def register_plugin_handlers(manager: "ConnectionManager"):
    _manager = manager

    async def handle_plugin_register(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            plugin_manager = get_plugin_manager()
            if plugin_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=PluginActions.REGISTER,
                    code="PLUGIN_NOT_AVAILABLE",
                    message="Plugin service is not available"
                ))
                return

            result = await plugin_manager.register(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=PluginActions.REGISTER,
                data=result
            ))
        except Exception as e:
            logger.error(f"Plugin register error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=PluginActions.REGISTER,
                code="PLUGIN_ERROR",
                message=str(e)
            ))

    async def handle_plugin_heartbeat(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            plugin_manager = get_plugin_manager()
            if plugin_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=PluginActions.HEARTBEAT,
                    code="PLUGIN_NOT_AVAILABLE",
                    message="Plugin service is not available"
                ))
                return

            result = await plugin_manager.heartbeat(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=PluginActions.HEARTBEAT,
                data=result
            ))
        except Exception as e:
            logger.error(f"Plugin heartbeat error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=PluginActions.HEARTBEAT,
                code="PLUGIN_ERROR",
                message=str(e)
            ))

    async def handle_plugin_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            plugin_manager = get_plugin_manager()
            if plugin_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=PluginActions.LIST,
                    code="PLUGIN_NOT_AVAILABLE",
                    message="Plugin service is not available"
                ))
                return

            result = await plugin_manager.list_plugins(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=PluginActions.LIST,
                data=result
            ))
        except Exception as e:
            logger.error(f"Plugin list error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=PluginActions.LIST,
                code="PLUGIN_ERROR",
                message=str(e)
            ))

    _manager.register_handler(PluginActions.REGISTER, handle_plugin_register)
    _manager.register_handler(PluginActions.HEARTBEAT, handle_plugin_heartbeat)
    _manager.register_handler(PluginActions.LIST, handle_plugin_list)


class LocalPluginManager:
    def __init__(self):
        self._plugin_service = None

    def _get_plugin_service(self):
        if self._plugin_service is None:
            try:
                from server.core.plugins import get_plugin_service
                self._plugin_service = get_plugin_service()
            except ImportError:
                logger.warning("Plugin service not available")
        return self._plugin_service

    async def register(self, data: dict) -> dict:
        plugin_service = self._get_plugin_service()
        if plugin_service is None:
            return {"success": False, "error": "service_unavailable"}

        try:
            return await plugin_service.register(data)
        except Exception as e:
            logger.error(f"Plugin register error: {e}")
            return {"success": False, "error": str(e)}

    async def heartbeat(self, data: dict) -> dict:
        plugin_service = self._get_plugin_service()
        if plugin_service is None:
            return {"success": False, "error": "service_unavailable"}

        try:
            return await plugin_service.heartbeat(data)
        except Exception as e:
            logger.error(f"Plugin heartbeat error: {e}")
            return {"success": False, "error": str(e)}

    async def list_plugins(self, data: dict) -> dict:
        plugin_service = self._get_plugin_service()
        if plugin_service is None:
            return {"plugins": [], "error": "service_unavailable"}

        try:
            return await plugin_service.list_plugins(data)
        except Exception as e:
            logger.error(f"Plugin list error: {e}")
            return {"plugins": [], "error": str(e)}


_plugin_manager: Optional[LocalPluginManager] = None


def get_plugin_manager() -> Optional[LocalPluginManager]:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = LocalPluginManager()
    return _plugin_manager