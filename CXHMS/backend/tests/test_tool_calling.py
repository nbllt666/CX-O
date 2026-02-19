"""工具调用测试"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.core.llm.client import OllamaClient, VLLMClient
from backend.core.tools import register_master_tools, set_master_dependencies, tool_registry


class TestToolCalling:
    """测试工具调用功能"""

    def test_tool_registration(self):
        """测试工具注册"""
        set_master_dependencies(memory_manager=None, secondary_router=None, context_manager=None)
        register_master_tools()

        stats = tool_registry.get_tool_stats()
        assert stats["total_tools"] > 0, "应该有工具注册"
        assert stats["enabled_tools"] > 0, "应该有启用的工具"

    def test_tool_to_openai_function(self):
        """测试工具转换为 OpenAI 格式"""
        set_master_dependencies(memory_manager=None, secondary_router=None, context_manager=None)
        register_master_tools()

        tool = tool_registry.get_tool("write_long_term_memory")
        assert tool is not None, "工具应该存在"

        openai_func = tool.to_openai_function()
        assert "type" in openai_func, "应该有 type 字段"
        assert openai_func["type"] == "function", "type 应该是 function"
        assert "function" in openai_func, "应该有 function 字段"
        assert openai_func["function"]["name"] == "write_long_term_memory"

    def test_tool_call_execution(self):
        """测试工具调用执行"""
        set_master_dependencies(memory_manager=None, secondary_router=None, context_manager=None)
        register_master_tools()

        result = tool_registry.call_tool("set_alarm", {"seconds": 60, "message": "测试提醒"})
        assert result["success"] is True, "工具调用应该成功"
        assert "alarm_id" in result["result"], "应该返回 alarm_id"

    def test_tool_not_found(self):
        """测试工具不存在的情况"""
        set_master_dependencies(memory_manager=None, secondary_router=None, context_manager=None)
        register_master_tools()

        result = tool_registry.call_tool("non_existent_tool", {})
        assert result["success"] is False, "工具调用应该失败"
        assert "error" in result, "应该返回错误信息"

    def test_tool_disabled(self):
        """测试禁用工具的调用"""
        set_master_dependencies(memory_manager=None, secondary_router=None, context_manager=None)
        register_master_tools()

        tool_registry.disable_tool("set_alarm")
        result = tool_registry.call_tool("set_alarm", {"seconds": 60, "message": "测试提醒"})
        assert result["success"] is False, "禁用工具调用应该失败"
        assert "error" in result, "应该返回错误信息"

        tool_registry.enable_tool("set_alarm")

    def test_tool_list_api(self):
        """测试工具列表 API"""
        set_master_dependencies(memory_manager=None, secondary_router=None, context_manager=None)
        register_master_tools()

        tools = tool_registry.list_openai_functions(include_builtin=True)
        assert isinstance(tools, list), "工具列表应该是列表"
        assert len(tools) > 0, "应该有工具"

        for tool in tools:
            assert "type" in tool, "工具应该有 type 字段"
            assert "function" in tool, "工具应该有 function 字段"

    def test_tool_stats(self):
        """测试工具统计"""
        set_master_dependencies(memory_manager=None, secondary_router=None, context_manager=None)
        register_master_tools()

        stats = tool_registry.get_tool_stats()
        assert "total_tools" in stats, "应该有 total_tools 字段"
        assert "enabled_tools" in stats, "应该有 enabled_tools 字段"
        assert "disabled_tools" in stats, "应该有 disabled_tools 字段"
        assert "by_category" in stats, "应该有 by_category 字段"
        assert "top_tools" in stats, "应该有 top_tools 字段"

    def test_tool_enable_disable(self):
        """测试工具启用和禁用"""
        set_master_dependencies(memory_manager=None, secondary_router=None, context_manager=None)
        register_master_tools()

        tool_registry.disable_tool("set_alarm")
        stats = tool_registry.get_tool_stats()
        assert stats["disabled_tools"] > 0, "应该有禁用工具"

        tool_registry.enable_tool("set_alarm")
        stats = tool_registry.get_tool_stats()
        assert stats["disabled_tools"] == 0, "不应该有禁用工具"
