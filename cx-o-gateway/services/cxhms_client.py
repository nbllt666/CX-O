"""
CXHMS WebSocket 客户端
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Optional
import websockets
from websockets.client import WebSocketClientProtocol

from protocol.message import create_request, MessageType

logger = logging.getLogger(__name__)


class CXHMSClient:
    def __init__(self, url: str, pool_size: int = 5):
        self._url = url
        self._pool_size = pool_size
        self._connections: list[WebSocketClientProtocol] = []
        self._connection_available = asyncio.Event()
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._running = False
        self._receive_tasks: list[asyncio.Task] = []
        self._reconnect_interval = 5
        self._heartbeat_interval = 30
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def connect(self):
        self._running = True
        for i in range(self._pool_size):
            try:
                conn = await websockets.connect(self._url)
                self._connections.append(conn)
                task = asyncio.create_task(self._receive_loop(conn, i))
                self._receive_tasks.append(task)
            except Exception as e:
                logger.error(f"Failed to connect connection {i}: {e}")
        
        if self._connections:
            self._connection_available.set()
        
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"Connected to CXHMS with {len(self._connections)} connections")

    async def disconnect(self):
        self._running = False
        self._connection_available.clear()
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        
        for task in self._receive_tasks:
            task.cancel()
        
        for conn in self._connections:
            await conn.close()
        
        self._connections.clear()
        self._receive_tasks.clear()
        logger.info("Disconnected from CXHMS")

    async def _receive_loop(self, conn: WebSocketClientProtocol, conn_id: int):
        try:
            async for message in conn:
                try:
                    data = json.loads(message)
                    request_id = data.get("request_id")
                    
                    if request_id and request_id in self._pending_requests:
                        future = self._pending_requests.pop(request_id)
                        if not future.done():
                            future.set_result(data)
                    else:
                        logger.debug(f"Received message without pending request: {data}")
                        
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from CXHMS connection {conn_id}")
                    
        except websockets.ConnectionClosed:
            logger.warning(f"CXHMS connection {conn_id} closed")
            await self._reconnect(conn_id)
        except Exception as e:
            logger.error(f"Error in receive loop {conn_id}: {e}")

    async def _reconnect(self, conn_id: int):
        while self._running:
            try:
                await asyncio.sleep(self._reconnect_interval)
                conn = await websockets.connect(self._url)
                if conn_id < len(self._connections):
                    self._connections[conn_id] = conn
                else:
                    self._connections.append(conn)
                
                task = asyncio.create_task(self._receive_loop(conn, conn_id))
                if conn_id < len(self._receive_tasks):
                    self._receive_tasks[conn_id] = task
                else:
                    self._receive_tasks.append(task)
                
                logger.info(f"Reconnected CXHMS connection {conn_id}")
                break
            except Exception as e:
                logger.error(f"Reconnect failed for {conn_id}: {e}")

    async def _heartbeat_loop(self):
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                for conn in self._connections:
                    if conn.open:
                        await conn.send(json.dumps({"type": "ping", "timestamp": time.time()}))
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    def _get_connection(self) -> Optional[WebSocketClientProtocol]:
        for conn in self._connections:
            if conn.open:
                return conn
        return None

    async def request(self, action: str, data: dict[str, Any], timeout: float = 30.0) -> dict:
        request_id = str(uuid.uuid4())
        message = create_request(action, data, request_id)
        
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future
        
        conn = self._get_connection()
        if not conn:
            self._pending_requests.pop(request_id, None)
            raise ConnectionError("No available connection to CXHMS")
        
        try:
            await conn.send(json.dumps(message))
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"Request {action} timed out")
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            raise

    async def stream(self, action: str, data: dict[str, Any], callback: Callable[[dict], None], timeout: float = 60.0):
        request_id = str(uuid.uuid4())
        message = create_request(action, data, request_id)
        
        stream_complete = asyncio.Event()
        
        def handle_stream_response(response: dict):
            if response.get("request_id") == request_id:
                callback(response)
                if response.get("is_final", False) or response.get("type") == "error":
                    stream_complete.set()
        
        self._pending_requests[request_id] = handle_stream_response
        
        conn = self._get_connection()
        if not conn:
            self._pending_requests.pop(request_id, None)
            raise ConnectionError("No available connection to CXHMS")
        
        try:
            await conn.send(json.dumps(message))
            await asyncio.wait_for(stream_complete.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"Stream {action} timed out")
        finally:
            self._pending_requests.pop(request_id, None)
