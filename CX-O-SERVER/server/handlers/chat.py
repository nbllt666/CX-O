"""
聊天处理器
"""
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from server.config import Settings
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

    agent_config = _get_agent_config(agent_id)
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
            memory_context = "\n".join([f"- {m['content']}" for m in routing_result.memories[:Settings().config.limits.memory.inject_memories_count]])

    return ChatContext(
        agent_config=agent_config,
        context_mgr=context_mgr,
        llm=llm,
        session_id=session_id,
        memory_context=memory_context,
    )


def _get_agent_config(agent_id: str):
    from server.api.routers.agents import _load_agents
    agents = _load_agents()
    return next((a for a in agents if a["id"] == agent_id), None)


def _get_llm_client_for_agent(agent_config: dict):
    from server.dependencies import get_llm_client, get_model_router

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


def _build_messages(
    agent_config,
    context_mgr,
    session_id,
    user_message,
    memory_context=None,
    images=None,
    is_realtime_voice: bool = False,
    tts_engine: str = "f5-tts",
):
    """构建发送给 LLM 的消息列表。

    Args:
        agent_config: Agent 配置字典，包含 system_prompt / model / use_memory 等。
        context_mgr: 上下文管理器，用于读取对话历史。
        session_id: 会话 ID。
        user_message: 当前用户输入文本。
        memory_context: 记忆检索结果（可选）。
        images: 多模态图像列表（可选）。
        is_realtime_voice: 是否为实时语音模式。True 时走瘦身分支，
            跳过重型隐藏提示词，仅保留核心人设 + voice_prompt + 最近 2 轮对话。
        tts_engine: TTS 引擎名称，决定实时模式下注入哪个 voice_prompt。
            "orpheus" → orpheus_voice_prompt（含情感标签指南）；
            其他值 → realtime_voice_prompt（默认）。

    Returns:
        list[dict]: OpenAI 格式的消息列表。
    """
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
    # 核心人设 System Prompt：实时与非实时模式均保留，确保 LLM 不丢失基础人设和能力。
    # 前 spec（optimize-ttfa-sub-300ms）曾在此处对实时模式跳过 system_prompt，导致 LLM
    # 丢失人设；本 task 修复为：实时模式同样注入 system_prompt（约 ~100 tokens）。
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # ====================================================================
    # 实时语音模式：瘦身 Prompt，确保 Tokens < 600，锁死 80ms TTFT
    # --------------------------------------------------------------------
    # 保留：核心人设 system_prompt（上方已注入）+ 对应 voice_prompt + 最近 2 轮对话
    # 跳过：MemoryRouter 深度图检索、HybridSearch、技能注入、tool_instructions、
    #       effect_prompts、emotion_prompts 等重型提示词（合计约 1500 tokens）
    # ====================================================================
    if is_realtime_voice:
        # 根据 TTS 引擎选择对应的 voice_prompt：
        # - orpheus：注入 orpheus_voice_prompt（含 Orpheus 情感标签使用指南，~200 tokens）
        # - 其他（f5-tts 等）：注入 realtime_voice_prompt（默认实时语音规则，~100 tokens）
        if tts_engine == "orpheus":
            voice_prompt = hidden_prompts.get("orpheus_voice_prompt", "")
        else:
            voice_prompt = hidden_prompts.get("realtime_voice_prompt", "")
        if voice_prompt:
            messages.append({"role": "system", "content": voice_prompt})

        # 跳过 memory_context 注入：避免 MemoryRouter 深度图检索的 50-100ms
        # 跳过 cxfc_mgr 技能注入：避免 skill_registry 关键词匹配 + 模板渲染的 10-30ms
        # 跳过 tool_instructions / emotion_prompts / effect_prompts 等重型隐藏提示词

        # 仅保留最近 2 轮对话历史（limit=4，即 2 user + 2 assistant，~200 tokens）
        # 每多 1K tokens 历史约增加 20-40ms Prefill，裁剪到 4 条可省 60-120ms
        history = context_mgr.get_messages(session_id, limit=4)
        for msg in history:
            if msg.get("role") in ["user", "assistant"]:
                messages.append({"role": msg["role"], "content": msg.get("content", "")})

        # 实时语音模式不支持多模态图像注入，直接送文本
        messages.append({"role": "user", "content": user_message})

        # Token 预算：核心人设 ~100 + voice_prompt ~200 + 2 轮对话 ~200 = ~500 tokens < 600
        return messages

    # ====================================================================
    # 以下为非实时模式（默认）：行为与改造前完全一致，保持向后兼容
    # ====================================================================

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

    try:
        from server.dependencies import get_cxfc_manager
        cxfc_mgr = get_cxfc_manager()
        if cxfc_mgr:
            skill_registry = cxfc_mgr.get_skill_registry()
            matched_skills = skill_registry.find_by_keywords(user_message)
            if matched_skills:
                skill_prompts = []
                for skill in matched_skills:
                    if skill.auto_inject:
                        rendered = skill_registry.render_template(
                            skill.prompt_template,
                            {"user_message": user_message},
                        )
                        skill_prompts.append(rendered)
                if skill_prompts:
                    skill_context = "\n\n".join(skill_prompts)
                    messages.append({"role": "system", "content": skill_context})
    except Exception as e:
        logger.warning(f"Skills injection failed: {e}")

    history = context_mgr.get_messages(session_id, limit=Settings().config.limits.context.chat_context_limit)
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

            messages = _build_messages(ctx.agent_config, ctx.context_mgr, ctx.session_id, text, ctx.memory_context, images)
            tools = _get_tools_for_agent(ctx.agent_config)

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
            agent_id = data.get("agent_id", "default")
            text = data.get("text", "")

            ctx = await _build_chat_context(agent_id, text, _manager, client_id, request_id, ChatActions.STREAM)
            if not ctx:
                return

            messages = _build_messages(ctx.agent_config, ctx.context_mgr, ctx.session_id, text, ctx.memory_context)
            tools = _get_tools_for_agent(ctx.agent_config)

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

            messages = _build_messages(ctx.agent_config, ctx.context_mgr, ctx.session_id, text, ctx.memory_context, images)
            tools = _get_tools_for_agent(ctx.agent_config)

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
