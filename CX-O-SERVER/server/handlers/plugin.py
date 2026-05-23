"""
插件处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error
from server.protocol.actions import PluginActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def register_plugin_handlers(manager: "WebSocketManager"):

    async def handle_plugin_register(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.core.plugins.manager import get_plugin_manager

            plugin_mgr = get_plugin_manager()
            plugin_id = data.get("plugin_id", "")

            plugin = plugin_mgr.load_plugin(plugin_id)
            if plugin and data.get("enabled", True):
                plugin_mgr.enable_plugin(plugin_id)

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=PluginActions.REGISTER,
                data={"plugin_id": plugin_id, "registered": plugin is not None}
            ))
        except Exception as e:
            logger.error(f"Plugin register error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=PluginActions.REGISTER,
                code="PLUGIN_ERROR",
                message=str(e)
            ))

    async def handle_plugin_heartbeat(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.core.plugins.manager import get_plugin_manager

            plugin_mgr = get_plugin_manager()
            plugin_id = data.get("plugin_id", "")

            plugin = plugin_mgr.get_plugin(plugin_id)
            if plugin:
                plugin.hook_calls += 0

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=PluginActions.HEARTBEAT,
                data={"plugin_id": plugin_id, "alive": plugin is not None}
            ))
        except Exception as e:
            logger.error(f"Plugin heartbeat error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=PluginActions.HEARTBEAT,
                code="PLUGIN_ERROR",
                message=str(e)
            ))

    async def handle_plugin_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.core.plugins.manager import get_plugin_manager

            plugin_mgr = get_plugin_manager()

            if data.get("enabled_only"):
                plugins = plugin_mgr.get_enabled_plugins()
            else:
                plugins = plugin_mgr.get_all_plugins()

            plugin_list = [
                {
                    "id": p.metadata.id,
                    "name": p.metadata.name,
                    "version": p.metadata.version,
                    "enabled": p.enabled,
                    "description": p.metadata.description,
                }
                for p in plugins
            ]

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=PluginActions.LIST,
                data={"plugins": plugin_list}
            ))
        except Exception as e:
            logger.error(f"Plugin list error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=PluginActions.LIST,
                code="PLUGIN_ERROR",
                message=str(e)
            ))

    manager.register_handler(PluginActions.REGISTER, handle_plugin_register)
    manager.register_handler(PluginActions.HEARTBEAT, handle_plugin_heartbeat)
    manager.register_handler(PluginActions.LIST, handle_plugin_list)
