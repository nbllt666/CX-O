# MCP 测试工具预置工具定义与执行处理器
"""预置工具集：提供计算器、字符串反转、时间查询、回声四个测试工具。

每个工具包含：
- 定义（name / description / parameters JSON Schema）：暴露给主系统
- 处理器（handler）：当主系统通过 POST /call 调用时实际执行
"""
import datetime
from typing import Any, Dict, List


def _tool_calculator(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """简易计算器：支持加减乘除表达式求值。

    参数 expression 为字符串，例如 "1 + 2"、"3.5 * 4"、"10 / 2"。
    仅支持 + - * / 四则运算，避免使用 eval 以保证安全。
    """
    expression = arguments.get("expression", "")
    if not isinstance(expression, str) or not expression.strip():
        return {"success": False, "error": "expression 参数必须为非空字符串"}

    expr = expression.strip()
    try:
        result = _safe_eval_arithmetic(expr)
    except ValueError as e:
        return {"success": False, "error": f"表达式解析失败: {e}"}
    except ZeroDivisionError:
        return {"success": False, "error": "除数不能为 0"}
    except Exception as e:
        return {"success": False, "error": f"计算失败: {e}"}

    return {
        "success": True,
        "result": result,
        "expression": expr,
    }


def _safe_eval_arithmetic(expr: str) -> float:
    """安全解析仅含 + - * / 与数字/小数点/空格的算术表达式。

    通过分词与栈式求值实现，避免 eval 注入风险。
    支持整数与浮点数，支持运算优先级。
    """
    import re

    # 仅允许数字、空格、+ - * / . ( )
    if not re.match(r"^[\d\s\+\-\*/\.\(\)]+$", expr):
        raise ValueError("表达式包含非法字符")

    tokens = re.findall(r"\d+\.?\d*|[\+\-\*/\(\)]", expr)
    if not tokens:
        raise ValueError("未识别到有效 token")

    # 中缀转后缀（Shunting-Yard）
    precedence = {"+": 1, "-": 1, "*": 2, "/": 2}
    output: List[str] = []
    operators: List[str] = []

    for token in tokens:
        if token == "":
            continue
        if re.match(r"^\d+\.?\d*$", token):
            output.append(token)
        elif token in ("+", "-", "*", "/"):
            while (
                operators
                and operators[-1] != "("
                and precedence.get(operators[-1], 0) >= precedence[token]
            ):
                output.append(operators.pop())
            operators.append(token)
        elif token == "(":
            operators.append(token)
        elif token == ")":
            while operators and operators[-1] != "(":
                output.append(operators.pop())
            if not operators:
                raise ValueError("括号不匹配")
            operators.pop()  # 弹出 "("

    while operators:
        op = operators.pop()
        if op == "(":
            raise ValueError("括号不匹配")
        output.append(op)

    # 后缀求值
    stack: List[float] = []
    for token in output:
        if re.match(r"^\d+\.?\d*$", token):
            stack.append(float(token))
        else:
            if len(stack) < 2:
                raise ValueError("表达式不完整")
            b = stack.pop()
            a = stack.pop()
            if token == "+":
                stack.append(a + b)
            elif token == "-":
                stack.append(a - b)
            elif token == "*":
                stack.append(a * b)
            elif token == "/":
                if b == 0:
                    raise ZeroDivisionError("division by zero")
                stack.append(a / b)

    if len(stack) != 1:
        raise ValueError("表达式求值异常")

    result = stack[0]
    # 若为整数则返回 int，否则返回 float
    if result == int(result):
        return int(result)
    return result


def _tool_string_reverse(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """字符串反转：返回输入字符串的逆序。"""
    text = arguments.get("text", "")
    if not isinstance(text, str):
        return {"success": False, "error": "text 参数必须是字符串"}
    return {"success": True, "result": text[::-1], "length": len(text)}


def _tool_time_query(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """时间查询：返回当前时间。"""
    fmt = arguments.get("format", "%Y-%m-%d %H:%M:%S")
    if not isinstance(fmt, str):
        return {"success": False, "error": "format 参数必须是字符串"}
    now = datetime.datetime.now()
    try:
        return {
            "success": True,
            "result": now.strftime(fmt),
            "iso8601": now.isoformat(),
            "timestamp": now.timestamp(),
            "weekday": now.strftime("%A"),
        }
    except Exception as e:
        return {"success": False, "error": f"时间格式化失败: {e}"}


def _tool_echo(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """回声工具：原样返回输入内容，用于验证调用链路。"""
    text = arguments.get("text", "")
    return {
        "success": True,
        "result": text,
        "received_at": datetime.datetime.now().isoformat(),
        "echo_type": type(text).__name__,
    }


# 工具定义（JSON Schema 格式，供主系统注册时使用）
PRESET_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "calculator",
        "description": "计算器工具，支持加减乘除四则运算表达式，例如 '1 + 2'、'3.5 * 4'",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "算术表达式，仅支持 + - * / 与数字及括号",
                },
            },
            "required": ["expression"],
        },
    },
    {
        "name": "string_reverse",
        "description": "字符串反转工具，返回输入字符串的逆序",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要反转的字符串"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "time_query",
        "description": "时间查询工具，返回当前时间，支持自定义格式化",
        "parameters": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "strftime 格式字符串，默认 '%Y-%m-%d %H:%M:%S'",
                    "default": "%Y-%m-%d %H:%M:%S",
                },
            },
            "required": [],
        },
    },
    {
        "name": "echo",
        "description": "回声工具，原样返回输入内容，用于验证调用链路",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要回声的内容",
                },
            },
            "required": ["text"],
        },
    },
]

# 工具名 → 处理器映射
TOOL_HANDLERS = {
    "calculator": _tool_calculator,
    "string_reverse": _tool_string_reverse,
    "time_query": _tool_time_query,
    "echo": _tool_echo,
}


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """执行指定工具，返回结果字典。

    Args:
        tool_name: 工具名称
        arguments: 工具参数

    Returns:
        包含 success 字段的结果字典
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {"success": False, "error": f"未知工具: {tool_name}"}
    try:
        return handler(arguments or {})
    except Exception as e:
        return {"success": False, "error": f"工具执行异常: {e}"}


def get_preset_definitions() -> List[Dict[str, Any]]:
    """返回预置工具定义的深拷贝，避免外部修改污染。"""
    import copy

    return copy.deepcopy(PRESET_TOOL_DEFINITIONS)


def list_tool_names() -> List[str]:
    """返回所有预置工具名列表。"""
    return [t["name"] for t in PRESET_TOOL_DEFINITIONS]
