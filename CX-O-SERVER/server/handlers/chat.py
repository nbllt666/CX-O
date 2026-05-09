"""
聊天处理器
"""
import logging
import httpx
from typing import TYPE_CHECKING

from server.gateway.config import get_config
from server.protocol.message import create_response, create_error, create_stream
from server.protocol.actions import ChatActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager
    from server.services.cxhms_client import CXHMSClient

logger = logging.getLogger(__name__)


def register_chat_handlers(manager: "ConnectionManager", cxhms_client: "CXHMSClient"):
    _manager = manager

    async def handle_chat_message(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(ChatActions.MESSAGE, data)
            await _manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"Chat message error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ChatActions.MESSAGE,
                code="CHAT_ERROR",
                message=str(e)
            ))

    async def handle_chat_stream(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        logger.info(f"Chat stream request: request_id={request_id}, data={data}")

        try:
            config = get_config()
            cxhms_http_url = config.services.cxhms.http_url

            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, read=300.0)) as client:
                async with client.stream(
                    "POST",
                    f"{cxhms_http_url}/api/chat/stream",
                    json={
                        "message": data.get("text", ""),
                        "agent_id": data.get("agent_id", "default"),
                        "stream": True
                    }
                ) as response:
                    response.raise_for_status()
                    chunk_index = 0
                    logger.info(f"HTTP stream started, status={response.status_code}")

                    async for line in response.aiter_lines():
                        logger.info(f"Received line: {line[:100] if line else '(empty)'}")
                        if not line or line.strip() == "":
                            continue

                        if line.startswith("data: "):
                            chunk_data = line[6:]
                            import json
                            try:
                                event = json.loads(chunk_data)
                                event_type = event.get("type")
                                logger.info(f"Event type: {event_type}")

                                if event_type == "thinking":
                                    logger.debug(f"Thinking: {event.get('content', '')[:50]}")
                                    pass
                                elif event_type == "content":
                                    content = event.get("content", "")
                                    await _manager.send_message(client_id, create_stream(
                                        request_id=request_id,
                                        action=ChatActions.STREAM,
                                        chunk_index=chunk_index,
                                        data={"content": content},
                                        is_final=False
                                    ))
                                    logger.info(f"Sent content chunk {chunk_index}: {content[:50]}")
                                    chunk_index += 1
                                elif event_type == "done":
                                    await _manager.send_message(client_id, create_stream(
                                        request_id=request_id,
                                        action=ChatActions.STREAM,
                                        chunk_index=chunk_index,
                                        data={},
                                        is_final=True
                                    ))
                                    _manager.increment_llm_count()
                                    logger.info("Stream done - LLM count incremented")
                                    break
                                elif event_type == "error":
                                    logger.error(f"Stream error: {event.get('error')}")
                                    break
                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse event: {e}")

        except Exception as e:
            logger.error(f"Chat stream error: {e}", exc_info=True)
            await _manager.send_message(client_id, create_error(
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
            await _manager.send_message(client_id, response)
        except Exception as e:
            logger.error(f"Chat multimodal error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ChatActions.MULTIMODAL,
                code="CHAT_MULTIMODAL_ERROR",
                message=str(e)
            ))

    manager.register_handler(ChatActions.MESSAGE, handle_chat_message)
    manager.register_handler(ChatActions.STREAM, handle_chat_stream)
    manager.register_handler(ChatActions.MULTIMODAL, handle_chat_multimodal)
