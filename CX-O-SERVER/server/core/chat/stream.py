"""
server/core/chat/stream.py
==========================
CX-O 流式聊天管线（含工具调用循环）。

供后台/非后端传输场景复用（当前唯一消费方：ACP 自动回复）。
对外契约：
  - ``ChatStreamState``：聚合状态对象（accumulated_response / tool_calls / ...）
  - ``generate_chat_stream(...)``：异步生成器，逐步产出内容 chunk，
    并把聚合结果写入传入的 ``state``。

设计要点：
  - 与 ``server.handlers.chat`` 的工具调用循环语义一致：内置工具 + 注册表工具，
    工具调用后的二次生成不再注入工具列表。
  - 产出 chunk 格式与 ``server.core.llm.client`` 的 ``stream_chat`` 一致：
    {"type": "content"|"thinking"|"tool_calls"|"error", ...} 或裸 str（兼容）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)

# 工具调用最大轮数（防止 LLM 无限循环调用工具）
MAX_TOOL_ROUNDS = 5


@dataclass
class ChatStreamState:
    """流式聊天聚合状态。"""

    accumulated_response: str = ""
    thinking: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    chunk_count: int = 0
    llm_rounds: int = 0
    done: bool = False


async def generate_chat_stream(
    llm: Any,
    messages: List[Dict[str, Any]],
    agent_config: Dict[str, Any],
    tools: Optional[List[Dict[str, Any]]] = None,
    session_id: Optional[str] = None,
    state: Optional[ChatStreamState] = None,
    is_background: bool = False,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
) -> AsyncIterator[Dict[str, Any]]:
    """流式聊天管线（含工具调用循环），逐步产出内容 chunk。

    参数语义与 ``server.handlers.chat`` 的流式聊天一致：
      - ``llm``：具备 ``stream_chat`` 的客户端（如 OllamaClient）。
      - ``messages``：可变列表，工具调用结果会就地追加。
      - ``agent_config``：含 temperature / max_tokens。
      - ``tools``：首轮注入的工具列表；工具调用后的二次生成不再注入。
      - ``state``：聚合状态（缺省自建），调用后可读取 accumulated_response / tool_calls。
      - ``session_id``：保留参数，供调用方标记会话（本实现不依赖）。
      - ``is_background``：后台场景异常不打印堆栈。
    """
    state = state or ChatStreamState()
    temperature = agent_config.get("temperature", 0.7)
    max_tokens = agent_config.get("max_tokens", 4096)

    for _ in range(max_tool_rounds):
        state.llm_rounds += 1
        # 工具调用后的二次生成不再注入工具（与 handlers.chat 语义一致）
        round_tools = tools if state.llm_rounds == 1 else None
        tool_calls_buffer: List[Dict[str, Any]] = []

        try:
            async for chunk in llm.stream_chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=round_tools,
            ):
                if not chunk:
                    continue
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type")
                    if chunk_type == "content":
                        content = chunk.get("content", "")
                        state.accumulated_response += content
                        state.chunk_count += 1
                        yield {"type": "content", "content": content}
                    elif chunk_type == "thinking":
                        state.thinking += chunk.get("content", "")
                    elif chunk_type == "tool_calls":
                        tool_calls_buffer.extend(chunk.get("tool_calls", []))
                    elif chunk_type == "error":
                        yield chunk
                elif isinstance(chunk, str):
                    state.accumulated_response += chunk
                    state.chunk_count += 1
                    yield {"type": "content", "content": chunk}
        except Exception as e:
            logger.error(
                f"流式聊天失败: {e}", exc_info=not is_background
            )
            yield {"type": "error", "content": str(e)}
            break

        if not tool_calls_buffer:
            break

        state.tool_calls.extend(tool_calls_buffer)
        from server.core.tools.builtin import execute_tool_calls

        execute_tool_calls(tool_calls_buffer, messages)

    state.done = True
