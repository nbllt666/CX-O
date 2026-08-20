"""提示词工程优化回归测试。

覆盖 20260806_模块0_提示词工程系统优化 的全部 5 项改动：
  1. D1 决策对齐（few-shot + importance 真正参与位置判断）
  2. D2 元数据对齐（JSON 元数据解析 + 实际使用）
  3. 工具名一致性（hidden_prompt.yaml 与注册表对齐）
  4. 提示词去重（agents.py 单源常量 + secondary_router 单源引用）
  5. JSON 健壮化（extract_json + summarizer/secondary_router 统一使用）

不依赖真实 LLM / 后端服务，全部使用 mock 与纯函数断言。
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

import yaml

# 确保 server 包可导入
_CX_SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CX_SERVER not in sys.path:
    sys.path.insert(0, _CX_SERVER)


# --------------------------------------------------------------------------- #
# 1. D1 决策对齐
# --------------------------------------------------------------------------- #
class TestD1DecisionAlignment:
    def _core(self, content="用户在傍晚喜欢去海边散步"):
        from server.core.decision.decision_core import (
            DecisionCore,
            DecisionInput,
            RubricSnapshot,
        )

        rubric = RubricSnapshot(
            importance_threshold_permanent=0.7,
            quality_reject_threshold=0.3,
            max_redistill_turns=2,
            ask_user_confidence_threshold=0.4,
            cross_validate_sources=[],
        )
        di = DecisionInput(
            artifact_summary=content,
            session_state="S_STORAGE_DECISION",
            quality_score=0.85,
        )
        return DecisionCore, di, rubric

    def test_d1_prompt_has_few_shot_and_format(self):
        DecisionCore, di, rubric = self._core()
        core = DecisionCore()
        prompt = core._build_d1_prompt(di, rubric)
        assert "importance:0.85 confidence:0.9" in prompt
        assert "importance:0.2 confidence:0.95" in prompt
        assert "importance:<0-1> confidence:<0-1>" in prompt
        assert str(rubric.importance_threshold_permanent) in prompt

    def test_d1_uses_llm_importance_for_location(self):
        DecisionCore, di, rubric = self._core()
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            core = DecisionCore(log_dir=tmp, llm_available=True)
            # mock LLM 返回高 importance → 永久记忆
            with patch.object(core, "_llm_call", return_value="importance:0.9 confidence:0.8"):
                dec = core.decide_location("s1", di, rubric)
            assert dec.location == "permanent_memories"
            assert dec.llm_confidence == 0.8
            assert dec.metadata["importance"] == 0.75  # D1 metadata 仍用默认（与行为一致）

    def test_d1_low_importance_goes_to_memories(self):
        DecisionCore, di, rubric = self._core()
        with tempfile.TemporaryDirectory() as tmp:
            core = DecisionCore(log_dir=tmp, llm_available=True)
            with patch.object(core, "_llm_call", return_value="importance:0.2 confidence:0.9"):
                dec = core.decide_location("s2", di, rubric)
            assert dec.location == "memories"

    def test_d1_fallback_when_llm_unavailable(self):
        DecisionCore, di, rubric = self._core()
        with tempfile.TemporaryDirectory() as tmp:
            core = DecisionCore(log_dir=tmp, llm_available=False)
            dec = core.decide_location("s3", di, rubric)
            assert dec.llm_confidence is None
            # 回退默认 importance=0.75 >= 0.7 → permanent
            assert dec.location == "permanent_memories"

    def test_d1_quality_reject(self):
        DecisionCore, di, rubric = self._core()
        di.quality_score = 0.1
        with tempfile.TemporaryDirectory() as tmp:
            core = DecisionCore(log_dir=tmp, llm_available=False)
            dec = core.decide_location("s4", di, rubric)
            assert dec.location == "rejected"


# --------------------------------------------------------------------------- #
# 2. D2 元数据对齐
# --------------------------------------------------------------------------- #
class TestD2MetadataAlignment:
    def test_d2_prompt_has_few_shot_and_json_format(self):
        from server.core.decision.decision_core import DecisionCore, DecisionInput

        core = DecisionCore()
        di = DecisionInput(artifact_summary="用户喜欢在海边散步", session_state="S_DISTILL")
        prompt = core._build_d2_prompt(di)
        assert '"importance":4' in prompt
        assert '"tags":["海边","散步","爱好"]' in prompt
        assert "importance" in prompt and "tags" in prompt and "source" in prompt

    def test_d2_parses_and_uses_metadata(self):
        from server.core.decision.decision_core import DecisionCore, DecisionInput

        core = DecisionCore()
        di = DecisionInput(artifact_summary="用户喜欢在海边散步", session_state="S_DISTILL")
        with patch.object(core, "_llm_call", return_value=(
            '{"importance":4,"tags":["海边","散步"],"source":"user","confidence":0.9}'
        )):
            meta = core.decide_metadata("s1", di)
        assert meta["importance"] == 4
        assert meta["tags"] == ["海边", "散步"]
        assert meta["source"] == "user"

    def test_d2_handles_markdown_fence(self):
        from server.core.decision.decision_core import DecisionCore, DecisionInput

        core = DecisionCore()
        di = DecisionInput(artifact_summary="测试", session_state="S_DISTILL")
        with patch.object(core, "_llm_call", return_value=(
            "```json\n{\"importance\":2,\"tags\":[\"a\"],\"source\":\"assistant\",\"confidence\":0.7}\n```"
        )):
            meta = core.decide_metadata("s2", di)
        assert meta["importance"] == 2
        assert meta["tags"] == ["a"]

    def test_d2_fallback_on_bad_json(self):
        from server.core.decision.decision_core import DecisionCore, DecisionInput

        core = DecisionCore()
        di = DecisionInput(artifact_summary="测试", session_state="S_DISTILL")
        with patch.object(core, "_llm_call", return_value="not json at all"):
            meta = core.decide_metadata("s3", di)
        assert meta["importance"] == 3  # 默认 1-5
        assert meta["tags"] == ["radix", "d2_metadata"]
        assert meta["source"] == "测试"

    def test_d2_fallback_when_llm_unavailable(self):
        from server.core.decision.decision_core import DecisionCore, DecisionInput

        core = DecisionCore(llm_available=False)
        di = DecisionInput(artifact_summary="测试", session_state="S_DISTILL")
        meta = core.decide_metadata("s4", di)
        assert meta["tags"] == ["radix", "d2_metadata", "fallback"]
        assert meta["source"] == "测试"


# --------------------------------------------------------------------------- #
# 5. JSON 健壮化 extract_json
# --------------------------------------------------------------------------- #
class TestExtractJson:
    def test_extract_json_plain_object(self):
        from server.core.utils import extract_json

        assert extract_json('{"a": 1}') == {"a": 1}

    def test_extract_json_markdown_fence(self):
        from server.core.utils import extract_json

        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_extract_json_with_prefix_suffix_text(self):
        from server.core.utils import extract_json

        assert extract_json('好的，结果如下：{"a": 1} 请查收') == {"a": 1}

    def test_extract_json_array(self):
        from server.core.utils import extract_json

        assert extract_json('["a", "b"]') == ["a", "b"]

    def test_extract_json_bad_input_returns_default(self):
        from server.core.utils import extract_json

        assert extract_json("完全不是 json", default={"x": 1}) == {"x": 1}
        assert extract_json(None, default=[]) == []
        assert extract_json("", default="d") == "d"

    def test_extract_json_brace_in_string(self):
        from server.core.utils import extract_json

        # JSON 值内包含花括号，不应被误截
        assert extract_json('{"a": "x {y} z"}') == {"a": "x {y} z"}

    def test_extract_json_non_string_passthrough(self):
        from server.core.utils import extract_json

        assert extract_json({"already": "dict"}) == {"already": "dict"}


# --------------------------------------------------------------------------- #
# 4. 提示词去重（agents.py 单源常量）
# --------------------------------------------------------------------------- #
class TestPromptDeduplication:
    def test_agents_module_has_constants(self):
        from server.api.routers.agents import (
            DEFAULT_AGENT_SYSTEM_PROMPT,
            MEMORY_AGENT_SYSTEM_PROMPT,
        )

        assert "write_long_term_memory" in DEFAULT_AGENT_SYSTEM_PROMPT
        assert "search_all_memories" in DEFAULT_AGENT_SYSTEM_PROMPT
        assert "update_memory_node" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "search_memories" in MEMORY_AGENT_SYSTEM_PROMPT

    def test_secondary_router_uses_single_source_prompt(self):
        from server.api.routers.agents import MEMORY_AGENT_SYSTEM_PROMPT
        from server.core.memory.secondary_router import _get_memory_agent_prompt

        assert _get_memory_agent_prompt() == MEMORY_AGENT_SYSTEM_PROMPT

    def test_agents_json_matches_constants(self):
        from server.api.routers.agents import (
            DEFAULT_AGENT_SYSTEM_PROMPT,
            MEMORY_AGENT_SYSTEM_PROMPT,
        )

        agents_json = os.path.join(_CX_SERVER, "data", "agents.json")
        with open(agents_json, "r", encoding="utf-8") as fh:
            agents = json.load(fh)
        by_id = {a["id"]: a for a in agents}
        assert by_id["default"]["system_prompt"] == DEFAULT_AGENT_SYSTEM_PROMPT
        assert by_id["memory-agent"]["system_prompt"] == MEMORY_AGENT_SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# 0. hidden_prompt.yaml 键完整性守卫
# --------------------------------------------------------------------------- #
class TestHiddenPromptKeyCompleteness:
    """build_messages 引用的每个 hidden_prompt.yaml 键必须存在。

    若某键缺失，prompt_builder 会静默跳过对应提示词段（_get_hidden_prompts 失败
    返回 {}，build_messages 对不存在的键直接 continue），导致提示词段无声丢失。
    本守卫在键缺失时立即失败，防止提示词段静默回归。
    """

    def _referenced_keys(self):
        from server.prompt_builder import build_messages
        import inspect

        src = inspect.getsource(build_messages)
        keys = set()

        def _plain(s):
            return s.strip().strip('"\' ')

        for line in src.splitlines():
            line = line.strip()
            if line.startswith("#"):
                continue
            # 1) 形如 hidden_prompts.get("key", "") / hidden_prompts[key]
            if "hidden_prompts" in line:
                for seg in line.split("hidden_prompts")[1:]:
                    if ".get(" in seg:
                        keys.add(_plain(seg.split(".get(")[1].split(",")[0]))
                    elif "[" in seg:
                        keys.add(_plain(seg.split("[")[1].split("]")[0]))
            # 2) 模型分支的隐藏提示词键列表字面量：
            #    for key in ["tool_instructions", "tools", ...]
            # 仅当列表是 for 迭代源（for key in [...]）时才抽取，避免把 _msg["content"]
            # / msg["role"] 等消息 dict 下标误判为 hidden_prompt 键。
            if ".load(" in line or "import" in line:
                continue
            if " in [" in line and "hidden_prompts" not in line:
                inner = line[line.index("[") + 1: line.index("]")]
                for seg in inner.split(","):
                    token = _plain(seg)
                    if token and token not in ("", "None"):
                        keys.add(token)

        # 过滤类型注解等噪声（List[dict / List[str / str / dict）与模型名分支值
        noise = {
            "List[dict", "List[str", "str", "dict", "Optional[str]",
            "key", "main", "summary", "assistant", "memory",
            "REALTIME_VOICE_HISTORY_LIMIT",
        }
        keys = {
            k for k in keys
            if k not in noise
            and not k.startswith(":")  # 切片写法 [:LIMIT] 非键引用
            and "_HISTORY_LIMIT" not in k
        }
        return keys

    def test_all_referenced_keys_exist_in_yaml(self):
        config_path = os.path.join(os.path.dirname(_CX_SERVER), "config", "hidden_prompt.yaml")
        with open(config_path, "r", encoding="utf-8") as fh:
            hidden = yaml.safe_load(fh) or {}

        referenced = self._referenced_keys()
        assert referenced, "未从 build_messages 提取到任何引用键"
        missing = referenced - set(hidden)
        assert not missing, (
            f"build_messages 引用了 hidden_prompt.yaml 中不存在的键: {missing}。"
            "缺失将导致对应提示词段静默丢失，请补全或修正引用。"
        )

    def test_critical_sections_present(self):
        """核心提示词段必须存在，防止误删导致人设/情感/工具功能退化。"""
        config_path = os.path.join(os.path.dirname(_CX_SERVER), "config", "hidden_prompt.yaml")
        with open(config_path, "r", encoding="utf-8") as fh:
            hidden = yaml.safe_load(fh) or {}

        for key in [
            "tools",
            "emotion_prompts",
            "effect_prompts",
            "tool_usage_prompts",
            "graph_tools",
            "master_model_prompt",
            "summary_model_prompt",
            "assistant_model_prompt",
        ]:
            assert key in hidden and hidden[key], f"关键提示词段 {key} 缺失或为空"


# --------------------------------------------------------------------------- #
# 3. 工具名一致性（hidden_prompt.yaml 与注册表）
# --------------------------------------------------------------------------- #
class TestHiddenPromptToolNames:
    def test_hidden_prompt_tool_names_match_registry(self):
        # 权威工具名来源：
        #   1. server/core/tools/__config__.__all__（master/assistant/graph 等已注册工具）
        #   2. registry.BUILTIN_TOOL_NAMES（get_alarms / cancel_alarm 等）
        #   3. get_builtin_tools()（calculator 等内置工具，OpenAI function 格式）
        import server.core.tools as tools_pkg
        from server.core.tools import tool_registry
        from server.core.tools.registry import BUILTIN_TOOL_NAMES
        from server.core.tools.builtin import get_builtin_tools

        real = set(tools_pkg.__all__) | set(BUILTIN_TOOL_NAMES)
        for t in get_builtin_tools():
            if isinstance(t, dict):
                fn = t.get("function", t)
                if isinstance(fn, dict) and fn.get("name"):
                    real.add(fn["name"])

        # 防御：若注册表已初始化，叠加已注册工具
        if tool_registry._tools:
            real |= {t.name for t in tool_registry.list_tools(include_builtin=True)}

        config_path = os.path.join(os.path.dirname(_CX_SERVER), "config", "hidden_prompt.yaml")
        with open(config_path, "r", encoding="utf-8") as fh:
            hidden = yaml.safe_load(fh) or {}

        # 提取提示词中出现的所有工具名引用（遍历全部分段，防止任一残留分段静默失效）。
        # 中文文本无空格，无法用 split() 切分（工具名会被全角括号/后续文字粘连），
        # 改用正则提取含下划线的标识符式 token，对中文夹杂场景稳健。
        import re

        _IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
        referenced = set()
        for key, text in hidden.items():
            if not isinstance(text, str):
                continue
            for token in _IDENTIFIER.findall(text):
                if "_" in token:
                    referenced.add(token)

        # 不存在的工具名不应出现在提示词中（danmaku_decide 已被删除）
        # 排除：
        #   - json：格式关键字
        #   - SCHEMA_FIELDS：graph_tools 分段的图数据契约字段名（JSON 属性，如
        #     entity_type / relation_type / from_entity 等），非可调用工具名
        schema_fields = {
            "entity_type", "relation_type", "from_entity", "to_entity",
            "related_to", "part_of", "similar_to", "located_at", "made_of",
            "opposite_of", "subtopic_of", "followed_by", "concurrent_with",
            "memory_ids", "evidence_memory_ids",
        }
        # tts_instruction：Qwen3 TTS 语音情感/韵律指令标签（<tts_instruction>），
        # 非工具名，属协议标签而非可调用工具，与 json/schema_fields 同类排除。
        missing = referenced - real - {"json"} - {"tts_instruction"} - schema_fields
        assert not missing, f"hidden_prompt.yaml 引用了不存在的工具: {missing}"

    def test_no_stale_tool_names(self):
        config_path = os.path.join(os.path.dirname(_CX_SERVER), "config", "hidden_prompt.yaml")
        with open(config_path, "r", encoding="utf-8") as fh:
            hidden = yaml.safe_load(fh) or {}
        text = "\n".join(str(hidden.get(k, "")) for k in hidden)
        assert "write_memory" not in text.replace("write_long_term_memory", "")
        assert "danmaku_decide" not in text


# --------------------------------------------------------------------------- #
# 6. build_messages ACP 自动回复模式（单入口收敛）
# --------------------------------------------------------------------------- #
class _FakeContextMgr:
    def get_recent_messages(self, session_id, limit):
        return [
            {"role": "user", "content": "上一轮用户"},
            {"role": "assistant", "content": "上一轮助手"},
        ]


class TestBuildMessagesAcpMode:
    """回归：ACP 自动回复收敛到 build_messages 单入口（AGENTS.md §4.9）。

    修正前 manager._trigger_auto_reply 手动拼 system_prompt + ACP_REPLY_HINT
    + history + incoming_message，绕过了 build_messages。本类验证 acp_context
    非 None 时 build_messages 产出的消息列表与历史 ACP 结构一致。
    """

    def _cfg(self):
        return {"system_prompt": "你是小C。", "model": "main"}

    def test_acp_mode_message_shape(self):
        from server.prompt_builder import ACP_REPLY_HINT_PROMPT, build_messages

        msgs = build_messages(
            agent_config=self._cfg(),
            context_mgr=_FakeContextMgr(),
            session_id="agent-default",
            user_message="",
            acp_context={"from_agent_id": "agent-remote"},
        )
        # 1) 核心人设
        assert msgs[0] == {"role": "system", "content": "你是小C。"}
        # 2) ACP 专用提示
        assert msgs[1]["role"] == "system"
        assert msgs[1]["content"] == ACP_REPLY_HINT_PROMPT
        # 3) 历史（user/assistant 透传）
        assert {"role": "user", "content": "上一轮用户"} in msgs
        assert {"role": "assistant", "content": "上一轮助手"} in msgs
        # 4) incoming_message 上下文（携带发送方 ID）
        tail = msgs[-1]
        assert tail["role"] == "system"
        assert "agent-remote" in tail["content"]
        assert "<incoming_message>" in tail["content"]
        # 5) 无新 user 轮次追加（Agent 通过工具决定是否回复）：末条为 incoming 系统块，
        #    不在历史之后再追加 user_message 轮次。历史里的 user 消息属上一轮对话，正常存在。
        assert msgs[-1]["role"] == "system"
        assert msgs[-1]["content"].startswith("<incoming_message>")

    def test_acp_mode_without_system_prompt(self):
        from server.prompt_builder import ACP_REPLY_HINT_PROMPT, build_messages

        msgs = build_messages(
            agent_config={"model": "main"},
            context_mgr=_FakeContextMgr(),
            session_id="agent-default",
            user_message="",
            acp_context={"from_agent_id": "x"},
        )
        assert msgs[0]["content"] == ACP_REPLY_HINT_PROMPT

    def test_acp_mode_default_from_agent_id(self):
        from server.prompt_builder import build_messages

        msgs = build_messages(
            agent_config=self._cfg(),
            context_mgr=_FakeContextMgr(),
            session_id="agent-default",
            user_message="",
            acp_context={},
        )
        assert "unknown" in msgs[-1]["content"]
