# -*- coding: utf-8 -*-
"""server.core.tools.builtin (BuiltinTools) 单元测试。

覆盖：计算器（安全沙箱/非法名拒绝/异常回退）、日期时间格式化与格式映射、
随机数（int/float/非法类型）、JSON 格式化（成功/非法/类型名）、工具定义清单
（OpenAI 格式）、call_tool 分发（未知工具/参数错误/正确用法回填/通用异常）、
模块级便捷入口与向后兼容注册函数。

运行：python -m pytest tests/test_builtin_tools.py -v
"""
import pytest

from server.core.tools.builtin import (
    BuiltinTools,
    builtin_tools,
    call_builtin_tool,
    get_builtin_tools,
    register_builtin_tools,
)


class TestCalculator:
    def test_basic_arithmetic(self):
        r = BuiltinTools.calculator("2 + 2")
        assert r["success"] is True
        assert r["result"] == 4

    def test_safe_functions(self):
        assert BuiltinTools.calculator("sqrt(16)")["result"] == 4
        assert round(BuiltinTools.calculator("sin(pi/2)")["result"], 3) == 1.0
        assert BuiltinTools.calculator("log2(8)")["result"] == 3

    def test_unsafe_name_rejected(self):
        r = BuiltinTools.calculator("__import__('os')")
        assert r["success"] is False
        assert "不安全" in r["error"]

    def test_unsafe_builtin_open_rejected(self):
        r = BuiltinTools.calculator("open('/etc/passwd')")
        assert r["success"] is False
        assert "不安全" in r["error"]

    def test_syntax_error_returns_failure(self):
        r = BuiltinTools.calculator("2 +")
        assert r["success"] is False
        assert "error" in r

    def test_expression_echoed(self):
        r = BuiltinTools.calculator("3 * 3")
        assert r["expression"] == "3 * 3"

    def test_single_power_still_works(self):
        # 护栏不应误伤普通单次幂运算
        r = BuiltinTools.calculator("2 ** 3")
        assert r["success"] is True
        assert r["result"] == 8

    def test_chained_power_rejected(self):
        # 9**9**9 链式幂运算必须被预扫描拦截，而非进入 eval 拖垮进程
        r = BuiltinTools.calculator("9 ** 9 ** 9")
        assert r["success"] is False
        assert "链式幂" in r["error"]

    def test_large_literal_exponent_rejected(self):
        r = BuiltinTools.calculator("2 ** 20000")
        assert r["success"] is False
        assert "指数过大" in r["error"]

    def test_oversized_expression_rejected(self):
        r = BuiltinTools.calculator("1 + " * 200 + "1")
        assert len("1 + " * 200 + "1") > 300
        assert r["success"] is False
        assert "过长" in r["error"]


class TestDatetime:
    def test_default_format(self):
        r = BuiltinTools.datetime_tool()
        assert r["success"] is True
        assert r["year"] is not None
        assert ":" in r["formatted"]  # HH:mm:ss 默认格式

    def test_custom_format_mapping(self):
        r = BuiltinTools.datetime_tool(format="YYYY/MM/DD")
        assert r["success"] is True
        # 映射后应为 %Y/%m/%d
        parts = r["formatted"].split("/")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_invalid_format_returns_failure(self):
        # 非法 strftime 占位符（如孤立 %）被捕获并返回错误，不向上抛异常
        r = BuiltinTools.datetime_tool(format="%%%")
        assert r["success"] is False
        assert "error" in r

    def test_iso_and_timestamp(self):
        r = BuiltinTools.datetime_tool()
        assert "iso" in r
        assert isinstance(r["timestamp"], float)

    def test_timezone_utc(self):
        # timezone 参数应生效：UTC 时区的 iso 应带 +00:00 偏移（仅当 zoneinfo 可用时断言；
        # Windows 无 tzdata 时 valid 时区会静默回退本地，属规格允许的降级行为）
        from datetime import datetime
        from zoneinfo import ZoneInfo

        r = BuiltinTools.datetime_tool(timezone="UTC")
        assert r["success"] is True
        assert r["timezone"] == "UTC"
        try:
            aware = datetime.now(ZoneInfo("UTC"))
            zinfo_ok = aware.utcoffset() is not None
        except Exception:
            zinfo_ok = False
        if zinfo_ok:
            assert r["iso"].endswith("+00:00")

    def test_invalid_timezone_falls_back(self):
        # 无效时区名应静默回退本地时间（不抛异常，保持原行为）
        r = BuiltinTools.datetime_tool(timezone="Not/AZone")
        assert r["success"] is True


class TestRandom:
    def test_int_in_range(self):
        r = BuiltinTools.random(min=5, max=5)
        assert r["success"] is True
        assert r["value"] == 5

    def test_float(self):
        r = BuiltinTools.random(min=0, max=1, type="float")
        assert r["success"] is True
        assert 0 <= r["value"] <= 1

    def test_unsupported_type(self):
        r = BuiltinTools.random(type="bigint")
        assert r["success"] is False
        assert "不支持" in r["error"]


class TestJsonFormat:
    def test_valid_json(self):
        r = BuiltinTools.json_format('{"a": 1}')
        assert r["success"] is True
        assert r["type"] == "dict"
        assert '"a": 1' in r["formatted"]

    def test_invalid_json(self):
        r = BuiltinTools.json_format("{invalid")
        assert r["success"] is False
        assert r["is_valid"] is False
        assert "解析错误" in r["error"]

    def test_list_type(self):
        r = BuiltinTools.json_format("[1, 2]")
        assert r["success"] is True
        assert r["type"] == "list"


class TestGetAllTools:
    def test_four_builtin_tools(self):
        tools = BuiltinTools.get_all_tools()
        names = [t["function"]["name"] for t in tools]
        assert names == ["calculator", "datetime", "random", "json_format"]

    def test_openai_format(self):
        tools = BuiltinTools.get_all_tools()
        for t in tools:
            assert t["type"] == "function"
            assert "parameters" in t["function"]
            assert "properties" in t["function"]["parameters"]

    def test_module_level_entry(self):
        assert get_builtin_tools() == BuiltinTools.get_all_tools()


class TestCallTool:
    def test_dispatch_calculator(self):
        r = call_builtin_tool("calculator", {"expression": "10 / 2"})
        assert r["success"] is True
        assert r["result"] == 5

    def test_unknown_tool(self):
        r = call_builtin_tool("nope", {})
        assert r["success"] is False
        assert "未知工具" in r["error"]

    def test_type_error_returns_correct_usage(self):
        r = call_builtin_tool("json_format", {})  # 缺必需参数 json_string
        assert r["success"] is False
        assert "正确参数" in r.get("correct_usage", {}).get("parameters", {}) or "json_string" in r.get("error", "")

    def test_generic_exception(self):
        r = call_builtin_tool("calculator", {"expression": None})
        assert r["success"] is False
        assert "工具执行错误" in r["error"] or "error" in r


class TestRegister:
    def test_register_is_noop(self):
        register_builtin_tools()  # 不抛异常即通过


class TestSingleton:
    def test_singleton_instance(self):
        assert builtin_tools is BuiltinTools()


# --------------------------------------------------------------------------- #
# 统一异步工具执行（_execute_single_tool_async / execute_tool_calls_async）
# --------------------------------------------------------------------------- #
class TestAsyncToolExecutor:
    @pytest.mark.asyncio
    async def test_builtin_sync_tool(self):
        from server.core.tools.builtin import _execute_single_tool_async

        r = await _execute_single_tool_async("calculator", {"expression": "1+1"})
        assert r["success"] is True
        assert r["result"] == 2

    @pytest.mark.asyncio
    async def test_registry_async_handler(self, monkeypatch):
        from server.core.tools import tool_registry

        ran = []

        async def _async_handler(q=""):
            ran.append(q)
            return {"ok": True, "q": q}

        tool_registry.register(
            name="_test_async_helper", description="t", parameters={"type": "object"},
            function=_async_handler, category="test", tags=[], enabled=True,
        )
        try:
            from server.core.tools.builtin import _execute_single_tool_async

            r = await _execute_single_tool_async("_test_async_helper", {"q": "hi"})
            assert r["success"] is True and ran == ["hi"]
        finally:
            tool_registry._tools.pop("_test_async_helper", None)

    @pytest.mark.asyncio
    async def test_cxfc_tool_via_manager(self, monkeypatch):
        from server.core.tools import tool_registry
        from server.core.tools.builtin import _execute_single_tool_async

        tool_registry.register(
            name="_test_cxfc_tool", description="t", parameters={"type": "object"},
            function=None, category="cxfc", tags=["plugin-1"], enabled=True,
        )
        calls = []

        class _FakeManager:
            async def call_tool(self, plugin_id, tool_name, arguments):
                calls.append((plugin_id, tool_name, arguments))
                return {"success": True, "result": "ran"}

        monkeypatch.setattr("server.dependencies.get_cxfc_manager", lambda: _FakeManager())
        try:
            r = await _execute_single_tool_async("_test_cxfc_tool", {"x": 1})
            assert r["success"] is True
            assert calls == [("plugin-1", "_test_cxfc_tool", {"x": 1})]
        finally:
            tool_registry._tools.pop("_test_cxfc_tool", None)
            monkeypatch.delattr("server.dependencies.get_cxfc_manager")