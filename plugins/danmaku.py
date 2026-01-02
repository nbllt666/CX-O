#!/usr/bin/env python3
"""
弹幕监听插件（基于RSocket）

功能：
- 连接弹幕服务器
- 接收弹幕消息
- 回调处理
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Callable, Optional, Dict, Any
from pathlib import Path

import aiohttp
from rsocket.payload import Payload
from rsocket.rsocket_client import RSocketClient
from rsocket.streams.stream_from_async_generator import StreamFromAsyncGenerator
from rsocket.transports.aiohttp_websocket import TransportAioHttpClient
from reactivestreams.subscriber import Subscriber
from reactivestreams.subscription import Subscription

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.danmaku_cache import DanmakuCacheManager, DanmakuMessage

logger = logging.getLogger(__name__)


class DanmakuSubscriber(Subscriber):
    """弹幕订阅处理器"""
    
    def __init__(self, callback: Callable[[Dict], None]):
        """
        初始化
        
        Args:
            callback: 弹幕回调函数，接收弹幕数据
        """
        self.subscription = None
        self.callback = callback
        self._wait_complete = asyncio.Event()
    
    def on_subscribe(self, subscription: Subscription):
        self.subscription = subscription
        self.subscription.request(0x7FFFFFFF)  # 请求所有消息
    
    def on_next(self, value: Payload, is_complete=False):
        """收到消息"""
        try:
            msg_dto = json.loads(value.data)
            
            if not isinstance(msg_dto, dict):
                return
            
            msg_type = msg_dto.get('type')
            
            if msg_type == "DANMU":
                # 弹幕消息
                danmaku_data = {
                    "id": f"danmaku_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}",
                    "platform": "live",
                    "room_id": str(msg_dto.get('roomId', '')),
                    "username": msg_dto.get('msg', {}).get('username', '未知用户'),
                    "uid": str(msg_dto.get('msg', {}).get('uid', '0')),
                    "content": msg_dto.get('msg', {}).get('content', ''),
                    "badge_level": msg_dto.get('msg', {}).get('badgeLevel', 0),
                    "badge_name": msg_dto.get('msg', {}).get('badgeName', ''),
                    "timestamp": datetime.now().isoformat()
                }
                
                logger.info(f"[弹幕] {danmaku_data['username']}: {danmaku_data['content']}")
                
                # 回调处理
                self.callback(danmaku_data)
            
            elif msg_type == "GIFT":
                # 礼物消息
                gift_data = {
                    "type": "gift",
                    "platform": "live",
                    "room_id": str(msg_dto.get('roomId', '')),
                    "username": msg_dto.get('msg', {}).get('username', '未知用户'),
                    "gift_name": msg_dto.get('msg', {}).get('giftName', ''),
                    "gift_count": msg_dto.get('msg', {}).get('giftCount', 0),
                    "gift_price": msg_dto.get('msg', {}).get('giftPrice', 0)
                }
                
                logger.info(f"[礼物] {gift_data['username']} 赠送 {gift_data['gift_name']}")
                self.callback(gift_data)
            
            else:
                logger.debug(f"收到其他消息: {msg_type}")
        
        except Exception as e:
            logger.error(f"处理弹幕消息失败: {e}")
        
        if is_complete:
            self._wait_complete.set()
    
    def on_error(self, exception: Exception):
        logger.error(f"RSocket错误: {exception}")
        self._wait_complete.set()
    
    def on_complete(self):
        logger.info("RSocket连接关闭")
        self._wait_complete.set()


class DanmakuPlugin:
    """弹幕监听插件"""
    
    def __init__(
        self,
        cache_manager: DanmakuCacheManager = None,
        config: Dict = None
    ):
        """
        初始化弹幕插件
        
        Args:
            cache_manager: 弹幕缓存管理器
            config: 配置
        """
        self.cache_manager = cache_manager or DanmakuCacheManager()
        self.config = config or {}
        
        self.is_connected = False
        self._client = None
        self._danmaku_subscriber = None
        self._danmaku_callback = None
        self._task_ids = []
    
    def set_danmaku_callback(self, callback: Callable[[Dict], None]):
        """
        设置弹幕回调函数
        
        Args:
            callback: 处理弹幕的回调函数
        """
        self._danmaku_callback = callback
    
    async def connect(self, websocket_uri: str, task_ids: list):
        """
        连接弹幕服务器
        
        Args:
            websocket_uri: WebSocket URI（如 ws://localhost:9898）
            task_ids: 任务ID列表（房间号）
        """
        if self.is_connected:
            logger.warning("已连接到弹幕服务器，请先断开")
            return
        
        self._task_ids = task_ids
        
        try:
            # 创建订阅者
            self._danmaku_subscriber = DanmakuSubscriber(
                callback=self._handle_danmaku
            )
            
            # 准备订阅请求
            subscribe_payload = {
                "data": {
                    "taskIds": task_ids,
                    "cmd": "SUBSCRIBE"
                }
            }
            
            async def generator():
                yield Payload(
                    data=json.dumps(subscribe_payload["data"]).encode()
                ), False
                await asyncio.Event().wait()
            
            stream = StreamFromAsyncGenerator(generator)
            
            # 建立连接
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(websocket_uri) as websocket:
                    self._client = RSocketClient(
                        TransportAioHttpClient(websocket),
                        keep_alive_period=30
                    )
                    
                    async with self._client:
                        requested = self._client.request_channel(Payload(), stream)
                        requested.subscribe(self._danmaku_subscriber)
                        
                        self.is_connected = True
                        logger.info(f"已连接到弹幕服务器: {websocket_uri}")
                        
                        # 保持连接
                        await self._danmaku_subscriber._wait_complete.wait()
            
        except Exception as e:
            logger.error(f"连接弹幕服务器失败: {e}")
            self.is_connected = False
            raise
    
    async def disconnect(self):
        """断开弹幕服务器连接"""
        if self._client:
            try:
                await self._client.close()
            except:
                pass
            self._client = None
        
        self.is_connected = False
        logger.info("已断开弹幕服务器连接")
    
    async def _handle_danmaku(self, danmaku_data: Dict):
        """
        处理收到的弹幕
        
        Args:
            danmaku_data: 弹幕数据
        """
        # 1. 创建弹幕消息
        danmaku = DanmakuMessage(
            id=danmaku_data.get('id', f"danmaku_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}"),
            platform=danmaku_data.get('platform', 'live'),
            room_id=danmaku_data.get('room_id', ''),
            username=danmaku_data.get('username', '未知用户'),
            uid=danmaku_data.get('uid', '0'),
            content=danmaku_data.get('content', ''),
            badge_level=danmaku_data.get('badge_level', 0),
            badge_name=danmaku_data.get('badge_name', ''),
            timestamp=danmaku_data.get('timestamp', datetime.now().isoformat())
        )
        
        # 2. 添加到原始弹幕缓存
        self.cache_manager.add_raw_danmaku(danmaku)
        
        # 3. 回调通知
        if self._danmaku_callback:
            self._danmaku_callback({
                "type": "danmaku",
                "data": danmaku.to_dict()
            })
    
    def get_status(self) -> Dict:
        """获取插件状态"""
        return {
            "is_connected": self.is_connected,
            "task_ids": self._task_ids,
            "cache_stats": self.cache_manager.get_statistics()
        }
