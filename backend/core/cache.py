"""
智能缓存模块
提供内存缓存功能，支持 TTL 和 LRU 淘汰策略
"""
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, Optional, TypeVar
from functools import wraps

T = TypeVar("T")
K = TypeVar("K")


@dataclass
class CacheEntry(Generic[T]):
    value: T
    created_at: float
    expires_at: Optional[float] = None
    hits: int = 0
    last_accessed: float = field(default_factory=time.time)


class LRUCache(Generic[K, T]):
    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[K, CacheEntry[T]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: K) -> Optional[T]:
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
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def get_stats(self) -> Dict[str, Any]:
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
        if self._initialized:
            return
        
        self._caches: Dict[str, LRUCache] = {}
        self._global_lock = threading.Lock()
        self._initialized = True

    def get_cache(self, name: str, max_size: int = 1000, ttl: Optional[float] = None) -> LRUCache:
        with self._global_lock:
            if name not in self._caches:
                self._caches[name] = LRUCache(max_size=max_size, default_ttl=ttl)
            return self._caches[name]

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        with self._global_lock:
            return {name: cache.get_stats() for name, cache in self._caches.items()}

    def clear_all(self) -> None:
        with self._global_lock:
            for cache in self._caches.values():
                cache.clear()


def cached(cache_name: str, key_func: Optional[Callable] = None, ttl: Optional[float] = None):
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            cache_manager = CacheManager()
            cache = cache_manager.get_cache(cache_name, ttl=ttl)
            
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = (args, frozenset(kwargs.items()))
            
            result = cache.get(cache_key)
            if result is not None:
                return result
            
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl=ttl)
            return result
        
        return wrapper
    return decorator


agent_config_cache = CacheManager().get_cache("agent_configs", max_size=100, ttl=300)
tool_list_cache = CacheManager().get_cache("tool_lists", max_size=50, ttl=60)
session_cache = CacheManager().get_cache("sessions", max_size=500, ttl=600)
