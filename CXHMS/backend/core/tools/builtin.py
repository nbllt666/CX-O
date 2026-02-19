"""
内置工具 - 强制开启，无需注册

这些工具对所有 Agent 默认可用，不依赖工具注册表
"""

import json
import math
import random as random_module
from datetime import datetime
from typing import Any, Dict, List


class BuiltinTools:
    """内置工具集合 - 单例模式，全局可用"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

    @staticmethod
    def calculator(expression: str) -> Dict[str, Any]:
        """
        执行数学计算

        Args:
            expression: 数学表达式，如 "2 + 2", "sqrt(16)", "sin(pi/2)"

        Returns:
            计算结果
        """
        try:
            # 定义允许的安全函数和常量
            safe_dict = {
                "abs": abs,
                "round": round,
                "max": max,
                "min": min,
                "sum": sum,
                "pow": pow,
                "sqrt": math.sqrt,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "asin": math.asin,
                "acos": math.acos,
                "atan": math.atan,
                "sinh": math.sinh,
                "cosh": math.cosh,
                "tanh": math.tanh,
                "exp": math.exp,
                "log": math.log,
                "log10": math.log10,
                "log2": math.log2,
                "ceil": math.ceil,
                "floor": math.floor,
                "trunc": math.trunc,
                "pi": math.pi,
                "e": math.e,
                "tau": math.tau,
                "inf": math.inf,
                "nan": math.nan,
            }

            # 编译表达式
            code = compile(expression, "<string>", "eval")

            # 检查是否包含不安全的名称
            for name in code.co_names:
                if name not in safe_dict:
                    return {
                        "success": False,
                        "error": f"不安全的函数或变量: {name}",
                        "result": None,
                    }

            # 执行计算
            result = eval(code, {"__builtins__": {}}, safe_dict)

            return {"success": True, "result": result, "expression": expression}

        except Exception as e:
            return {"success": False, "error": str(e), "result": None}

    @staticmethod
    def datetime_tool(
        format: str = "YYYY-MM-DD HH:mm:ss", timezone: str = "local"
    ) -> Dict[str, Any]:
        """
        获取当前日期和时间

        Args:
            format: 日期格式，如 "YYYY-MM-DD HH:mm:ss"
            timezone: 时区，如 "local", "UTC"

        Returns:
            当前时间信息
        """
        try:
            now = datetime.now()

            # 转换格式
            format_mapping = {
                "YYYY": "%Y",
                "MM": "%m",
                "DD": "%d",
                "HH": "%H",
                "mm": "%M",
                "ss": "%S",
            }

            python_format = format
            for key, value in format_mapping.items():
                python_format = python_format.replace(key, value)

            formatted_time = now.strftime(python_format)

            return {
                "success": True,
                "formatted": formatted_time,
                "timestamp": now.timestamp(),
                "iso": now.isoformat(),
                "year": now.year,
                "month": now.month,
                "day": now.day,
                "hour": now.hour,
                "minute": now.minute,
                "second": now.second,
                "weekday": now.strftime("%A"),
                "timezone": timezone,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def random(min: int = 0, max: int = 100, type: str = "int") -> Dict[str, Any]:
        """
        生成随机数

        Args:
            min: 最小值（包含）
            max: 最大值（包含）
            type: 类型，"int" 或 "float"

        Returns:
            随机数
        """
        try:
            if type == "int":
                result = random_module.randint(min, max)
            elif type == "float":
                result = random_module.uniform(min, max)
            else:
                return {"success": False, "error": f"不支持的类型: {type}，请使用 'int' 或 'float'"}

            return {"success": True, "value": result, "min": min, "max": max, "type": type}

        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def json_format(json_string: str, indent: int = 2) -> Dict[str, Any]:
        """
        格式化 JSON 字符串

        Args:
            json_string: 要格式化的 JSON 字符串
            indent: 缩进空格数

        Returns:
            格式化后的 JSON
        """
        try:
            # 解析 JSON
            data = json.loads(json_string)

            # 格式化
            formatted = json.dumps(data, indent=indent, ensure_ascii=False)

            return {
                "success": True,
                "formatted": formatted,
                "compact": json.dumps(data, ensure_ascii=False),
                "is_valid": True,
                "type": type(data).__name__,
            }

        except json.JSONDecodeError as e:
            return {"success": False, "error": f"JSON 解析错误: {str(e)}", "is_valid": False}
        except Exception as e:
            return {"success": False, "error": str(e), "is_valid": False}

    @classmethod
    def get_all_tools(cls) -> List[Dict[str, Any]]:
        """
        获取所有内置工具的 OpenAI 格式定义

        Returns:
            工具定义列表
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "执行数学计算，支持基本运算、三角函数、对数、幂运算等。例如：'2 + 2', 'sqrt(16)', 'sin(pi/2)'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string", "description": "数学表达式"}
                        },
                        "required": ["expression"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "datetime",
                    "description": "获取当前日期和时间信息",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "format": {
                                "type": "string",
                                "description": "日期格式，如 'YYYY-MM-DD HH:mm:ss'",
                                "default": "YYYY-MM-DD HH:mm:ss",
                            },
                            "timezone": {
                                "type": "string",
                                "description": "时区",
                                "default": "local",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "random",
                    "description": "生成随机数",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "min": {"type": "integer", "description": "最小值", "default": 0},
                            "max": {"type": "integer", "description": "最大值", "default": 100},
                            "type": {
                                "type": "string",
                                "description": "类型: 'int' 或 'float'",
                                "default": "int",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "json_format",
                    "description": "格式化 JSON 字符串，使其更易读",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "json_string": {
                                "type": "string",
                                "description": "要格式化的 JSON 字符串",
                            },
                            "indent": {
                                "type": "integer",
                                "description": "缩进空格数",
                                "default": 2,
                            },
                        },
                        "required": ["json_string"],
                    },
                },
            },
        ]

    @classmethod
    def call_tool(cls, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用指定工具

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        tools_map = {
            "calculator": cls.calculator,
            "datetime": cls.datetime_tool,
            "random": cls.random,
            "json_format": cls.json_format,
        }

        if name not in tools_map:
            return {"success": False, "error": f"未知工具: {name}"}

        # 获取工具定义
        all_tools = cls.get_all_tools()
        tool_def = None
        for t in all_tools:
            if t.get("function", {}).get("name") == name:
                tool_def = t.get("function", {})
                break

        try:
            return tools_map[name](**arguments)
        except TypeError as e:
            params = tool_def.get("parameters", {}).get("properties", {}) if tool_def else {}
            required = tool_def.get("parameters", {}).get("required", []) if tool_def else []
            valid_params = list(params.keys())
            return {
                "success": False,
                "error": f"参数错误: {str(e)}。正确参数为: {', '.join(valid_params)}",
                "tool_name": name,
                "correct_usage": {
                    "description": tool_def.get("description", "") if tool_def else "",
                    "parameters": params,
                    "required": required,
                },
            }
        except Exception as e:
            params = tool_def.get("parameters", {}).get("properties", {}) if tool_def else {}
            required = tool_def.get("parameters", {}).get("required", []) if tool_def else []
            return {
                "success": False,
                "error": f"工具执行错误: {str(e)}",
                "tool_name": name,
                "correct_usage": {
                    "description": tool_def.get("description", "") if tool_def else "",
                    "parameters": params,
                    "required": required,
                },
            }


# 全局单例实例
builtin_tools = BuiltinTools()


def get_builtin_tools() -> List[Dict[str, Any]]:
    """获取所有内置工具的 OpenAI 格式定义"""
    return builtin_tools.get_all_tools()


def call_builtin_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """调用内置工具"""
    return builtin_tools.call_tool(name, arguments)


def register_builtin_tools():
    """
    向后兼容的注册函数
    内置工具现在强制开启，无需注册到注册表
    """
    # 内置工具不再注册到注册表，直接通过 BuiltinTools 类使用
    pass
