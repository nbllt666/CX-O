"""voice_context（contextvars 语音上下文）单元测试。

覆盖：默认值、set/get、reset 复位、不同 asyncio task 间天然隔离。
运行：python -m pytest tests/test_voice_context.py -v
"""
import asyncio

from server.services import voice_context as vc


def test_default_value():
    assert vc.get_active_client_id() == "default"


def test_set_and_get():
    token = vc.set_active_client_id("client-1")
    assert vc.get_active_client_id() == "client-1"
    vc.reset_active_client_id(token)
    assert vc.get_active_client_id() == "default"


def test_task_isolation():
    async def task_a():
        vc.set_active_client_id("client-a")
        await asyncio.sleep(0.01)
        assert vc.get_active_client_id() == "client-a"

    async def task_b():
        vc.set_active_client_id("client-b")
        await asyncio.sleep(0.01)
        assert vc.get_active_client_id() == "client-b"

    async def main():
        await asyncio.gather(task_a(), task_b())
        # 外层 task 从未 set，读到默认值
        assert vc.get_active_client_id() == "default"

    asyncio.run(main())


def test_reset_restores_default():
    token = vc.set_active_client_id("tmp-client")
    assert vc.get_active_client_id() == "tmp-client"
    vc.reset_active_client_id(token)
    assert vc.get_active_client_id() == "default"