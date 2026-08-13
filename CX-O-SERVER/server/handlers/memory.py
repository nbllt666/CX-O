"""
记忆处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error
from server.protocol.actions import MemoryActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def register_memory_handlers(manager: "WebSocketManager"):
    """将记忆（列表/创建/删除/搜索）处理器注册到 WebSocket 管理器。"""

    async def handle_memory_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.dependencies import get_memory_manager

            memory_mgr = get_memory_manager()
            result = await memory_mgr.search_memories_async(
                query=data.get("query"),
                memory_type=data.get("type"),
                tags=data.get("tags"),
                time_range=data.get("time_range"),
                limit=data.get("limit", 10),
                offset=data.get("offset", 0),
                workspace_id=data.get("workspace_id", "default"),
                agent_id=data.get("agent_id", "default"),
            )

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.LIST,
                data={"memories": result}
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
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.dependencies import get_memory_manager

            memory_mgr = get_memory_manager()
            memory_id = await memory_mgr.write_memory_async(
                content=data.get("content", ""),
                memory_type=data.get("type", "long_term"),
                importance=data.get("importance", 3),
                tags=data.get("tags"),
                metadata=data.get("metadata"),
                permanent=data.get("permanent", False),
                emotion_score=data.get("emotion_score", 0.0),
                workspace_id=data.get("workspace_id", "default"),
                agent_id=data.get("agent_id", "default"),
            )

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.CREATE,
                data={"memory_id": memory_id}
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
            from server.dependencies import get_memory_manager

            memory_mgr = get_memory_manager()
            success = await memory_mgr.delete_memory_async(
                memory_id=data.get("memory_id"),
                soft_delete=data.get("soft_delete", True),
                agent_id=data.get("agent_id", "default"),
            )

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.DELETE,
                data={"success": success}
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
            from server.dependencies import get_memory_manager

            memory_mgr = get_memory_manager()

            if data.get("semantic") and memory_mgr.is_vector_search_enabled():
                # 向量检索单独 try/except，在错误消息中区分"向量检索失败"与"普通检索失败"
                try:
                    result = await memory_mgr.hybrid_search(
                        query=data.get("query", ""),
                        memory_type=data.get("type"),
                        tags=data.get("tags"),
                        limit=data.get("limit", 10),
                        workspace_id=data.get("workspace_id"),
                    )
                except Exception as vector_e:
                    logger.error(f"Memory vector search error: {vector_e}")
                    await manager.send_message(client_id, create_error(
                        request_id=request_id,
                        action=MemoryActions.SEARCH,
                        code="MEMORY_ERROR",
                        message=f"Vector search failed: {vector_e}"
                    ))
                    return
            else:
                result = memory_mgr.search_memories(
                    query=data.get("query"),
                    memory_type=data.get("type"),
                    tags=data.get("tags"),
                    time_range=data.get("time_range"),
                    limit=data.get("limit", 10),
                    offset=data.get("offset", 0),
                    workspace_id=data.get("workspace_id", "default"),
                    agent_id=data.get("agent_id", "default"),
                )

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=MemoryActions.SEARCH,
                data={"memories": result}
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
