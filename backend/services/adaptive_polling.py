"""
自适应频率轮询管理器
基于滑动窗口的包延迟记录，动态调整轮询频率
"""
import time
from collections import deque
from typing import Deque, Optional
import logging

logger = logging.getLogger(__name__)


class AdaptivePollingManager:
    """自适应频率轮询管理器
    
    记录每次请求的包间隔延迟，使用滑动窗口计算平均延迟，
    动态调整轮询频率以平衡资源消耗和响应速度。
    """
    
    def __init__(
        self,
        window_size: int = 3,
        offset_ms: int = 0,
        min_interval_ms: int = 50,
        max_interval_ms: int = 2000
    ):
        """初始化
        
        Args:
            window_size: 滑动窗口大小（保留最近 N 个延迟值）
            offset_ms: 微调值（毫秒），在自适应基础上 ± 微调
            min_interval_ms: 最小轮询间隔（毫秒）
            max_interval_ms: 最大轮询间隔（毫秒）
        """
        self._window_size = window_size
        self._offset_ms = offset_ms
        self._min_interval_ms = min_interval_ms
        self._max_interval_ms = max_interval_ms
        
        self._latencies: Deque[float] = deque(maxlen=window_size)
        self._last_packet_time: Optional[float] = None
        self._current_interval_ms: int = 100
        
    def record_packet(self) -> float:
        """记录收到数据包的时间，计算与上一个包的间隔
        
        应在每次收到流式响应数据包时调用。
        
        Returns:
            当前包间隔延迟（毫秒），如果是第一个包则返回 0
        """
        current_time = time.time()
        
        if self._last_packet_time is None:
            self._last_packet_time = current_time
            return 0.0
        
        interval_ms = (current_time - self._last_packet_time) * 1000
        self._last_packet_time = current_time
        
        self._latencies.append(interval_ms)
        
        self._update_interval()
        
        logger.debug(f"Recorded packet interval: {interval_ms:.1f}ms, avg: {self.get_average_latency():.1f}ms, poll_interval: {self._current_interval_ms}ms")
        
        return interval_ms
    
    def _update_interval(self):
        """根据平均延迟更新轮询间隔"""
        avg_latency = self.get_average_latency()
        
        if avg_latency <= 0:
            return
        
        if avg_latency < 100:
            base_interval = 50
        elif avg_latency < 500:
            base_interval = avg_latency * 0.8
        else:
            base_interval = avg_latency * 0.5
        
        final_interval = base_interval + self._offset_ms
        
        self._current_interval_ms = max(
            self._min_interval_ms,
            min(self._max_interval_ms, int(final_interval))
        )
    
    def get_average_latency(self) -> float:
        """获取平均延迟
        
        Returns:
            平均延迟（毫秒），如果没有记录则返回 0
        """
        if not self._latencies:
            return 0.0
        return sum(self._latencies) / len(self._latencies)
    
    def get_poll_interval(self) -> int:
        """获取当前轮询间隔
        
        Returns:
            轮询间隔（毫秒）
        """
        return self._current_interval_ms
    
    def set_offset(self, offset_ms: int):
        """设置微调值
        
        Args:
            offset_ms: 微调值（毫秒），范围 -500 ~ +500
        """
        self._offset_ms = max(-500, min(500, offset_ms))
        self._update_interval()
    
    def set_window_size(self, size: int):
        """设置滑动窗口大小
        
        Args:
            size: 窗口大小，范围 1-10
        """
        self._window_size = max(1, min(10, size))
        new_latencies = deque(maxlen=self._window_size)
        new_latencies.extend(list(self._latencies)[-self._window_size:])
        self._latencies = new_latencies
    
    def reset(self):
        """重置状态"""
        self._latencies.clear()
        self._last_packet_time = None
        self._current_interval_ms = 100
    
    def get_stats(self) -> dict:
        """获取统计信息
        
        Returns:
            包含延迟统计和当前配置的字典
        """
        return {
            "current_interval_ms": self._current_interval_ms,
            "average_latency_ms": round(self.get_average_latency(), 1),
            "latency_count": len(self._latencies),
            "recent_latencies": [round(l, 1) for l in list(self._latencies)],
            "config": {
                "window_size": self._window_size,
                "offset_ms": self._offset_ms,
                "min_interval_ms": self._min_interval_ms,
                "max_interval_ms": self._max_interval_ms
            }
        }


_manager_instance: Optional[AdaptivePollingManager] = None


def get_adaptive_polling_manager() -> AdaptivePollingManager:
    """获取全局 AdaptivePollingManager 实例"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = AdaptivePollingManager()
    return _manager_instance


def init_adaptive_polling_manager(
    window_size: int = 3,
    offset_ms: int = 0,
    min_interval_ms: int = 50,
    max_interval_ms: int = 2000
) -> AdaptivePollingManager:
    """初始化全局 AdaptivePollingManager 实例"""
    global _manager_instance
    _manager_instance = AdaptivePollingManager(
        window_size=window_size,
        offset_ms=offset_ms,
        min_interval_ms=min_interval_ms,
        max_interval_ms=max_interval_ms
    )
    return _manager_instance
