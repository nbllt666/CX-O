"""
直播客户端处理器
"""
import logging
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)


class LiveClientHandler:
    def __init__(self, manager: "ConnectionManager", client_id: str, client_config: Dict[str, Any]):
        self.manager = manager
        self.client_id = client_id
        self.client_config = client_config

    async def handle_message(self, websocket, message: dict, client_id: str):
        msg_type = message.get("type", "")
        data = message.get("data", {})

        if msg_type == "config":
            self.client_config.update(data)
            await self.manager.send_message(client_id, {
                "type": "config_ack",
                "data": {"status": "ok"}
            })
        elif msg_type == "ping":
            await self.manager.send_message(client_id, {
                "type": "pong",
                "data": {}
            })

    async def handle_audio(self, websocket, audio_data: bytes, client_id: str):
        pass