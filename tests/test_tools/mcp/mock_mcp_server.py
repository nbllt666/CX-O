# MCP 模拟服务器：基于 FastAPI 的 Mock MCP 服务
"""模拟 MCP 服务器，用于测试主系统的 MCP 服务器注册、工具发现与调用链路。

启动后在后台线程运行 uvicorn，暴露以下端点：
- GET  /health  -> {"status": "ok"}
- GET  /tools   -> {"tools": [...]}
- POST /call    -> {"tool": "...", "arguments": {...}} -> 执行结果

默认加载 preset_tools.get_preset_definitions() 中的预置工具。
"""
import threading
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI

from tests.test_tools.mcp.preset_tools import (
    execute_tool,
    get_preset_definitions,
    list_tool_names,
)


class MockMCPServer:
    """MCP 模拟服务器，提供工具列表与调用执行。

    与 MockPluginServer 的模式一致：在后台 daemon 线程运行 uvicorn，
    通过 start()/stop() 控制生命周期，is_running() 查询状态。
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8600,
        tools: Optional[List[Dict[str, Any]]] = None,
    ):
        self.host = host
        self.port = port
        # 默认加载预置工具
        self.tools = tools if tools is not None else get_preset_definitions()

        # 调用日志
        self.call_logs: List[Dict[str, Any]] = []

        # FastAPI 应用与路由
        self.app = FastAPI()
        self._setup_routes()

        # uvicorn 服务器
        self._server: Optional[uvicorn.Server] = None
        self._server_thread: Optional[threading.Thread] = None

    def _setup_routes(self) -> None:
        @self.app.get("/health")
        async def health():
            return {"status": "ok"}

        @self.app.get("/tools")
        async def tools():
            return {"tools": self.tools}

        @self.app.post("/call")
        async def call_tool(payload: dict):
            """工具调用端点。

            请求格式：{"tool": "<tool_name>", "arguments": {...}}
            返回格式：{"success": true/false, "result": ..., "error": ...}
            """
            import datetime

            tool_name = payload.get("tool", "")
            arguments = payload.get("arguments", {}) or {}

            log_entry = {
                "tool": tool_name,
                "arguments": arguments,
                "called_at": datetime.datetime.now().isoformat(),
            }

            # 校验工具是否在已注册工具列表中
            registered_names = {t.get("name", "") for t in self.tools}
            if tool_name not in registered_names:
                log_entry["status"] = "rejected"
                log_entry["error"] = f"工具 {tool_name} 未注册"
                self.call_logs.append(log_entry)
                return {
                    "success": False,
                    "error": f"工具 {tool_name} 未在 MCP 服务器中注册",
                }

            # 优先使用预置工具处理器实际执行
            if tool_name in list_tool_names():
                result = execute_tool(tool_name, arguments)
                log_entry["status"] = "success" if result.get("success") else "failed"
                log_entry["result"] = result
                self.call_logs.append(log_entry)
                return result

            # 非预置工具（用户自定义）：返回 Mock 响应
            log_entry["status"] = "mocked"
            mock_result = {
                "success": True,
                "result": f"[mock] 工具 {tool_name} 被调用，参数: {arguments}",
                "tool": tool_name,
                "arguments": arguments,
            }
            log_entry["result"] = mock_result
            self.call_logs.append(log_entry)
            return mock_result

    def start(self) -> None:
        """在后台 daemon 线程中启动 uvicorn 服务，非阻塞。"""
        if self._server is not None and self._server_thread is not None and self._server_thread.is_alive():
            return  # 已在运行
        config = uvicorn.Config(
            self.app, host=self.host, port=self.port, log_level="warning"
        )
        self._server = uvicorn.Server(config)
        self._server_thread = threading.Thread(target=self._server.run, daemon=True)
        self._server_thread.start()

    def stop(self) -> None:
        """停止 uvicorn 服务。"""
        if self._server is not None:
            self._server.should_exit = True
        if self._server_thread is not None:
            self._server_thread.join(timeout=5.0)
            self._server_thread = None
        self._server = None

    def is_running(self) -> bool:
        """返回服务是否正在运行。"""
        return (
            self._server is not None
            and self._server_thread is not None
            and self._server_thread.is_alive()
        )
