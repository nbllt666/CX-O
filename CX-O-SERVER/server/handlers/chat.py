"""
聊天处理器
"""
import json
import logging
import time
from typing import TYPE_CHECKING

from server.protocol.message import create_response, create_error, create_stream
from server.protocol.actions import ChatActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def _get_agent_config(agent_id: str):
    from server.api.routers.agents import _load_agents
    agents = _load_agents()
    return next((a for a in agents if a["id"] == agent_id), None)


def _get_llm_client_for_agent(agent_config: dict):
    from server.api.app import get_llm_client, get_model_router

    model = agent_config.get("model", "main")

    try:
        model_router = get_model_router()

        if model.lower() in ["main", "summary", "memory"]:
            client = model_router.get_client(model.lower())
            if client:
                return client
        else:
            main_client = model_router.get_client("main")
            if main_client:
                from server.core.llm.client import OllamaClient

                return OllamaClient(
                    host=main_client.host,
                    model=model,
                    temperature=agent_config.get("temperature", 0.7),
                    max_tokens=agent_config.get("max_tokens", 4096),
                )
    except Exception as e:
        logger.warning(f"Failed to create client for model {model}: {e}")

    return get_llm_client()


def _build_messages(agent_config, context_mgr, session_id, user_message, memory_context=None, images=None):
    import yaml
    from pathlib import Path
    from server.config import get_settings

    messages = []

    try:
        settings = get_settings()
        config_dir = Path(settings._config_path).parent if settings._config_path else Path("config")
        hidden_prompt_path = config_dir / "hidden_prompt.yaml"
        hidden_prompts = {}
        if hidden_prompt_path.exists():
            with open(hidden_prompt_path, "r", encoding="utf-8") as f:
                hidden_prompts = yaml.safe_load(f) or {}
    except Exception:
        hidden_prompts = {}

    system_prompt = agent_config.get("system_prompt", "")
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    model_type = agent_config.get("model", "main").lower()
    hidden_parts = []

    for key in ["tool_instructions", "tools"]:
        if key in hidden_prompts:
            hidden_parts.append(hidden_prompts[key])

    if model_type == "main":
        for key in ["emotion_prompts", "effect_prompts", "tool_usage_prompts", "graph_tools", "master_model_prompt"]:
            if key in hidden_prompts:
                hidden_parts.append(hidden_prompts[key])
    elif model_type == "summary":
        for key in ["emotion_prompts", "effect_prompts", "graph_tools", "summary_model_prompt"]:
            if key in hidden_prompts:
                hidden_parts.append(hidden_prompts[key])
    elif model_type in ["assistant", "memory"]:
        for key in ["emotion_prompts", "effect_prompts", "tool_usage_prompts", "graph_tools", "assistant_model_prompt"]:
            if key in hidden_prompts:
                hidden_parts.append(hidden_prompts[key])

    if hidden_parts:
        messages.append({"role": "system", "content": "\n\n".join(hidden_parts)})

    if memory_context and agent_config.get("use_memory", True):
        messages.append({"role": "system", "content": f"相关记忆:\n{memory_context}"})

    history = context_mgr.get_messages(session_id, limit=10)
    for msg in history:
        if msg.get("role") in ["user", "assistant"]:
            messages.append({"role": msg["role"], "content": msg.get("content", "")})

    if images and agent_config.get("vision_enabled", False):
        content = [{"type": "text", "text": user_message}]
        for img_base64 in images:
            if img_base64.startswith("data:"):
                img_data = img_base64.split(",", 1)[1] if "," in img_base64 else img_base64
                mime_type = img_base64.split(";")[0].split(":")[1] if ":" in img_base64 else "image/jpeg"
            else:
                img_data = img_base64
                mime_type = "image/jpeg"
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_data}"}})
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_message})

    return messages


def _get_tools_for_agent(agent_config):
    from server.core.tools import tool_registry
    from server.core.tools.builtin import get_builtin_tools

    builtin_tools = get_builtin_tools()

    EXCLUDED_CATEGORIES = {"summary"}
    main_tool_names = {
        "write_long_term_memory", "search_all_memories", "call_assistant",
        "set_alarm", "mono", "write_permanent_memory",
        "acp_list_agents", "acp_connect", "acp_disconnect",
        "acp_send_message", "acp_create_group", "acp_join_group", "acp_leave_group",
    }
    main_tools = []
    for tool_name in main_tool_names:
        tool = tool_registry.get_tool(tool_name)
        if tool and tool.enabled and tool.category not in EXCLUDED_CATEGORIES:
            main_tools.append(tool.to_openai_function())

    tools = builtin_tools + main_tools
    return tools


async def _process_tool_calls(tool_calls_buffer, messages, llm, agent_config):
    from server.core.tools import tool_registry
    from server.core.tools.builtin import call_builtin_tool

    BUILTIN_TOOL_NAMES = {"calculator", "datetime", "random", "json_format"}

    for tool_call in tool_calls_buffer:
        tool_name = tool_call.get("name") or tool_call.get("function", {}).get("name")
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
            from server.api.app import get_context_manager, get_memory_manager

            agent_id = data.get("agent_id", "default")
            text = data.get("text", "")
            images = data.get("images")

            agent_config = _get_agent_config(agent_id)
            if not agent_config:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ChatActions.MESSAGE,
                    code="AGENT_NOT_FOUND",
                    message=f"Agent '{agent_id}' 不存在"
                ))
                return

            memory_mgr = get_memory_manager()
            context_mgr = get_context_manager()
            llm = _get_llm_client_for_agent(agent_config)

            session_id = f"agent-{agent_id}"
            existing_session = context_mgr.get_session(session_id)
            if not existing_session:
                context_mgr.create_session(
                    workspace_id="agent-chats",
                    title=f"{agent_config['name']} 的对话",
                    session_id=session_id,
                    metadata={"agent_id": agent_id},
                )

            context_mgr.add_message(session_id=session_id, role="user", content=text)

            memory_context = None
            if agent_config.get("use_memory", True) and memory_mgr:
                from server.core.memory.router import MemoryRouter
                router = MemoryRouter(memory_manager=memory_mgr)
                routing_result = await router.route(
                    query=text, session_id=session_id,
                    scene_type=agent_config.get("memory_scene", "chat"),
                )
                if routing_result.memories:
                    memory_context = "\n".join([f"- {m['content']}" for m in routing_result.memories[:5]])

            messages = _build_messages(agent_config, context_mgr, session_id, text, memory_context, images)
            tools = _get_tools_for_agent(agent_config)

            response = await llm.chat(messages=messages, stream=False, tools=tools)

            final_response = response.content
            if hasattr(response, "tool_calls") and response.tool_calls:
                response = await _process_tool_calls(response.tool_calls, messages, llm, agent_config)
                final_response = response.content

            context_mgr.add_message(session_id=session_id, role="assistant", content=final_response)

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ChatActions.MESSAGE,
                data={
                    "content": final_response,
                    "session_id": session_id,
                    "tokens_used": response.usage.get("total_tokens", 0) if response.usage else 0,
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
            from server.api.app import get_context_manager, get_memory_manager

            agent_id = data.get("agent_id", "default")
            text = data.get("text", "")

            agent_config = _get_agent_config(agent_id)
            if not agent_config:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ChatActions.STREAM,
                    code="AGENT_NOT_FOUND",
                    message=f"Agent '{agent_id}' 不存在"
                ))
                return

            memory_mgr = get_memory_manager()
            context_mgr = get_context_manager()
            llm = _get_llm_client_for_agent(agent_config)

            session_id = f"agent-{agent_id}"
            existing_session = context_mgr.get_session(session_id)
            if not existing_session:
                context_mgr.create_session(
                    workspace_id="agent-chats",
                    title=f"{agent_config['name']} 的对话",
                    session_id=session_id,
                    metadata={"agent_id": agent_id},
                )

            context_mgr.add_message(session_id=session_id, role="user", content=text)

            memory_context = None
            if agent_config.get("use_memory", True) and memory_mgr:
                from server.core.memory.router import MemoryRouter
                router = MemoryRouter(memory_manager=memory_mgr)
                routing_result = await router.route(
                    query=text, session_id=session_id,
                    scene_type=agent_config.get("memory_scene", "chat"),
                )
                if routing_result.memories:
                    memory_context = "\n".join([f"- {m['content']}" for m in routing_result.memories[:5]])

            messages = _build_messages(agent_config, context_mgr, session_id, text, memory_context)
            tools = _get_tools_for_agent(agent_config)

            full_response = ""
            tool_calls_buffer = []
            chunk_index = 0

            async for chunk in llm.stream_chat(
                messages=messages,
                temperature=agent_config.get("temperature", 0.7),
                max_tokens=agent_config.get("max_tokens", 4096),
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
                from server.core.tools import tool_registry
                from server.core.tools.builtin import call_builtin_tool

                BUILTIN_TOOL_NAMES = {"calculator", "datetime", "random", "json_format"}

                for tool_call in tool_calls_buffer:
                    tool_name = tool_call.get("name") or tool_call.get("function", {}).get("name")
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

                    if tool_name in BUILTIN_TOOL_NAMES:
                        tool_result = call_builtin_tool(tool_name, tool_args or {})
                    else:
                        tool_result = tool_registry.call_tool(tool_name, tool_args)

                    messages.append({"role": "assistant", "content": None, "tool_calls": [tool_call]})
                    tool_call_id = tool_call.get("id", "")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })

                full_response = ""
                async for chunk in llm.stream_chat(
                    messages=messages,
                    temperature=agent_config.get("temperature", 0.7),
                    max_tokens=agent_config.get("max_tokens", 4096),
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
                context_mgr.add_message(session_id=session_id, role="assistant", content=full_response)

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
            from server.api.app import get_context_manager, get_memory_manager

            agent_id = data.get("agent_id", "default")
            text = data.get("text", "")
            images = data.get("images")

            agent_config = _get_agent_config(agent_id)
            if not agent_config:
                await _manager.send_message(client_id, create_error(
                    request_id=request_id,
                    action=ChatActions.MULTIMODAL,
                    code="AGENT_NOT_FOUND",
                    message=f"Agent '{agent_id}' 不存在"
                ))
                return

            memory_mgr = get_memory_manager()
            context_mgr = get_context_manager()
            llm = _get_llm_client_for_agent(agent_config)

            session_id = f"agent-{agent_id}"
            existing_session = context_mgr.get_session(session_id)
            if not existing_session:
                context_mgr.create_session(
                    workspace_id="agent-chats",
                    title=f"{agent_config['name']} 的对话",
                    session_id=session_id,
                    metadata={"agent_id": agent_id},
                )

            context_mgr.add_message(session_id=session_id, role="user", content=text)

            memory_context = None
            if agent_config.get("use_memory", True) and memory_mgr:
                from server.core.memory.router import MemoryRouter
                router = MemoryRouter(memory_manager=memory_mgr)
                routing_result = await router.route(
                    query=text, session_id=session_id,
                    scene_type=agent_config.get("memory_scene", "chat"),
                )
                if routing_result.memories:
                    memory_context = "\n".join([f"- {m['content']}" for m in routing_result.memories[:5]])

            messages = _build_messages(agent_config, context_mgr, session_id, text, memory_context, images)
            tools = _get_tools_for_agent(agent_config)

            response = await llm.chat(messages=messages, stream=False, tools=tools)

            final_response = response.content
            if hasattr(response, "tool_calls") and response.tool_calls:
                response = await _process_tool_calls(response.tool_calls, messages, llm, agent_config)
                final_response = response.content

            context_mgr.add_message(session_id=session_id, role="assistant", content=final_response)

            await _manager.send_message(client_id, create_response(
                request_id=request_id,
                action=ChatActions.MULTIMODAL,
                data={
                    "content": final_response,
                    "session_id": session_id,
                    "tokens_used": response.usage.get("total_tokens", 0) if response.usage else 0,
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

    manager.register_handler(ChatActions.MESSAGE, handle_chat_message)
    manager.register_handler(ChatActions.STREAM, handle_chat_stream)
    manager.register_handler(ChatActions.MULTIMODAL, handle_chat_multimodal)
