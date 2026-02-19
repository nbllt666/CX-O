"""
上下文 Action 处理器
"""
import logging
from typing import TYPE_CHECKING

from ..protocol import create_response, create_error

if TYPE_CHECKING:
    from ..server import ConnectionManager

logger = logging.getLogger(__name__)


class ContextActions:
    GET = "context.get"
    APPEND = "context.append"
    CLEAR = "context.clear"
    SET = "context.set"


_contexts: dict = {}


def register_context_handlers(manager: "ConnectionManager"):
    
    async def handle_context_get(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            session_id = data.get("session_id", "default")
            context = _contexts.get(session_id, [])
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ContextActions.GET,
                data={"context": context}
            ))
        except Exception as e:
            logger.error(f"Context get error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ContextActions.GET,
                code="CONTEXT_ERROR",
                message=str(e)
            ))

    async def handle_context_append(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            session_id = data.get("session_id", "default")
            content = data.get("content", "")
            if session_id not in _contexts:
                _contexts[session_id] = []
            _contexts[session_id].append(content)
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ContextActions.APPEND,
                data={"success": True}
            ))
        except Exception as e:
            logger.error(f"Context append error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ContextActions.APPEND,
                code="CONTEXT_ERROR",
                message=str(e)
            ))

    async def handle_context_clear(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            session_id = data.get("session_id", "default")
            _contexts[session_id] = []
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ContextActions.CLEAR,
                data={"success": True}
            ))
        except Exception as e:
            logger.error(f"Context clear error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ContextActions.CLEAR,
                code="CONTEXT_ERROR",
                message=str(e)
            ))

    manager.register_handler(ContextActions.GET, handle_context_get)
    manager.register_handler(ContextActions.APPEND, handle_context_append)
    manager.register_handler(ContextActions.CLEAR, handle_context_clear)
