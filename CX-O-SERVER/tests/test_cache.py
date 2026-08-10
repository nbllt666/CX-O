"""server.core.cache 单元测试。

覆盖 LRUCache TTL/LRU 淘汰/统计、CacheManager 单例与 cached 装饰器。
运行：python -m pytest tests/test_cache.py -v
"""
import pytest

from server.core.cache import LRUCache, CacheManager, cached


class TestLRUCache:
    def test_miss(self):
        c = LRUCache()
        assert c.get("k") is None

    def test_set_get(self):
        c = LRUCache()
        c.set("k", "v")
        assert c.get("k") == "v"

    def test_overwrite(self):
        c = LRUCache()
        c.set("k", 1)
        c.set("k", 2)
        assert c.get("k") == 2

    def test_ttl_expired(self):
        c = LRUCache()
        c.set("k", "v", ttl=-1)  # 立即过期
        assert c.get("k") is None

    def test_default_ttl(self):
        c = LRUCache(default_ttl=-1)
        c.set("k", "v")
        assert c.get("k") is None

    def test_delete(self):
        c = LRUCache()
        c.set("k", "v")
        assert c.delete("k") is True
        assert c.delete("k") is False

    def test_clear(self):
        c = LRUCache()
        c.set("k", "v")
        c.clear()
        assert c.get_stats()["size"] == 0

    def test_lru_eviction(self):
        c = LRUCache(max_size=2)
        c.set("a", 1)
        c.set("b", 2)
        c.get("a")  # a 变为最近使用
        c.set("c", 3)  # 淘汰最久未用的 b
        assert c.get("a") == 1
        assert c.get("b") is None
        assert c.get("c") == 3

    def test_stats(self):
        c = LRUCache()
        c.set("k", "v")
        c.get("k")  # hit
        c.get("missing")  # miss
        s = c.get_stats()
        assert s["size"] == 1
        assert s["hits"] == 1
        assert s["misses"] == 1
        assert s["total_requests"] == 2
        assert s["hit_rate"] == 0.5

    def test_stats_empty(self):
        s = LRUCache().get_stats()
        assert s["hit_rate"] == 0


class TestCacheManager:
    def test_singleton(self):
        assert CacheManager() is CacheManager()

    def test_get_cache_reuses(self):
        mgr = CacheManager()
        a = mgr.get_cache("c1")
        b = mgr.get_cache("c1")
        assert a is b

    def test_get_all_stats(self):
        mgr = CacheManager()
        mgr.get_cache("s1").set("k", 1)
        stats = mgr.get_all_stats()
        assert "s1" in stats

    def test_clear_all(self):
        mgr = CacheManager()
        cache = mgr.get_cache("s2")
        cache.set("k", 1)
        mgr.clear_all()
        assert cache.get_stats()["size"] == 0


class TestCachedDecorator:
    def test_caches_result(self):
        calls = []

        @cached("deco_test_1")
        def add(a, b):
            calls.append(1)
            return a + b

        assert add(1, 2) == 3
        assert add(1, 2) == 3
        assert len(calls) == 1

    def test_different_args_not_cached(self):
        calls = []

        @cached("deco_test_2")
        def add(a, b):
            calls.append(1)
            return a + b

        add(1, 2)
        add(3, 4)
        assert len(calls) == 2

    def test_key_func(self):
        calls = []

        @cached("deco_test_3", key_func=lambda x: x % 2)
        def f(x):
            calls.append(1)
            return x

        assert f(1) == 1
        assert f(3) == 1  # key_func(3)=key_func(1)=1，命中缓存返回缓存值
        assert len(calls) == 1