"""
智能缓存模块
提供内存缓存功能，支持 TTL 和 LRU 淘汰策略
"""
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Optional, TypeVar

T = TypeVar("T")
K = TypeVar("K")


@dataclass
class CacheEntry(Generic[T]):
    """缓存条目数据类，记录缓存值、创建/过期时间、命中次数与最后访问时间，供 LRU 淘汰策略使用。"""
    value: T
    created_at: float
    expires_at: Optional[float] = None
    hits: int = 0
    last_accessed: float = field(default_factory=time.time)


class LRUCache(Generic[K, T]):
    """线程安全的 LRU 缓存容器，支持按容量淘汰最久未访问项与 TTL 过期，并统计命中/未命中次数。"""

    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[K, CacheEntry[T]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: K) -> Optional[T]:
        """获取缓存值，不存在或已过期时返回 None。"""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[key]
            
            if entry.expires_at and time.time() > entry.expires_at:
                del self._cache[key]
                self._misses += 1
                return None

            self._cache.move_to_end(key)
            entry.hits += 1
            entry.last_accessed = time.time()
            self._hits += 1
            return entry.value

    def set(self, key: K, value: T, ttl: Optional[float] = None) -> None:
        """写入缓存项，优先用传入 ttl，否则用默认 ttl；超出容量时淘汰最久未访问的条目。"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]

            now = time.time()
            expires_at = None
            if ttl is not None:
                expires_at = now + ttl
            elif self.default_ttl is not None:
                expires_at = now + self.default_ttl

            self._cache[key] = CacheEntry(
                value=value,
                created_at=now,
                expires_at=expires_at,
            )

            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def delete(self, key: K) -> bool:
        """删除指定键的缓存项，存在并删除成功返回 True，否则返回 False。"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """清空缓存并重置统计计数。"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def get_stats(self) -> Dict[str, Any]:
        """返回缓存大小、上限、命中/未命中次数、命中率与总请求数的统计字典。"""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0
            
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "total_requests": total_requests,
            }


class CacheManager:
    """全局缓存管理器单例，按名称维护多个 LRUCache 实例，用于集中管理各用途的命名缓存。"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # 初始化判定移入类级锁内：避免多线程同时通过 _initialized 检查的窗口
        # 导致 _caches/_global_lock 被重复构造（后建实例覆盖先建的命名缓存引用）
        with self._lock:
            if self._initialized:
                return

            self._caches: Dict[str, LRUCache] = {}
            self._global_lock = threading.Lock()
            self._initialized = True

    def get_cache(self, name: str, max_size: int = 1000, ttl: Optional[float] = None) -> LRUCache:
        """按名称获取（或创建）一个 LRU 缓存实例。"""
        with self._global_lock:
            if name not in self._caches:
                self._caches[name] = LRUCache(max_size=max_size, default_ttl=ttl)
            return self._caches[name]


agent_config_cache = CacheManager().get_cache("agent_configs", max_size=100, ttl=300)
