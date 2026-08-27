"""setup_autonomy 装配异常清理测试（修复第六轮 B2：停止已启动引擎防泄漏）。

通过直接验证 _safe_stop_after_assembly_error（被装配 except 路径调用的清理逻辑），
确认异常后 engine / dream_engine 的 stop 都会被调用、每个 stop 单独被 try/except
包裹（单个失败不遮蔽原始异常、不影响其余），且对 awaitable/sync 的 stop 均兼容。
"""
import asyncio

from server.autonomy import main


class _FakeEngine:
    def __init__(self, async_stop=False, fail=False):
        self.async_stop = async_stop
        self.fail = fail
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        if self.fail:
            raise RuntimeError("stop boom")
        if self.async_stop:
            async def _inner():
                return None

            return _inner()
        return None


def test_cleanup_stops_both_engines_sync_and_async() -> None:
    """注册失败后被调用的清理应同时 stop sync(dream) 与 async(engine)。"""
    engine = _FakeEngine()          # 仿 AutonomyEngine.async stop 之外也用 sync 验证
    dream = _FakeEngine(async_stop=True)  # DreamEngine.stop 为 sync，engine 用 async
    asyncio.run(main._safe_stop_after_assembly_error(dream, engine))
    assert dream.stop_calls == 1
    assert engine.stop_calls == 1


def test_cleanup_swallows_single_stop_error() -> None:
    """单个 stop 抛异常被隔离，不遮蔽原始装配异常，也不影响其余对象。"""
    engine = _FakeEngine(fail=True)
    dream = _FakeEngine(async_stop=True)
    # 不应抛出任何异常
    asyncio.run(main._safe_stop_after_assembly_error(dream, engine))
    assert dream.stop_calls == 1
    assert engine.stop_calls == 1


def test_cleanup_skips_none_and_non_callable() -> None:
    """None 或缺少可调用 stop 的对象被跳过（未启动场景），不抛错。"""
    engine = _FakeEngine()
    # 同时验证 None 与无 stop 属性的对象均安全跳过
    nobody = object()  # 无 stop 属性
    asyncio.run(main._safe_stop_after_assembly_error(None, engine))
    asyncio.run(main._safe_stop_after_assembly_error(nobody, engine))
    assert engine.stop_calls == 2