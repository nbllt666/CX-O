import asyncio
import inspect
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

BUILTIN_TOOL_NAMES = {
    "calculator", "datetime", "random", "json_format",
    "write_long_term_memory", "search_all_memories", "call_assistant", "set_alarm", "get_alarms", "cancel_alarm", "mono",
    "summarize_content", "save_summary_memory",
    "update_memory_node", "search_memories", "delete_memory", "merge_memories", "clean_expired", "export_memories", "get_memory_stats",
    "search_by_time", "search_by_tag", "bulk_delete", "restore_memory", "search_similar_memories", "get_chat_history", "get_similar_memories",
    "get_memory_logs", "get_available_commands", "save_memory",
}


@dataclass
class Tool:
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
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat()))
    call_count: int = 0
    last_called: Optional[str] = None

    def to_dict(self) -> Dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters, "enabled": self.enabled,
            "version": self.version, "category": self.category, "tags": self.tags, "examples": self.examples,
            "created_at": self.created_at, "updated_at": self.updated_at, "call_count": self.call_count, "last_called": self.last_called}

    def to_openai_function(self) -> Dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


class ToolRegistry:
    _instance = None
    _tools: Dict[str, Tool] = {}
    _lock = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
            cls._instance._lock = threading.Lock()
        return cls._instance

    def register(self, name: str, description: str, parameters: Dict, function: Callable = None, enabled: bool = True,
                 version: str = "1.0.0", category: str = "general", tags: List[str] = None, examples: List[str] = None) -> Tool:
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
                tool = Tool(name=name, description=description, parameters=parameters, function=function, enabled=enabled,
                           version=version, category=category, tags=tags or [], examples=examples or [])
                self._tools[name] = tool
            logger.info(f"工具已注册: {name} (类别: {category})")
            return tool

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self, enabled_only: bool = True, include_builtin: bool = False) -> List[Tool]:
        tools = []
        for name, tool in self._tools.items():
            if enabled_only and not tool.enabled:
                continue
            if not include_builtin and name in BUILTIN_TOOL_NAMES:
                continue
            tools.append(tool)
        return tools

    def list_openai_functions(self, enabled_only: bool = True, include_builtin: bool = False, category: str = None) -> List[Dict]:
        tools = self.list_tools(enabled_only, include_builtin)
        if category:
            tools = [t for t in tools if t.category == category]
        return [tool.to_openai_function() for tool in tools]

    def call_tool(self, name: str, arguments: Dict = None) -> Dict:
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
                            future = executor.submit(asyncio.run, tool.function(**(arguments or {})))
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
            return {"success": False, "error": f"参数错误: {str(e)}。正确参数为: {', '.join(valid_params)}", "tool_name": name,
                "correct_usage": {"description": tool.description, "parameters": params, "required": required}}
        except Exception as e:
            logger.error(f"调用工具 {name} 失败: {e}")
            params = tool.parameters.get("properties", {}) if tool else {}
            required = tool.parameters.get("required", []) if tool else []
            return {"success": False, "error": str(e), "tool_name": name,
                "correct_usage": {"description": tool.description if tool else "", "parameters": params, "required": required}}

    async def call_tool_async(self, name: str, arguments: Dict = None) -> Dict:
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
        if name in self._tools:
            self._tools[name].enabled = True
            return True
        return False

    def disable_tool(self, name: str) -> bool:
        if name in self._tools:
            self._tools[name].enabled = False
            return True
        return False

    def delete_tool(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get_tool_stats(self) -> Dict:
        tools = list(self._tools.values())
        total_calls = sum(t.call_count for t in tools)
        enabled_count = sum(1 for t in tools if t.enabled)
        by_category = {}
        for t in tools:
            if t.category not in by_category:
                by_category[t.category] = []
            by_category[t.category].append(t.name)
        return {"total_tools": len(tools), "enabled_tools": enabled_count, "disabled_tools": len(tools) - enabled_count,
            "total_calls": total_calls, "by_category": by_category,
            "top_tools": sorted([(t.name, t.call_count) for t in tools], key=lambda x: x[1], reverse=True)[:5]}

    def export_tools(self) -> List[Dict]:
        return [t.to_dict() for t in self._tools.values()]

    def import_tools(self, tools_data: List[Dict]) -> int:
        imported = 0
        for tool_data in tools_data:
            try:
                self.register(name=tool_data["name"], description=tool_data["description"], parameters=tool_data.get("parameters", {}),
                             enabled=tool_data.get("enabled", True), version=tool_data.get("version", "1.0.0"),
                             category=tool_data.get("category", "general"), tags=tool_data.get("tags", []), examples=tool_data.get("examples", []))
                imported += 1
            except Exception as e:
                logger.error(f"导入工具失败: {e}")
        return imported


tool_registry = ToolRegistry()