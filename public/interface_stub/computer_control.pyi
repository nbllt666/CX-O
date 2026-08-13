"""电脑控制 CXFC 插件服务接口契约存根（零实现，仅签名）。

源真理: public/schema/computer_control_plugin.schema.json + computer_control_error_codes.json
完成 Skill: s0201
当前状态: 契约冻结——仅声明签名，无实现逻辑。
迁移自: .trae/specs/add-computer-control-cxfc/contracts/plugin_interface.pyi

本文件同时声明两类调用方边界：
- 插件服务端（Electron 主进程 HTTPS 插件服务）对外暴露的端点处理签名：
  GET /health、GET /tools、GET /skills、POST /call。
- 后端（CX-O-SERVER CXFCManager.call_tool）调用插件时使用的客户端签名。

安全边界（与冻结决策一致）：
- 认证：注册令牌经 Authorization: Bearer <token> 携带，令牌缺失/错误抛 UnauthorizedError。
- 防重放：每次 /call 携带唯一 request_id，时间窗内重复抛 ReplayError。
- TLS：自签名证书指纹在注册时校验（首次信任），指纹不匹配拒绝连接。
- 授权：本地授权状态未开启时，即使认证通过也抛 NotAuthorizedError，不执行任何本机动作。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = [
    "PluginError",
    "UnauthorizedError",
    "ReplayError",
    "InvalidArgumentError",
    "NotAuthorizedError",
    "ExecutionError",
    "TimeoutError",
    "SystemError",
    "PluginOfflineError",
    "ToolDescriptor",
    "CallRequest",
    "CallResponse",
    "HealthResponse",
    "ToolResult",
    "ScreenResult",
    "KeyboardResult",
    "CommandResult",
    "health",
    "list_tools",
    "list_skills",
    "call_tool",
]


class PluginError(Exception):
    """所有插件调用错误的基类。

    Attributes:
        error_code: 统一错误码（见 computer_control_error_codes.json）。
        http_status: 建议映射的 HTTP 状态码。
    """

    error_code: str = "SYSTEM_ERROR"
    http_status: int = 500

    def __init__(self, message: str) -> None: ...
    def __str__(self) -> str: ...


class UnauthorizedError(PluginError):
    """认证失败：注册令牌缺失/错误或 TLS 指纹不匹配。

    error_code: UNAUTHORIZED (401)。不得执行任何本机动作。
    """

    error_code: str = "UNAUTHORIZED"
    http_status: int = 401


class ReplayError(PluginError):
    """防重放拒绝：request_id 在当前时间窗内重复。

    error_code: REPLAY_DETECTED (409)。不得执行任何本机动作。
    """

    error_code: str = "REPLAY_DETECTED"
    http_status: int = 409


class InvalidArgumentError(PluginError):
    """参数非法：请求参数不符合工具请求契约。

    error_code: INVALID_ARGUMENT (400)。不得执行本机动作。
    """

    error_code: str = "INVALID_ARGUMENT"
    http_status: int = 400


class NotAuthorizedError(PluginError):
    """本地授权状态未开启（授权被撤销或未授权）。

    与 UnauthorizedError 不同：认证已通过，但本地授权关闭。
    error_code: NOT_AUTHORIZED (403)。不得执行任何本机动作。
    """

    error_code: str = "NOT_AUTHORIZED"
    http_status: int = 403


class ExecutionError(PluginError):
    """工具执行失败：进程启动失败、系统权限不足或执行链路错误。

    error_code: EXECUTION_FAILED (500)。
    """

    error_code: str = "EXECUTION_FAILED"
    http_status: int = 500


class TimeoutError(PluginError):
    """执行超时：超出 timeout_ms，已回收整个进程树。

    error_code: TIMEOUT (504)。
    """

    error_code: str = "TIMEOUT"
    http_status: int = 504


class SystemError(PluginError):
    """系统级失败：插件内部错误、配置缺失等。

    error_code: SYSTEM_ERROR (500)。
    """

    error_code: str = "SYSTEM_ERROR"
    http_status: int = 500


class PluginOfflineError(PluginError):
    """插件不可用：插件未注册、已断开或 /call 不可达。

    error_code: PLUGIN_OFFLINE (503)。
    """

    error_code: str = "PLUGIN_OFFLINE"
    http_status: int = 503


class ToolDescriptor:
    """工具描述（对应 computer_control_plugin.schema.json 中 tools 数组项）。"""

    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema（请求参数契约）
    returns: Dict[str, Any]  # JSON Schema（返回结构契约）


class CallRequest:
    """POST /call 请求体。"""

    tool: str
    arguments: Dict[str, Any]
    request_id: str


class HealthResponse:
    """GET /health 响应。"""

    name: str
    version: str
    status: str  # 如 "ok"
    authorized: bool


class ToolResult:
    """工具调用的公共返回外壳。"""

    success: bool
    tool: str
    result: Any
    error: Optional[str]
    error_code: Optional[str]
    authorized: bool


class ScreenResult(ToolResult):
    """屏幕控制返回：success、action、result、error、error_code、authorized。"""

    action: str


class KeyboardResult(ToolResult):
    """键盘控制返回：success、action、result、error、error_code、authorized。"""

    action: str


class CommandResult(ToolResult):
    """运行指令返回：success、exit_code、stdout（截断）、stderr（截断）、timed_out、truncated、error。"""

    exit_code: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool


class CallResponse:
    """后端接收 /call 的统一响应。"""

    success: bool
    tool: str
    result: Any
    error: Optional[str]
    error_code: Optional[str]
    authorized: bool


# ---------------------------------------------------------------------------
# 插件服务端端点签名（零实现）
# ---------------------------------------------------------------------------


def health() -> HealthResponse:
    """GET /health — 健康检查。

    Returns:
        HealthResponse: 插件名、版本、状态与授权状态。
    """
    ...


def list_tools() -> List[ToolDescriptor]:
    """GET /tools — 返回三个电脑控制工具描述列表。

    Returns:
        List[ToolDescriptor]: 稳定工具列表（computer_screen_control /
        computer_keyboard_control / computer_run_command）。
    """
    ...


def list_skills() -> List[Dict[str, Any]]:
    """GET /skills — 返回插件声明的技能清单。

    Returns:
        List[Dict[str, Any]]: 技能定义列表（结构见 CXFC SkillDefinition）。
    """
    ...


def call_tool(
    tool: str,
    arguments: Dict[str, Any],
    token: str,
    request_id: str,
) -> CallResponse:
    """POST /call — 执行已授权的电脑控制工具。

    调用顺序约束：
    1. 校验 Authorization: Bearer <token>，失败抛 UnauthorizedError。
    2. 校验 request_id 时间窗内是否重复，重复抛 ReplayError。
    3. 校验本地授权状态，未授权抛 NotAuthorizedError。
    4. 校验 tool 与 arguments 契约，非法抛 InvalidArgumentError。
    5. 执行本机动作；超时回收进程树抛 TimeoutError；权限/启动失败抛
       ExecutionError；其他系统失败抛 SystemError。

    Args:
        tool: 工具稳定标识（computer_screen_control /
            computer_keyboard_control / computer_run_command）。
        arguments: 结构化工具参数（对应 computer_control_plugin.schema.json 各工具请求契约）。
        token: 注册令牌（后端转发时以 Authorization: Bearer <token> 携带）。
        request_id: 唯一调用标识，用于防重放。

    Returns:
        CallResponse: 统一返回外壳，携带 result 与 error_code / authorized。

    Raises:
        UnauthorizedError: 令牌缺失/错误或 TLS 指纹不匹配。
        ReplayError: request_id 在当前时间窗内重复。
        NotAuthorizedError: 本地授权未开启。
        InvalidArgumentError: 工具名或参数不符合契约。
        ExecutionError: 进程启动失败或系统权限不足。
        TimeoutError: 执行超时，已回收进程树。
        SystemError: 其他系统级失败。
        PluginOfflineError: 插件不可达/未注册（后端调用侧）。
    """
    ...
