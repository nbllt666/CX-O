"""
server/core/lifecycle.py 回归测试
统一的服务初始化/关闭辅助函数（同步/异步分发、异常降级）
"""
import logging

import pytest

from server.core.lifecycle import init_service, shutdown_service


async def _async_ok(a: int = 0, b: int = 0) -> int:
    return a + b


async def _async_fail():
    raise RuntimeError("async boom")


def _sync_ok(a: int = 0) -> int:
    return a + 1


def _sync_fail():
    raise ValueError("sync boom")


@pytest.mark.asyncio
class TestInitService:
    async def test_sync_factory(self, caplog):
        caplog.set_level(logging.INFO)
        result = await init_service("测试", _sync_ok, args=(5,))
        assert result == 6
        assert any("已启动" in r.message for r in caplog.records)

    async def test_async_factory(self):
        result = await init_service("测试", _async_ok, args=(2, 3))
        assert result == 5

    async def test_sync_factory_kwargs(self):
        result = await init_service("测试", _sync_ok, kwargs={"a": 10})
        assert result == 11

    async def test_sync_failure_returns_none(self, caplog):
        result = await init_service("测试", _sync_fail)
        assert result is None
        assert any("启动失败" in r.message for r in caplog.records)

    async def test_async_failure_returns_none(self):
        result = await init_service("测试", _async_fail)
        assert result is None


@pytest.mark.asyncio
class TestShutdownService:
    async def test_sync_close(self, caplog):
        caplog.set_level(logging.INFO)
        calls = []

        def _close():
            calls.append(1)

        await shutdown_service("测试", _close)
        assert calls == [1]
        assert any("已关闭" in r.message for r in caplog.records)

    async def test_async_close(self):
        calls = []

        async def _close():
            calls.append(1)

        await shutdown_service("测试", _close)
        assert calls == [1]

    async def test_sync_failure_caught(self, caplog):
        await shutdown_service("测试", _sync_fail)
        assert any("关闭失败" in r.message for r in caplog.records)

    async def test_async_failure_caught(self):
        await shutdown_service("测试", _async_fail)  # 不抛异常，仅告警