"""
tests/test_prompt_builder.py
============================
统一提示词组装模块（server.prompt_builder）单元测试。

覆盖：
  - 非实时 main / summary / assistant 模型类型的隐藏提示词注入
  - 实时语音瘦身分支（f5 / orpheus voice_prompt + 最近 2 轮对话）
  - history 透传（AnythingLLM 兼容路径）
  - include_hidden_prompts=False 最小化行为
  - 记忆上下文注入
  - 多模态图像组装
  - hidden_prompt.yaml 键完整性（防漂移守卫）
"""
from __future__ import annotations

import sys
from pathlib import Path

# 项目根（CX-O-SERVER）加入 sys.path，保证 import server.*
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from server.prompt_builder import (  # noqa: E402
    REALTIME_VOICE_HISTORY_LIMIT,
    build_messages,
)


class _FakeContextMgr:
    """最小上下文管理器：模拟真实 ContextManager 的 count+offset 语义。"""

    def __init__(self, history):
        self._history = history

    def get_message_count(self, session_id):
        return len(self._history)

    def get_messages(self, session_id, limit=None, offset=0):
        if limit is None:
            return self._history[offset:]
        return self._history[offset:offset + limit]


_AGENT = {
    "system_prompt": "你是测试人设",
    "model": "main",
    "use_memory": True,
    "vision_enabled": True,
}

_HISTORY = [
    {"role": "user", "content": "u1"},
    {"role": "assistant", "content": "a1"},
    {"role": "user", "content": "u2"},
    {"role": "assistant", "content": "a2"},
    {"role": "user", "content": "u3"},
]


def _roles(messages):
    return [m["role"] for m in messages]


def _contents(messages):
    return [m.get("content") for m in messages]


# ---------------------------------------------------------------------------
# 非实时模式
# ---------------------------------------------------------------------------

class TestNonRealtime:
    def test_main_injects_persona_and_hidden_prompts(self):
        msgs = build_messages(_AGENT, _FakeContextMgr(_HISTORY), "s", "你好")
        assert _roles(msgs)[0] == "system"
        assert msgs[0]["content"] == "你是测试人设"
        # 第二个 system 为隐藏提示词（tool_instructions + tools ...）
        assert msgs[1]["role"] == "system"
        assert msgs[1]["content"].startswith("## 工具调用规则")
        # 大模型类型提示词（master_model_prompt）也应注入
        assert "## 主模型操作指南" in msgs[1]["content"]
        # 末尾为当前用户消息
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "你好"

    def test_summary_model_injects_summary_prompt(self):
        agent = dict(_AGENT, model="summary")
        msgs = build_messages(agent, _FakeContextMgr(_HISTORY), "s", "你好")
        assert "## 摘要模型操作指南" in msgs[1]["content"]

    def test_assistant_model_injects_assistant_prompt(self):
        for model in ("assistant", "memory"):
            agent = dict(_AGENT, model=model)
            msgs = build_messages(agent, _FakeContextMgr(_HISTORY), "s", "你好")
            assert "## 记忆管理 Agent 操作指南" in msgs[1]["content"]

    def test_memory_context_injected_when_enabled(self):
        msgs = build_messages(_AGENT, _FakeContextMgr(_HISTORY), "s", "你好", memory_context="记忆内容")
        assert "相关记忆:\n记忆内容" in _contents(msgs)

    def test_memory_context_skipped_when_disabled(self):
        agent = dict(_AGENT, use_memory=False)
        msgs = build_messages(agent, _FakeContextMgr(_HISTORY), "s", "你好", memory_context="记忆内容")
        # 注意：graph_tools 文案含"相关记忆 ID"，故用精确的记忆注入标记断言
        assert not any("相关记忆:\n记忆内容" in c for c in _contents(msgs))


# ---------------------------------------------------------------------------
# 实时语音模式
# ---------------------------------------------------------------------------

class TestRealtime:
    def test_realtime_keeps_system_prompt_and_last_turns(self):
        msgs = build_messages(
            _AGENT, _FakeContextMgr(_HISTORY), "s", "你好",
            is_realtime_voice=True,
        )
        # 实时语音保留核心人设 system_prompt，并追加 REALTIME_VOICE_PROMPT_PADDING（token 补足 + 语音标签引导）
        assert msgs[0]["content"].startswith("你是测试人设")
        assert "<tts_instruction>" in msgs[0]["content"]
        # 不再注入重型语音隐藏提示词，直接进入最近 2 轮历史
        body = _contents(msgs)
        assert "u2" in body and "a2" in body
        assert "u1" not in body
        assert not any(c.startswith("##") for c in body)
        # 不注入重型隐藏提示词
        assert "## 工具调用规则" not in body
        # 末尾当前用户
        assert msgs[-1] == {"role": "user", "content": "你好"}

    def test_realtime_history_limit(self):
        # 10 条历史 → 实时模式只保留 REALTIME_VOICE_HISTORY_LIMIT 条
        long_history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
            for i in range(10)
        ]
        msgs = build_messages(
            _AGENT, _FakeContextMgr(long_history), "s", "你好",
            is_realtime_voice=True,
        )
        # 取最近 REALTIME_VOICE_HISTORY_LIMIT 条历史（不含末尾的当前用户消息）
        history_msgs = [m for m in msgs[:-1] if m["role"] in ("user", "assistant")]
        assert len(history_msgs) == REALTIME_VOICE_HISTORY_LIMIT
        # 且应为最近的消息（m6..m9），而非最旧的 m0..m3
        contents = [m["content"] for m in history_msgs]
        assert "m6" in contents and "m9" in contents
        assert "m0" not in contents

    def test_realtime_contains_ignore_rule(self):
        # 【忽略传导】实时语音 system prompt 须含"回应边界（忽略规则）"：
        # 主 LLM 对情绪/自言自语等非对话性输入可选择不回应，对提问/请求务必回答。
        msgs = build_messages(
            _AGENT, _FakeContextMgr(_HISTORY), "s", "你好",
            is_realtime_voice=True,
        )
        system_content = msgs[0]["content"]
        assert "回应边界" in system_content
        assert "只是表达情绪" in system_content
        assert "不回应" in system_content
        assert "明确提问" in system_content


# ---------------------------------------------------------------------------
# history 透传 / 最小化模式
# ---------------------------------------------------------------------------

class TestHistoryAndMinimal:
    def test_history_param_used_when_provided(self):
        msgs = build_messages(_AGENT, None, "s", "你好", history=_HISTORY)
        # 构造时传入 history，不再依赖 context_mgr
        assert "u1" in _contents(msgs)

    def test_include_hidden_prompts_false_is_minimal(self):
        msgs = build_messages(
            _AGENT, _FakeContextMgr(_HISTORY), "s", "你好",
            history=_HISTORY, include_hidden_prompts=False,
        )
        # 仅：人设 + 历史 + 用户，无隐藏提示词
        assert _roles(msgs) == ["system", "user", "assistant", "user", "assistant", "user", "user"]
        assert not any(c.startswith("##") for c in _contents(msgs))


# ---------------------------------------------------------------------------
# 多模态
# ---------------------------------------------------------------------------

class TestMultimodal:
    def test_images_produce_multimodal_user(self):
        msgs = build_messages(
            _AGENT, _FakeContextMgr(_HISTORY), "s", "看看这张图",
            images=["data:image/png;base64,AAAABBBB"],
        )
        user_msg = msgs[-1]
        assert isinstance(user_msg["content"], list)
        assert user_msg["content"][0]["type"] == "text"
        assert user_msg["content"][1]["type"] == "image_url"
        assert "image/png" in user_msg["content"][1]["image_url"]["url"]

    def test_images_ignored_when_vision_disabled(self):
        agent = dict(_AGENT, vision_enabled=False)
        msgs = build_messages(
            agent, _FakeContextMgr(_HISTORY), "s", "看看这张图",
            images=["data:image/png;base64,AAAABBBB"],
        )
        assert msgs[-1] == {"role": "user", "content": "看看这张图"}


# ---------------------------------------------------------------------------
# 配置键完整性守卫
# ---------------------------------------------------------------------------

class TestPromptKeyIntegrity:
    _CONSUMED_KEYS = {
        "tools",
        "emotion_prompts", "effect_prompts", "tool_usage_prompts",
        "graph_tools", "master_model_prompt",
        "summary_model_prompt", "assistant_model_prompt",
    }

    def test_all_consumed_keys_exist_in_hidden_prompt_yaml(self):
        import yaml

        from server.prompt_builder import _get_hidden_prompts

        prompts = _get_hidden_prompts()
        missing = self._CONSUMED_KEYS - set(prompts)
        assert not missing, f"hidden_prompt.yaml 缺少被代码消费的键: {missing}"

    def test_hidden_prompt_yaml_is_valid_yaml(self):
        import yaml

        from server.prompt_builder import _get_hidden_prompts

        yaml.safe_dump(_get_hidden_prompts())  # 可再序列化即视为合法 YAML 结构