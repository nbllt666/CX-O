"""
聊天 Action 处理器
"""
import logging
from typing import TYPE_CHECKING

from ..protocol import create_response, create_error, create_stream

if TYPE_CHECKING:
    from ..server import ConnectionManager

logger = logging.getLogger(__name__)


class ChatActions:
    MESSAGE = "chat.message"
    STREAM = "chat.stream"
    MULTIMODAL = "chat.multimodal"


def register_chat_handlers(manager: "ConnectionManager"):
    
    async def handle_chat_message(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        text = data.get("text", "")
        session_id = data.get("session_id", "")
        
        if not text:
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ChatActions.MESSAGE,
                code="INVALID_REQUEST",
                message="Missing text"
            ))
            return
        
        try:
            response_data = {
                "message": f"Echo: {text}",
                "session_id": session_id
            }
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ChatActions.MESSAGE,
                data=response_data
            ))
        except Exception as e:
            logger.error(f"Chat message error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ChatActions.MESSAGE,
                code="CHAT_ERROR",
                message=str(e)
            ))

    async def handle_chat_stream(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        text = data.get("text", "")
        
        if not text:
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ChatActions.STREAM,
                code="INVALID_REQUEST",
                message="Missing text"
            ))
            return
        
        try:
            words = text.split()
            for i, word in enumerate(words):
                await manager.send_message(client_id, create_stream(
                    request_id=request_id,
                    action=ChatActions.STREAM,
                    chunk_index=i,
                    data={"content": word + " "},
                    is_final=(i == len(words) - 1)
                ))
                import asyncio
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ChatActions.STREAM,
                code="CHAT_STREAM_ERROR",
                message=str(e)
            ))

    async def handle_chat_multimodal(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            response_data = {
                "message": "Multimodal response",
                "session_id": data.get("session_id", "")
            }
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ChatActions.MULTIMODAL,
                data=response_data
            ))
        except Exception as e:
            logger.error(f"Chat multimodal error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ChatActions.MULTIMODAL,
                code="CHAT_MULTIMODAL_ERROR",
                message=str(e)
            ))

    manager.register_handler(ChatActions.MESSAGE, handle_chat_message)
    manager.register_handler(ChatActions.STREAM, handle_chat_stream)
    manager.register_handler(ChatActions.MULTIMODAL, handle_chat_multimodal)
