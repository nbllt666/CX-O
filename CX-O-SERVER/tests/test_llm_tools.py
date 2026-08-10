"""server.core.llm.tools (LLMTools) 单元测试。

覆盖工具格式化、工具调用解析、结果消息构造、工具执行、带工具的多轮对话。
通过 Mock llm_client 与 tool_registry 隔离外部依赖。

运行：python -m pytest tests/test_llm_tools.py -v
"""
import pytest

from server.core.llm.client import LLMResponse
from server.core.llm.tools import LLMTools


class FakeLLMClient:
    """按脚本返回 LLMResponse 的模拟客户端。"""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    async def chat(self, messages, stream=False, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="", finish_reason="stop")


class FakeToolRegistry:
    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.results.get(name, {"success": True, "result": "ok"})


@pytest.fixture
def tools():
    return LLMTools(llm_client=FakeLLMClient())


# ---------------------------------------------------------------- 格式化
class TestFormatTools:
    def test_basic(self, tools):
        formatted = tools.format_tools_for_llm(
            [{"name": "calc", "description": "计算", "parameters": {"type": "object"}}]
        )
        assert formatted == [
            {
                "type": "function",
                "function": {
                    "name": "calc",
                    "description": "计算",
                    "parameters": {"type": "object"},
                },
            }
        ]

    def test_empty(self, tools):
        assert tools.format_tools_for_llm([]) == []

    def test_missing_parameters_defaults(self, tools):
        formatted = tools.format_tools_for_llm([{"name": "x"}])
        assert formatted[0]["function"]["parameters"] == {}


# ---------------------------------------------------------------- 解析
class TestParseToolCalls:
    def test_parses_standard(self, tools):
        msg = {
            "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "calc", "arguments": {"a": 1}}}
            ]
        }
        parsed = tools.parse_tool_calls(msg)
        assert parsed == [
            {"id": "1", "type": "function", "function": {"name": "calc", "arguments": {"a": 1}}}
        ]

    def test_skips_non_dict(self, tools):
        parsed = tools.parse_tool_calls({"tool_calls": ["not a dict"]})
        assert parsed == []

    def test_empty(self, tools):
        assert tools.parse_tool_calls({}) == []


# ---------------------------------------------------------------- 结果消息
class TestCreateResultMessage:
    def test_basic(self, tools):
        msg = tools.create_tool_result_message("tc1", "calc", "3")
        assert msg == {"role": "tool", "content": "3", "tool_call_id": "tc1", "name": "calc"}


# ---------------------------------------------------------------- 执行工具
class TestExecuteTools:
    @pytest.mark.asyncio
    async def test_executes_and_builds_messages(self):
        registry = FakeToolRegistry({"calc": {"success": True, "result": 3}})
        client = FakeLLMClient()
        tools = LLMTools(llm_client=client)
        tool_calls = [
            {"id": "tc1", "function": {"name": "calc", "arguments": {"a": 1}}}
        ]
        results = await tools.execute_tools(tool_calls, registry)
        assert registry.calls == [("calc", {"a": 1})]
        assert results[0]["role"] == "tool"
        assert '"result": 3' in results[0]["content"]


# ---------------------------------------------------------------- 带工具对话
class TestChatWithTools:
    @pytest.mark.asyncio
    async def test_returns_error_on_llm_failure(self):
        client = FakeLLMClient([LLMResponse(content="", finish_reason="error", error="down")])
        tools = LLMTools(llm_client=client)
        result = await tools.chat_with_tools([{"role": "user", "content": "hi"}], [], FakeToolRegistry())
        assert result["error"] == "LLM调用失败"

    @pytest.mark.asyncio
    async def test_returns_content_when_no_tool_calls(self):
        client = FakeLLMClient([LLMResponse(content="直接回答", finish_reason="stop")])
        tools = LLMTools(llm_client=client)
        result = await tools.chat_with_tools(
            [{"role": "user", "content": "hi"}], [], FakeToolRegistry()
        )
        assert result["content"] == "直接回答"
        assert result["tool_calls"] == []

    @pytest.mark.asyncio
    async def test_executes_tool_calls_and_loops(self):
        """带工具调用时应执行工具并进入下一轮。"""
        client = FakeLLMClient(
            [
                LLMResponse(
                    content="",
                    finish_reason="stop",
                    tool_calls=[
                        {"id": "tc1", "function": {"name": "calc", "arguments": {"a": 1}}}
                    ],
                ),
                LLMResponse(content="结果是3", finish_reason="stop"),
            ]
        )
        registry = FakeToolRegistry({"calc": {"success": True, "result": 3}})
        tools = LLMTools(llm_client=client)
        result = await tools.chat_with_tools(
            [{"role": "user", "content": "算一下"}],
            [{"name": "calc", "description": "计算"}],
            registry,
        )
        assert result["content"] == "结果是3"
        assert registry.calls == [("calc", {"a": 1})]
        # 第二轮消息应包含第一轮工具结果
        assert any("tool" in m.get("role", "") for m in client.calls[1]["messages"])

    @pytest.mark.asyncio
    async def test_max_iterations_warning(self):
        """一直返回工具调用时达到最大迭代次数并告警。"""
        tool_call_resp = LLMResponse(
            content="",
            finish_reason="stop",
            tool_calls=[{"id": "tc", "function": {"name": "calc", "arguments": {}}}],
        )
        client = FakeLLMClient(responses=[tool_call_resp] * 10)
        registry = FakeToolRegistry({"calc": {"success": True, "result": 1}})
        tools = LLMTools(llm_client=client)
        result = await tools.chat_with_tools(
            [{"role": "user", "content": "hi"}],
            [{"name": "calc", "description": "计算"}],
            registry,
        )
        assert result["warning"] == "达到最大迭代次数"
        # 默认 max_iterations=5
        assert len(registry.calls) == 5