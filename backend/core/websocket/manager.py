import asyncio
import json
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Set

from fastapi import WebSocket

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class WebSocketConnection:
    """WebSocket 连接封装"""

    def __init__(self, websocket: WebSocket, client_id: str, metadata: Optional[Dict] = None):
        self.websocket = websocket
        self.client_id = client_id
        self.metadata = metadata or {}
        self.connected_at = datetime.now()
        self.last_activity = datetime.now()
        self.subscriptions: Set[str] = set()  # 订阅的频道

    async def send(self, data: Dict[str, Any]):
        """发送消息"""
        try:
            await self.websocket.send_json(data)
            self.last_activity = datetime.now()
        except Exception as e:
            logger.error(f"发送消息失败 {self.client_id}: {e}")
            raise

    async def receive(self) -> Dict[str, Any]:
        """接收消息"""
        data = await self.websocket.receive_json()
        self.last_activity = datetime.now()
        return data

    def subscribe(self, channel: str):
        """订阅频道"""
        self.subscriptions.add(channel)

    def unsubscribe(self, channel: str):
        """取消订阅"""
        self.subscriptions.discard(channel)

    def is_subscribed(self, channel: str) -> bool:
        """是否订阅了频道"""
        return channel in self.subscriptions


class WebSocketManager:
    """WebSocket 连接管理器

    管理所有 WebSocket 连接，支持广播、分组、订阅等功能
    """

    def __init__(self):
        self.connections: Dict[str, WebSocketConnection] = {}
        self.channels: Dict[str, Set[str]] = {}  # 频道 -> 客户端ID集合
        self.message_handlers: Dict[str, Callable] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        self._offline_callback: Optional[Callable] = None
        self._agent_timeouts: Dict[str, int] = {}  # agent_id -> timeout seconds

    async def connect(
        self, websocket: WebSocket, client_id: Optional[str] = None, metadata: Optional[Dict] = None
    ) -> WebSocketConnection:
        """接受新连接"""
        await websocket.accept()

        if not client_id:
            import uuid

            client_id = str(uuid.uuid4())

        connection = WebSocketConnection(websocket, client_id, metadata)
        self.connections[client_id] = connection

        logger.info(f"WebSocket 连接已建立: {client_id}, 当前连接数: {len(self.connections)}")

        # 发送连接成功消息
        await connection.send(
            {"type": "connected", "client_id": client_id, "timestamp": datetime.now().isoformat()}
        )

        return connection

    async def disconnect(self, client_id: str):
        """断开连接"""
        if client_id in self.connections:
            connection = self.connections[client_id]

            # 从所有频道中移除
            for channel in list(connection.subscriptions):
                self._remove_from_channel(channel, client_id)

            del self.connections[client_id]
            logger.info(f"WebSocket 连接已断开: {client_id}, 当前连接数: {len(self.connections)}")

    async def send_to_client(self, client_id: str, message: Dict[str, Any]):
        """发送消息给指定客户端"""
        if client_id in self.connections:
            await self.connections[client_id].send(message)

    async def broadcast(self, message: Dict[str, Any], exclude: Optional[str] = None):
        """广播消息给所有客户端"""
        disconnected = []
        for client_id, connection in self.connections.items():
            if client_id == exclude:
                continue
            try:
                await connection.send(message)
            except Exception:
                disconnected.append(client_id)

        # 清理断开的连接
        for client_id in disconnected:
            await self.disconnect(client_id)

    async def broadcast_to_channel(self, channel: str, message: Dict[str, Any]):
        """广播消息给频道内所有客户端"""
        if channel not in self.channels:
            return

        disconnected = []
        for client_id in self.channels[channel]:
            if client_id in self.connections:
                try:
                    await self.connections[client_id].send(message)
                except Exception:
                    disconnected.append(client_id)

        # 清理断开的连接
        for client_id in disconnected:
            await self.disconnect(client_id)

    def subscribe_to_channel(self, client_id: str, channel: str):
        """订阅频道"""
        if client_id not in self.connections:
            return

        if channel not in self.channels:
            self.channels[channel] = set()

        self.channels[channel].add(client_id)
        self.connections[client_id].subscribe(channel)

        logger.debug(f"客户端 {client_id} 订阅频道: {channel}")

    def unsubscribe_from_channel(self, client_id: str, channel: str):
        """取消订阅频道"""
        if client_id in self.connections:
            self.connections[client_id].unsubscribe(channel)

        self._remove_from_channel(channel, client_id)

        logger.debug(f"客户端 {client_id} 取消订阅频道: {channel}")

    def _remove_from_channel(self, channel: str, client_id: str):
        """从频道中移除客户端"""
        if channel in self.channels:
            self.channels[channel].discard(client_id)
            if not self.channels[channel]:
                del self.channels[channel]

    def register_handler(self, message_type: str, handler: Callable):
        """注册消息处理器"""
        self.message_handlers[message_type] = handler
        logger.debug(f"注册消息处理器: {message_type}")

    def set_offline_callback(self, callback: Callable):
        """设置离线回调函数

        当连接超时离线时调用，用于保存上下文到长期记忆
        callback(agent_id: str) -> None
        """
        self._offline_callback = callback
        logger.debug("已设置离线回调函数")

    def set_agent_timeout(self, agent_id: str, timeout: int):
        """设置 Agent 的离线超时时间"""
        self._agent_timeouts[agent_id] = timeout
        logger.debug(f"设置 Agent {agent_id} 离线超时: {timeout}秒")

    async def handle_message(self, client_id: str, message: Dict[str, Any]):
        """处理收到的消息"""
        msg_type = message.get("type", "unknown")

        if msg_type in self.message_handlers:
            try:
                await self.message_handlers[msg_type](client_id, message)
            except Exception as e:
                logger.error(f"处理消息失败 {msg_type}: {e}")
                await self.send_to_client(
                    client_id, {"type": "error", "error": f"处理消息失败: {str(e)}"}
                )
        else:
            logger.warning(f"未知消息类型: {msg_type}")
            await self.send_to_client(
                client_id, {"type": "error", "error": f"未知消息类型: {msg_type}"}
            )

    async def start_cleanup_task(self, interval_seconds: int = 300):
        """启动清理任务"""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval_seconds))
        logger.info("WebSocket 清理任务已启动")

    async def stop_cleanup_task(self):
        """停止清理任务"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("WebSocket 清理任务已停止")

    async def _cleanup_loop(self, interval_seconds: int):
        """清理循环"""
        while self._running:
            try:
                await self._cleanup_inactive_connections()
            except Exception as e:
                logger.error(f"清理连接失败: {e}")

            await asyncio.sleep(interval_seconds)

    async def _cleanup_inactive_connections(self):
        """清理不活跃的连接，并触发离线保存"""
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
        """获取统计信息"""
        return {
            "total_connections": len(self.connections),
            "total_channels": len(self.channels),
            "channels": {channel: len(clients) for channel, clients in self.channels.items()},
        }


# 全局 WebSocket 管理器实例
_websocket_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """获取全局 WebSocket 管理器实例"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager
