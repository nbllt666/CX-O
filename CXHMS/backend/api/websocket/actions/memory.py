"""
记忆 Action 处理器
"""
import logging
from typing import TYPE_CHECKING

from ..protocol import create_response, create_error

if TYPE_CHECKING:
    from ..server import ConnectionManager

logger = logging.getLogger(__name__)


class MemoryActions:
    LIST = "memory.list"
    CREATE = "memory.create"
    DELETE = "memory.delete"
    SEARCH = "memory.search"
    GET = "memory.get"
    UPDATE = "memory.update"


_memories: dict = {}
_memory_counter = 0


def register_memory_handlers(manager: "ConnectionManager"):
    
    async def handle_memory_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        
        try:
            memories_list = list(_memories.values())
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.LIST,
                data={"memories": memories_list}
            ))
        except Exception as e:
            logger.error(f"Memory list error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MemoryActions.LIST,
                code="MEMORY_ERROR",
                message=str(e)
            ))

    async def handle_memory_create(websocket, message, client_id):
        global _memory_counter
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            _memory_counter += 1
            memory_id = str(_memory_counter)
            memory = {
                "id": memory_id,
                "content": data.get("content", ""),
                "tags": data.get("tags", []),
                "created_at": int(__import__("time").time())
            }
            _memories[memory_id] = memory
            
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.CREATE,
                data={"memory": memory}
            ))
        except Exception as e:
            logger.error(f"Memory create error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MemoryActions.CREATE,
                code="MEMORY_ERROR",
                message=str(e)
            ))

    async def handle_memory_delete(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            memory_id = data.get("id", "")
            if memory_id in _memories:
                del _memories[memory_id]
                await manager.send_message(client_id, create_response(
                    request_id=request_id,
                    action=MemoryActions.DELETE,
                    data={"success": True}
                ))
            else:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=MemoryActions.DELETE,
                    code="NOT_FOUND",
                    message="Memory not found"
                ))
        except Exception as e:
            logger.error(f"Memory delete error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MemoryActions.DELETE,
                code="MEMORY_ERROR",
                message=str(e)
            ))

    async def handle_memory_search(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})
        
        try:
            query = data.get("query", "").lower()
            results = [
                m for m in _memories.values()
                if query in m.get("content", "").lower()
            ]
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.SEARCH,
                data={"memories": results}
            ))
        except Exception as e:
            logger.error(f"Memory search error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=MemoryActions.SEARCH,
                code="MEMORY_ERROR",
                message=str(e)
            ))

    manager.register_handler(MemoryActions.LIST, handle_memory_list)
    manager.register_handler(MemoryActions.CREATE, handle_memory_create)
    manager.register_handler(MemoryActions.DELETE, handle_memory_delete)
    manager.register_handler(MemoryActions.SEARCH, handle_memory_search)
