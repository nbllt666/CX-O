"""CX-O-Autonomy P1-T6 LLM 规划器单测（mock llm_client）。

覆盖：
① 正常返回结构化 action（mock content 为合法 JSON，断言 action/target/payload/
   reason/expected_outcome 逐项）
② JSON 被 markdown 代码块包裹也能解析
③ 非法 action 被改写为 wait（保留原 reason）
④ 解析失败返回 {"action": "wait", "reason": "parse_failed"}
⑤ LLM 抛错返回 {"action": "wait", "reason": "llm_error"}
⑥ 工具调用循环：mock 首轮返回 tool_calls、执行 tool_executor、次轮返回最终
   action（断言 tool_executor 被调用且观察结果进入消息）
⑦ tool_calls 全部轮次仍不收敛时按最终轮文本处理

运行：python -m pytest tests/test_autonomy_planner.py -q
"""
import json

import pytest

from server.autonomy.core.planner.action_planner import ActionPlanner
from server.core.llm.client import LLMResponse


class FakeLLMClient:
    """LLMClient 替身：按顺序返回预设响应，最后一个响应复用作为兜底。"""

    def __init__(self, responses, supports_tools=True):
        self.responses = list(responses)
        self.chat_calls = []
        self.supports_tools = supports_tools

    async def chat(self, messages, stream=False, **kwargs):
        self.chat_calls.append({"messages": messages, "stream": stream, "kwargs": kwargs})
        if len(self.responses) <= 1:
            return self.responses[0]
        return self.responses.pop(0)


class RaisingLLMClient:
    """每次 chat 都抛异常的客户端，用于验证 llm_error 不冒泡。"""

    async def chat(self, messages, stream=False, **kwargs):
        raise RuntimeError("mock llm down")


@pytest.fixture
def context():
    """标准输入上下文：motivations / phase / hotspots / context_snapshot。"""
    return {
        "motivations": {
            "curiosity": 0.7,
            "social_need": 0.5,
            "creative_drive": 0.3,
            "fatigue": 0.1,
        },
        "phase": "active",
        "hotspots": [{"title": "AI 新突破", "link": "http://x", "snippet": "..."}],
        "context_snapshot": {
            "local_time": "2026-08-22 10:00:00",
            "user_online": True,
            "weather": "sunny",
        },
    }


# ================================================================ ① 正常返回结构化 action
class TestNormalAction:
    @pytest.mark.asyncio
    async def test_returns_structured_action(self, context):
        content = json.dumps(
            {
                "action": "search",
                "target": "AI 新闻",
                "payload": {"query": "最新 AI 进展"},
                "reason": "好奇心较高",
                "expected_outcome": "获取新鲜素材",
            },
            ensure_ascii=False,
        )
        client = FakeLLMClient([LLMResponse(content=content, finish_reason="stop")])
        planner = ActionPlanner(llm_client=client)
        result = await planner.plan(context)
        assert result["action"] == "search"
        assert result["target"] == "AI 新闻"
        assert result["payload"] == {"query": "最新 AI 进展"}
        assert result["reason"] == "好奇心较高"
        assert result["expected_outcome"] == "获取新鲜素材"

    @pytest.mark.asyncio
    async def test_missing_fields_filled_with_defaults(self, context):
        """仅给 action 时其余字段补默认值（对齐 schema 的缺省语义）。"""
        client = FakeLLMClient(
            [LLMResponse(content=json.dumps({"action": "wait"}), finish_reason="stop")]
        )
        planner = ActionPlanner(llm_client=client)
        result = await planner.plan(context)
        assert result == {
            "action": "wait",
            "target": "",
            "payload": {},
            "reason": "",
            "expected_outcome": "",
        }


# ================================================================ ② markdown 代码块包裹
class TestMarkdownCodeBlock:
    @pytest.mark.asyncio
    async def test_json_wrapped_in_markdown_codeblock(self, context):
        content = (
            '```json\n{"action": "read_news", "target": "", "payload": {}, '
            '"reason": "了解时事", "expected_outcome": "信息摄入"}\n```'
        )
        client = FakeLLMClient([LLMResponse(content=content, finish_reason="stop")])
        planner = ActionPlanner(llm_client=client)
        result = await planner.plan(context)
        assert result["action"] == "read_news"
        assert result["reason"] == "了解时事"
        assert result["expected_outcome"] == "信息摄入"

    @pytest.mark.asyncio
    async def test_json_with_prefix_suffix_text(self, context):
        """前后缀文本包裹的 JSON 块也能提取。"""
        content = (
            "好的，我的决策如下：\n"
            '{"action": "write_memory", "target": "记忆", "payload": '
            '{"content": "今日见闻"}, "reason": "值得记录", "expected_outcome": "沉淀经验"}\n'
            "以上。"
        )
        client = FakeLLMClient([LLMResponse(content=content, finish_reason="stop")])
        planner = ActionPlanner(llm_client=client)
        result = await planner.plan(context)
        assert result["action"] == "write_memory"
        assert result["payload"] == {"content": "今日见闻"}


# ================================================================ ③ 非法 action 改写为 wait
class TestInvalidAction:
    @pytest.mark.asyncio
    async def test_invalid_action_rewritten_to_wait(self, context):
        content = json.dumps(
            {"action": "delete_content", "reason": "尝试越权行动"},
            ensure_ascii=False,
        )
        client = FakeLLMClient([LLMResponse(content=content, finish_reason="stop")])
        planner = ActionPlanner(llm_client=client)
        result = await planner.plan(context)
        assert result["action"] == "wait"
        assert "delete_content" in result["reason"]
        assert "尝试越权行动" in result["reason"]

    @pytest.mark.asyncio
    async def test_action_not_in_custom_allowed_set_rewritten(self, context):
        """自定义 allowed_actions 不含某 action 时同样改写为 wait。"""
        content = json.dumps({"action": "write_post", "reason": "想发帖"})
        client = FakeLLMClient([LLMResponse(content=content, finish_reason="stop")])
        planner = ActionPlanner(llm_client=client, allowed_actions=["wait", "sleep"])
        result = await planner.plan(context)
        assert result["action"] == "wait"
        assert "write_post" in result["reason"]


# ================================================================ ④ 解析失败 → parse_failed
class TestParseFailed:
    @pytest.mark.asyncio
    async def test_non_json_content_returns_parse_failed(self, context):
        client = FakeLLMClient(
            [LLMResponse(content="抱歉，我无法理解你的请求", finish_reason="stop")]
        )
        planner = ActionPlanner(llm_client=client)
        result = await planner.plan(context)
        assert result == {"action": "wait", "reason": "parse_failed"}

    @pytest.mark.asyncio
    async def test_empty_content_returns_parse_failed(self, context):
        client = FakeLLMClient([LLMResponse(content="", finish_reason="stop")])
        planner = ActionPlanner(llm_client=client)
        result = await planner.plan(context)
        assert result == {"action": "wait", "reason": "parse_failed"}


# ================================================================ ⑤ LLM 抛错 → llm_error
class TestLlmError:
    @pytest.mark.asyncio
    async def test_client_raise_returns_llm_error(self, context):
        planner = ActionPlanner(llm_client=RaisingLLMClient())
        result = await planner.plan(context)
        assert result == {"action": "wait", "reason": "llm_error"}

    @pytest.mark.asyncio
    async def test_response_error_returns_llm_error(self, context):
        """客户端返回 LLMResponse.error 非空（如 HTTP 错误）同样视为 llm_error。"""
        client = FakeLLMClient(
            [LLMResponse(content="", finish_reason="error", error="HTTP 500")]
        )
        planner = ActionPlanner(llm_client=client)
        result = await planner.plan(context)
        assert result == {"action": "wait", "reason": "llm_error"}


# ================================================================ ⑥ 工具调用循环
class TestToolCallLoop:
    @pytest.mark.asyncio
    async def test_executes_tool_then_returns_final_action(self, context):
        tool_calls = [
            {"function": {"name": "action_tool", "arguments": {"query": "热点话题"}}}
        ]
        resp_tool = LLMResponse(content="", finish_reason="tool_calls", tool_calls=tool_calls)
        resp_final = LLMResponse(
            content=json.dumps(
                {
                    "action": "write_post",
                    "target": "动态",
                    "payload": {"draft": "今日热点速递"},
                    "reason": "结合查询结果",
                    "expected_outcome": "引发讨论",
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
        )
        executed = []

        async def tool_executor(name, args):
            executed.append((name, args))
            return {"result": "ok", "items": ["a", "b"]}

        client = FakeLLMClient([resp_tool, resp_final])
        planner = ActionPlanner(llm_client=client, tool_executor=tool_executor)
        result = await planner.plan(context)
        # 工具被执行且收到 (name, arguments)
        assert executed == [("action_tool", {"query": "热点话题"})]
        # 最终决策来自次轮响应
        assert result["action"] == "write_post"
        assert result["payload"] == {"draft": "今日热点速递"}
        # 首轮调用带 tools；次轮消息中已回填 tool 观察结果
        assert "tools" in client.chat_calls[0]["kwargs"]
        second_messages = client.chat_calls[1]["messages"]
        tool_msgs = [m for m in second_messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["name"] == "action_tool"
        assert "result" in tool_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_sync_tool_executor_supported(self, context):
        """同步 tool_executor 同样可用（_maybe_await 兼容）。"""
        tool_calls = [{"function": {"name": "action_tool", "arguments": {}}}]
        resp_tool = LLMResponse(content="", finish_reason="tool_calls", tool_calls=tool_calls)
        resp_final = LLMResponse(
            content=json.dumps({"action": "wait", "reason": "无需行动"}),
            finish_reason="stop",
        )
        executed = []

        def tool_executor(name, args):
            executed.append((name, args))
            return {"ok": True}

        client = FakeLLMClient([resp_tool, resp_final])
        planner = ActionPlanner(llm_client=client, tool_executor=tool_executor)
        result = await planner.plan(context)
        assert executed == [("action_tool", {})]
        assert result["action"] == "wait"


# ================================================================ ⑦ 不收敛时按最终轮文本处理
class TestToolCallNoConvergence:
    @pytest.mark.asyncio
    async def test_max_rounds_exhausted_uses_final_round_text(self, context):
        tool_calls = [{"function": {"name": "action_tool", "arguments": {}}}]
        resp_tool = LLMResponse(content="", finish_reason="tool_calls", tool_calls=tool_calls)
        resp_final = LLMResponse(
            content=json.dumps({"action": "sleep", "reason": "轮次耗尽后收敛"}),
            finish_reason="stop",
        )
        executed = []

        async def tool_executor(name, args):
            executed.append((name, args))
            return {"ok": True}

        # max_tool_rounds=2：前两轮均返回 tool_calls，最终轮文本被解析
        client = FakeLLMClient([resp_tool, resp_tool, resp_final])
        planner = ActionPlanner(
            llm_client=client, tool_executor=tool_executor, max_tool_rounds=2
        )
        result = await planner.plan(context)
        # 工具轮全部跑满（2 次执行）
        assert len(executed) == 2
        # 按最终轮文本（第 3 次 chat）解析
        assert len(client.chat_calls) == 3
        assert result["action"] == "sleep"
        assert result["reason"] == "轮次耗尽后收敛"

    @pytest.mark.asyncio
    async def test_exhausted_with_empty_final_text_returns_parse_failed(self, context):
        """所有轮次 tool_calls 且最终轮无文本时按 parse_failed 兜底。"""
        tool_calls = [{"function": {"name": "action_tool", "arguments": {}}}]
        resp_tool = LLMResponse(content="", finish_reason="tool_calls", tool_calls=tool_calls)
        executed = []

        async def tool_executor(name, args):
            executed.append((name, args))
            return {"ok": True}

        # 每次 chat 都返回 tool_calls（兜底复用最后一个响应）
        client = FakeLLMClient([resp_tool])
        planner = ActionPlanner(
            llm_client=client, tool_executor=tool_executor, max_tool_rounds=2
        )
        result = await planner.plan(context)
        assert len(executed) == 2
        assert result == {"action": "wait", "reason": "parse_failed"}
