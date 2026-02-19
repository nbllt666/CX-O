"""
配置 Action 处理器
"""
import logging
from typing import TYPE_CHECKING

from ..protocol import create_response, create_error

if TYPE_CHECKING:
    from ..server import ConnectionManager

logger = logging.getLogger(__name__)


class ConfigActions:
    GET = "config.get"
    SET = "config.set"
    RESET = "config.reset"


_config: dict = {}


def register_config_handlers(manager: "ConnectionManager"):
    
    async def handle_config_get(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            key = data.get("key")
            if key:
                value = _config.get(key)
                await manager.send_message(client_id, create_response(
                    request_id=request_id,
                    action=ConfigActions.GET,
                    data={"key": key, "value": value}
                ))
            else:
                await manager.send_message(client_id, create_response(
                    request_id=request_id,
                    action=ConfigActions.GET,
                    data={"config": _config}
                ))
        except Exception as e:
            logger.error(f"Config get error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ConfigActions.GET,
                code="CONFIG_ERROR",
                message=str(e)
            ))

    async def handle_config_set(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            key = data.get("key", "")
            value = data.get("value")
            _config[key] = value
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ConfigActions.SET,
                data={"success": True, "key": key}
            ))
        except Exception as e:
            logger.error(f"Config set error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ConfigActions.SET,
                code="CONFIG_ERROR",
                message=str(e)
            ))

    manager.register_handler(ConfigActions.GET, handle_config_get)
    manager.register_handler(ConfigActions.SET, handle_config_set)
