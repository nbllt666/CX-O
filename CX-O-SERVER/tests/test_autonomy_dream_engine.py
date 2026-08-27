"""DreamEngine 后台任务引用管理测试（修复第六轮 B2：fire-and-forget 任务被 GC 回收）。"""
import asyncio

from server.autonomy.dream.engine import DreamEngine


def _make_engine() -> DreamEngine:
    """构造最小 DreamEngine（__init__ 仅保存组件，不调用；传 None 即可）。"""
    return DreamEngine(
        collector=None,
        generator=None,
        dream_filter=None,
        buffer=None,
        consolidator=None,
        purge_job=None,
    )


def test_tracked_task_discarded_after_done() -> None:
    """任务完成后经 done 回调从 _bg_tasks 集合清空，防止集合无限增长。"""

    async def scenario() -> set:
        engine = _make_engine()

        async def _short():
            await asyncio.sleep(0)

        task = engine._track_background_task(asyncio.create_task(_short()))
        assert task in engine._bg_tasks
        await task
        # 给 done callback 一个执行机会
        await asyncio.sleep(0)
        return engine._bg_tasks

    result = asyncio.run(scenario())
    assert result == set()


def test_stop_cancels_background_tasks() -> None:
    """stop() 取消仍运行的后台子任务并清空集合，避免循环退出后遗留。"""

    async def scenario() -> bool:
        engine = _make_engine()

        async def _long():
            await asyncio.sleep(3600)

        engine._track_background_task(asyncio.create_task(_long()))
        engine._track_background_task(asyncio.create_task(_long()))
        assert len(engine._bg_tasks) == 2
        engine.stop()
        return engine._bg_tasks == set()

    assert asyncio.run(scenario())