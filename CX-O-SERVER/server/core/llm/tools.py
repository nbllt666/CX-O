"""LLM 工具辅助——模型调用场景下的工具定义与消息处理辅助。"""
from typing import Any, Dict, List
import json

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


def _normalize_tool_arguments(arguments: Any) -> Dict:
    """归一化工具调用参数为 dict。

    OpenAI 兼容协议下 ``function.arguments`` 可能是 JSON 字符串而非 dict；
    直接 ``tool.function(**arguments)`` 会退化为 ``str(**kwargs)`` 抛 TypeError。
    复用 registry.parse_tool_args（JSON 解析 + ast.literal_eval 兜底）解析后展开。
    """
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        # 延迟导入避免 server.core.tools 包 __init__ 的重依赖链条进入本模块导入期
        from server.core.tools.registry import parse_tool_args

        return parse_tool_args({"arguments": arguments})
    return {}


class LLMTools:
    """LLM 工具辅助——工具定义格式化、工具调用解析与带工具的对话执行。"""

    def __init__(self, llm_client):
        self.client = llm_client

    def format_tools_for_llm(self, tools: List[Dict]) -> List[Dict]:
        """将内部工具定义格式化为 LLM function calling 所需的 schema 列表。"""
        formatted = []
        for tool in tools:
            formatted.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("parameters", {}),
                    },
                }
            )
        return formatted

    def parse_tool_calls(self, response_message: Dict) -> List[Dict]:
        """从 LLM 响应消息中解析工具调用，标准化为统一的调用结构。

        ``function.arguments`` 为字符串形式的 JSON 时在此解析展开为 dict，
        保证下游 execute_tools 拿到的始终是可直接展开的参数字典。
        """
        tool_calls = response_message.get("tool_calls", [])
        parsed = []

        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                function = tool_call.get("function") or {}
                parsed.append(
                    {
                        "id": tool_call.get("id", ""),
                        "type": tool_call.get("type", "function"),
                        "function": {
                            "name": function.get("name", ""),
                            "arguments": _normalize_tool_arguments(
                                function.get("arguments", {})
                            ),
                        },
                    }
                )

        return parsed

    def create_tool_result_message(self, tool_call_id: str, tool_name: str, result: str) -> Dict:
        """构造工具执行结果消息，回填给 LLM。"""
        return {"role": "tool", "content": result, "tool_call_id": tool_call_id, "name": tool_name}

    async def execute_tools(self, tool_calls: List[Dict], tool_registry) -> List[Dict]:
        """执行一批工具调用，返回对应的工具结果消息列表。"""
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call.get("function", {}).get("name", "")
            # 防御性归一化：即使调用方绕过 parse_tool_calls 直接传入原始响应，
            # 字符串形式 arguments 也不会以 str(**kwargs) TypeError 退化
            arguments = _normalize_tool_arguments(
                tool_call.get("function", {}).get("arguments", {})
            )
            tool_call_id = tool_call.get("id", "")

            # 优先 call_tool_async（支持 async handler）；缺失时回退同步 call_tool（兼容内联/测试注入的 registry）
            call_async = getattr(tool_registry, "call_tool_async", None)
            if call_async is not None:
                result = await call_async(tool_name, arguments)
            else:
                result = tool_registry.call_tool(tool_name, arguments)

            message = self.create_tool_result_message(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                result=json.dumps(result, ensure_ascii=False),
            )

            results.append(message)

        return results

    async def chat_with_tools(
        self, messages: List[Dict], tools: List[Dict], tool_registry, max_iterations: int = 5
    ) -> Dict:
        """循环对话并自动执行工具调用，直至无工具调用或达到最大迭代次数。"""
        current_messages = messages.copy()
        current_messages.append({"role": "system", "content": "请在适当时使用工具调用。"})
        iterations = 0

        while iterations < max_iterations:
            response = await self.client.chat(
                messages=current_messages,
                tools=self.format_tools_for_llm(tools) if tools else None,
            )

            if response.finish_reason == "error":
                return {"content": response.content, "error": "LLM调用失败"}

            response_message = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": response.tool_calls or [],
            }

            tool_calls = self.parse_tool_calls(response_message)

            if not tool_calls:
                return {"content": response.content, "tool_calls": []}

            current_messages.append(response_message)

            tool_results = await self.execute_tools(tool_calls, tool_registry)
            current_messages.extend(tool_results)

            iterations += 1

        return {
            "content": response.content,
            "tool_calls": tool_calls,
            "warning": "达到最大迭代次数",
        }
