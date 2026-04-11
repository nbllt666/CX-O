"""
记忆处理器
"""
import logging
from typing import TYPE_CHECKING, Optional

from server.protocol.message import create_response, create_error
from server.protocol.actions import MemoryActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager

logger = logging.getLogger(__name__)


def register_memory_handlers(manager: "ConnectionManager"):
    _manager = manager

    async def handle_memory_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            memory_manager = get_memory_manager()
            if memory_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=MemoryActions.LIST,
                    code="MEMORY_NOT_AVAILABLE",
                    message="Memory service is not available"
                ))
                return

            result = await memory_manager.list_memories(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.LIST,
                data=result
            ))
        except Exception as e:
            logger.error(f"Memory list error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MemoryActions.LIST,
                code="MEMORY_ERROR",
                message=str(e)
            ))

    async def handle_memory_create(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            memory_manager = get_memory_manager()
            if memory_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=MemoryActions.CREATE,
                    code="MEMORY_NOT_AVAILABLE",
                    message="Memory service is not available"
                ))
                return

            result = await memory_manager.create_memory(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.CREATE,
                data=result
            ))
        except Exception as e:
            logger.error(f"Memory create error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MemoryActions.CREATE,
                code="MEMORY_ERROR",
                message=str(e)
            ))

    async def handle_memory_delete(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            memory_manager = get_memory_manager()
            if memory_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=MemoryActions.DELETE,
                    code="MEMORY_NOT_AVAILABLE",
                    message="Memory service is not available"
                ))
                return

            result = await memory_manager.delete_memory(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.DELETE,
                data=result
            ))
        except Exception as e:
            logger.error(f"Memory delete error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MemoryActions.DELETE,
                code="MEMORY_ERROR",
                message=str(e)
            ))

    async def handle_memory_search(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            memory_manager = get_memory_manager()
            if memory_manager is None:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=MemoryActions.SEARCH,
                    code="MEMORY_NOT_AVAILABLE",
                    message="Memory service is not available"
                ))
                return

            result = await memory_manager.search_memories(data)
            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.SEARCH,
                data=result
            ))
        except Exception as e:
            logger.error(f"Memory search error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MemoryActions.SEARCH,
                code="MEMORY_ERROR",
                message=str(e)
            ))

    _manager.register_handler(MemoryActions.LIST, handle_memory_list)
    _manager.register_handler(MemoryActions.CREATE, handle_memory_create)
    _manager.register_handler(MemoryActions.DELETE, handle_memory_delete)
    _manager.register_handler(MemoryActions.SEARCH, handle_memory_search)


class LocalMemoryManager:
    def __init__(self):
        self._memory_service = None

    def _get_memory_service(self):
        if self._memory_service is None:
            try:
                from server.services.memory import get_memory_service
                self._memory_service = get_memory_service()
            except ImportError:
                logger.warning("Memory service not available")
        return self._memory_service

    async def list_memories(self, data: dict) -> dict:
        memory_service = self._get_memory_service()
        if memory_service is None:
            return {"memories": [], "error": "service_unavailable"}

        try:
            return await memory_service.list_memories(data)
        except Exception as e:
            logger.error(f"List memories error: {e}")
            return {"memories": [], "error": str(e)}

    async def create_memory(self, data: dict) -> dict:
        memory_service = self._get_memory_service()
        if memory_service is None:
            return {"id": None, "error": "service_unavailable"}

        try:
            return await memory_service.create_memory(data)
        except Exception as e:
            logger.error(f"Create memory error: {e}")
            return {"id": None, "error": str(e)}

    async def delete_memory(self, data: dict) -> dict:
        memory_service = self._get_memory_service()
        if memory_service is None:
            return {"success": False, "error": "service_unavailable"}

        try:
            return await memory_service.delete_memory(data)
        except Exception as e:
            logger.error(f"Delete memory error: {e}")
            return {"success": False, "error": str(e)}

    async def search_memories(self, data: dict) -> dict:
        memory_service = self._get_memory_service()
        if memory_service is None:
            return {"results": [], "error": "service_unavailable"}

        try:
            return await memory_service.search_memories(data)
        except Exception as e:
            logger.error(f"Search memories error: {e}")
            return {"results": [], "error": str(e)}


_memory_manager: Optional[LocalMemoryManager] = None


def get_memory_manager() -> Optional[LocalMemoryManager]:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = LocalMemoryManager()
    return _memory_manager