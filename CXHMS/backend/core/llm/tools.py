from typing import Any, Dict, List

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class LLMTools:
    def __init__(self, llm_client):
        self.client = llm_client

    def format_tools_for_llm(self, tools: List[Dict]) -> List[Dict]:
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
        tool_calls = response_message.get("tool_calls", [])
        parsed = []

        for tool_call in tool_calls:
            if isinstance(tool_call, dict):
                parsed.append(
                    {
                        "id": tool_call.get("id", ""),
                        "type": tool_call.get("type", "function"),
                        "function": {
                            "name": tool_call.get("function", {}).get("name", ""),
                            "arguments": tool_call.get("function", {}).get("arguments", {}),
                        },
                    }
                )

        return parsed

    def create_tool_result_message(self, tool_call_id: str, tool_name: str, result: str) -> Dict:
        return {"role": "tool", "content": result, "tool_call_id": tool_call_id, "name": tool_name}

    async def execute_tools(self, tool_calls: List[Dict], tool_registry) -> List[Dict]:
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call.get("function", {}).get("name", "")
            arguments = tool_call.get("function", {}).get("arguments", {})
            tool_call_id = tool_call.get("id", "")

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
        current_messages = messages.copy()
        iterations = 0

        while iterations < max_iterations:
            response = await self.client.chat(
                messages=current_messages
                + [{"role": "system", "content": "请在适当时使用工具调用。"}],
                tools=self.format_tools_for_llm(tools) if tools else None,
            )

            if response.finish_reason == "error":
                return {"content": response.content, "error": "LLM调用失败"}

            response_message = {"role": "assistant", "content": response.content}

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


import json
