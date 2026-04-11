"""
聊天路由 - 支持 Agent 的聊天 API
前端只发送最新一条消息，后端根据 Agent 配置构建完整上下文
"""

import json
import time
import yaml
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server.api.routers.agents import _load_agents
from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    agent_id: str = "default"
    stream: bool = True
    images: Optional[List[str]] = None


class ChatResponse(BaseModel):
    status: str
    response: str
    session_id: str
    tokens_used: int = 0


class AgentModelType(Enum):
    MAIN = "main"
    SUMMARY = "summary"
    MEMORY = "memory"
    ASSISTANT = "assistant"
    CUSTOM = "custom"


class LLMClientFactory:
    @staticmethod
    def get_model_type(model: str) -> AgentModelType:
        try:
            return AgentModelType(model.lower())
        except ValueError:
            return AgentModelType.CUSTOM

    @classmethod
    def create_client_for_agent(cls, agent_config: dict):
        from server.api.app import get_llm_client, get_model_router

        model = agent_config.get("model", "main")
        model_type = cls.get_model_type(model)

        try:
            model_router = get_model_router()

            if model_type in (AgentModelType.MAIN, AgentModelType.SUMMARY, AgentModelType.MEMORY):
                client = model_router.get_client(model.lower())
                if client:
                    return client
            else:
                return cls._create_custom_model_client(model_router, model, agent_config)

        except Exception as e:
            logger.warning(f"Failed to create client for model {model}: {e}")

        return get_llm_client()

    @classmethod
    def _create_custom_model_client(cls, model_router, model: str, agent_config: dict):
        main_client = model_router.get_client("main")
        if main_client:
            from server.core.llm.client import OllamaClient

            return OllamaClient(
                host=main_client.host,
                model=model,
                temperature=agent_config.get("temperature", 0.7),
                max_tokens=agent_config.get("max_tokens", 4096),
            )
        return None


def get_agent_config(agent_id: str) -> Optional[dict]:
    """获取 Agent 配置"""
    agents = _load_agents()
    return next((a for a in agents if a["id"] == agent_id), None)


def get_llm_client_for_agent(agent_config: dict):
    """根据 Agent 配置获取 LLM 客户端"""
    return LLMClientFactory.create_client_for_agent(agent_config)


def build_messages(
    agent_config: dict,
    context_mgr,
    session_id: str,
    user_message: str,
    memory_context: Optional[str] = None,
    images: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """构建消息列表"""
    messages = []

    from server.config import settings

    config_dir = Path(settings._config_path).parent if settings._config_path else Path("config")
    hidden_prompt_path = config_dir / "hidden_prompt.yaml"
    hidden_prompts = {}
    if hidden_prompt_path.exists():
        with open(hidden_prompt_path, "r", encoding="utf-8") as f:
            hidden_prompts = yaml.safe_load(f) or {}

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
                mime_type = (
                    img_base64.split(";")[0].split(":")[1] if ":" in img_base64 else "image/jpeg"
                )
            else:
                img_data = img_base64
                mime_type = "image/jpeg"

            content.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{img_data}"}}
            )
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_message})

    return messages


@router.post("/chat")
async def chat(request: ChatRequest):
    """
    非流式聊天
    前端只发送最新消息，后端根据 Agent 配置构建完整上下文
    每个 Agent 对应一个固定会话
    """
    from server.api.app import get_context_manager, get_memory_manager

    try:
        agent_config = get_agent_config(request.agent_id)
        if not agent_config:
            raise HTTPException(status_code=404, detail=f"Agent '{request.agent_id}' 不存在")

        memory_mgr = get_memory_manager()
        context_mgr = get_context_manager()
        llm = get_llm_client_for_agent(agent_config)

        session_id = f"agent-{request.agent_id}"
        existing_session = context_mgr.get_session(session_id)
        if not existing_session:
            context_mgr.create_session(
                workspace_id="agent-chats",
                title=f"{agent_config['name']} 的对话",
                session_id=session_id,
                metadata={"agent_id": request.agent_id},
            )

        context_mgr.add_message(session_id=session_id, role="user", content=request.message)

        memory_context = None
        if agent_config.get("use_memory", True) and memory_mgr:
            from server.core.memory.router import MemoryRouter

            router = MemoryRouter(memory_manager=memory_mgr)
            routing_result = await router.route(
                query=request.message,
                session_id=session_id,
                scene_type=agent_config.get("memory_scene", "chat"),
            )
            if routing_result.memories:
                memory_context = "\n".join(
                    [f"- {m['content']}" for m in routing_result.memories[:5]]
                )

        messages = build_messages(
            agent_config=agent_config,
            context_mgr=context_mgr,
            session_id=session_id,
            user_message=request.message,
            memory_context=memory_context,
            images=request.images,
        )

        from server.core.tools import tool_registry

        all_tools = tool_registry.list_openai_functions(include_builtin=True)
        EXCLUDED_CATEGORIES = {"summary"}
        tools = [
            t
            for t in all_tools
            if tool_registry.get_tool(t.get("function", {}).get("name", ""))
            and tool_registry.get_tool(t.get("function", {}).get("name", "")).category
            not in EXCLUDED_CATEGORIES
        ]
        if not tools:
            tools = []

        response = await llm.chat(messages=messages, stream=False, tools=tools)

        final_response = response.content
        if hasattr(response, "tool_calls") and response.tool_calls:
            from server.core.tools import tool_registry
            from server.core.tools.builtin import call_builtin_tool

            BUILTIN_TOOL_NAMES = {"calculator", "datetime", "random", "json_format"}

            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name") or tool_call.get("function", {}).get("name")
                tool_args = tool_call.get("arguments") or tool_call.get("function", {}).get(
                    "arguments", "{}"
                )

                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except json.JSONDecodeError as e:
                        logger.warning(f"工具参数 JSON 解析失败: {e}, 原始参数: {tool_args}")
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
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id") or f"call_{tool_name}_{int(time.time() * 1000)}",
                        "name": tool_name,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

            response = await llm.chat(messages=messages, stream=False)
            final_response = response.content

        context_mgr.add_message(session_id=session_id, role="assistant", content=final_response)

        return {
            "status": "success",
            "response": final_response,
            "session_id": session_id,
            "tokens_used": response.usage.get("total_tokens", 0) if response.usage else 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    流式聊天
    前端只发送最新消息，后端根据 Agent 配置构建完整上下文
    每个 Agent 对应一个固定会话
    """
    from server.api.app import get_context_manager, get_memory_manager

    try:
        agent_config = get_agent_config(request.agent_id)
        if not agent_config:
            raise HTTPException(status_code=404, detail=f"Agent '{request.agent_id}' 不存在")

        memory_mgr = get_memory_manager()
        context_mgr = get_context_manager()
        llm = get_llm_client_for_agent(agent_config)

        session_id = f"agent-{request.agent_id}"
        existing_session = context_mgr.get_session(session_id)
        if not existing_session:
            context_mgr.create_session(
                workspace_id="agent-chats",
                title=f"{agent_config['name']} 的对话",
                session_id=session_id,
                metadata={"agent_id": request.agent_id},
            )

        context_mgr.add_message(session_id=session_id, role="user", content=request.message)

        memory_context = None
        if agent_config.get("use_memory", True) and memory_mgr:
            from server.core.memory.router import MemoryRouter

            router = MemoryRouter(memory_manager=memory_mgr)
            routing_result = await router.route(
                query=request.message,
                session_id=session_id,
                scene_type=agent_config.get("memory_scene", "chat"),
            )
            if routing_result.memories:
                memory_context = "\n".join(
                    [f"- {m['content']}" for m in routing_result.memories[:5]]
                )

        messages = build_messages(
            agent_config=agent_config,
            context_mgr=context_mgr,
            session_id=session_id,
            user_message=request.message,
            memory_context=memory_context,
        )

        from server.core.tools import tool_registry
        from server.core.tools.builtin import get_builtin_tools

        builtin_tools = get_builtin_tools()

        EXCLUDED_CATEGORIES = {"summary"}
        main_tool_names = {
            "write_long_term_memory",
            "search_all_memories",
            "call_assistant",
            "set_alarm",
            "mono",
            "write_permanent_memory",
            "acp_list_agents",
            "acp_connect",
            "acp_disconnect",
            "acp_send_message",
            "acp_create_group",
            "acp_join_group",
            "acp_leave_group",
        }
        main_tools = []
        for tool_name in main_tool_names:
            tool = tool_registry.get_tool(tool_name)
            if tool and tool.enabled and tool.category not in EXCLUDED_CATEGORIES:
                main_tools.append(tool.to_openai_function())

        tools = builtin_tools + main_tools

        logger.info(
            f"为 Agent '{agent_config.get('name')}' 配置了 {len(tools)} 个工具: {[t['function']['name'] for t in tools]}"
        )

        async def generate_stream():
            """生成流式响应"""
            full_response = ""
            full_thinking = ""
            tool_calls_buffer = []

            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

            try:
                logger.info(
                    f"开始流式聊天，消息数: {len(messages)}, 工具数: {len(tools) if tools else 0}"
                )
                async for chunk in llm.stream_chat(
                    messages=messages,
                    temperature=agent_config.get("temperature", 0.7),
                    max_tokens=agent_config.get("max_tokens", 4096),
                    tools=tools,
                ):
                    if chunk:
                        logger.debug(f"收到 chunk: {type(chunk)}, 内容: {chunk}")
                        if isinstance(chunk, dict):
                            chunk_type = chunk.get("type")
                            if chunk_type == "thinking":
                                thinking_content = chunk.get("content", "")
                                full_thinking += thinking_content
                                yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_content})}\n\n"
                            elif chunk_type == "content":
                                content = chunk.get("content", "")
                                full_response += content
                                yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                            elif chunk_type == "tool_calls":
                                new_tool_calls = chunk.get("tool_calls", [])
                                logger.info(f"检测到工具调用: {new_tool_calls}")
                                tool_calls_buffer.extend(new_tool_calls)
                                for tool_call in new_tool_calls:
                                    yield f"data: {json.dumps({'type': 'tool_call', 'tool_call': tool_call})}\n\n"
                        elif isinstance(chunk, str):
                            full_response += chunk
                            yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"

                if tool_calls_buffer:
                    from server.core.tools import tool_registry
                    from server.core.tools.builtin import call_builtin_tool

                    BUILTIN_TOOL_NAMES = {"calculator", "datetime", "random", "json_format"}

                    for tool_call in tool_calls_buffer:
                        tool_name = tool_call.get("name") or tool_call.get("function", {}).get(
                            "name"
                        )
                        tool_args = tool_call.get("arguments") or tool_call.get("function", {}).get(
                            "arguments", "{}"
                        )

                        if isinstance(tool_args, str):
                            try:
                                tool_args = json.loads(tool_args)
                            except json.JSONDecodeError as e:
                                logger.warning(
                                    f"工具参数 JSON 解析失败: {e}, 原始参数: {tool_args}"
                                )
                                try:
                                    import ast

                                    tool_args = ast.literal_eval(tool_args)
                                    if not isinstance(tool_args, dict):
                                        tool_args = {}
                                except Exception:
                                    tool_args = {}

                        yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': tool_name})}\n\n"

                        if tool_name in BUILTIN_TOOL_NAMES:
                            tool_result = call_builtin_tool(tool_name, tool_args or {})
                            logger.info(f"内置工具 {tool_name} 执行结果: {tool_result}")
                        else:
                            tool_result = tool_registry.call_tool(tool_name, tool_args)
                            logger.info(f"注册工具 {tool_name} 执行结果: {tool_result}")

                        yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'result': tool_result})}\n\n"

                        messages.append(
                            {"role": "assistant", "content": None, "tool_calls": [tool_call]}
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.get("id", ""),
                                "name": tool_name,
                                "content": json.dumps(tool_result, ensure_ascii=False),
                            }
                        )

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
                                    yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                                elif chunk_type == "thinking":
                                    thinking_content = chunk.get("content", "")
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_content})}\n\n"
                            elif isinstance(chunk, str):
                                full_response += chunk
                                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"

                if full_response:
                    context_mgr.add_message(
                        session_id=session_id, role="assistant", content=full_response
                    )

                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

            except Exception as e:
                logger.error(f"流式聊天错误: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/history/{session_id}")
async def get_chat_history(session_id: str, limit: int = 50):
    """获取聊天历史"""
    from server.api.app import get_context_manager

    try:
        context_mgr = get_context_manager()
        session = context_mgr.get_session(session_id)

        if not session:
            if session_id.startswith("agent-"):
                agent_id = session_id.replace("agent-", "")
                agent_config = get_agent_config(agent_id)

                if agent_config:
                    context_mgr.create_session(
                        session_id=session_id,
                        workspace_id="agent-chats",
                        title=f"{agent_config.get('name', 'Agent')} 的对话",
                    )
                    context_mgr.update_session(session_id, metadata={"agent_id": agent_id})
                    session = context_mgr.get_session(session_id)

            if not session:
                return {
                    "status": "success",
                    "session_id": session_id,
                    "session": None,
                    "messages": [],
                }

        messages = context_mgr.get_messages(session_id, limit=limit)

        return {
            "status": "success",
            "session_id": session_id,
            "session": session,
            "messages": messages,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取聊天历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class MemoryAgentChatRequest(BaseModel):
    """记忆管理模型聊天请求"""

    message: str


@router.post("/memory-agent/chat/stream")
async def memory_agent_chat_stream(request: MemoryAgentChatRequest):
    """
    记忆管理模型流式聊天 - 支持上下文持久化
    记忆管理Agent只有一个固定会话
    """
    from server.api.app import get_context_manager, get_memory_manager, get_model_router
    from server.core.context.agent_context_manager import AgentContextManager

    try:
        agent_config = get_agent_config("memory-agent")
        if not agent_config:
            raise HTTPException(status_code=404, detail="记忆管理Agent未配置")

        memory_mgr = get_memory_manager()
        context_mgr = get_context_manager()
        agent_context_mgr = AgentContextManager()

        model_router = get_model_router()
        llm = model_router.get_client("memory")
        if not llm:
            raise HTTPException(status_code=503, detail="记忆管理模型不可用")

        session_id = "memory-agent-default"
        try:
            context_mgr.get_session(session_id)
        except Exception:
            session_id = context_mgr.create_session(
                workspace_id="memory-agent", title="记忆管理对话"
            )

        agent_id = "memory-agent"
        history_context = agent_context_mgr.load_context(agent_id, limit=20)

        context_mgr.add_message(session_id=session_id, role="user", content=request.message)
        agent_context_mgr.append_message(agent_id, "user", request.message)

        messages = []

        system_prompt = agent_config.get("system_prompt", "")
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for msg in history_context:
            if msg.get("role") in ["user", "assistant", "system"]:
                messages.append({"role": msg["role"], "content": msg.get("content", "")})

        messages.append({"role": "user", "content": request.message})

        from server.core.tools import tool_registry

        tools = tool_registry.list_openai_functions(include_builtin=False, category="assistant")

        logger.info(
            f"记忆管理模型配置了 {len(tools)} 个工具: {[t['function']['name'] for t in tools]}"
        )

        async def generate_stream():
            """生成流式响应"""
            full_response = ""
            full_thinking = ""
            tool_calls_buffer = []

            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

            try:
                logger.info(
                    f"开始记忆管理模型流式聊天，消息数: {len(messages)}, 工具数: {len(tools)}"
                )
                async for chunk in llm.stream_chat(
                    messages=messages,
                    temperature=agent_config.get("temperature", 0.3),
                    max_tokens=agent_config.get("max_tokens", 4096),
                    tools=tools,
                ):
                    if chunk:
                        if isinstance(chunk, dict):
                            chunk_type = chunk.get("type")
                            if chunk_type == "thinking":
                                thinking_content = chunk.get("content", "")
                                full_thinking += thinking_content
                                yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_content})}\n\n"
                            elif chunk_type == "content":
                                content = chunk.get("content", "")
                                full_response += content
                                yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                            elif chunk_type == "tool_calls":
                                new_tool_calls = chunk.get("tool_calls", [])
                                logger.info(f"检测到工具调用: {new_tool_calls}")
                                tool_calls_buffer.extend(new_tool_calls)
                                for tool_call in new_tool_calls:
                                    yield f"data: {json.dumps({'type': 'tool_call', 'tool_call': tool_call})}\n\n"
                        elif isinstance(chunk, str):
                            full_response += chunk
                            yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"

                if tool_calls_buffer:
                    from server.core.tools.builtin import call_builtin_tool

                    BUILTIN_TOOL_NAMES = {"calculator", "datetime", "random", "json_format"}

                    for tool_call in tool_calls_buffer:
                        tool_name = tool_call.get("name") or tool_call.get("function", {}).get(
                            "name"
                        )
                        tool_args = tool_call.get("arguments") or tool_call.get("function", {}).get(
                            "arguments", "{}"
                        )

                        if isinstance(tool_args, str):
                            try:
                                tool_args = json.loads(tool_args)
                            except json.JSONDecodeError as e:
                                logger.warning(
                                    f"工具参数 JSON 解析失败: {e}, 原始参数: {tool_args}"
                                )
                                try:
                                    import ast

                                    tool_args = ast.literal_eval(tool_args)
                                    if not isinstance(tool_args, dict):
                                        tool_args = {}
                                except Exception:
                                    tool_args = {}

                        yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': tool_name})}\n\n"

                        if tool_name in BUILTIN_TOOL_NAMES:
                            tool_result = call_builtin_tool(tool_name, tool_args or {})
                        else:
                            tool_result = tool_registry.call_tool(tool_name, tool_args)

                        yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'result': tool_result})}\n\n"

                        messages.append(
                            {"role": "assistant", "content": None, "tool_calls": [tool_call]}
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.get("id", ""),
                                "name": tool_name,
                                "content": json.dumps(tool_result, ensure_ascii=False),
                            }
                        )

                    full_response = ""
                    async for chunk in llm.stream_chat(
                        messages=messages,
                        temperature=agent_config.get("temperature", 0.3),
                        max_tokens=agent_config.get("max_tokens", 4096),
                    ):
                        if chunk:
                            if isinstance(chunk, dict):
                                chunk_type = chunk.get("type")
                                if chunk_type == "content":
                                    content = chunk.get("content", "")
                                    full_response += content
                                    yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                                elif chunk_type == "thinking":
                                    thinking_content = chunk.get("content", "")
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_content})}\n\n"
                            elif isinstance(chunk, str):
                                full_response += chunk
                                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"

                if full_response:
                    context_mgr.add_message(
                        session_id=session_id, role="assistant", content=full_response
                    )

                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

            except Exception as e:
                logger.error(f"记忆管理模型流式聊天错误: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
