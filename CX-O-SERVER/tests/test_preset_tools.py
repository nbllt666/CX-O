"""preset_tools 工具测试（Task 3 / SubTask 3.2）。

覆盖：
- 注册接线：4 个工具进入注册表、BUILTIN_TOOL_NAMES、chat_helpers 主模型白名单
- save/list/delete 经工具层的 CRUD 闭环（agent_id 来自 contextvar）
- agent 隔离：不同 agent_id 互不可见
- 错误风格：入参非法返回 {"error": ...}，与「写记忆」类工具一致
- 经 tool_registry.call_tool 的全链路调用成功

运行：python -m pytest tests/test_preset_tools.py -x -q
"""
import pytest

from server.services import preset_service as ps
from server.core.tools import tool_registry
from server.core.tools.preset_tools import register_preset_tools
from server.core.tools.graph_tools import set_current_agent_id, get_current_agent_id
from server.core.tools.registry import BUILTIN_TOOL_NAMES

AGENT = "toolagent"


@pytest.fixture
def env(monkeypatch, tmp_path):
    """隔离：预设根目录重定向 + agent 上下文设定 + 工具注册。"""
    root = tmp_path / "presets"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ps, "_PRESETS_ROOT", root)
    monkeypatch.setattr(ps, "_CACHE", {})
    set_current_agent_id(AGENT)
    register_preset_tools()
    yield root
    set_current_agent_id("default")  # 防上下文泄漏到其他测试


class TestRegistration:
    def test_four_tools_registered(self, env):
        for name in ("save_emotion_preset", "save_action_preset", "list_presets", "delete_preset"):
            tool = tool_registry.get_tool(name)
            assert tool is not None, f"工具 {name} 未注册"
            assert tool.category == "preset"

    def test_in_registry_builtin_whitelist(self, env):
        for name in ("save_emotion_preset", "save_action_preset", "list_presets", "delete_preset"):
            assert name in BUILTIN_TOOL_NAMES

    def test_in_chat_helpers_main_whitelist(self, env):
        # get_tools_for_agent 是工具注入 LLM 的单一真相源，4 个工具必须出现在其中
        from server.chat_helpers import get_tools_for_agent

        names = {t.get("function", {}).get("name") for t in get_tools_for_agent()}
        for name in ("save_emotion_preset", "save_action_preset", "list_presets", "delete_preset"):
            assert name in names, f"工具 {name} 未注入主模型工具清单"

    def test_description_contains_usage_hints(self, env):
        save_emotion = tool_registry.get_tool("save_emotion_preset")
        assert "tts_instruction" in save_emotion.description
        save_action = tool_registry.get_tool("save_action_preset")
        assert "[action:" in save_action.description


class TestSaveAndList:
    def test_save_emotion_preset_success(self, env):
        from server.core.tools.preset_tools import save_emotion_preset

        r = save_emotion_preset(name="元气满满", text="元气活泼", speed=1.2)
        assert r["status"] == "success"
        assert r["usage"]
        stored = ps.get_emotion_preset(AGENT, "元气满满")
        assert stored is not None and stored["speed"] == 1.2

    def test_save_action_preset_success(self, env):
        from server.core.tools.preset_tools import save_action_preset

        r = save_action_preset(name="打招呼", tags=["[emotion:happy]", "[action:wave]"])
        assert r["status"] == "success"
        assert ps.get_action_preset(AGENT, "打招呼") is not None

    def test_save_emotion_missing_args_error(self, env):
        from server.core.tools.preset_tools import save_emotion_preset

        assert "error" in save_emotion_preset(name="", text="t")
        assert "error" in save_emotion_preset(name="n", text="")

    def test_save_action_invalid_tag_error(self, env):
        from server.core.tools.preset_tools import save_action_preset

        r = save_action_preset(name="n", tags=["emotion:happy"])  # 缺方括号
        assert "error" in r

    def test_save_emotion_invalid_number_error(self, env):
        from server.core.tools.preset_tools import save_emotion_preset

        r = save_emotion_preset(name="n", text="t", speed="飞快")
        assert "error" in r

    def test_list_presets_both_kinds(self, env):
        from server.core.tools.preset_tools import save_emotion_preset, save_action_preset, list_presets

        save_emotion_preset(name="e1", text="t", description="情感一")
        save_action_preset(name="a1", tags=["[action:nod]"], description="动作一")
        r = list_presets()
        assert r["status"] == "success"
        assert r["emotion_presets"] == [{"name": "e1", "description": "情感一"}]
        assert r["action_presets"] == [{"name": "a1", "description": "动作一"}]
        assert "preset" in r["emotion_usage"] and "[action:" in r["action_usage"]

    def test_list_presets_kind_filter(self, env):
        from server.core.tools.preset_tools import save_emotion_preset, list_presets

        save_emotion_preset(name="e1", text="t")
        only_emotion = list_presets(kind="emotion")
        assert only_emotion["emotion_presets"] and "action_presets" not in only_emotion
        only_action = list_presets(kind="action")
        assert only_action["action_presets"] == []
        assert "error" in list_presets(kind="bad")


class TestDelete:
    def test_delete_flow(self, env):
        from server.core.tools.preset_tools import save_emotion_preset, delete_preset

        save_emotion_preset(name="待删", text="t")
        r = delete_preset(kind="emotion", name="待删")
        assert r["status"] == "success"
        missing = delete_preset(kind="emotion", name="待删")
        assert missing.get("status") == "not_found" and "error" in missing

    def test_delete_invalid_kind_error(self, env):
        from server.core.tools.preset_tools import delete_preset

        assert "error" in delete_preset(kind="wrong", name="n")
        assert "error" in delete_preset(kind="emotion", name="")


class TestAgentIsolation:
    def test_agents_isolated(self, env):
        from server.core.tools.preset_tools import save_emotion_preset, list_presets

        save_emotion_preset(name="私有", text="t")
        set_current_agent_id("other-agent")
        assert list_presets()["emotion_presets"] == []
        set_current_agent_id(AGENT)
        assert list_presets()["emotion_presets"][0]["name"] == "私有"


class TestViaRegistryCall:
    def test_call_tool_success_wrapper(self, env):
        """经 tool_registry.call_tool 全链路调用（与 LLM 工具调用同一执行路径）。"""
        result = tool_registry.call_tool(
            "save_action_preset",
            {"name": "全链路", "tags": ["[action:nod]"], "description": "d"},
        )
        assert result["success"] is True
        assert result["result"]["status"] == "success"
        assert ps.get_action_preset(get_current_agent_id(), "全链路") is not None

    def test_call_tool_validation_error_wrapped(self, env):
        result = tool_registry.call_tool(
            "save_action_preset", {"name": "n", "tags": "not-a-list"}
        )
        assert result["success"] is True  # 调用本身成功，错误在 result 内
        assert "error" in result["result"]
