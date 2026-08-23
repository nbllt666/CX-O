"""server/autonomy/dream/engine.py SleepSensor 生理确认触发单测（Task 4）。

覆盖：
1. 零回归：未注入 sleep_sensor 时保持纯 circadian 时间窗口（窗口进入触发、清醒不触发）
2. 窗口内确认：sleep_sensor.snapshot()['state']=='ASLEEP' 且睡眠窗口内 → 触发 run_session
3. S4 短路：窗口外 ASLEEP（S4 显式睡眠语短路）也可触发；无 S4 的窗口外 ASLEEP 不触发
4. 冷却：距上次触发不足冷却不触发；超过冷却可再次触发
5. 异常隔离：sleep_sensor.snapshot() / refresh 抛异常不中断主循环
6. refresh：每轮调用 sleep_sensor_refresh（S9 置信度 / S7 时间先验刷新）

运行：python -m pytest tests/test_dream_engine_physio.py -q
"""
import asyncio
import json
import types
from datetime import datetime, timedelta

import pytest

import server.autonomy.dream.engine as engine_module
from server.autonomy.dream.collector import DreamMaterialSnapshot
from server.autonomy.dream.config import DreamConfig
from server.autonomy.dream.engine import DreamEngine
from server.autonomy.dream.generator import DreamCandidate, DreamGenerator

# 引擎关闭后让后台任务退出的沉降时间
_SETTLE = 0.05

# 测试用冷却：显著小于默认 30min，便于在真实循环中观察再次触发
_SHORT_COOLDOWN = 0.01


# ================================================================ fakes
class FakeCollector:
    def __init__(self, snapshot=None, delay=0.0):
        self.snapshot = snapshot or DreamMaterialSnapshot(
            memories=[], isolated_entities=[], emotion_baseline=0.0, agent_id="default"
        )
        self.delay = delay
        self.calls = 0

    async def collect(self, agent_id="default"):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.calls += 1
        return self.snapshot


class FakeGenerator:
    def __init__(self):
        self.calls = 0

    async def generate(self, snapshot):
        self.calls += 1
        return []


class FakeFilter:
    def filter_candidate(self, candidate, meta, config):
        return {"approved": True, "decision": "approved", "reason": None}


class FakeBuffer:
    def __init__(self):
        self.putted = []

    def put(self, candidate):
        self.putted.append(candidate)
        return len(self.putted)


class FakePurgeJob:
    def __init__(self):
        self.calls = 0

    async def run(self, agent_id="default"):
        self.calls += 1
        return {"purged_memories": 0, "purged_buffer": 0}


class FakeConsolidator:
    def __init__(self):
        self.surface_calls = 0

    async def surface(self, agent_id="default"):
        self.surface_calls += 1
        return True


class FakeScheduler:
    """模拟 circadian 相位序列：is_sleep_time 依次返回 sequence，耗尽后固定最后值。

    start() 以 CircadianScheduler(schedule) 形式构造，故 __init__ 接受任意参数。
    """

    sequence = [False]

    def __init__(self, *args, **kwargs):
        self.iterations = 0

    def is_sleep_time(self, now):
        seq = type(self).sequence
        idx = min(self.iterations, len(seq) - 1)
        self.iterations += 1
        return seq[idx]


def make_s4_signals(value=1.0, available=True):
    """S4 显式睡眠语短路信号（对齐 SleepSensor.snapshot() 的 signals 结构）。"""
    return [{"name": "S4", "weight": 1.0, "value": value, "available": available}]


class FakeSleepSensor:
    """可切换状态/信号的假 SleepSensor；exc 非 None 时 snapshot() 抛异常。"""

    def __init__(self, state="AWAKE", signals=None, exc=None):
        self.state = state
        self.signals = list(signals or [])
        self.exc = exc
        self.snapshots = 0

    def snapshot(self):
        self.snapshots += 1
        if self.exc:
            raise self.exc
        return {
            "state": self.state,
            "confidence": 0.9,
            "signals": list(self.signals),
            "updated_at": datetime.now().isoformat(),
        }


# ================================================================ helpers
def make_engine(
    *,
    config=None,
    collector=None,
    interval=0.05,
    sleep_sensor=None,
    sleep_sensor_refresh=None,
):
    """构造 DreamEngine（默认 enabled=True，循环间隔 0.05s 便于测试）。"""
    return DreamEngine(
        collector=collector or FakeCollector(),
        generator=FakeGenerator(),
        dream_filter=FakeFilter(),
        buffer=FakeBuffer(),
        consolidator=FakeConsolidator(),
        purge_job=FakePurgeJob(),
        config=config or DreamConfig(enabled=True),
        interval_seconds=interval,
        sleep_sensor=sleep_sensor,
        sleep_sensor_refresh=sleep_sensor_refresh,
    )


# ================================================================ ① 零回归（无 sleep_sensor）
@pytest.mark.asyncio
class TestZeroRegression:
    async def test_sleep_window_still_triggers_without_sensor(self, monkeypatch):
        FakeScheduler.sequence = [True, False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = FakeCollector()
        engine = make_engine(collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.calls >= 1  # 纯时间窗口进入仍触发
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_awake_no_trigger_without_sensor(self, monkeypatch):
        FakeScheduler.sequence = [False, False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = FakeCollector()
        engine = make_engine(collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.12)
            assert collector.calls == 0  # 清醒时段不触发
            assert engine.get_status()["status"] == "idle"
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)


# ================================================================ ② 窗口内 ASLEEP 确认触发
@pytest.mark.asyncio
class TestSensorTriggerInWindow:
    async def test_asleep_in_window_triggers(self):
        sensor = FakeSleepSensor(state="ASLEEP")
        collector = FakeCollector()
        engine = make_engine(collector=collector, sleep_sensor=sensor)
        # 直调触发分支：窗口内 ASLEEP → 触发 run_session
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.05)
        assert collector.calls == 1
        assert engine.get_status()["stats"]["sessions"] == 1

    async def test_awake_in_window_does_not_trigger(self):
        sensor = FakeSleepSensor(state="AWAKE")
        collector = FakeCollector()
        engine = make_engine(collector=collector, sleep_sensor=sensor)
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.05)
        assert collector.calls == 0

    async def test_loop_with_sensor_asleep_in_window(self, monkeypatch):
        # 真实循环：睡眠窗口内 ASLEEP 持续触发（冷却后再次触发）
        FakeScheduler.sequence = [True, True, True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        sensor = FakeSleepSensor(state="ASLEEP")
        collector = FakeCollector()
        engine = make_engine(collector=collector, sleep_sensor=sensor)
        engine._sleep_sensor_cooldown_seconds = _SHORT_COOLDOWN
        try:
            engine.start()
            await asyncio.sleep(0.15)
            # 窗口边沿 + SleepSensor 确认均产生会话 → 至少 2 次
            assert collector.calls >= 2
            assert sensor.snapshots >= 1
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)


# ================================================================ ③ S4 短路窗口外触发
@pytest.mark.asyncio
class TestS4ShortcutOutsideWindow:
    async def test_s4_shortcut_outside_window_triggers(self):
        sensor = FakeSleepSensor(state="ASLEEP", signals=make_s4_signals(value=1.0))
        collector = FakeCollector()
        engine = make_engine(collector=collector, sleep_sensor=sensor)
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=False)
        await asyncio.sleep(0.05)
        assert collector.calls == 1

    async def test_asleep_outside_window_without_s4_does_not_trigger(self):
        sensor = FakeSleepSensor(state="ASLEEP", signals=make_s4_signals(value=0.0))
        collector = FakeCollector()
        engine = make_engine(collector=collector, sleep_sensor=sensor)
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=False)
        await asyncio.sleep(0.05)
        assert collector.calls == 0

    async def test_loop_s4_shortcut_outside_window_triggers(self, monkeypatch):
        # 真实循环：全程清醒（窗口外）+ S4 短路 ASLEEP → 仍触发
        FakeScheduler.sequence = [False, False, False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        sensor = FakeSleepSensor(state="ASLEEP", signals=make_s4_signals(value=1.0))
        collector = FakeCollector()
        engine = make_engine(collector=collector, sleep_sensor=sensor)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.calls >= 1
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)


# ================================================================ ④ 冷却防高频
@pytest.mark.asyncio
class TestCooldown:
    async def test_cooldown_blocks_repeat_trigger(self):
        sensor = FakeSleepSensor(state="ASLEEP")
        collector = FakeCollector()
        engine = make_engine(collector=collector, sleep_sensor=sensor)
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.05)  # 会话完成，状态回 idle
        assert collector.calls == 1
        # 冷却未过（默认 30min）→ 不再触发
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.05)
        assert collector.calls == 1

    async def test_cooldown_passed_allows_retrigger(self):
        sensor = FakeSleepSensor(state="ASLEEP")
        collector = FakeCollector()
        engine = make_engine(collector=collector, sleep_sensor=sensor)
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.05)
        assert collector.calls == 1
        # 手动将上次触发置为 31 分钟前 → 冷却已过，可再次触发
        engine._last_trigger_at = datetime.now() - timedelta(minutes=31)
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.05)
        assert collector.calls == 2


# ================================================================ ⑤ 异常隔离
@pytest.mark.asyncio
class TestExceptionIsolation:
    async def test_snapshot_exception_isolated_in_loop(self, monkeypatch):
        FakeScheduler.sequence = [True, True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        sensor = FakeSleepSensor(state="ASLEEP", exc=RuntimeError("sensor down"))
        collector = FakeCollector()
        engine = make_engine(collector=collector, sleep_sensor=sensor)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            # snapshot 抛异常 → 不触发，但主循环仍存活（状态可查询、stop 正常）
            assert collector.calls >= 1  # 窗口边沿触发不受影响
            assert engine.get_status()["status"] in ("idle", "dreaming")
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_refresh_exception_isolated_in_loop(self, monkeypatch):
        FakeScheduler.sequence = [False, False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)

        def _bad_refresh(now):
            raise RuntimeError("refresh down")

        engine = make_engine(sleep_sensor=FakeSleepSensor(state="AWAKE"), sleep_sensor_refresh=_bad_refresh)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            # refresh 抛异常 → 主循环不中断
            assert engine.get_status()["status"] == "idle"
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_snapshot_exception_unit(self):
        sensor = FakeSleepSensor(state="ASLEEP", exc=RuntimeError("sensor down"))
        collector = FakeCollector()
        engine = make_engine(collector=collector, sleep_sensor=sensor)
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.05)
        assert collector.calls == 0  # 异常被隔离，不触发
        assert sensor.snapshots == 1


# ================================================================ ⑥ refresh 每轮调用
@pytest.mark.asyncio
class TestRefreshCalled:
    async def test_refresh_called_each_iteration(self, monkeypatch):
        FakeScheduler.sequence = [False, False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        refreshed = []

        def _refresh(now):
            refreshed.append(now)

        engine = make_engine(sleep_sensor=FakeSleepSensor(state="AWAKE"), sleep_sensor_refresh=_refresh)
        try:
            engine.start()
            await asyncio.sleep(0.12)
            assert len(refreshed) >= 1  # 每轮调用（刷新 S9 置信度 / S7 时间先验）
            assert all(isinstance(n, datetime) for n in refreshed)
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)


# ================================================================ ⑦ 隐私红线 R6 负向断言（F3）
class _FakeModelRouter:
    """捕获生成器 prompt 的假模型路由器（chat 返回合法 JSON 候选）。"""

    def __init__(self):
        self.prompts = []

    def get_client(self, model):
        return self

    async def chat(self, messages, stream=False, **kw):
        user = [m for m in messages if m["role"] == "user"]
        self.prompts.append(user[0]["content"] if user else "")
        return types.SimpleNamespace(
            content=json.dumps(
                {
                    "content": "梦见一片发光的海",
                    "emotion_shift": {"valence": 0.3, "arousal": 0.5},
                    "associated_entities": ["海"],
                    "lucidity_score": 0.8,
                }
            ),
            error=None,
        )


class TestPrivacyNoRawHrLeak:
    """R6 负向断言：梦境生成输入链 / 缓冲候选 / 记忆写入 metadata 不含原始 HR 字段。

    - 生成器 prompt 构造只读取 content/created_at，忽略记忆中的 bpm/heart_rate/raw_hr 等键
    - _build_associated_meta / _to_buffer_candidate 只复制白名单字段，原始 HR 不进入
      过滤 metadata 与缓冲候选
    - run_session 端到端：真实 DreamGenerator 的 prompt 与缓冲候选均无原始 HR 字段
    （PhysioSignalStore 持久化键白名单断言见 tests/test_physio_store.py，本处补梦境侧）
    """

    _RAW_HR_FIELDS = ("bpm", "heart_rate", "raw_hr", "hr_samples")

    @staticmethod
    def _memory_with_raw_hr():
        """一条携带原始 HR 字段的记忆（模拟上游误入库，验证梦境侧不读取）。"""
        return {
            "id": 1,
            "importance_score": 0.3,
            "permanent": False,
            "content": "记忆A",
            "bpm": 60,
            "heart_rate": [60, 61],
            "raw_hr": [60, 61, 62],
            "hr_samples": [{"bpm": 60, "ts": 1}],
        }

    def test_generator_prompt_construction_ignores_raw_hr(self):
        snapshot = DreamMaterialSnapshot(
            memories=[self._memory_with_raw_hr()],
            isolated_entities=["孤岛"],
            emotion_baseline=0.4,
            agent_id="default",
        )
        prompt = DreamGenerator(config=DreamConfig())._build_prompt(snapshot)
        for field in self._RAW_HR_FIELDS:
            assert field not in prompt

    def test_associated_meta_and_buffer_candidate_clean(self):
        engine = make_engine()
        meta = engine._build_associated_meta([self._memory_with_raw_hr()])
        # 过滤 metadata 仅复制白名单字段
        assert set(meta[0]) == {"id", "importance_score", "permanent", "content"}
        cand = DreamCandidate(
            content="梦见云海",
            emotion_shift={"valence": 0.3, "arousal": 0.5},
            associated_entities=["云"],
            lucidity_score=0.8,
            session_id="s1",
        )
        buf_item = engine._to_buffer_candidate(cand, "default", meta)
        for field in self._RAW_HR_FIELDS:
            assert field not in buf_item

    @pytest.mark.asyncio
    async def test_run_session_no_raw_hr_in_prompt_and_buffer(self):
        router = _FakeModelRouter()
        gen = DreamGenerator(
            model_router=router, config=DreamConfig(candidates_per_session=1)
        )
        buf = FakeBuffer()
        engine = DreamEngine(
            collector=FakeCollector(
                DreamMaterialSnapshot(
                    memories=[self._memory_with_raw_hr()],
                    isolated_entities=["孤岛"],
                    emotion_baseline=0.4,
                    agent_id="default",
                )
            ),
            generator=gen,
            dream_filter=FakeFilter(),
            buffer=buf,
            consolidator=FakeConsolidator(),
            purge_job=FakePurgeJob(),
            config=DreamConfig(enabled=True),
            interval_seconds=0.05,
        )
        result = await engine.run_session()
        assert result == {"generated": 1, "approved": 1, "rejected": 0}
        # 生成器 prompt 构造输入不含原始 HR 字段
        assert len(router.prompts) == 1
        for field in self._RAW_HR_FIELDS:
            assert field not in router.prompts[0]
        # 缓冲候选不含原始 HR 字段
        assert len(buf.putted) == 1
        for field in self._RAW_HR_FIELDS:
            assert field not in buf.putted[0]
