"""
聊天处理器
"""
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from server.chat_helpers import get_agent_config, get_llm_client_for_agent, get_tools_for_agent
from server.config import Settings, get_settings
from server.prompt_builder import build_messages
from server.protocol.message import create_response, create_error, create_stream
from server.protocol.actions import ChatActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


@dataclass
class ChatContext:
    agent_config: dict
    context_mgr: object
    llm: object
    session_id: str
    memory_context: Optional[str] = None


async def _build_chat_context(
    agent_id: str,
    user_message: str,
    manager: "WebSocketManager",
    client_id: str,
    request_id: str,
    action: str,
) -> Optional[ChatContext]:
    from server.dependencies import get_context_manager, get_memory_manager

    agent_config = get_agent_config(agent_id)
    if not agent_config:
        await manager.send_message(client_id, create_error(
            request_id=request_id,
            action=action,
            code="AGENT_NOT_FOUND",
            message=f"Agent '{agent_id}' 不存在"
        ))
        return None

    memory_mgr = get_memory_manager()
    context_mgr = get_context_manager()
    llm = get_llm_client_for_agent(agent_config)

    session_id = f"agent-{agent_id}"
    existing_session = context_mgr.get_session(session_id)
    if not existing_session:
        context_mgr.create_session(
            workspace_id="agent-chats",
            title=f"{agent_config['name']} 的对话",
            session_id=session_id,
            metadata={"agent_id": agent_id},
        )

    context_mgr.add_message(session_id=session_id, role="user", content=user_message)

    memory_context = None
    if agent_config.get("use_memory", True) and memory_mgr:
        from server.core.memory.router import MemoryRouter
        router = MemoryRouter(memory_manager=memory_mgr)
        routing_result = await router.route(
            query=user_message, session_id=session_id,
            scene_type=agent_config.get("memory_scene", "chat"),
        )
        if routing_result.memories:
            _settings = get_settings()
            memory_context = "\n".join([f"- {m['content']}" for m in routing_result.memories[:_settings.config.limits.memory.inject_memories_count]])

    return ChatContext(
        agent_config=agent_config,
        context_mgr=context_mgr,
        llm=llm,
        session_id=session_id,
        memory_context=memory_context,
    )


def _parse_tool_args(tool_call: dict) -> dict:
    tool_args = tool_call.get("arguments") or tool_call.get("function", {}).get("arguments", "{}")

    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except json.JSONDecodeError:
            try:
                import ast
                tool_args = ast.literal_eval(tool_args)
                if not isinstance(tool_args, dict):
                    tool_args = {}
            except Exception:
                tool_args = {}

    return tool_args if isinstance(tool_args, dict) else {}


async def _process_tool_calls(tool_calls_buffer, messages, llm, agent_config):
    from server.core.tools import tool_registry
    from server.core.tools.builtin import call_builtin_tool

    BUILTIN_TOOL_NAMES = {"calculator", "datetime", "random", "json_format"}

    for tool_call in tool_calls_buffer:
        tool_name = tool_call.get("name") or tool_call.get("function", {}).get("name")
        tool_args = _parse_tool_args(tool_call)

        if tool_name in BUILTIN_TOOL_NAMES:
            tool_result = call_builtin_tool(tool_name, tool_args or {})
        else:
            tool_result = tool_registry.call_tool(tool_name, tool_args)

        messages.append({"role": "assistant", "content": None, "tool_calls": [tool_call]})
        tool_call_id = tool_call.get("id")
        if not tool_call_id:
            tool_call_id = f"call_{tool_name}_{int(time.time() * 1000)}_{id(tool_call)}"
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": json.dumps(tool_result, ensure_ascii=False),
        })

    response = await llm.chat(messages=messages, stream=False)
    return response


def register_chat_handlers(manager: "WebSocketManager"):
    _manager = manager

    async def handle_chat_message(websocket, message, client_id):
        request_id = message.get("request_id", "")
        data = message.get("data", {})

        try:
            agent_id = data.get("agent_id", "default")
            text = data.get("text", "")
            images = data.get("images")

            ctx = await _build_chat_context(agent_id, text, _manager, client_id, request_id, ChatActions.MESSAGE)
            if not ctx:
                return

            messages = build_messages(ctx.agent_config, ctx.context_mgr, ctx.session_id, text, ctx.memory_context, images)
            tools = get_tools_for_agent(ctx.agent_config)

            response = await ctx.llm.chat(messages=messages, stream=False, tools=tools)

            final_response = response.content
            if hasattr(response, "tool_calls") and response.tool_calls:
                response = await _process_tool_calls(response.tool_calls, messages, ctx.llm, ctx.agent_config)
                final_response = response.content

            ctx.context_mgr.add_message(session_id=ctx.session_id, role="assistant", content=final_response)

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ChatActions.MESSAGE,
                data={
                    "content": final_response,
                    "session_id": ctx.session_id,
                    "tokens_used": (response.usage or {}).get("total_tokens", 0),
                }
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

        try:
            agent_id = data.get("agent_id", "default")
            text = data.get("text", "")

            ctx = await _build_chat_context(agent_id, text, _manager, client_id, request_id, ChatActions.STREAM)
            if not ctx:
                return

            messages = build_messages(ctx.agent_config, ctx.context_mgr, ctx.session_id, text, ctx.memory_context)
            tools = get_tools_for_agent(ctx.agent_config)

            full_response = ""
            tool_calls_buffer = []
            chunk_index = 0

            async for chunk in ctx.llm.stream_chat(
                messages=messages,
                temperature=ctx.agent_config.get("temperature", 0.7),
                max_tokens=ctx.agent_config.get("max_tokens", 4096),
                tools=tools,
            ):
                if chunk:
                    if isinstance(chunk, dict):
                        chunk_type = chunk.get("type")
                        if chunk_type == "thinking":
                            pass
                        elif chunk_type == "content":
                            content = chunk.get("content", "")
                            full_response += content
                            await _manager.send_message(client_id, create_stream(
                                request_id=request_id,
                                action=ChatActions.STREAM,
                                chunk_index=chunk_index,
                                data={"content": content},
                                is_final=False
                            ))
                            chunk_index += 1
                        elif chunk_type == "tool_calls":
                            new_tool_calls = chunk.get("tool_calls", [])
                            tool_calls_buffer.extend(new_tool_calls)
                    elif isinstance(chunk, str):
                        full_response += chunk
                        await _manager.send_message(client_id, create_stream(
                            request_id=request_id,
                            action=ChatActions.STREAM,
                            chunk_index=chunk_index,
                            data={"content": chunk},
                            is_final=False
                        ))
                        chunk_index += 1

            if tool_calls_buffer:
                await _process_tool_calls(tool_calls_buffer, messages, ctx.llm, ctx.agent_config)

                full_response = ""
                async for chunk in ctx.llm.stream_chat(
                    messages=messages,
                    temperature=ctx.agent_config.get("temperature", 0.7),
                    max_tokens=ctx.agent_config.get("max_tokens", 4096),
                ):
                    if chunk:
                        if isinstance(chunk, dict):
                            chunk_type = chunk.get("type")
                            if chunk_type == "content":
                                content = chunk.get("content", "")
                                full_response += content
                                await _manager.send_message(client_id, create_stream(
                                    request_id=request_id,
                                    action=ChatActions.STREAM,
                                    chunk_index=chunk_index,
                                    data={"content": content},
                                    is_final=False
                                ))
                                chunk_index += 1
                            elif chunk_type == "thinking":
                                pass
                        elif isinstance(chunk, str):
                            full_response += chunk
                            await _manager.send_message(client_id, create_stream(
                                request_id=request_id,
                                action=ChatActions.STREAM,
                                chunk_index=chunk_index,
                                data={"content": chunk},
                                is_final=False
                            ))
                            chunk_index += 1

            if full_response:
                ctx.context_mgr.add_message(session_id=ctx.session_id, role="assistant", content=full_response)

            await _manager.send_message(client_id, create_stream(
                request_id=request_id,
                action=ChatActions.STREAM,
                chunk_index=chunk_index,
                data={},
                is_final=True
            ))
            _manager.increment_llm_count()

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
            agent_id = data.get("agent_id", "default")
            text = data.get("text", "")
            images = data.get("images")

            ctx = await _build_chat_context(agent_id, text, _manager, client_id, request_id, ChatActions.MULTIMODAL)
            if not ctx:
                return

            messages = build_messages(ctx.agent_config, ctx.context_mgr, ctx.session_id, text, ctx.memory_context, images)
            tools = get_tools_for_agent(ctx.agent_config)

            response = await ctx.llm.chat(messages=messages, stream=False, tools=tools)

            final_response = response.content
            if hasattr(response, "tool_calls") and response.tool_calls:
                response = await _process_tool_calls(response.tool_calls, messages, ctx.llm, ctx.agent_config)
                final_response = response.content

            ctx.context_mgr.add_message(session_id=ctx.session_id, role="assistant", content=final_response)

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ChatActions.MULTIMODAL,
                data={
                    "content": final_response,
                    "session_id": ctx.session_id,
                    "tokens_used": (response.usage or {}).get("total_tokens", 0),
                }
            ))
        except Exception as e:
            logger.error(f"Chat multimodal error: {e}")
            await _manager.send_message(client_id, create_error(
                request_id=request_id,
                action=ChatActions.MULTIMODAL,
                code="CHAT_MULTIMODAL_ERROR",
                message=str(e)
            ))

    manager.register_action_handler(ChatActions.MESSAGE, handle_chat_message)
    manager.register_action_handler(ChatActions.STREAM, handle_chat_stream)
    manager.register_action_handler(ChatActions.MULTIMODAL, handle_chat_multimodal)