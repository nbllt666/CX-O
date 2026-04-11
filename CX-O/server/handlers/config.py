"""
配置处理器
"""
import logging
from typing import TYPE_CHECKING, Optional

from server.protocol.message import create_response, create_error
from server.protocol.actions import ConfigActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)


def register_config_handlers(manager: "ConnectionManager"):
    _manager = manager

    async def handle_config_get(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.gateway.gateway_config import get_config
            config = get_config()

            key = data.get("key", "")
            if key:
                value = getattr(config, key, None)
                if value is not None:
                    await _manager.send_message(client_id, create_response(
                        request_id=request_id,
                        action=ConfigActions.GET,
                        data={"key": key, "value": value}
                    ))
                else:
                    await _manager.send_message(client_id, create_error(
                        request_id=request_id,
                        action=ConfigActions.GET,
                        code="CONFIG_NOT_FOUND",
                        message=f"Config key not found: {key}"
                    ))
            else:
                await _manager.send_message(client_id, create_response(
                    request_id=request_id,
                    action=ConfigActions.GET,
                    data={"config": config.model_dump() if hasattr(config, 'model_dump') else str(config)}
                ))
        except Exception as e:
            logger.error(f"Config get error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ConfigActions.GET,
                code="CONFIG_ERROR",
                message=str(e)
            ))

    async def handle_config_set(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.gateway.gateway_config import get_config, save_config
            config = get_config()

            key = data.get("key", "")
            value = data.get("value")

            if key and value is not None:
                if hasattr(config, key):
                    setattr(config, key, value)
                    save_config(config)
                    await _manager.send_message(client_id, create_response(
                        request_id=request_id,
                        action=ConfigActions.SET,
                        data={"key": key, "value": value, "saved": True}
                    ))
                else:
                    await _manager.send_message(client_id, create_error(
                        request_id=request_id,
                        action=ConfigActions.SET,
                        code="CONFIG_NOT_FOUND",
                        message=f"Config key not found: {key}"
                    ))
            else:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ConfigActions.SET,
                    code="INVALID_REQUEST",
                    message="Missing key or value"
                ))
        except Exception as e:
            logger.error(f"Config set error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ConfigActions.SET,
                code="CONFIG_ERROR",
                message=str(e)
            ))

    _manager.register_handler(ConfigActions.GET, handle_config_get)
    _manager.register_handler(ConfigActions.SET, handle_config_set)