import asyncio
import json
from typing import Any, Callable, Dict, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class ChatWebSocketHandler:
    def __init__(self, ws_manager, agent_manager=None):
        self.ws_manager = ws_manager
        self.agent_manager = agent_manager
        self._register_handlers()

    def _register_handlers(self):
        self.ws_manager.register_handler("chat", self._handle_chat)
        self.ws_manager.register_handler("chat_stream", self._handle_chat_stream)
        self.ws_manager.register_handler("chat_complete", self._handle_chat_complete)
        self.ws_manager.register_handler("ping", self._handle_ping)

    async def _handle_chat(self, client_id: str, message: Dict[str, Any]):
        content = message.get("content", "")
        session_id = message.get("session_id")
        if not content:
            await self.ws_manager.send_to_client(client_id, {"type": "error", "error": "内容不能为空"})
            return
        if self.agent_manager:
            response = await self.agent_manager.chat(content, session_id=session_id)
            await self.ws_manager.send_to_client(client_id, {"type": "chat_response", "content": response})
        else:
            await self.ws_manager.send_to_client(client_id, {"type": "chat_response", "content": "Agent manager not available"})

    async def _handle_chat_stream(self, client_id: str, message: Dict[str, Any]):
        content = message.get("content", "")
        session_id = message.get("session_id")
        if not content:
            await self.ws_manager.send_to_client(client_id, {"type": "error", "error": "内容不能为空"})
            return
        await self.ws_manager.send_to_client(client_id, {"type": "stream_start"})
        if self.agent_manager:
            async for chunk in self.agent_manager.chat_stream(content, session_id=session_id):
                await self.ws_manager.send_to_client(client_id, {"type": "stream_chunk", "content": chunk})
        await self.ws_manager.send_to_client(client_id, {"type": "stream_end"})

    async def _handle_chat_complete(self, client_id: str, message: Dict[str, Any]):
        await self.ws_manager.send_to_client(client_id, {"type": "chat_complete", "status": "success"})

    async def _handle_ping(self, client_id: str, message: Dict[str, Any]):
        await self.ws_manager.send_to_client(client_id, {"type": "pong", "timestamp": message.get("timestamp")})


_chat_handler: Optional[ChatWebSocketHandler] = None


def get_chat_handler(ws_manager, agent_manager=None) -> ChatWebSocketHandler:
    global _chat_handler
    if _chat_handler is None:
        _chat_handler = ChatWebSocketHandler(ws_manager, agent_manager)
    return _chat_handler