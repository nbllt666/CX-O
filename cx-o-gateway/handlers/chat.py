"""
聊天处理器
"""
import logging
from typing import TYPE_CHECKING

from protocol.message import create_response, create_error, create_stream
from protocol.actions import ChatActions

if TYPE_CHECKING:
    from gateway.server import ConnectionManager
    from services.cxhms_client import CXHMSClient

logger = logging.getLogger(__name__)


def register_chat_handlers(manager: "ConnectionManager", cxhms_client: "CXHMSClient"):
    
    async def handle_chat_message(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            response = await cxhms_client.request(ChatActions.MESSAGE, data)
            await manager.send_message(client_id, response)
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
        
        try:
            async def on_chunk(chunk):
                await manager.send_message(client_id, chunk)
            
            await cxhms_client.stream(ChatActions.STREAM, data, on_chunk)
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
            response = await cxhms_client.request(ChatActions.MULTIMODAL, data)
            await manager.send_message(client_id, response)
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
