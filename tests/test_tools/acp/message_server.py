"""ACP 独立消息接收服务器

基于 FastAPI 实现 HTTP 消息接收端点，作为独立 ACP 节点的消息接收层。

端点：
- POST /acp/message  接收其他 Agent 发来的消息
- GET  /acp/health   健康检查
- GET  /acp/info     返回本节点 Agent 信息
"""
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def create_app(
    agent_id: str,
    agent_name: str,
    http_port: int,
    capabilities: List[str],
    on_message_received: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> FastAPI:
    """创建消息接收 FastAPI 应用

    Args:
        agent_id: 本节点 Agent ID
        agent_name: 本节点 Agent 名称
        http_port: HTTP 端口
        capabilities: 能力列表
        on_message_received: 消息接收回调
    """
    app = FastAPI(title="ACP Test Tool Message Server")

    @app.get("/acp/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "agent_id": agent_id,
            "agent_name": agent_name,
            "timestamp": datetime.now().isoformat(),
        }

    @app.get("/acp/info")
    async def info() -> Dict[str, Any]:
        return {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "host": "0.0.0.0",
            "port": http_port,
            "capabilities": capabilities,
            "version": "1.0.0",
        }

    @app.post("/acp/message")
    async def receive_message(request: Request) -> Dict[str, Any]:
        try:
            payload = await request.json()
        except Exception as exc:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "error": f"无效的 JSON: {exc}"},
            )

        message = {
            "id": payload.get("id", ""),
            "type": payload.get("msg_type", payload.get("type", "chat")),
            "from_agent_id": payload.get("from_agent_id", ""),
            "from_agent_name": payload.get("from_agent_name", ""),
            "to_agent_id": payload.get("to_agent_id"),
            "to_group_id": payload.get("to_group_id"),
            "content": payload.get("content", {}),
            "timestamp": payload.get("timestamp", datetime.now().isoformat()),
            "is_read": False,
            "is_sent": False,
            "metadata": payload.get("metadata", {}),
        }

        if on_message_received:
            try:
                on_message_received(message)
            except Exception:
                pass

        return {"status": "ok", "message_id": message["id"]}

    @app.post("/acp/receive")
    async def receive_external(request: Request) -> Dict[str, Any]:
        """兼容主系统的 /acp/receive 端点"""
        return await receive_message(request)

    return app


class MessageServer:
    """消息接收服务器

    在后台线程运行 uvicorn 服务，接收其他 Agent 的消息。
    """

    def __init__(
        self,
        agent_id: str,
        agent_name: str,
        host: str,
        http_port: int,
        capabilities: List[str],
        on_message_received: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.host = host
        self.http_port = http_port
        self.capabilities = list(capabilities)
        self.on_message_received = on_message_received

        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """启动消息服务器（后台线程）"""
        if self._running:
            return

        app = create_app(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            http_port=self.http_port,
            capabilities=self.capabilities,
            on_message_received=self.on_message_received,
        )

        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.http_port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        self._running = True

        # 等待服务器启动
        time.sleep(0.5)

    def stop(self) -> None:
        """停止消息服务器"""
        self._running = False
        if self._server:
            try:
                self._server.should_exit = True
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._server = None

    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "host": self.host,
            "http_port": self.http_port,
            "agent_id": self.agent_id,
        }
