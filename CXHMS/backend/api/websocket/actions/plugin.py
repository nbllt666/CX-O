"""
插件 Action 处理器
"""
import logging
import time
from typing import TYPE_CHECKING

from ..protocol import create_response, create_error

if TYPE_CHECKING:
    from ..server import ConnectionManager

logger = logging.getLogger(__name__)


class PluginActions:
    REGISTER = "plugin.register"
    HEARTBEAT = "plugin.heartbeat"
    LIST = "plugin.list"
    UNREGISTER = "plugin.unregister"


_plugins: dict = {}


def register_plugin_handlers(manager: "ConnectionManager"):
    
    async def handle_plugin_register(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            plugin_name = data.get("name", "")
            _plugins[plugin_name] = {
                "name": plugin_name,
                "status": "online",
                "last_heartbeat": time.time()
            }
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=PluginActions.REGISTER,
                data={"success": True, "name": plugin_name}
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
            plugin_name = data.get("name", "")
            if plugin_name in _plugins:
                _plugins[plugin_name]["last_heartbeat"] = time.time()
                _plugins[plugin_name]["status"] = "online"
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=PluginActions.HEARTBEAT,
                data={"success": True}
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
        
        try:
            plugins_list = list(_plugins.values())
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=PluginActions.LIST,
                data={"plugins": plugins_list}
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
