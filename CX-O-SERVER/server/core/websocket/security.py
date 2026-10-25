"""WebSocket 握手鉴权——网关与 /api/ws 路由共用的安全闸门。"""
from __future__ import annotations

import ipaddress
import os
import secrets
from typing import Optional

from fastapi import WebSocket

from server.config import get_config


def is_loopback_client(websocket: WebSocket) -> bool:
    """判断 WebSocket 对端是否为本机连接。

    无法取得对端地址或地址不可解析时按“非本机”处理（fail-closed），
    避免反向代理/精简 ASGI 实现未提供 client 信息时被误判为本机而绕过密钥。
    测试客户端（TestClient）如需本机语义，应显式提供 127.0.0.1 形式地址。
    """
    client = websocket.client
    if client is None or not client.host:
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        return False


def authorize_websocket(websocket: WebSocket) -> Optional[str]:
    """WebSocket 握手鉴权。

    返回 None 表示放行，否则返回拒绝原因：
    - Origin 不在配置白名单且非 same-origin 时拒绝（防跨站网页劫持）；
    - 配置了 ADMIN_API_KEY 时，要求 x-api-key 头或 token/api_key 查询参数匹配；
    - 未配置密钥时，仅允许本机连接，拒绝局域网内任意设备的裸连接。
    """
    config = get_config()
    cors = config.cors
    origin = websocket.headers.get("origin")
    if origin:
        allowed_origins = set(cors.origins or [])
        host = websocket.headers.get("host", "")
        same_origin = bool(host) and origin in (f"http://{host}", f"https://{host}")
        if origin not in allowed_origins and not same_origin:
            return "origin_not_allowed"

    admin_key = os.environ.get("ADMIN_API_KEY", "")
    provided = (
        websocket.headers.get("x-api-key")
        or websocket.query_params.get("token")
        or websocket.query_params.get("api_key")
    )
    if admin_key:
        if not provided or not secrets.compare_digest(provided, admin_key):
            return "invalid_credentials"
    elif not is_loopback_client(websocket):
        return "remote_requires_api_key"

    return None
