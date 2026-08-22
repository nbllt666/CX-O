"""
聊天处理器
"""
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from server.chat_helpers import get_agent_config, get_llm_client_for_agent, get_tools_for_agent, retrieve_memory_context, ensure_agent_session
from server.prompt_builder import build_messages
from server.protocol.message import create_response, create_error, create_stream
from server.protocol.actions import ChatActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


@dataclass
class ChatContext:
    """一次聊天请求的上下文：agent 配置、上下文管理器、LLM 客户端与会话信息。"""
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
    ensure_agent_session(context_mgr, agent_id, agent_config["name"])

    context_mgr.add_message(session_id=session_id, role="user", content=user_message)

    memory_context = await retrieve_memory_context(
        agent_config, memory_mgr, user_message, session_id
    )

    return ChatContext(
        agent_config=agent_config,
        context_mgr=context_mgr,
        llm=llm,
        session_id=session_id,
        memory_context=memory_context,
    )


async def _process_tool_calls(tool_calls_buffer, messages, llm):
    from server.core.tools.builtin import execute_tool_calls

    execute_tool_calls(tool_calls_buffer, messages)

    response = await llm.chat(messages=messages, stream=False)
    return response


async def _consume_and_send_stream(
    llm,
    messages,
    agent_config,
    manager,
    client_id,
    request_id,
    chunk_index,
    tools=None,
):
    """消费流式分块并通过 WebSocket 增量发送 content。

    收敛自 handle_chat_stream 首轮与工具后二次生成的两套几乎相同的消费循环，
    返回 (full_response, tool_calls_buffer, chunk_index)。
    """
    full_response = ""
    tool_calls_buffer = []

    async def _send(content):
        nonlocal chunk_index
        await manager.send_message(client_id, create_stream(
            request_id=request_id,
            action=ChatActions.STREAM,
            chunk_index=chunk_index,
            data={"content": content},
            is_final=False,
        ))
        chunk_index += 1

    async for chunk in llm.stream_chat(
        messages=messages,
        temperature=agent_config.get("temperature", 0.7),
        max_tokens=agent_config.get("max_tokens", 4096),
        tools=tools,
    ):
        if not chunk:
            continue
        if isinstance(chunk, dict):
            chunk_type = chunk.get("type")
            if chunk_type == "content":
                content = chunk.get("content", "")
                full_response += content
                await _send(content)
            elif chunk_type == "tool_calls":
                tool_calls_buffer.extend(chunk.get("tool_calls", []))
            # thinking 分块忽略不发送
        elif isinstance(chunk, str):
            full_response += chunk
            await _send(chunk)

    return full_response, tool_calls_buffer, chunk_index


def _record_live_feedback(text: str, prompt: str, session_id: str) -> None:
    """在 AI 回复产生处记录「上一轮回复」到隐式反馈追踪器（增量接入，静默降级）。"""
    try:
        from server.services.live_feedback import get_live_feedback_tracker

        get_live_feedback_tracker().record_ai_response(text, prompt=prompt)
    except Exception as e:  # 记录失败不影响聊天主路径
        logger.warning(f"live_feedback 回复记录降级: {e}")


def register_chat_handlers(manager: "WebSocketManager"):
    """将聊天（普通/流式/多模态）处理器注册到 WebSocket 管理器。"""
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
            tools = get_tools_for_agent()

            response = await ctx.llm.chat(messages=messages, stream=False, tools=tools)

            final_response = response.content
            if hasattr(response, "tool_calls") and response.tool_calls:
                response = await _process_tool_calls(response.tool_calls, messages, ctx.llm)
                final_response = response.content

            _record_live_feedback(final_response, text, ctx.session_id)

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
            tools = get_tools_for_agent()

            full_response, tool_calls_buffer, chunk_index = await _consume_and_send_stream(
                ctx.llm, messages, ctx.agent_config, _manager, client_id, request_id, 0, tools=tools,
            )

            if tool_calls_buffer:
                await _process_tool_calls(tool_calls_buffer, messages, ctx.llm)

                full_response, _, chunk_index = await _consume_and_send_stream(
                    ctx.llm, messages, ctx.agent_config, _manager, client_id, request_id, chunk_index,
                )

            if full_response:
                _record_live_feedback(full_response, text, ctx.session_id)
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
            tools = get_tools_for_agent()

            response = await ctx.llm.chat(messages=messages, stream=False, tools=tools)

            final_response = response.content
            if hasattr(response, "tool_calls") and response.tool_calls:
                response = await _process_tool_calls(response.tool_calls, messages, ctx.llm)
                final_response = response.content

            _record_live_feedback(final_response, text, ctx.session_id)

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
