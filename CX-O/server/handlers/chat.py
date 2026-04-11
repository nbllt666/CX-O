"""
聊天处理器
"""
import logging
from typing import TYPE_CHECKING, Any, Optional

from server.protocol.message import create_response, create_error, create_stream
from server.protocol.actions import ChatActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)


def register_chat_handlers(manager: "ConnectionManager"):
    _manager = manager

    async def handle_chat_message(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.gateway.server import get_llm_client
            llm_client = get_llm_client()

            if llm_client is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ChatActions.MESSAGE,
                    code="LLM_NOT_AVAILABLE",
                    message="LLM service is not available"
                ))
                return

            messages = data.get("messages", [])
            if isinstance(messages, str):
                messages = [{"role": "user", "content": messages}]
            elif isinstance(data.get("text"), str):
                messages = [{"role": "user", "content": data.get("text", "")}]

            response = await llm_client.chat(messages)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ChatActions.MESSAGE,
                data=response
            ))
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
            from server.gateway.server import get_llm_client
            llm_client = get_llm_client()

            if llm_client is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ChatActions.STREAM,
                    code="LLM_NOT_AVAILABLE",
                    message="LLM service is not available"
                ))
                return

            messages = data.get("messages", [])
            if isinstance(messages, str):
                messages = [{"role": "user", "content": messages}]
            elif isinstance(data.get("text"), str):
                messages = [{"role": "user", "content": data.get("text", "")}]

            chunk_index = 0
            async for chunk in llm_client.stream_chat(messages):
                content = chunk.get("content", "")
                is_final = chunk.get("is_final", False)

                await _manager.send_message(client_id, create_stream(
                    request_id=request_id,
                    action=ChatActions.STREAM,
                    chunk_index=chunk_index,
                    data={"content": content},
                    is_final=is_final
                ))
                chunk_index += 1

                if is_final:
                    _manager.increment_llm_count()
                    logger.info("Stream done - LLM count incremented")
                    break

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
            from server.gateway.server import get_llm_client
            llm_client = get_llm_client()

            if llm_client is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ChatActions.MULTIMODAL,
                    code="LLM_NOT_AVAILABLE",
                    message="LLM service is not available"
                ))
                return

            messages = data.get("messages", [])
            response = await llm_client.chat(messages)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ChatActions.MULTIMODAL,
                data=response
            ))
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


class LocalLLMClient:
    def __init__(self):
        self._llm_service = None

    def _get_llm_service(self):
        if self._llm_service is None:
            try:
                from server.services.llm import get_llm_service
                self._llm_service = get_llm_service()
            except ImportError:
                logger.warning("LLM service not available")
        return self._llm_service

    async def chat(self, messages: list) -> dict:
        llm_service = self._get_llm_service()
        if llm_service is None:
            return {"content": "LLM service not available", "error": "service_unavailable"}

        try:
            result = await llm_service.chat(messages)
            return result
        except Exception as e:
            logger.error(f"LLM chat error: {e}")
            return {"content": str(e), "error": "chat_error"}

    async def stream_chat(self, messages: list):
        llm_service = self._get_llm_service()
        if llm_service is None:
            yield {"content": "LLM service not available", "is_final": True}
            return

        try:
            async for chunk in llm_service.stream_chat(messages):
                yield chunk
        except Exception as e:
            logger.error(f"LLM stream chat error: {e}")
            yield {"content": str(e), "is_final": True}


_llm_client: Optional[LocalLLMClient] = None


def get_llm_client() -> Optional[LocalLLMClient]:
    global _llm_client
    if _llm_client is None:
        _llm_client = LocalLLMClient()
    return _llm_client