"""
WebSocket 路由 - 提供实时双向通信
"""

import asyncio
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.core.logging_config import get_contextual_logger
from server.core.websocket import get_websocket_manager
from server.services.live_client import LiveClientHandler

logger = get_contextual_logger(__name__)
router = APIRouter()


class LiveTTSSyncBroadcaster:
    """TTS 播放同步广播器"""

    def __init__(self):
        self._ws_manager = None
        self._current_playback_id = None
        self._tick_task = None
        self._start_time = None
        self._duration = 0
        self._text = ""
        self._running = False

    def _get_ws_manager(self):
        if self._ws_manager is None:
            self._ws_manager = get_websocket_manager()
        return self._ws_manager

    async def start_playback(self, text: str, duration_ms: int):
        """开始 TTS 播放同步广播"""
        await self.end_playback()

        import uuid
        self._current_playback_id = str(uuid.uuid4())[:12]
        self._text = text
        self._duration = duration_ms
        self._start_time = time.monotonic()
        self._running = True

        server_ts = int(time.time() * 1000)
        sync_msg = {
            "type": "tts_sync",
            "data": {
                "playback_id": self._current_playback_id,
                "server_ts": server_ts,
                "text": text,
                "duration": duration_ms,
            },
        }
        ws_mgr = self._get_ws_manager()
        await ws_mgr.broadcast_to_channel("live", sync_msg)

        self._tick_task = asyncio.create_task(self._tick_loop())
        logger.info(f"TTS sync started: {self._current_playback_id}, duration={duration_ms}ms")

    async def _tick_loop(self):
        """定时广播 tts_tick"""
        try:
            while self._running:
                await asyncio.sleep(0.1)
                if not self._running:
                    break

                elapsed = (time.monotonic() - self._start_time) * 1000
                position = min(int(elapsed), self._duration)
                server_ts = int(time.time() * 1000)

                tick_msg = {
                    "type": "tts_tick",
                    "data": {
                        "playback_id": self._current_playback_id,
                        "server_ts": server_ts,
                        "position": position,
                    },
                }
                ws_mgr = self._get_ws_manager()
                await ws_mgr.broadcast_to_channel("live", tick_msg)

                if position >= self._duration:
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await self.end_playback()

    async def end_playback(self):
        """结束当前播放"""
        self._running = False
        if self._tick_task and not self._tick_task.done():
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
            self._tick_task = None

        if self._current_playback_id:
            server_ts = int(time.time() * 1000)
            end_msg = {
                "type": "tts_end",
                "data": {
                    "playback_id": self._current_playback_id,
                    "server_ts": server_ts,
                },
            }
            ws_mgr = self._get_ws_manager()
            await ws_mgr.broadcast_to_channel("live", end_msg)
            logger.info(f"TTS sync ended: {self._current_playback_id}")
            self._current_playback_id = None


_tts_sync_broadcaster: Optional[LiveTTSSyncBroadcaster] = None


def get_tts_sync_broadcaster() -> LiveTTSSyncBroadcaster:
    global _tts_sync_broadcaster
    if _tts_sync_broadcaster is None:
        _tts_sync_broadcaster = LiveTTSSyncBroadcaster()
    return _tts_sync_broadcaster


@router.websocket("/ws/{agent_id}")
async def websocket_agent_endpoint(websocket: WebSocket, agent_id: str, timeout: int = 60):
    """
    Agent 专用 WebSocket 端点

    前端主要使用的端点，支持自动关联 Agent 和离线超时配置

    Path 参数:
    - agent_id: Agent ID

    Query 参数:
    - timeout: 离线超时时间（秒），默认 60
    """
    ws_manager = get_websocket_manager()

    connection = await ws_manager.connect(
        websocket=websocket, metadata={"agent_id": agent_id, "timeout": timeout}
    )

    ws_manager.set_agent_timeout(agent_id, timeout)

    client_id = connection.client_id

    try:
        while True:
            message = await connection.receive()

            if "agent_id" not in message:
                message["agent_id"] = agent_id

            await ws_manager.handle_message(client_id, message)

    except WebSocketDisconnect:
        logger.info(f"WebSocket Agent 客户端断开连接: {client_id}, agent={agent_id}")
        await ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket Agent 错误 {client_id}: {e}")
        await ws_manager.disconnect(client_id)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket, client_id: Optional[str] = None, token: Optional[str] = None
):
    """
    WebSocket 连接端点

    支持实时聊天、消息订阅、心跳检测等功能

    Query 参数:
    - client_id: 客户端ID（可选，不传则自动生成）
    - token: 认证令牌（可选）
    """
    ws_manager = get_websocket_manager()

    # 建立连接
    connection = await ws_manager.connect(
        websocket=websocket, client_id=client_id, metadata={"token": token} if token else {}
    )

    client_id = connection.client_id

    try:
        # 保持连接并处理消息
        while True:
            # 接收消息
            message = await connection.receive()

            # 处理消息
            await ws_manager.handle_message(client_id, message)

    except WebSocketDisconnect:
        logger.info(f"WebSocket 客户端断开连接: {client_id}")
        await ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket 错误 {client_id}: {e}")
        await ws_manager.disconnect(client_id)


@router.websocket("/ws/chat")
async def websocket_chat_endpoint(
    websocket: WebSocket, session_id: Optional[str] = None, agent_id: Optional[str] = "default"
):
    """
    WebSocket 聊天专用端点

    简化版聊天连接，自动订阅到指定会话

    Query 参数:
    - session_id: 会话ID（可选）
    - agent_id: Agent ID（可选，默认 default）
    """
    ws_manager = get_websocket_manager()

    # 建立连接
    connection = await ws_manager.connect(
        websocket=websocket, metadata={"session_id": session_id, "agent_id": agent_id}
    )

    client_id = connection.client_id

    # 如果有会话ID，订阅到该会话频道
    if session_id:
        ws_manager.subscribe_to_channel(client_id, f"session:{session_id}")

    try:
        while True:
            message = await connection.receive()

            # 自动添加会话和Agent信息
            if "session_id" not in message and session_id:
                message["session_id"] = session_id
            if "agent_id" not in message and agent_id:
                message["agent_id"] = agent_id

            await ws_manager.handle_message(client_id, message)

    except WebSocketDisconnect:
        logger.info(f"WebSocket 聊天客户端断开连接: {client_id}")
        await ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket 聊天错误 {client_id}: {e}")
        await ws_manager.disconnect(client_id)


@router.websocket("/ws/live")
async def websocket_live_endpoint(
    websocket: WebSocket, session_id: Optional[str] = None
):
    """
    直播专用 WebSocket 端点

    用于直播场景的实时通信，支持弹幕、音频、TTS 同步等

    Query 参数:
    - session_id: 会话ID（可选）
    """
    ws_manager = get_websocket_manager()

    connection = await ws_manager.connect(
        websocket=websocket, metadata={"session_id": session_id, "type": "live"}
    )

    client_id = connection.client_id

    ws_manager.subscribe_to_channel(client_id, "live")

    live_handler = LiveClientHandler(ws_manager, client_id, {})

    try:
        while True:
            raw = await websocket.receive()

            if "bytes" in raw:
                await live_handler.handle_audio(websocket, raw["bytes"], client_id)
            elif "text" in raw:
                import json
                try:
                    message = json.loads(raw["text"])
                except json.JSONDecodeError:
                    logger.warning(f"Live client sent invalid JSON: {raw['text'][:100]}")
                    continue

                await live_handler.handle_message(websocket, message, client_id)

    except WebSocketDisconnect:
        logger.info(f"直播客户端断开连接: {client_id}")
        await ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"直播 WebSocket 错误 {client_id}: {e}")
        await ws_manager.disconnect(client_id)
