"""server.core.tools.registry (ToolRegistry) 单元测试。

覆盖工具注册/查询/列表/OpenAI 格式导出、同步与异步调用、启用禁用删除、
统计与导入导出等核心逻辑。通过重置单例避免用例间状态污染。

运行：python -m pytest tests/test_tool_registry.py -v
"""
import asyncio

import pytest

from server.core.tools.registry import BUILTIN_TOOL_NAMES, Tool, ToolRegistry


@pytest.fixture
def registry():
    """每个用例独立的空 ToolRegistry（重置单例内部状态）。"""
    ToolRegistry._instance = None
    r = ToolRegistry()
    yield r
    ToolRegistry._instance = None


def _register(r, name="echo", fn=None, category="general", enabled=True, description="测试工具"):
    return r.register(
        name=name,
        description=description,
        parameters={"type": "object", "properties": {}, "required": []},
        function=fn,
        enabled=enabled,
        category=category,
    )


# ---------------------------------------------------------------- 注册与查询
class TestRegister:
    def test_register_returns_tool(self, registry):
        tool = _register(registry)
        assert isinstance(tool, Tool)
        assert tool.name == "echo"
        assert tool.enabled is True

    def test_get_tool(self, registry):
        _register(registry, name="calc")
        tool = registry.get_tool("calc")
        assert tool is not None
        assert tool.description == "测试工具"

    def test_get_missing_tool(self, registry):
        assert registry.get_tool("nope") is None

    def test_register_updates_existing(self, registry):
        _register(registry, name="dup")
        _register(registry, name="dup", description="更新后的描述")
        tools = registry.list_tools(enabled_only=False, include_builtin=True)
        dup = [t for t in tools if t.name == "dup"][0]
        assert dup.description == "更新后的描述"


# ---------------------------------------------------------------- 列表与过滤
class TestList:
    def test_list_respects_enabled(self, registry):
        _register(registry, name="on", enabled=True)
        _register(registry, name="off", enabled=False)
        enabled = [t.name for t in registry.list_tools(enabled_only=True)]
        assert "on" in enabled and "off" not in enabled

    def test_list_excludes_builtin_by_default(self, registry):
        _register(registry, name="calculator")  # 内置名
        _register(registry, name="custom_tool")
        names = [t.name for t in registry.list_tools(enabled_only=False)]
        assert "custom_tool" in names
        assert "calculator" not in names

    def test_list_include_builtin(self, registry):
        _register(registry, name="calculator")
        names = [t.name for t in registry.list_tools(enabled_only=False, include_builtin=True)]
        assert "calculator" in names

    def test_list_tools_dict(self, registry):
        _register(registry, name="dict_tool")
        d = registry.list_tools_dict(enabled_only=False, include_builtin=True)
        assert "dict_tool" in d and "name" in d["dict_tool"]

    def test_list_openai_functions_filter_category(self, registry):
        _register(registry, name="a", category="memory")
        _register(registry, name="b", category="general")
        fns = registry.list_openai_functions(
            enabled_only=False, include_builtin=True, category="memory"
        )
        names = [f["function"]["name"] for f in fns]
        assert names == ["a"]


# ---------------------------------------------------------------- Tool 序列化
class TestToolSerialization:
    def test_to_dict(self, registry):
        _register(registry, name="ser")
        tool = registry.get_tool("ser")
        d = tool.to_dict()
        assert d["name"] == "ser"
        assert set(d.keys()) >= {
            "name", "description", "parameters", "enabled", "version", "category",
        }

    def test_to_openai_function(self, registry):
        _register(registry, name="ofn")
        tool = registry.get_tool("ofn")
        f = tool.to_openai_function()
        assert f["type"] == "function"
        assert f["function"]["name"] == "ofn"


# ---------------------------------------------------------------- 同步调用
class TestCallToolSync:
    def test_missing_tool(self, registry):
        result = registry.call_tool("nope")
        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_disabled_tool(self, registry):
        _register(registry, name="off", fn=lambda: 1, enabled=False)
        result = registry.call_tool("off")
        assert result["success"] is False
        assert "已禁用" in result["error"]

    def test_sync_function(self, registry):
        _register(registry, name="add", fn=lambda a, b: a + b)
        result = registry.call_tool("add", {"a": 1, "b": 2})
        assert result["success"] is True
        assert result["result"] == 3

    def test_async_function_in_sync_context(self):
        """在无事件循环的同步上下文调用异步工具应直接 asyncio.run。"""
        ToolRegistry._instance = None
        r = ToolRegistry()

        async def afn(x):
            return x * 2

        _register(r, name="afn", fn=afn)
        result = r.call_tool("afn", {"x": 21})
        assert result["success"] is True
        assert result["result"] == 42
        ToolRegistry._instance = None

    def test_tool_call_count_increments(self, registry):
        _register(registry, name="counted", fn=lambda: 0)
        registry.call_tool("counted")
        registry.call_tool("counted")
        assert registry.get_tool("counted").call_count == 2

    def test_argument_error_hints(self, registry):
        _register(registry, name="need", fn=lambda a: a)
        result = registry.call_tool("need", {})
        assert result["success"] is False
        assert "正确参数为" in result["error"]


# ---------------------------------------------------------------- 异步调用
class TestCallToolAsync:
    @pytest.mark.asyncio
    async def test_async_function(self, registry):
        async def afn(x):
            await asyncio.sleep(0)
            return x + 1

        _register(registry, name="afn", fn=afn)
        result = await registry.call_tool_async("afn", {"x": 1})
        assert result["success"] is True
        assert result["result"] == 2

    @pytest.mark.asyncio
    async def test_sync_function_in_async_context(self, registry):
        _register(registry, name="sfn", fn=lambda: "ok")
        result = await registry.call_tool_async("sfn")
        assert result["success"] is True
        assert result["result"] == "ok"

    @pytest.mark.asyncio
    async def test_missing_tool(self, registry):
        result = await registry.call_tool_async("nope")
        assert result["success"] is False


# ---------------------------------------------------------------- 启停与删除
class TestEnableDisableDelete:
    def test_enable_disable(self, registry):
        _register(registry, name="t", enabled=True)
        assert registry.disable_tool("t") is True
        assert registry.get_tool("t").enabled is False
        assert registry.enable_tool("t") is True
        assert registry.get_tool("t").enabled is True

    def test_enable_missing(self, registry):
        assert registry.enable_tool("missing") is False

    def test_delete(self, registry):
        _register(registry, name="gone")
        assert registry.delete_tool("gone") is True
        assert registry.get_tool("gone") is None

    def test_delete_missing(self, registry):
        assert registry.delete_tool("missing") is False


# ---------------------------------------------------------------- 统计与导入导出
class TestStatsAndImport:
    def test_get_tool_stats(self, registry):
        _register(registry, name="s1", fn=lambda: 0, category="cat")
        _register(registry, name="s2", enabled=False)
        registry.call_tool("s1")
        stats = registry.get_tool_stats()
        assert stats["total_tools"] == 2
        assert stats["enabled_tools"] == 1
        assert stats["disabled_tools"] == 1
        assert stats["total_calls"] == 1
        assert stats["top_tools"][0][0] == "s1"

    def test_export_import_roundtrip(self, registry):
        _register(registry, name="exp", category="mem")
        data = registry.export_tools()
        assert len(data) == 1
        ToolRegistry._instance = None
        r2 = ToolRegistry()
        imported = r2.import_tools(data)
        assert imported == 1
        assert r2.get_tool("exp").category == "mem"
        ToolRegistry._instance = None


# ---------------------------------------------------------------- 内置工具集合
class TestBuiltinSet:
    def test_builtin_names_are_strings(self):
        assert all(isinstance(n, str) for n in BUILTIN_TOOL_NAMES)
        assert "calculator" in BUILTIN_TOOL_NAMES