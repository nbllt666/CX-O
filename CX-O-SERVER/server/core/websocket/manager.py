"""WebSocket 连接与消息管理器——管理客户端连接生命周期、消息路由与广播。"""
import asyncio
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Set

from fastapi import WebSocket

from server.core.logging_config import get_contextual_logger

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
        self._action_handlers: Dict[str, Callable] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._background_tasks: Set[asyncio.Task] = set()
        self._running = False
        self._offline_callback: Optional[Callable] = None
        self._agent_timeouts: Dict[str, int] = {}  # agent_id -> timeout seconds
        self._llm_count: int = 0
        # BUG-B07 修复: 使用 asyncio.Lock 保护共享可变 dict 的并发读写
        # 避免在 FastAPI 多请求并发访问时出现数据竞争
        self._lock = asyncio.Lock()
        # BUG-B-M4 修复: 同步方法 subscribe_to_channel / unsubscribe_from_channel
        # 修改共享 dict/set,使用 threading.Lock 保护,避免多线程并发调用时数据竞争
        self._sync_lock = threading.Lock()

    def _track_background_task(self, task: asyncio.Task) -> asyncio.Task:
        """追踪后台任务，防止被GC回收；任务完成后自动从集合中移除"""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def connect(
        self, websocket: WebSocket, client_id: Optional[str] = None, metadata: Optional[Dict] = None,
        send_connected: bool = True
    ) -> WebSocketConnection:
        """接受新连接

        BUG-B07 修复: 在锁内完成 ``self.connections`` 写入,保证与
        ``disconnect``/``broadcast`` 的并发安全。
        """
        await websocket.accept()

        if not client_id:
            import uuid

            client_id = str(uuid.uuid4())

        connection = WebSocketConnection(websocket, client_id, metadata)
        async with self._lock:
            self.connections[client_id] = connection

        logger.info(f"WebSocket 连接已建立: {client_id}, 当前连接数: {len(self.connections)}")

        if send_connected:
            await connection.send(
                {"type": "connected", "client_id": client_id, "timestamp": datetime.now().isoformat()}
            )

        return connection

    async def disconnect(self, client_id: str):
        """断开连接

        BUG-B07 修复: 在锁内完成 ``self.connections`` / ``self.channels``
        的修改,避免与 ``broadcast``/``subscribe_to_channel`` 的并发竞争。
        """
        async with self._lock:
            connection = self.connections.pop(client_id, None)
            if connection is None:
                return

            # 从所有频道中移除
            for channel in list(connection.subscriptions):
                self._remove_from_channel(channel, client_id)

        logger.info(f"WebSocket 连接已断开: {client_id}, 当前连接数: {len(self.connections)}")

        # 清理该客户端的双流式语音会话（根治孤儿 pipeline 泄漏：
        # 不清理则 LLM+TTS 流水线持续运行占用资源并向空连接推流，
        # 多轮累积致 TTS 服务并发排队、端到端延迟暴涨）
        try:
            from server.handlers.audio import cleanup_dual_stream_session
            await cleanup_dual_stream_session(client_id)
        except Exception as e:
            logger.warning(f"清理双流式会话失败 {client_id}: {e}")

    async def send_to_client(self, client_id: str, message: Dict[str, Any]):
        """发送消息给指定客户端

        BUG-B07 修复: 在锁内读取连接并复制出引用,然后在锁外执行 await send,
        避免长时间持锁阻塞其他协程。
        """
        async with self._lock:
            connection = self.connections.get(client_id)
        if connection is not None:
            # isEnabledFor 门控：send_to_client 每帧调用（voice.dual_stream 热路径），
            # 避免每帧对 message.get('type') 急切求值；仅 DEBUG 才做 DIAG-SEND 诊断。
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[DIAG-SEND] sending type=%s to client_id=%s", message.get('type'), client_id)
            await connection.send(message)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[DIAG-SEND] sent type=%s to client_id=%s", message.get('type'), client_id)
        else:
            logger.warning(f"[DIAG-SEND] connection is None for client_id={client_id}, type={message.get('type')}")

    async def send_message(self, client_id: str, message: Dict[str, Any]):
        """发送消息给指定客户端（send_to_client 的别名）"""
        await self.send_to_client(client_id, message)

    async def broadcast(self, message: Dict[str, Any], exclude: Optional[str] = None):
        """广播消息给所有客户端

        先对 `self.connections` 进行快照后再迭代，避免在发送过程中因
        `disconnect` 触发 `RuntimeError: dictionary changed size during iteration`。
        断连清理通过延迟异步任务执行。

        BUG-B07 修复: 快照在锁内完成,确保一致视图。
        """
        # 1) 迭代前在锁内对字典进行快照,避免快照过程中字典被改
        async with self._lock:
            connections_snapshot = list(self.connections.items())
        disconnected: list[str] = []

        for client_id, connection in connections_snapshot:
            if client_id == exclude:
                continue
            try:
                await connection.send(message)
            except Exception:
                disconnected.append(client_id)

        # 2) 清理断开的连接：延迟到下一次事件循环，避免在当前调用栈中修改字典
        if disconnected:
            self._track_background_task(asyncio.create_task(self._cleanup_disconnected(disconnected)))

    async def _cleanup_disconnected(self, client_ids: list[str]):
        """延迟清理已断开的连接（异步任务中执行）"""
        for client_id in client_ids:
            try:
                await self.disconnect(client_id)
            except Exception as e:
                logger.debug(f"清理断开连接 {client_id} 失败: {e}")

    async def broadcast_external_event(self, source: str, event_type: str, title: str, body: str):
        message = {
            "event": "external_event",
            "data": {
                "source": source,
                "type": event_type,
                "title": title,
                "body": body,
            }
        }
        await self.broadcast(message)

    async def broadcast_to_channel(self, channel: str, message: Dict[str, Any]):
        """广播消息给频道内所有客户端

        先对频道订阅者集合及全局连接字典进行快照后再迭代，
        避免在发送过程中因 `disconnect` 触发字典修改异常。
        断连清理通过延迟异步任务执行。

        BUG-B07 修复: 快照在锁内完成,确保一致视图。
        """
        # 1) 迭代前在锁内对频道成员和连接字典分别做快照
        async with self._lock:
            members_snapshot = list(self.channels.get(channel, set()))
            connections_snapshot = dict(self.connections)
        disconnected: list[str] = []

        for client_id in members_snapshot:
            connection = connections_snapshot.get(client_id)
            if connection is None:
                continue
            try:
                await connection.send(message)
            except Exception:
                disconnected.append(client_id)

        # 2) 清理断开的连接：延迟到下一次事件循环
        if disconnected:
            self._track_background_task(asyncio.create_task(self._cleanup_disconnected(disconnected)))

    def subscribe_to_channel(self, client_id: str, channel: str):
        """订阅频道

        BUG-B-M4 修复: 使用 threading.Lock 保护对共享 self.channels /
        self.connections 的读写,避免多线程并发调用时数据竞争。
        """
        with self._sync_lock:
            if client_id not in self.connections:
                return

            if channel not in self.channels:
                self.channels[channel] = set()

            self.channels[channel].add(client_id)
            self.connections[client_id].subscribe(channel)

        logger.debug(f"客户端 {client_id} 订阅频道: {channel}")

    def unsubscribe_from_channel(self, client_id: str, channel: str):
        """取消订阅频道

        BUG-B-M4 修复: 使用 threading.Lock 保护对共享 self.channels /
        self.connections 的读写,避免多线程并发调用时数据竞争。
        """
        with self._sync_lock:
            if client_id in self.connections:
                self.connections[client_id].unsubscribe(channel)

            self._remove_from_channel(channel, client_id)

        logger.debug(f"客户端 {client_id} 取消订阅频道: {channel}")

    def _remove_from_channel(self, channel: str, client_id: str):
        """从频道中移除客户端

        BUG-B07 修复: 由调用方在事件循环线程内调用;``disconnect`` 内部
        通过 ``async with self._lock`` 持有锁后调用本方法,确保与
        ``broadcast_to_channel`` 的快照读不会并发。
        """
        if channel in self.channels:
            self.channels[channel].discard(client_id)
            if not self.channels[channel]:
                del self.channels[channel]

    def register_handler(self, message_type: str, handler: Callable):
        """注册消息处理器（基于 type 路由）"""
        self.message_handlers[message_type] = handler
        logger.debug(f"注册消息处理器: {message_type}")

    def register_action_handler(self, action: str, handler: Callable):
        """注册 action 处理器（基于 action 路由）"""
        self._action_handlers[action] = handler
        logger.debug(f"注册 action 处理器: {action}")

    def get_handler(self, action: str) -> Optional[Callable]:
        """获取 action 对应的处理器"""
        return self._action_handlers.get(action)

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
        """处理收到的消息（基于 type 路由，action 回退）

        路由优先级：
        1. type 字段匹配 message_handlers → 走 type 路由（向后兼容）
        2. action 字段存在 → 走 handle_action_message（voice.dual_stream 等）
        3. 都不匹配 → 报错"未知消息类型"
        """
        msg_type = message.get("type", "unknown")

        if msg_type in self.message_handlers:
            try:
                await self.message_handlers[msg_type](client_id, message)
            except Exception as e:
                logger.error(f"处理消息失败 {msg_type}: {e}")
                await self.send_to_client(
                    client_id, {"type": "error", "error": f"处理消息失败: {str(e)}"}
                )
        elif "action" in message:
            # action 回退：type 不匹配但有 action 字段，走 action 路由
            # 支持 voice.dual_stream / chat.message / chat.stream 等 action-based 协议
            await self.handle_action_message(client_id, message)
        else:
            logger.warning(f"未知消息类型: {msg_type}")
            await self.send_to_client(
                client_id, {"type": "error", "error": f"未知消息类型: {msg_type}"}
            )

    async def handle_action_message(self, client_id: str, message: Dict[str, Any]):
        """处理收到的消息（基于 action 路由）"""
        action = message.get("action", "")
        if action in self._action_handlers:
            handler = self._action_handlers[action]
            connection = self.connections.get(client_id)
            websocket = connection.websocket if connection else None
            await handler(websocket, message, client_id)
        else:
            logger.warning(f"未知 action: {action}")
            await self.send_to_client(
                client_id, {"type": "error", "error": f"未知 action: {action}"}
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
        """清理不活跃的连接，并触发离线保存

        BUG-B07 修复: 迭代 ``self.connections`` / ``self._agent_timeouts`` 时
        在锁内拷贝,避免迭代过程中字典被改。
        """
        from datetime import timedelta

        now = datetime.now()

        async with self._lock:
            connections_snapshot = list(self.connections.items())
            agent_timeouts_snapshot = dict(self._agent_timeouts)
            offline_callback = self._offline_callback

        inactive = []
        for client_id, connection in connections_snapshot:
            agent_id = connection.metadata.get("agent_id", "default")
            timeout_seconds = agent_timeouts_snapshot.get(agent_id, 1800)
            timeout = timedelta(seconds=timeout_seconds)

            if now - connection.last_activity > timeout:
                inactive.append((client_id, agent_id))

        for client_id, agent_id in inactive:
            logger.info(f"连接超时离线: {client_id}, agent={agent_id}")
            await self.disconnect(client_id)

            if offline_callback:
                try:
                    await offline_callback(agent_id)
                except Exception as e:
                    logger.error(f"离线回调失败 {agent_id}: {e}")

    def increment_llm_count(self):
        self._llm_count += 1

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_connections": len(self.connections),
            "total_channels": len(self.channels),
            "channels": {channel: len(clients) for channel, clients in self.channels.items()},
            "llm_count": self._llm_count,
            "client_count": len(self.connections),
        }


# 全局 WebSocket 管理器实例
_websocket_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """获取全局 WebSocket 管理器实例"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager
