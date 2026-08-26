"""
WebSocket 服务端
"""
from __future__ import annotations

import json
import logging
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response

from server.protocol.message import (
    MessageType, create_response, create_error, create_pong
)
from server.protocol.actions import SystemActions
from server.config import get_config
from server.gateway.health import health_checker
from server.core.websocket.manager import get_websocket_manager
from server.core.utils import get_shared_http_client

logger = logging.getLogger(__name__)

ws_manager = get_websocket_manager()


async def handle_ping(websocket: WebSocket, message: dict, client_id: str):
    """处理 PING 协议消息，返回 PONG 响应。"""
    timestamp = message.get("timestamp", time.time())
    await ws_manager.send_message(client_id, create_pong(timestamp))


async def handle_live_connection(websocket: WebSocket, client_id: str):
    """处理实时语音客户端连接，接收并路由文本/音频消息。"""
    await ws_manager.connect(websocket, client_id, send_connected=False)
    logger.info(f"Live client connected: {client_id}")

    client_config = {
        "client_type": None,
        "room_id": None,
        "supported_markers": [],
        "marker_config": {}
    }

    from server.services.live_client import LiveClientHandler

    live_handler = LiveClientHandler(ws_manager, client_id, client_config)

    try:
        while True:
            msg = await websocket.receive()

            if msg.get("type") == "text":
                data = msg.get("text", "")
                try:
                    message = json.loads(data)
                    await live_handler.handle_message(websocket, message, client_id)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from live client {client_id}")

            elif msg.get("type") == "bytes":
                audio_data = msg.get("bytes", b"")
                await live_handler.handle_audio(websocket, audio_data, client_id)

            elif msg.get("type") == "disconnect":
                break

    except WebSocketDisconnect:
        logger.info(f"Live client disconnected: {client_id}")
    except Exception as e:
        logger.error(f"Live WebSocket error: {e}")
    finally:
        # H3: 与 websocket_handler 断连路径一致，显式触发清理（移除连接、
        # 释放双流式会话与 per-client 音频/ASR/打断模块实例）；disconnect
        # 对已不存在的 client_id 幂等返回，正常断开与异常路径均安全。
        await ws_manager.disconnect(client_id)
        logger.info(f"Live client cleanup: {client_id}")


async def handle_system_health(websocket: WebSocket, message: dict, client_id: str):
    """处理系统健康查询请求，返回所有注册服务的健康状态。"""
    request_id = message.get("request_id", "")
    status = health_checker.get_all_status()
    await ws_manager.send_message(client_id, create_response(
        request_id=request_id,
        action=SystemActions.HEALTH,
        data=status
    ))


async def websocket_handler(websocket: WebSocket, client_id: str):
    """主 WebSocket 消息处理器——解析 JSON 并按 action 分发到注册的处理器。"""
    await ws_manager.connect(websocket, client_id, send_connected=False)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await ws_manager.send_message(client_id, create_error(
                    request_id="",
                    action="",
                    code="INVALID_JSON",
                    message="Invalid JSON format"
                ))
                continue

            msg_type = message.get("type")

            if msg_type == MessageType.PING.value:
                await handle_ping(websocket, message, client_id)
                continue

            action = message.get("action", "")
            request_id = message.get("request_id", "")

            if action == SystemActions.HEALTH:
                await handle_system_health(websocket, message, client_id)
                continue

            handler = ws_manager.get_handler(action)
            if handler:
                try:
                    await handler(websocket, message, client_id)
                except Exception as e:
                    logger.error(f"Handler error for {action}: {e}", exc_info=True)
                    await ws_manager.send_message(client_id, create_error(
                        request_id=request_id,
                        action=action,
                        code="HANDLER_ERROR",
                        # BUG-B-M7 修复: 不向客户端返回内部异常信息,仅返回通用错误消息
                        message="处理请求时发生内部错误"
                    ))
            elif msg_type:
                await ws_manager.handle_message(client_id, message)
            else:
                logger.warning(f"未知的 WebSocket action: {action}")
                await websocket.send_json({"type": "error", "data": {"message": f"未知操作: {action}"}})

    except WebSocketDisconnect:
        await ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await ws_manager.disconnect(client_id)


def register_gateway_routes(app: FastAPI):
    """Register gateway routes onto an existing FastAPI app

    Gateway只负责：
    - WebSocket端点 (/ws, /ws/live)
    - WebSocket统计 (/api/ws/stats)
    - Control服务代理 (/control/{path})
    - WebSocket处理器注册
    """
    config = get_config()

    control_service_url = getattr(config.services, 'control_service_url', 'http://localhost:8765')

    health_checker.register_service("asr")
    health_checker.register_service("tts")

    from server.services.tts_service import get_tts_service
    from server.services.asr_service import get_asr_service

    tts_service = get_tts_service()

    asr_service = get_asr_service()

    from server.handlers.chat import register_chat_handlers
    from server.handlers.memory import register_memory_handlers
    from server.handlers.audio import register_audio_handlers
    from server.handlers.tools import register_tools_handlers
    from server.handlers.plugin import register_plugin_handlers
    from server.handlers.acp import register_acp_handlers
    from server.handlers.mcp import register_mcp_handlers
    from server.handlers.config import register_config_handlers
    from server.handlers.metrics import register_metrics_handlers
    from server.handlers.system import register_system_handlers
    from server.handlers.dream import register_dream_handlers

    register_chat_handlers(ws_manager)
    register_memory_handlers(ws_manager)
    register_tools_handlers(ws_manager)
    register_plugin_handlers(ws_manager)
    register_audio_handlers(ws_manager, asr_service, tts_service)
    register_acp_handlers(ws_manager)
    register_mcp_handlers(ws_manager)
    register_config_handlers(ws_manager)
    register_metrics_handlers(ws_manager)
    register_system_handlers(ws_manager)
    register_dream_handlers(ws_manager)

    # 触发 ChatWebSocketHandler 单例初始化，注册 type-based handlers
    # (chat/chat_stream/subscribe/unsubscribe/ping/cancel/config)
    # 否则前端发送 type-based 消息会报"未知消息类型: config"
    # 详见 .trae/documents/20260720_模块0_修复WS连接问题.md
    from server.core.websocket.handlers import get_chat_handler
    get_chat_handler()

    from server.handlers.audio import init_interrupt_module, init_audio_stream_processor
    init_interrupt_module()
    init_audio_stream_processor(asr_service)

    @app.get("/api/ws/stats")
    async def get_ws_stats():
        return ws_manager.get_stats()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        import uuid
        client_id = str(uuid.uuid4())
        try:
            await websocket_handler(websocket, client_id)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")

    @app.websocket("/ws/live")
    async def live_websocket_endpoint(websocket: WebSocket):
        import uuid
        client_id = str(uuid.uuid4())
        try:
            await handle_live_connection(websocket, client_id)
        except Exception as e:
            logger.error(f"Live WebSocket error: {e}")

    @app.api_route("/control/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    async def proxy_control(request: Request, path: str):
        import httpx
        import ipaddress
        import socket
        from urllib.parse import urlparse

        if not control_service_url or not control_service_url.startswith('http'):
            return Response(
                content=json.dumps({"error": "Control service not configured", "running": False}),
                status_code=503,
                media_type="application/json",
            )

        target_url = f"{control_service_url}/control/{path}"

        query_params = str(request.query_params)
        if query_params:
            target_url += f"?{query_params}"

        # SSRF 防护：验证目标 URL 主机与配置的 control_service_url 一致（白名单）
        parsed_config = urlparse(control_service_url)
        parsed_target = urlparse(target_url)
        target_host = parsed_target.hostname

        if parsed_target.hostname != parsed_config.hostname:
            return Response(
                content=json.dumps({"error": "Target host not allowed"}),
                status_code=403,
                media_type="application/json",
            )

        # SSRF 防护：阻止访问内部/保留 IP 地址范围（防止访问云元数据端点等）
        # 允许的主机白名单（localhost 用于本地开发默认配置）
        allowed_hosts = {"localhost", "127.0.0.1", "::1"}
        if target_host and target_host not in allowed_hosts:
            try:
                infos = socket.getaddrinfo(target_host, None)
                for info in infos:
                    ip = ipaddress.ip_address(info[4][0])
                    if ip.is_link_local or ip.is_private or ip.is_reserved:
                        return Response(
                            content=json.dumps({"error": "Access to internal addresses is blocked"}),
                            status_code=403,
                            media_type="application/json",
                        )
            except Exception:
                pass

        # SSRF 防护：过滤敏感请求头，防止凭据泄露到代理目标
        sensitive_headers = {"authorization", "cookie", "set-cookie", "x-api-key"}
        headers = {k: v for k, v in request.headers.items() if k.lower() not in sensitive_headers}
        headers.pop("host", None)

        body = await request.body()

        client = get_shared_http_client()
        try:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body if body else None,
                timeout=30.0,
            )

            excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
            response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in excluded_headers
            }

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get("content-type"),
            )
        except httpx.ConnectError:
            return Response(
                content=json.dumps({"error": "Control service not available", "running": False}),
                status_code=503,
                media_type="application/json",
            )
        except httpx.RequestError as e:
            logger.error(f"Control proxy error: {e}")
            return Response(
                content=json.dumps({"error": "Proxy error", "detail": str(e)}),
                status_code=502,
                media_type="application/json",
            )
