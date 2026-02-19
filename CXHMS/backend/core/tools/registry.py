"""
工具注册表 - 管理所有可用的工具
"""

import asyncio
import inspect
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 内置工具名称集合 - 这些工具不会显示在工具管理界面
BUILTIN_TOOL_NAMES = {
    # 基础工具
    "calculator",
    "datetime",
    "random",
    "json_format",
    # 主模型工具
    "write_long_term_memory",
    "search_all_memories",
    "call_assistant",
    "set_alarm",
    "get_alarms",
    "cancel_alarm",
    "mono",
    # 摘要模型工具
    "summarize_content",
    "save_summary_memory",
    # 助手工具
    "update_memory_node",
    "search_memories",
    "delete_memory",
    "merge_memories",
    "clean_expired",
    "export_memories",
    "get_memory_stats",
    "search_by_time",
    "search_by_tag",
    "bulk_delete",
    "restore_memory",
    "search_similar_memories",
    "get_chat_history",
    "get_similar_memories",
    "get_memory_logs",
    "get_available_commands",
    # 记忆工具
    "save_memory",
}


@dataclass
class Tool:
    """工具数据类"""

    name: str
    description: str
    parameters: Dict
    function: Callable = None
    enabled: bool = True
    version: str = "1.0.0"
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    call_count: int = 0
    last_called: Optional[str] = None

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "enabled": self.enabled,
            "version": self.version,
            "category": self.category,
            "tags": self.tags,
            "examples": self.examples,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "call_count": self.call_count,
            "last_called": self.last_called,
        }

    def to_openai_function(self) -> Dict:
        """转换为 OpenAI 函数格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """工具注册表 - 单例模式"""

    _instance = None
    _tools: Dict[str, Tool] = {}
    _lock = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
            cls._instance._lock = threading.Lock()
        return cls._instance

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict,
        function: Callable = None,
        enabled: bool = True,
        version: str = "1.0.0",
        category: str = "general",
        tags: List[str] = None,
        examples: List[str] = None,
    ) -> Tool:
        """注册工具"""
        with self._lock:
            if name in self._tools:
                tool = self._tools[name]
                tool.description = description
                tool.parameters = parameters
                tool.enabled = enabled
                tool.version = version
                tool.category = category
                tool.tags = tags or []
                tool.examples = examples or []
                tool.updated_at = datetime.now().isoformat()
            else:
                tool = Tool(
                    name=name,
                    description=description,
                    parameters=parameters,
                    function=function,
                    enabled=enabled,
                    version=version,
                    category=category,
                    tags=tags or [],
                    examples=examples or [],
                )
                self._tools[name] = tool

            logger.info(f"工具已注册: {name} (类别: {category})")
            return tool

    def get_tool(self, name: str) -> Optional[Tool]:
        """获取工具"""
        return self._tools.get(name)

    def list_tools(self, enabled_only: bool = True, include_builtin: bool = False) -> List[Tool]:
        """列出工具"""
        tools = []
        for name, tool in self._tools.items():
            if enabled_only and not tool.enabled:
                continue
            if not include_builtin and name in BUILTIN_TOOL_NAMES:
                continue
            tools.append(tool)
        return tools

    def list_tools_dict(
        self, enabled_only: bool = True, include_builtin: bool = False
    ) -> Dict[str, Dict]:
        """列出工具（字典格式）"""
        return {
            tool.name: tool.to_dict() for tool in self.list_tools(enabled_only, include_builtin)
        }

    def list_openai_functions(
        self, enabled_only: bool = True, include_builtin: bool = False, category: str = None
    ) -> List[Dict]:
        """列出 OpenAI 格式的函数

        Args:
            enabled_only: 是否只返回启用的工具
            include_builtin: 是否包含内置工具
            category: 按类别过滤（可选）
        """
        tools = self.list_tools(enabled_only, include_builtin)

        if category:
            tools = [t for t in tools if t.category == category]

        return [tool.to_openai_function() for tool in tools]

    def call_tool(self, name: str, arguments: Dict = None) -> Dict:
        """调用工具（同步版本）

        注意：如果在异步上下文中调用，建议使用 call_tool_async 方法
        """
        tool = self._tools.get(name)
        if not tool:
            return {"success": False, "error": f"工具 {name} 不存在"}

        if not tool.enabled:
            return {"success": False, "error": f"工具 {name} 已禁用"}

        try:
            tool.call_count += 1
            tool.last_called = datetime.now().isoformat()

            if tool.function:
                if asyncio.iscoroutinefunction(tool.function):
                    try:
                        loop = asyncio.get_running_loop()
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(
                                asyncio.run, tool.function(**(arguments or {}))
                            )
                            result = future.result(timeout=120)
                    except RuntimeError:
                        result = asyncio.run(tool.function(**(arguments or {})))
                else:
                    result = tool.function(**(arguments or {}))

                return {"success": True, "result": result, "tool_name": name}
            else:
                return {"success": False, "error": f"工具 {name} 没有实现函数"}
        except TypeError as e:
            logger.error(f"调用工具 {name} 参数错误: {e}")
            params = tool.parameters.get("properties", {})
            required = tool.parameters.get("required", [])
            valid_params = list(params.keys())
            return {
                "success": False,
                "error": f"参数错误: {str(e)}。正确参数为: {', '.join(valid_params)}",
                "tool_name": name,
                "correct_usage": {
                    "description": tool.description,
                    "parameters": params,
                    "required": required,
                },
            }
        except Exception as e:
            logger.error(f"调用工具 {name} 失败: {e}")
            params = tool.parameters.get("properties", {}) if tool else {}
            required = tool.parameters.get("required", []) if tool else []
            return {
                "success": False,
                "error": str(e),
                "tool_name": name,
                "correct_usage": {
                    "description": tool.description if tool else "",
                    "parameters": params,
                    "required": required,
                },
            }

    async def call_tool_async(self, name: str, arguments: Dict = None) -> Dict:
        """调用工具（异步版本）

        推荐在异步上下文（如 FastAPI 路由）中使用此方法
        """
        tool = self._tools.get(name)
        if not tool:
            return {"success": False, "error": f"工具 {name} 不存在"}

        if not tool.enabled:
            return {"success": False, "error": f"工具 {name} 已禁用"}

        try:
            tool.call_count += 1
            tool.last_called = datetime.now().isoformat()

            if tool.function:
                if asyncio.iscoroutinefunction(tool.function):
                    result = await tool.function(**(arguments or {}))
                else:
                    result = tool.function(**(arguments or {}))

                return {"success": True, "result": result, "tool_name": name}
            else:
                return {"success": False, "error": f"工具 {name} 没有实现函数"}
        except Exception as e:
            logger.error(f"调用工具 {name} 失败: {e}")
            return {"success": False, "error": str(e), "tool_name": name}

    def enable_tool(self, name: str) -> bool:
        """启用工具"""
        if name in self._tools:
            self._tools[name].enabled = True
            return True
        return False

    def disable_tool(self, name: str) -> bool:
        """禁用工具"""
        if name in self._tools:
            self._tools[name].enabled = False
            return True
        return False

    def delete_tool(self, name: str) -> bool:
        """删除工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get_tool_stats(self) -> Dict:
        """获取工具统计"""
        tools = list(self._tools.values())
        total_calls = sum(t.call_count for t in tools)
        enabled_count = sum(1 for t in tools if t.enabled)
        by_category = {}
        for t in tools:
            if t.category not in by_category:
                by_category[t.category] = []
            by_category[t.category].append(t.name)

        return {
            "total_tools": len(tools),
            "enabled_tools": enabled_count,
            "disabled_tools": len(tools) - enabled_count,
            "total_calls": total_calls,
            "by_category": by_category,
            "top_tools": sorted(
                [(t.name, t.call_count) for t in tools], key=lambda x: x[1], reverse=True
            )[:5],
        }

    def export_tools(self) -> List[Dict]:
        """导出工具"""
        return [t.to_dict() for t in self._tools.values()]

    def import_tools(self, tools_data: List[Dict]) -> int:
        """导入工具"""
        imported = 0
        for tool_data in tools_data:
            try:
                self.register(
                    name=tool_data["name"],
                    description=tool_data["description"],
                    parameters=tool_data.get("parameters", {}),
                    enabled=tool_data.get("enabled", True),
                    version=tool_data.get("version", "1.0.0"),
                    category=tool_data.get("category", "general"),
                    tags=tool_data.get("tags", []),
                    examples=tool_data.get("examples", []),
                )
                imported += 1
            except Exception as e:
                logger.error(f"导入工具失败: {e}")
        return imported


# 全局工具注册表实例
tool_registry = ToolRegistry()
