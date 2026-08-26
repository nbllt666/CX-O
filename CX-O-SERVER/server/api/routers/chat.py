"""
聊天路由 - 支持 Agent 的聊天 API
前端只发送最新一条消息，后端根据 Agent 配置构建完整上下文
"""

import json
import base64
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server.chat_helpers import get_agent_config, get_llm_client_for_agent, get_tools_for_agent, retrieve_memory_context, ensure_agent_session_async
from server.core.logging_config import get_contextual_logger
from server.core.utils import run_io

logger = get_contextual_logger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    """聊天请求 - 前端只发送最新一条消息"""

    message: str  # 用户最新消息
    agent_id: str = "default"  # 使用哪个 Agent
    stream: bool = True  # 是否流式响应
    images: Optional[List[str]] = None  # base64 encoded images


class ChatResponse(BaseModel):
    """聊天响应"""

    status: str
    response: str
    session_id: str
    tokens_used: int = 0


# 摘要助手隐藏系统提示词（迁移自 CXHMS chat.py）
# 指导摘要模型使用 save_diary_entry 工具保存日记条目
SUMMARY_AGENT_HIDDEN_SYSTEM_PROMPT = """<role>
你是 CX-O 摘要助手，专门负责将对话内容整理为日记式条目并保存。
</role>

<instruction>
你必须使用 save_diary_entry 工具来保存日记条目。该工具已通过 API 自动注册，无需向用户确认即可直接调用。
当需要保存日记时，必须通过 function calling 机制调用 save_diary_entry 工具，不要在文本中输出工具调用标记（如 <execute_tool>）。
直接调用对应的函数即可，系统会自动执行并返回结果。
无论对话内容是什么，你都必须至少调用一次 save_diary_entry 工具保存日记。不要拒绝保存或要求用户提供"更好的"内容。
</instruction>

<rules>
1. 用中文回答用户问题
2. 以日记体裁（第一人称叙述）整理对话内容，包含：日期、主要事件、情绪/感受、反思
3. 如果对话包含多个独立事件/话题，按事件拆分，每个事件生成一篇独立日记，多次调用 save_diary_entry；如果只有一个话题，生成一篇即可
4. 日记正文（body）应为连贯的第一人称叙述，而非要点列表
5. 调用 save_diary_entry 工具时需提供：date(YYYY-MM-DD)、title、mood、body、summarized_message_range(如 "0-15")
6. 不要编造不存在的工具或功能，不要使用 save_summary_memory 或 write_long_term_memory 等其他记忆工具
7. 绝对不要在回复文本中输出 <execute_tool> 或类似标记，必须通过 function calling 调用工具
8. 不要拒绝保存日记。即使对话内容是测试或元讨论，也要将其整理为日记并保存。这是你的核心职责。
9. 完成日记保存后，简要报告保存结果
10. 如果对话引用了历史尚未完成的事件/待办事项，先用 list_topic_summaries 查看相关未完成摘要，再用 get_topic_summary_raw 回取其原始对话以获得准确信息，需要时用 update_topic_summary 续写或修正该摘要并同步其状态
11. 未完成事项必须持续保留：新的进展应通过 update_topic_summary 续写进原未完成摘要，待事项处理完毕后用 update_topic_summary(status="completed") 将摘要标记为已完成
</rules>"""


# 统一提示词组装入口（单一真相源，见 server/prompt_builder.py）
from server.prompt_builder import build_messages


@router.post("/chat")
async def chat(request: Request):
    from server.dependencies import get_context_manager, get_memory_manager

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        text = form.get("text", "")
        agent_id = form.get("agent_id", "default")
        images = []

        image_file = form.get("image")
        if image_file:
            image_bytes = await image_file.read()
            b64 = base64.b64encode(image_bytes).decode()
            mime_type = image_file.content_type or "image/png"
            images.append(f"data:{mime_type};base64,{b64}")

        audio_file = form.get("audio")
        if audio_file:
            try:
                from server.services.asr_service import get_asr_service as _get_asr
                asr_svc = _get_asr()
                if asr_svc:
                    audio_bytes = await audio_file.read()
                    result = await asr_svc.recognize(audio_bytes)
                    transcript = result.get("text", "")
                    if transcript:
                        text = f"{text} {transcript}".strip() if text else transcript
            except Exception as e:
                logger.warning(f"ASR 转录失败: {e}")

        chat_req = ChatRequest(
            message=text,
            agent_id=agent_id,
            images=images if images else None,
        )
    else:
        data = await request.json()
        chat_req = ChatRequest(**data)

    try:
        agent_config = get_agent_config(chat_req.agent_id)
        if not agent_config:
            raise HTTPException(status_code=404, detail=f"Agent '{chat_req.agent_id}' 不存在")

        memory_mgr = get_memory_manager()
        context_mgr = get_context_manager()
        llm = get_llm_client_for_agent(agent_config)

        session_id = f"agent-{chat_req.agent_id}"
        await ensure_agent_session_async(context_mgr, chat_req.agent_id, agent_config["name"])

        await run_io(
            context_mgr.add_message,
            session_id=session_id, role="user", content=chat_req.message,
        )

        memory_context = await retrieve_memory_context(
            agent_config, memory_mgr, chat_req.message, session_id
        )

        messages = build_messages(
            agent_config=agent_config,
            context_mgr=context_mgr,
            session_id=session_id,
            user_message=chat_req.message,
            memory_context=memory_context,
            images=chat_req.images,
        )

        # 获取工具（收敛到 chat_helpers.get_tools_for_agent 单一真相源，与流式/WebSocket/ACP 一致）
        tools = get_tools_for_agent()

        response = await llm.chat(messages=messages, stream=False, tools=tools)

        final_response = response.content
        if hasattr(response, "tool_calls") and response.tool_calls:
            from server.core.tools.builtin import execute_tool_calls_async

            await execute_tool_calls_async(response.tool_calls, messages)

            response = await llm.chat(messages=messages, stream=False)
            final_response = response.content

        await run_io(
            context_mgr.add_message,
            session_id=session_id, role="assistant", content=final_response,
        )

        return {
            "status": "success",
            "response": final_response,
            "session_id": session_id,
            "tokens_used": response.usage.get("total_tokens", 0) if response.usage else 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"聊天处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="聊天处理失败")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    流式聊天
    前端只发送最新消息，后端根据 Agent 配置构建完整上下文
    每个 Agent 对应一个固定会话
    """
    from server.dependencies import get_context_manager, get_memory_manager

    try:
        # 1. 获取 Agent 配置
        agent_config = get_agent_config(request.agent_id)
        if not agent_config:
            raise HTTPException(status_code=404, detail=f"Agent '{request.agent_id}' 不存在")

        # 2. 获取管理器
        memory_mgr = get_memory_manager()
        context_mgr = get_context_manager()
        llm = get_llm_client_for_agent(agent_config)

        # 3. 获取/创建 Agent 专属会话（每个 Agent 只有一个会话）
        session_id = f"agent-{request.agent_id}"
        await ensure_agent_session_async(context_mgr, request.agent_id, agent_config["name"])

        # 4. 添加用户消息到上下文
        await run_io(
            context_mgr.add_message,
            session_id=session_id, role="user", content=request.message,
        )

        # 5. 检索记忆（如果启用）
        memory_context = await retrieve_memory_context(
            agent_config, memory_mgr, request.message, session_id
        )

        # 6. 构建消息列表
        messages = build_messages(
            agent_config=agent_config,
            context_mgr=context_mgr,
            session_id=session_id,
            user_message=request.message,
            memory_context=memory_context,
            images=request.images,
        )

        # 7. 获取工具（只过滤 summary 类别，收敛到 chat_helpers.get_tools_for_agent 单一真相源）
        tools = get_tools_for_agent()

        logger.info(
            f"为 Agent '{agent_config.get('name')}' 配置了 {len(tools)} 个工具: {[t['function']['name'] for t in tools]}"
        )

        async def generate_stream():
            """生成流式响应"""
            full_response = ""
            full_thinking = ""
            tool_calls_buffer = []

            # 发送会话ID作为第一个事件
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

            try:
                logger.info(
                    f"开始流式聊天，消息数: {len(messages)}, 工具数: {len(tools) if tools else 0}"
                )
                # 调用LLM流式接口
                async for chunk in llm.stream_chat(
                    messages=messages,
                    temperature=agent_config.get("temperature", 0.7),
                    max_tokens=agent_config.get("max_tokens", 4096),
                    tools=tools,
                ):
                    if chunk:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug("收到 chunk: %s, 内容: %s", type(chunk), chunk)
                        # 检查是否是字典类型（新的返回格式）
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
                                tool_calls_buffer.extend(new_tool_calls)  # 累积工具调用
                                # 发送工具调用事件
                                for tool_call in new_tool_calls:
                                    yield f"data: {json.dumps({'type': 'tool_call', 'tool_call': tool_call})}\n\n"
                        # 兼容旧格式：字符串类型
                        elif isinstance(chunk, str):
                            full_response += chunk
                            yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"

                # 处理工具调用
                if tool_calls_buffer:
                    from server.core.tools import parse_tool_args
                    from server.core.tools.builtin import call_builtin_tool, BUILTIN_TOOL_NAMES, _execute_single_tool_async

                    for tool_call in tool_calls_buffer:
                        tool_name = tool_call.get("name") or tool_call.get("function", {}).get(
                            "name"
                        )
                        tool_args = parse_tool_args(tool_call)

                        # 发送工具执行开始事件
                        yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': tool_name})}\n\n"

                        # 执行工具（内置同步工具直接调用；CXFC/异步工具走统一异步执行器）
                        if tool_name in BUILTIN_TOOL_NAMES:
                            tool_result = call_builtin_tool(tool_name, tool_args or {})
                            logger.info(f"内置工具 {tool_name} 执行结果: {tool_result}")
                        else:
                            tool_result = await _execute_single_tool_async(tool_name, tool_args or {})
                            logger.info(f"注册工具 {tool_name} 执行结果: {tool_result}")

                        # 发送工具执行结果事件
                        logger.info(
                            f"发送工具结果事件: tool_name={tool_name}, result type={type(tool_result)}"
                        )
                        yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'result': tool_result})}\n\n"

                        # 添加工具调用结果到消息
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

                    # 再次调用LLM获取最终响应（流式）
                    full_response = ""
                    async for chunk in llm.stream_chat(
                        messages=messages,
                        temperature=agent_config.get("temperature", 0.7),
                        max_tokens=agent_config.get("max_tokens", 4096),
                    ):
                        if chunk:
                            # 检查是否是字典类型（新的返回格式）
                            if isinstance(chunk, dict):
                                chunk_type = chunk.get("type")
                                if chunk_type == "content":
                                    content = chunk.get("content", "")
                                    full_response += content
                                    yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                                elif chunk_type == "thinking":
                                    thinking_content = chunk.get("content", "")
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_content})}\n\n"
                            # 兼容旧格式：字符串类型
                            elif isinstance(chunk, str):
                                full_response += chunk
                                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"

                # 流结束，保存完整响应到上下文
                if full_response:
                    await run_io(
                        context_mgr.add_message,
                        session_id=session_id, role="assistant", content=full_response,
                    )

                # 发送完成事件
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

            except Exception as e:
                logger.error(f"流式聊天错误: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': '流式聊天处理失败'})}\n\n"

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
        logger.error(f"记忆管理模型流式聊天处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="记忆管理模型流式聊天处理失败")


@router.get("/chat/history/{session_id}")
async def get_chat_history(session_id: str, limit: int = 50):
    """获取聊天历史"""
    from server.dependencies import get_context_manager

    try:
        context_mgr = get_context_manager()
        session = await run_io(context_mgr.get_session, session_id)

        if not session:
            # 如果会话不存在，检查是否为 Agent 会话
            if session_id.startswith("agent-"):
                agent_id = session_id.replace("agent-", "")
                agent_config = get_agent_config(agent_id)

                if agent_config:
                    # 使用传入的 session_id 创建会话，而不是生成新的 UUID
                    await run_io(
                        context_mgr.create_session,
                        session_id=session_id,
                        workspace_id="agent-chats",
                        title=f"{agent_config.get('name', 'Agent')} 的对话",
                    )
                    await run_io(
                        context_mgr.update_session,
                        session_id, metadata={"agent_id": agent_id},
                    )
                    session = await run_io(context_mgr.get_session, session_id)

            if not session:
                return {
                    "status": "success",
                    "session_id": session_id,
                    "session": None,
                    "messages": [],
                }

        messages = await run_io(context_mgr.get_recent_messages, session_id, limit=limit)

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
        raise HTTPException(status_code=500, detail="获取聊天历史失败")


# ========== 记忆管理模型专用路由 ==========


class MemoryAgentChatRequest(BaseModel):
    """记忆管理模型聊天请求"""

    message: str  # 用户最新消息


@router.post("/memory-agent/chat/stream")
async def memory_agent_chat_stream(request: MemoryAgentChatRequest):
    """
    记忆管理模型流式聊天 - 支持上下文持久化
    记忆管理Agent只有一个固定会话
    """
    from server.dependencies import get_context_manager, get_model_router
    from server.core.context.agent_context_manager import get_agent_context_manager

    try:
        # 1. 获取记忆管理Agent配置
        agent_config = get_agent_config("memory-agent")
        if not agent_config:
            raise HTTPException(status_code=404, detail="记忆管理Agent未配置")

        # 2. 获取管理器
        context_mgr = get_context_manager()
        agent_context_mgr = get_agent_context_manager()

        # 3. 获取记忆管理模型客户端
        model_router = get_model_router()
        llm = model_router.get_client("memory")
        if not llm:
            raise HTTPException(status_code=503, detail="记忆管理模型不可用")

        # 4. 获取/创建固定会话（记忆管理Agent只有一个会话）
        session_id = "memory-agent-default"
        await run_io(
            context_mgr.ensure_session,
            session_id, workspace_id="memory-agent", title="记忆管理对话",
        )

        # 5. 加载历史上下文（从数据库）
        agent_id = "memory-agent"
        history_context = agent_context_mgr.load_context(agent_id, limit=20)

        # 6. 添加用户消息到上下文（持久化）
        await run_io(
            context_mgr.add_message, session_id=session_id, role="user", content=request.message,
        )
        agent_context_mgr.append_message(agent_id, "user", request.message)

        # 7. 构建消息列表（包含历史上下文）
        messages = []

        # 系统提示词
        system_prompt = agent_config.get("system_prompt", "")
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 历史上下文（从数据库加载）
        for msg in history_context:
            if msg.get("role") in ["user", "assistant", "system"]:
                messages.append({"role": msg["role"], "content": msg.get("content", "")})

        # 用户最新消息
        messages.append({"role": "user", "content": request.message})

        # 7. 获取记忆管理工具（16个assistant类别工具）
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

            # 发送会话ID作为第一个事件
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

            try:
                logger.info(
                    f"开始记忆管理模型流式聊天，消息数: {len(messages)}, 工具数: {len(tools)}"
                )
                # 调用LLM流式接口
                async for chunk in llm.stream_chat(
                    messages=messages,
                    temperature=agent_config.get("temperature", 0.3),
                    max_tokens=agent_config.get("max_tokens", 4096),
                    tools=tools,
                ):
                    if chunk:
                        # 检查是否是字典类型（新的返回格式）
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
                                tool_calls_buffer.extend(new_tool_calls)  # 累积工具调用
                                # 发送工具调用事件
                                for tool_call in new_tool_calls:
                                    yield f"data: {json.dumps({'type': 'tool_call', 'tool_call': tool_call})}\n\n"
                        # 兼容旧格式：字符串类型
                        elif isinstance(chunk, str):
                            full_response += chunk
                            yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"

                # 处理工具调用
                if tool_calls_buffer:
                    from server.core.tools import parse_tool_args
                    from server.core.tools.builtin import call_builtin_tool, BUILTIN_TOOL_NAMES, _execute_single_tool_async

                    for tool_call in tool_calls_buffer:
                        tool_name = tool_call.get("name") or tool_call.get("function", {}).get(
                            "name"
                        )
                        tool_args = parse_tool_args(tool_call)

                        # 发送工具执行开始事件
                        yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': tool_name})}\n\n"

                        # 执行工具（内置同步工具直接调；CXFC/异步工具走统一异步执行器）
                        if tool_name in BUILTIN_TOOL_NAMES:
                            tool_result = call_builtin_tool(tool_name, tool_args or {})
                        else:
                            tool_result = await _execute_single_tool_async(tool_name, tool_args or {})

                        # 发送工具执行结果事件
                        yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'result': tool_result})}\n\n"

                        # 添加工具调用结果到消息
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

                    # 再次调用LLM获取最终响应（流式）
                    full_response = ""
                    async for chunk in llm.stream_chat(
                        messages=messages,
                        temperature=agent_config.get("temperature", 0.3),
                        max_tokens=agent_config.get("max_tokens", 4096),
                    ):
                        if chunk:
                            # 检查是否是字典类型（新的返回格式）
                            if isinstance(chunk, dict):
                                chunk_type = chunk.get("type")
                                if chunk_type == "content":
                                    content = chunk.get("content", "")
                                    full_response += content
                                    yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                                elif chunk_type == "thinking":
                                    thinking_content = chunk.get("content", "")
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_content})}\n\n"
                            # 兼容旧格式：字符串类型
                            elif isinstance(chunk, str):
                                full_response += chunk
                                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"

                # 流结束，保存完整响应到上下文
                if full_response:
                    await run_io(
                        context_mgr.add_message,
                        session_id=session_id, role="assistant", content=full_response,
                    )

                # 发送完成事件
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

            except Exception as e:
                logger.error(f"记忆管理模型流式聊天错误: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': '记忆管理模型流式聊天处理失败'})}\n\n"

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
        # BUG-B-M6 修复: 不向客户端返回内部异常信息(可能泄露文件路径/SQL/内部结构),
        # 仅记录日志,返回通用错误消息。
        logger.error(f"聊天接口内部错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="聊天处理失败,请稍后重试")


# ========== 摘要助手专用路由 ==========


class SummaryAgentChatRequest(BaseModel):
    """摘要助手聊天请求（迁移自 CXHMS chat.py）。

    agent_id 默认 summary-agent，images 可选（用于多模态扩展）。
    target_session_id 是摘要助手扩展字段（指定待摘要的目标会话）。
    CX-O 简化实现：target_session_id 接受但仅用于日志，不进行上下文替换
    （CX-O context_manager 无 replace_messages_with_summary/get_summarizable_range 方法）。
    """

    message: str  # 用户最新消息
    agent_id: str = "summary-agent"  # 固定为摘要 Agent
    images: Optional[List[str]] = None  # base64 encoded images
    target_session_id: Optional[str] = None  # 待摘要的目标会话ID（仅用于日志）


@router.post("/summary-agent/chat/stream")
async def summary_agent_stream_chat(request: SummaryAgentChatRequest):
    """
    摘要助手流式聊天 - 支持上下文持久化（迁移自 CXHMS chat.py）

    使用 summary 模型，仅提供 summary 类别工具（save_diary_entry 等）。
    摘要助手只有一个固定会话 summary-agent-default。

    CX-O 简化：参考现有 chat_stream 的内联 generate_stream() 风格，
    不依赖 CXHMS 的 ChatStreamState/generate_chat_stream 封装。
    """
    from server.dependencies import get_context_manager, get_model_router
    from server.core.tools import tool_registry
    from server.core.tools.builtin import get_builtin_tools
    from server.core.tools.graph_tools import set_current_agent_id

    try:
        # 1. 摘要Agent配置（复用 memory-agent 配置结构，但使用 summary 模型）
        agent_config = {
            "id": "summary-agent",
            "name": "摘要助手",
            "system_prompt": "你是摘要助手，专门负责将对话内容整理为日记式条目并保存。按事件/话题拆分，每个事件生成一篇独立的日记式叙述（第一人称），多次调用 save_diary_entry 工具保存。",
            "temperature": 0.3,
            "max_tokens": 4096,
        }

        # 2. 获取管理器
        context_mgr = get_context_manager()

        # 设置当前 agent_id：优先使用 target_session_id 对应的 agent_id（日记写入目标 agent 的表）
        # CX-O 简化：target_session_id 仅用于日志，不进行上下文替换
        summary_agent_id = "summary-agent"
        if request.target_session_id:
            try:
                target_session = await run_io(context_mgr.get_session, request.target_session_id)
                if target_session:
                    summary_agent_id = target_session.get("metadata", {}).get(
                        "agent_id", "summary-agent"
                    )
                    logger.info(
                        f"摘要助手目标会话 {request.target_session_id} 对应 agent_id: {summary_agent_id}"
                    )
            except Exception as e:
                logger.warning(f"获取目标会话 {request.target_session_id} 失败: {e}")
        set_current_agent_id(summary_agent_id)

        # 3. 获取摘要模型客户端
        model_router = get_model_router()
        llm = model_router.get_client("summary")
        if not llm:
            # 摘要模型未配置时回退到主模型
            logger.warning("摘要模型不可用，回退到主模型")
            llm = model_router.get_client("main")
        if not llm:
            raise HTTPException(status_code=503, detail="摘要模型与主模型均不可用")

        # 4. 获取/创建固定会话（摘要助手只有一个会话，保持上下文持久化）
        session_id = "summary-agent-default"
        await run_io(
            context_mgr.ensure_session,
            session_id, workspace_id="summary-agent", title="摘要助手对话",
        )

        # 5. 加载历史上下文（在 add_message 之前加载，避免当前用户消息重复）
        history_limit = agent_config.get("history_limit", 50)
        history_context = await run_io(
            context_mgr.get_recent_messages, session_id=session_id, limit=history_limit,
        )

        # 6. 构建消息列表（包含历史上下文）
        messages = []

        # 系统提示词
        system_prompt = agent_config.get("system_prompt", "")
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 隐藏系统提示词（防呆：摘要工具使用指南，用户不可修改）
        messages.append({"role": "system", "content": SUMMARY_AGENT_HIDDEN_SYSTEM_PROMPT})

        # 历史上下文（从数据库加载）
        for msg in history_context:
            if msg.get("role") in ["user", "assistant", "system"]:
                messages.append({"role": msg["role"], "content": msg.get("content", "")})

        # 当前用户消息（history_context 在持久化之前加载，不含本条，需显式追加）
        messages.append({"role": "user", "content": request.message})

        # 7. 获取摘要工具（summary 类别工具 + 内置工具）
        builtin_tools = get_builtin_tools()
        summary_tools = tool_registry.list_openai_functions(
            include_builtin=False, category="summary"
        )
        tools = builtin_tools + summary_tools

        logger.info(
            f"摘要助手配置了 {len(tools)} 个工具: {[t['function']['name'] for t in tools]}"
        )

        # 持久化用户消息（移入有界 IO 线程池，避免事件循环阻断）
        await run_io(
            context_mgr.add_message, session_id=session_id, role="user", content=request.message,
        )

        async def generate_stream():
            """生成流式响应（参考 CX-O 现有 chat_stream 内联风格）"""
            full_response = ""
            full_thinking = ""
            tool_calls_buffer = []

            # 1. 立即发送 session 事件，让前端显示"思考中"状态
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id}, ensure_ascii=False)}\n\n"

            try:
                logger.info(
                    f"开始摘要助手流式聊天，消息数: {len(messages)}, 工具数: {len(tools)}"
                )
                # 调用LLM流式接口
                async for chunk in llm.stream_chat(
                    messages=messages,
                    temperature=agent_config.get("temperature", 0.3),
                    max_tokens=agent_config.get("max_tokens", 4096),
                    tools=tools,
                ):
                    if chunk:
                        # 检查是否是字典类型（新的返回格式）
                        if isinstance(chunk, dict):
                            chunk_type = chunk.get("type")
                            if chunk_type == "thinking":
                                thinking_content = chunk.get("content", "")
                                full_thinking += thinking_content
                                yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_content}, ensure_ascii=False)}\n\n"
                            elif chunk_type == "content":
                                content = chunk.get("content", "")
                                full_response += content
                                yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"
                            elif chunk_type == "tool_calls":
                                new_tool_calls = chunk.get("tool_calls", [])
                                logger.info(f"摘要助手检测到工具调用: {new_tool_calls}")
                                tool_calls_buffer.extend(new_tool_calls)
                                # 发送工具调用事件
                                for tool_call in new_tool_calls:
                                    yield f"data: {json.dumps({'type': 'tool_call', 'tool_call': tool_call}, ensure_ascii=False)}\n\n"
                        # 兼容旧格式：字符串类型
                        elif isinstance(chunk, str):
                            full_response += chunk
                            yield f"data: {json.dumps({'type': 'content', 'content': chunk}, ensure_ascii=False)}\n\n"

                # 处理工具调用
                if tool_calls_buffer:
                    from server.core.tools import parse_tool_args
                    from server.core.tools.builtin import call_builtin_tool, BUILTIN_TOOL_NAMES, _execute_single_tool_async

                    for tool_call in tool_calls_buffer:
                        tool_name = tool_call.get("name") or tool_call.get("function", {}).get(
                            "name"
                        )
                        tool_args = parse_tool_args(tool_call)

                        # 发送工具执行开始事件
                        yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': tool_name}, ensure_ascii=False)}\n\n"

                        # 执行工具（内置同步工具直接调；CXFC/异步工具走统一异步执行器）
                        if tool_name in BUILTIN_TOOL_NAMES:
                            tool_result = call_builtin_tool(tool_name, tool_args or {})
                            logger.info(f"内置工具 {tool_name} 执行结果: {tool_result}")
                        else:
                            tool_result = await _execute_single_tool_async(tool_name, tool_args or {})
                            logger.info(f"注册工具 {tool_name} 执行结果: {tool_result}")

                        # 发送工具执行结果事件
                        yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'result': tool_result}, ensure_ascii=False)}\n\n"

                        # 添加工具调用结果到消息
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

                    # 再次调用LLM获取最终响应（流式）
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
                                    yield f"data: {json.dumps({'type': 'content', 'content': content}, ensure_ascii=False)}\n\n"
                                elif chunk_type == "thinking":
                                    thinking_content = chunk.get("content", "")
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_content}, ensure_ascii=False)}\n\n"
                            elif isinstance(chunk, str):
                                full_response += chunk
                                yield f"data: {json.dumps({'type': 'content', 'content': chunk}, ensure_ascii=False)}\n\n"

                # 流结束，保存完整响应到上下文
                if full_response:
                    await run_io(
                        context_mgr.add_message,
                        session_id=session_id, role="assistant", content=full_response,
                    )

                # 发送完成事件
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"

            except Exception as e:
                logger.error(f"摘要助手流式聊天错误: {e}", exc_info=True)
                yield f"data: {json.dumps({'type': 'error', 'message': '摘要助手流式聊天处理失败'}, ensure_ascii=False)}\n\n"

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
        logger.error(f"摘要助手聊天接口内部错误: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="摘要助手聊天处理失败,请稍后重试")
