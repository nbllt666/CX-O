"""
工具处理器
"""
import logging
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error
from server.protocol.actions import ToolsActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def register_tools_handlers(manager: "WebSocketManager"):
    """将工具（列表/调用/注册）处理器注册到 WebSocket 管理器。"""

    async def handle_tools_list(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.core.tools import tool_registry

            include_builtin = data.get("include_builtin", False)
            enabled_only = data.get("enabled_only", True)
            category = data.get("category")

            tools = tool_registry.list_openai_functions(
                enabled_only=enabled_only,
                include_builtin=include_builtin,
                category=category,
            )

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ToolsActions.LIST,
                data={"tools": tools}
            ))
        except Exception as e:
            logger.error(f"Tools list error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ToolsActions.LIST,
                code="TOOLS_ERROR",
                message=str(e)
            ))

    async def handle_tools_call(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.core.tools import tool_registry

            tool_name = data.get("name", "")
            arguments = data.get("arguments", {})

            result = await tool_registry.call_tool_async(tool_name, arguments)

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ToolsActions.CALL,
                data=result
            ))
        except Exception as e:
            logger.error(f"Tools call error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ToolsActions.CALL,
                code="TOOLS_ERROR",
                message=str(e)
            ))

    async def handle_tools_register(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            from server.core.tools import tool_registry

            name = data.get("name", "")
            parameters = data.get("parameters", {})

            # 输入验证：name 和 parameters 不可为空
            if not name:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ToolsActions.REGISTER,
                    code="INVALID_REQUEST",
                    message="Tool name cannot be empty"
                ))
                return
            if not parameters:
                await manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ToolsActions.REGISTER,
                    code="INVALID_REQUEST",
                    message="Tool parameters cannot be empty"
                ))
                return

            tool = tool_registry.register(
                name=name,
                description=data.get("description", ""),
                parameters=parameters,
                enabled=data.get("enabled", True),
                version=data.get("version", "1.0.0"),
                category=data.get("category", "general"),
                tags=data.get("tags"),
                examples=data.get("examples"),
            )

            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ToolsActions.REGISTER,
                data={"name": tool.name, "registered": True}
            ))
        except Exception as e:
            logger.error(f"Tools register error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ToolsActions.REGISTER,
                code="TOOLS_ERROR",
                message=str(e)
            ))

    manager.register_handler(ToolsActions.LIST, handle_tools_list)
    manager.register_handler(ToolsActions.CALL, handle_tools_call)
    manager.register_handler(ToolsActions.REGISTER, handle_tools_register)
