"""
配置处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error
from server.protocol.actions import ConfigActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def register_config_handlers(manager: "WebSocketManager"):
    """将配置读取/写入处理器注册到 WebSocket 管理器。"""

    async def handle_config_get(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.config import get_config

            config = get_config()
            section = data.get("section")

            if section:
                parts = section.split(".")
                result = config
                for part in parts:
                    result = getattr(result, part, None)
                    if result is None:
                        break
                config_data = result.model_dump() if hasattr(result, "model_dump") else result
            else:
                config_data = config.model_dump()

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ConfigActions.GET,
                data={"config": config_data}
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
            from server.config import get_config, save_config

            config = get_config()
            section = data.get("section", "")
            section_data = data.get("data", {})

            if not section:
                # section 为空时返回明确错误，避免"静默成功"路径遮蔽
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ConfigActions.SET,
                    code="INVALID_REQUEST",
                    message="Section cannot be empty"
                ))
                return

            parts = section.split(".")
            target = config
            for part in parts[:-1]:
                target = getattr(target, part, None)
                if target is None:
                    break

            if target is not None:
                last_part = parts[-1]
                if hasattr(target, last_part):
                    sub_config = getattr(target, last_part)
                    if hasattr(sub_config, "model_dump"):
                        for key, value in section_data.items():
                            # 校验 key 类型，非字符串 key 返回明确错误
                            if not isinstance(key, str):
                                await manager.send_message(client_id, create_error(
                                    request_id=request_id,
                                    action=ConfigActions.SET,
                                    code="INVALID_REQUEST",
                                    message=f"Config key must be string, got {type(key).__name__}"
                                ))
                                return
                            if hasattr(sub_config, key):
                                setattr(sub_config, key, value)
                    else:
                        setattr(target, last_part, section_data)

            save_config(config)

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ConfigActions.SET,
                data={"saved": True}
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
