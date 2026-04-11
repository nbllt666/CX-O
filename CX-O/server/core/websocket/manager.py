import asyncio
import json
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Set

from fastapi import WebSocket

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class WebSocketConnection:
    def __init__(self, websocket: WebSocket, client_id: str, metadata: Optional[Dict] = None):
        self.websocket = websocket
        self.client_id = client_id
        self.metadata = metadata or {}
        self.connected_at = datetime.now()
        self.last_activity = datetime.now()
        self.subscriptions: Set[str] = set()

    async def send(self, data: Dict[str, Any]):
        try:
            await self.websocket.send_json(data)
            self.last_activity = datetime.now()
        except Exception as e:
            logger.error(f"发送消息失败 {self.client_id}: {e}")
            raise

    async def receive(self) -> Dict[str, Any]:
        data = await self.websocket.receive_json()
        self.last_activity = datetime.now()
        return data

    def subscribe(self, channel: str):
        self.subscriptions.add(channel)

    def unsubscribe(self, channel: str):
        self.subscriptions.discard(channel)

    def is_subscribed(self, channel: str) -> bool:
        return channel in self.subscriptions


class WebSocketManager:
    def __init__(self):
        self.connections: Dict[str, WebSocketConnection] = {}
        self.channels: Dict[str, Set[str]] = {}
        self.message_handlers: Dict[str, Callable] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        self._offline_callback: Optional[Callable] = None
        self._agent_timeouts: Dict[str, int] = {}

    async def connect(self, websocket: WebSocket, client_id: Optional[str] = None, metadata: Optional[Dict] = None) -> WebSocketConnection:
        await websocket.accept()
        if not client_id:
            import uuid
            client_id = str(uuid.uuid4())
        connection = WebSocketConnection(websocket, client_id, metadata)
        self.connections[client_id] = connection
        logger.info(f"WebSocket 连接已建立: {client_id}, 当前连接数: {len(self.connections)}")
        await connection.send({"type": "connected", "client_id": client_id, "timestamp": datetime.now().isoformat()})
        return connection

    async def disconnect(self, client_id: str):
        if client_id in self.connections:
            connection = self.connections[client_id]
            for channel in list(connection.subscriptions):
                self._remove_from_channel(channel, client_id)
            del self.connections[client_id]
            logger.info(f"WebSocket 连接已断开: {client_id}, 当前连接数: {len(self.connections)}")

    async def send_to_client(self, client_id: str, message: Dict[str, Any]):
        if client_id in self.connections:
            await self.connections[client_id].send(message)

    async def broadcast(self, message: Dict[str, Any], exclude: Optional[str] = None):
        disconnected = []
        for client_id, connection in self.connections.items():
            if client_id == exclude:
                continue
            try:
                await connection.send(message)
            except Exception:
                disconnected.append(client_id)
        for client_id in disconnected:
            await self.disconnect(client_id)

    async def broadcast_to_channel(self, channel: str, message: Dict[str, Any]):
        if channel not in self.channels:
            return
        disconnected = []
        for client_id in self.channels[channel]:
            if client_id in self.connections:
                try:
                    await self.connections[client_id].send(message)
                except Exception:
                    disconnected.append(client_id)
        for client_id in disconnected:
            await self.disconnect(client_id)

    def subscribe_to_channel(self, client_id: str, channel: str):
        if client_id not in self.connections:
            return
        if channel not in self.channels:
            self.channels[channel] = set()
        self.channels[channel].add(client_id)
        self.connections[client_id].subscribe(channel)
        logger.debug(f"客户端 {client_id} 订阅频道: {channel}")

    def unsubscribe_from_channel(self, client_id: str, channel: str):
        if client_id in self.connections:
            self.connections[client_id].unsubscribe(channel)
        self._remove_from_channel(channel, client_id)
        logger.debug(f"客户端 {client_id} 取消订阅频道: {channel}")

    def _remove_from_channel(self, channel: str, client_id: str):
        if channel in self.channels:
            self.channels[channel].discard(client_id)
            if not self.channels[channel]:
                del self.channels[channel]

    def register_handler(self, message_type: str, handler: Callable):
        self.message_handlers[message_type] = handler
        logger.debug(f"注册消息处理器: {message_type}")

    def set_offline_callback(self, callback: Callable):
        self._offline_callback = callback
        logger.debug("已设置离线回调函数")

    def set_agent_timeout(self, agent_id: str, timeout: int):
        self._agent_timeouts[agent_id] = timeout
        logger.debug(f"设置 Agent {agent_id} 离线超时: {timeout}秒")

    async def handle_message(self, client_id: str, message: Dict[str, Any]):
        msg_type = message.get("type", "unknown")
        if msg_type in self.message_handlers:
            try:
                await self.message_handlers[msg_type](client_id, message)
            except Exception as e:
                logger.error(f"处理消息失败 {msg_type}: {e}")
                await self.send_to_client(client_id, {"type": "error", "error": f"处理消息失败: {str(e)}"})
        else:
            logger.warning(f"未知消息类型: {msg_type}")
            await self.send_to_client(client_id, {"type": "error", "error": f"未知消息类型: {msg_type}"})

    async def start_cleanup_task(self, interval_seconds: int = 300):
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval_seconds))
        logger.info("WebSocket 清理任务已启动")

    async def stop_cleanup_task(self):
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("WebSocket 清理任务已停止")

    async def _cleanup_loop(self, interval_seconds: int):
        while self._running:
            try:
                await self._cleanup_inactive_connections()
            except Exception as e:
                logger.error(f"清理连接失败: {e}")
            await asyncio.sleep(interval_seconds)

    async def _cleanup_inactive_connections(self):
        from datetime import timedelta
        now = datetime.now()
        default_timeout = timedelta(minutes=30)
        inactive = []
        for client_id, connection in self.connections.items():
            agent_id = connection.metadata.get("agent_id", "default")
            timeout_seconds = self._agent_timeouts.get(agent_id, 1800)
            timeout = timedelta(seconds=timeout_seconds)
            if now - connection.last_activity > timeout:
                inactive.append((client_id, agent_id))
        for client_id, agent_id in inactive:
            logger.info(f"连接超时离线: {client_id}, agent={agent_id}")
            await self.disconnect(client_id)
            if self._offline_callback:
                try:
                    await self._offline_callback(agent_id)
                except Exception as e:
                    logger.error(f"离线回调失败 {agent_id}: {e}")

    def get_stats(self) -> Dict[str, Any]:
        return {"total_connections": len(self.connections), "total_channels": len(self.channels),
                "channels": {channel: len(clients) for channel, clients in self.channels.items()}}


_websocket_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager