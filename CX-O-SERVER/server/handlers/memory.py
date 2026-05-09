"""
记忆处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_error
from server.protocol.actions import MemoryActions

if TYPE_CHECKING:
    from server.gateway.server import ConnectionManager
    from server.services.cxhms_client import CXHMSClient

logger = logging.getLogger(__name__)


def register_memory_handlers(manager: "ConnectionManager", cxhms_client: "CXHMSClient"):

    async def handle_memory_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            response = await cxhms_client.request(MemoryActions.LIST, data)
            await manager.send_message(client_id, response)
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
            response = await cxhms_client.request(MemoryActions.CREATE, data)
            await manager.send_message(client_id, response)
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
            response = await cxhms_client.request(MemoryActions.DELETE, data)
            await manager.send_message(client_id, response)
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
            response = await cxhms_client.request(MemoryActions.SEARCH, data)
            await manager.send_message(client_id, response)
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
