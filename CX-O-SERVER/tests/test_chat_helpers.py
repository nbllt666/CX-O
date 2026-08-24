"""
server/chat_helpers.py 单元测试
Agent 配置解析与 LLM 客户端选择（跨 HTTP 路由与 WebSocket 处理器共享）
"""
import pytest

import server.dependencies as deps
import server.chat_helpers as chat_helpers_mod
from server.chat_helpers import get_agent_config, get_llm_client_for_agent


class _FakeClient:
    def __init__(self, **kw):
        self.host = kw.get("host", "http://localhost:11434")
        self.model = kw.get("model", "main")
        self.temperature = kw.get("temperature")
        self.max_tokens = kw.get("max_tokens")


class _FakeRouter:
    def __init__(self, clients):
        self._clients = clients

    def get_client(self, name):
        return self._clients.get(name)


class TestGetAgentConfig:
    def test_found(self, monkeypatch):
        agents = [{"id": "a1", "name": "A"}, {"id": "a2", "name": "B"}]
        monkeypatch.setattr("server.api.routers.agents._load_agents", lambda: agents)
        assert get_agent_config("a2") == {"id": "a2", "name": "B"}

    def test_not_found(self, monkeypatch):
        monkeypatch.setattr("server.api.routers.agents._load_agents", lambda: [])
        assert get_agent_config("ghost") is None


class TestGetLLMClientForAgent:
    def test_main_type_from_router(self, monkeypatch):
        main = _FakeClient(model="main")
        monkeypatch.setattr(deps, "get_model_router",
                            lambda: _FakeRouter({"main": main}))
        monkeypatch.setattr(deps, "get_llm_client", lambda: _FakeClient(model="fallback"))
        c = get_llm_client_for_agent({"model": "main"})
        assert c is main

    def test_memory_type_from_router(self, monkeypatch):
        mem = _FakeClient(model="memory")
        monkeypatch.setattr(deps, "get_model_router", lambda: _FakeRouter({"memory": mem}))
        c = get_llm_client_for_agent({"model": "memory"})
        assert c is mem

    def test_type_missing_client_falls_back(self, monkeypatch):
        monkeypatch.setattr(deps, "get_model_router", lambda: _FakeRouter({}))
        fallback = _FakeClient(model="fallback")
        monkeypatch.setattr(deps, "get_llm_client", lambda: fallback)
        c = get_llm_client_for_agent({"model": "summary"})
        assert c is fallback

    def test_specific_model_creates_ollama(self, monkeypatch):
        main = _FakeClient(host="http://x:11434", model="main")
        monkeypatch.setattr(deps, "get_model_router", lambda: _FakeRouter({"main": main}))
        created = []
        class FakeOllama(_FakeClient):
            pass
        monkeypatch.setattr("server.core.llm.client.OllamaClient", FakeOllama)
        c = get_llm_client_for_agent({"model": "qwen", "temperature": 0.3, "max_tokens": 1024})
        assert isinstance(c, FakeOllama)
        assert c.host == "http://x:11434"
        assert c.model == "qwen"
        assert c.temperature == 0.3
        assert c.max_tokens == 1024

    def test_specific_model_no_main_client_fallback(self, monkeypatch):
        monkeypatch.setattr(deps, "get_model_router", lambda: _FakeRouter({}))
        fallback = _FakeClient(model="fallback")
        monkeypatch.setattr(deps, "get_llm_client", lambda: fallback)
        c = get_llm_client_for_agent({"model": "qwen"})
        assert c is fallback

    def test_router_error_falls_back(self, monkeypatch):
        def boom():
            raise RuntimeError("router down")
        monkeypatch.setattr(deps, "get_model_router", boom)
        fallback = _FakeClient(model="fallback")
        monkeypatch.setattr(deps, "get_llm_client", lambda: fallback)
        c = get_llm_client_for_agent({"model": "main"})
        assert c is fallback

    def test_default_model_main(self, monkeypatch):
        main = _FakeClient(model="main")
        monkeypatch.setattr(deps, "get_model_router", lambda: _FakeRouter({"main": main}))
        c = get_llm_client_for_agent({})  # 无 model 字段 → 默认 main
        assert c is main


class _FakeTool:
    def __init__(self, name, enabled=True, category=""):
        self.name = name
        self.enabled = enabled
        self.category = category

    def to_openai_function(self):
        return {"name": self.name}


class _FakeRegistry:
    def __init__(self, tools):
        self._tools = {t.name: t for t in tools}

    def get_tool(self, name):
        return self._tools.get(name)


class TestGetToolsForAgent:
    def test_builtin_plus_main_excludes_summary(self, monkeypatch):
        import server.core.tools as tools_mod
        from server.core.tools import builtin as builtin_mod
        from server.chat_helpers import get_tools_for_agent

        reg = _FakeRegistry([
            _FakeTool("write_long_term_memory", category="memory"),
            _FakeTool("some_summary_tool", category="summary"),
            _FakeTool("disabled_tool", enabled=False, category="memory"),
        ])
        monkeypatch.setattr(tools_mod, "tool_registry", reg)
        monkeypatch.setattr(builtin_mod, "get_builtin_tools", lambda: [{"name": "builtin"}])
        tools = get_tools_for_agent()
        names = [t["name"] for t in tools]
        assert "builtin" in names
        assert "write_long_term_memory" in names
        # summary 分类与禁用工具均被排除
        assert "some_summary_tool" not in names
        assert "disabled_tool" not in names

    def test_includes_cxfc_category_tools(self, monkeypatch):
        import server.core.tools as tools_mod
        from server.core.tools import builtin as builtin_mod
        from server.chat_helpers import get_tools_for_agent

        class _CXFCRegistry(_FakeRegistry):
            def list_openai_functions(self, enabled_only=True, include_builtin=False, category=None):
                if category == "cxfc":
                    return [
                        {"name": "computer_keyboard_control", "type": "function"},
                        {"name": "autonomy_write_post", "type": "function"},
                    ]
                return []

        reg = _CXFCRegistry([_FakeTool("write_long_term_memory", category="memory")])
        monkeypatch.setattr(tools_mod, "tool_registry", reg)
        monkeypatch.setattr(builtin_mod, "get_builtin_tools", lambda: [])
        tools = get_tools_for_agent()
        names = [t["name"] for t in tools]
        # 主工具仍在
        assert "write_long_term_memory" in names
        # CXFC 插件工具（电脑控制/自主系统）被纳入"全部工具"
        assert "computer_keyboard_control" in names
        assert "autonomy_write_post" in names