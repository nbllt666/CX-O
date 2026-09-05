"""server/autonomy/dream/engine.py（DreamEngine 主引擎与昼夜挂点）单测。

覆盖：
1. run_session happy path：collect/generate/filter/buffer.put 全 mock，
   approved 入缓冲（字段组装断言：dream_session_id/candidate_content/
   emotion_shift/associated_entities/associated_memories/lucidity_score）、
   rejected 计数
2. 真实 DreamFilter 集成：事实断言 / 低清醒度 / 触碰 permanent 记忆 → 拒
3. 异常隔离：collect / generate / filter / buffer.put 任一组件抛异常不中断整轮
4. start/_run_loop 相位触发：mock circadian 相位序列
   （sleep→run_session、wake→purge+surface；surface_on_wake=false 跳过 surface）
5. get_status 各态：disabled（未启动/已停止）、idle、dreaming、purge_scheduled
6. 生命周期：start 幂等 / enabled=false 不启动 / stop 幂等
7. 入睡流程（Task 3）：确认闸门通过/拒绝、首步自动摘要执行、摘要失败降级
   仍不阻断并最终进入 run_session 的分支
8. 触发闸门（Task 4）：默认配置零回归（不查情绪峰值）、情绪满足/不满足/
   空窗/查询异常降级、概率命中/未命中、Sensor 路径闸门拦截与冷却优先

运行：python -m pytest tests/test_dream_engine.py -q
"""
import asyncio
from datetime import datetime

import pytest

import server.autonomy.dream.engine as engine_module
from server.autonomy.dream.collector import DreamMaterialSnapshot
from server.autonomy.dream.config import DreamConfig, DreamTriggerConfig
from server.autonomy.dream.engine import DreamEngine
from server.autonomy.dream.filter import DreamFilter
from server.autonomy.dream.generator import DreamCandidate

# 引擎关闭后让后台任务退出的沉降时间
_SETTLE = 0.05


# ================================================================ fakes
class FakeCollector:
    def __init__(self, snapshot=None, exc=None, delay=0.0):
        self.snapshot = snapshot or DreamMaterialSnapshot(
            memories=[], isolated_entities=[], emotion_baseline=0.0, agent_id="default"
        )
        self.exc = exc
        self.delay = delay
        self.calls = 0

    async def collect(self, agent_id="default"):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.snapshot


class FakeGenerator:
    def __init__(self, candidates=None, exc=None):
        self.candidates = list(candidates or [])
        self.exc = exc
        self.calls = 0

    async def generate(self, snapshot):
        self.calls += 1
        if self.exc:
            raise self.exc
        return list(self.candidates)


class FakeFilter:
    """filter_candidate 默认放行；verdicts 依次返回（耗尽后默认放行）。

    verdicts 项可为判定 dict，或 Exception（表示该次调用抛异常）。
    """

    def __init__(self, verdicts=None):
        self.verdicts = list(verdicts or [])
        self.calls = []

    def filter_candidate(self, candidate, meta, config):
        self.calls.append((candidate, meta, config))
        if len(self.calls) <= len(self.verdicts):
            verdict = self.verdicts[len(self.calls) - 1]
        else:
            verdict = {"approved": True, "decision": "approved", "reason": None}
        if isinstance(verdict, Exception):
            raise verdict
        return verdict


class FakeBuffer:
    def __init__(self, exc=None):
        self.putted = []
        self.exc = exc

    def put(self, candidate):
        if self.exc:
            raise self.exc
        self.putted.append(candidate)
        return len(self.putted)


class FakePurgeJob:
    def __init__(self, result=None, exc=None, delay=0.0):
        self.result = result or {"purged_memories": 0, "purged_buffer": 0}
        self.exc = exc
        self.delay = delay
        self.calls = 0

    async def run(self, agent_id="default"):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return dict(self.result)


class FakeConsolidator:
    def __init__(self, surface_result=True, exc=None):
        self.surface_result = surface_result
        self.exc = exc
        self.surface_calls = 0

    async def surface(self, agent_id="default"):
        self.surface_calls += 1
        if self.exc:
            raise self.exc
        return self.surface_result


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


# ================================================================ helpers
def make_engine(
    *,
    config=None,
    collector=None,
    generator=None,
    dream_filter=None,
    buffer=None,
    consolidator=None,
    purge_job=None,
    interval=0.05,
    ws_manager=None,
):
    """构造 DreamEngine（默认 enabled=True，循环间隔 0.05s 便于测试）。"""
    return DreamEngine(
        collector=collector or FakeCollector(),
        generator=generator or FakeGenerator(),
        dream_filter=dream_filter or FakeFilter(),
        buffer=buffer or FakeBuffer(),
        consolidator=consolidator or FakeConsolidator(),
        purge_job=purge_job or FakePurgeJob(),
        config=config or DreamConfig(enabled=True),
        ws_manager=ws_manager,
        interval_seconds=interval,
    )


def _candidate(content="梦见一片发光的海", lucidity=0.8, session_id="sess-1", **overrides):
    cand = DreamCandidate(
        content=content,
        emotion_shift={"valence": 0.3, "arousal": 0.5},
        associated_entities=["海", "光"],
        lucidity_score=lucidity,
        session_id=session_id,
    )
    return cand


def _snapshot(memories=None, entities=None, baseline=0.4):
    return DreamMaterialSnapshot(
        memories=memories
        or [
            {"id": 1, "importance_score": 0.3, "permanent": False, "content": "记忆A"},
            {"id": 2, "importance_score": 0.2, "permanent": False, "content": "记忆B"},
        ],
        isolated_entities=entities or ["孤岛"],
        emotion_baseline=baseline,
        agent_id="default",
    )


# ================================================================ run_session
@pytest.mark.asyncio
class TestRunSession:
    async def test_happy_path_approved_into_buffer_and_rejected_counted(self):
        filt = FakeFilter(
            verdicts=[
                {"approved": True, "decision": "approved", "reason": None},
                {"approved": False, "decision": "rejected", "reason": "low_lucidity"},
                {"approved": False, "decision": "rejected", "reason": "factual_hallucination"},
            ]
        )
        buf = FakeBuffer()
        engine = make_engine(
            collector=FakeCollector(_snapshot()),
            generator=FakeGenerator([_candidate(), _candidate(), _candidate()]),
            dream_filter=filt,
            buffer=buf,
        )

        result = await engine.run_session("default")

        assert result == {"generated": 3, "approved": 1, "rejected": 2}
        # approved 入缓冲，字段组装断言
        assert len(buf.putted) == 1
        item = buf.putted[0]
        assert item["dream_session_id"] == "sess-1"
        assert item["agent_id"] == "default"
        assert item["candidate_content"] == "梦见一片发光的海"
        assert item["lucidity_score"] == 0.8
        assert item["emotion_shift"] == {"valence": 0.3, "arousal": 0.5}
        assert item["associated_entities"] == ["海", "光"]
        assert item["associated_memories"] == [1, 2]
        # 传给 filter 的 associated_memories_meta 含 importance_score/permanent
        assert filt.calls[0][1] == [
            {"id": 1, "importance_score": 0.3, "permanent": False, "content": "记忆A"},
            {"id": 2, "importance_score": 0.2, "permanent": False, "content": "记忆B"},
        ]
        # 统计累计
        stats = engine.get_status()["stats"]
        assert stats == {
            "sessions": 1,
            "generated": 3,
            "approved": 1,
            "rejected": 2,
            "purges": 0,
        }
        assert engine.get_status()["last_session_at"] is not None

    async def test_real_filter_rejects_factual_and_low_lucidity(self):
        buf = FakeBuffer()
        engine = make_engine(
            collector=FakeCollector(_snapshot()),
            generator=FakeGenerator(
                [
                    _candidate(content="梦见一片发光的海", lucidity=0.8),
                    _candidate(content="你昨天去了医院", lucidity=0.9),  # 事实断言 → 拒
                    _candidate(content="梦见在云上奔跑", lucidity=0.1),  # 低清醒度 → 拒
                ]
            ),
            dream_filter=DreamFilter(),
            buffer=buf,
        )

        result = await engine.run_session()

        assert result == {"generated": 3, "approved": 1, "rejected": 2}
        assert len(buf.putted) == 1
        assert buf.putted[0]["candidate_content"] == "梦见一片发光的海"

    async def test_real_filter_rejects_when_snapshot_touches_permanent(self):
        engine = make_engine(
            collector=FakeCollector(
                _snapshot(
                    memories=[
                        {"id": 9, "importance_score": 0.9, "permanent": True, "content": "重要记忆"},
                    ]
                )
            ),
            generator=FakeGenerator([_candidate()]),
            dream_filter=DreamFilter(),
        )

        result = await engine.run_session()

        # 红线 R2：触碰 permanent 记忆 → 拒
        assert result == {"generated": 1, "approved": 0, "rejected": 1}

    async def test_run_session_empty_candidates(self):
        engine = make_engine(generator=FakeGenerator([]))
        result = await engine.run_session()
        assert result == {"generated": 0, "approved": 0, "rejected": 0}


# ================================================================ 异常隔离
@pytest.mark.asyncio
class TestExceptionIsolation:
    async def test_collector_error_isolated_returns_zero(self):
        engine = make_engine(
            collector=FakeCollector(exc=RuntimeError("collect down")),
            generator=FakeGenerator([_candidate()]),
        )

        result = await engine.run_session()

        assert result == {"generated": 0, "approved": 0, "rejected": 0}

    async def test_generator_error_isolated_returns_zero(self):
        engine = make_engine(
            collector=FakeCollector(),
            generator=FakeGenerator(exc=RuntimeError("generate down")),
        )

        result = await engine.run_session()

        assert result == {"generated": 0, "approved": 0, "rejected": 0}

    async def test_filter_error_does_not_interrupt_round(self):
        # 第一条 filter 抛异常 → 该条按拒绝计数，第二条照常处理
        filt = FakeFilter(verdicts=[RuntimeError("filter down")])
        buf = FakeBuffer()
        engine = make_engine(
            generator=FakeGenerator([_candidate(), _candidate(content="第二条梦")]),
            dream_filter=filt,
            buffer=buf,
        )

        result = await engine.run_session()

        assert result == {"generated": 2, "approved": 1, "rejected": 1}
        assert len(buf.putted) == 1
        assert buf.putted[0]["candidate_content"] == "第二条梦"

    async def test_buffer_put_error_does_not_interrupt_round(self):
        # buffer.put 抛异常 → 该条按拒绝计数，整轮不抛出
        engine = make_engine(
            generator=FakeGenerator([_candidate(), _candidate(content="第二条梦")]),
            dream_filter=FakeFilter(),
            buffer=FakeBuffer(exc=RuntimeError("buffer down")),
        )

        result = await engine.run_session()

        assert result == {"generated": 2, "approved": 0, "rejected": 2}


# ================================================================ 相位触发
@pytest.mark.asyncio
class TestPhases:
    async def test_sleep_window_triggers_run_session(self, monkeypatch):
        FakeScheduler.sequence = [True, False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = FakeCollector(_snapshot())
        engine = make_engine(collector=collector)
        try:
            task = engine.start()
            assert task is not None
            await asyncio.sleep(0.15)
            # 睡眠窗口进入 → run_session 至少执行一次
            assert collector.calls >= 1
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_wake_window_triggers_purge_and_surface(self, monkeypatch):
        FakeScheduler.sequence = [True, False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        purge_job = FakePurgeJob()
        consolidator = FakeConsolidator()
        engine = make_engine(purge_job=purge_job, consolidator=consolidator)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            # 唤醒窗口进入 → purge + surface（surface_on_wake 默认 true）
            assert purge_job.calls >= 1
            assert consolidator.surface_calls >= 1
            assert engine.get_status()["stats"]["purges"] >= 1
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_wake_surface_skipped_when_surface_on_wake_false(self, monkeypatch):
        FakeScheduler.sequence = [True, False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        purge_job = FakePurgeJob()
        consolidator = FakeConsolidator()
        engine = make_engine(
            config=DreamConfig(enabled=True, surface_on_wake=False),
            purge_job=purge_job,
            consolidator=consolidator,
        )
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert purge_job.calls >= 1
            assert consolidator.surface_calls == 0
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_sleep_window_triggers_only_once_per_window(self, monkeypatch):
        # 连续两个 sleep 迭代只触发一次 run_session
        FakeScheduler.sequence = [True, True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = FakeCollector(_snapshot())
        engine = make_engine(collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.calls == 1
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_sleep_window_edge_skips_when_status_not_idle(self, monkeypatch):
        """M-E 定向: 边沿触发遇非 idle 状态（如 SleepSensor 已开跑）不再双开。"""
        FakeScheduler.sequence = [True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = FakeCollector(_snapshot())
        engine = make_engine(collector=collector)
        try:
            # 模拟 SleepSensor 路径已把引擎置为 dreaming
            engine._status = "dreaming"
            engine.start()
            await asyncio.sleep(0.15)
            # 非 idle → 边沿分支不触发第二路会话；状态不被边沿改写
            assert collector.calls == 0
            assert engine._status == "dreaming"
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_sleep_window_edge_skips_when_cooldown_pending(self, monkeypatch):
        """M-E 定向: 冷却未到（30 分钟内已有触发）时边沿跳过，防与 Sensor 双开。"""
        FakeScheduler.sequence = [True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = FakeCollector(_snapshot())
        engine = make_engine(collector=collector)
        try:
            engine._last_trigger_at = datetime.now()  # 刚触发过 → 冷却未过
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.calls == 0
            assert engine._status == "idle"  # 未进入 dreaming
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)


# ================================================================ M-E: Sensor 触发任务追踪
class TestSensorTaskTracking:
    class _AsleepSensor:
        def snapshot(self):
            return {"state": "ASLEEP", "signals": []}

    @pytest.mark.asyncio
    async def test_maybe_trigger_by_sensor_tracks_background_task(self):
        """M-E 定向: 裸 asyncio.create_task 改经 _track_background_task 登记。"""
        collector = FakeCollector(_snapshot(), delay=0.5)  # 拖慢会话便于断言在跑
        engine = make_engine(collector=collector, interval=5)
        engine._sleep_sensor = self._AsleepSensor()

        now = datetime.now()
        engine._maybe_trigger_by_sensor(now, sleeping=True)

        assert engine._status == "dreaming"
        # 任务已被登记（旧实现裸 create_task 无引用，GC 可静默回收）
        assert len(engine._bg_tasks) == 1
        engine.stop()
        await asyncio.sleep(_SETTLE)


# ================================================================ get_status
class TestGetStatus:
    def test_disabled_when_not_started(self):
        engine = make_engine(config=DreamConfig())  # enabled=False，未启动
        status = engine.get_status()
        assert status["status"] == "disabled"
        assert status["enabled"] is False
        assert status["last_session_at"] is None
        assert status["stats"] == {
            "sessions": 0,
            "generated": 0,
            "approved": 0,
            "rejected": 0,
            "purges": 0,
        }

    def test_disabled_when_enabled_but_not_started(self):
        engine = make_engine(config=DreamConfig(enabled=True))
        status = engine.get_status()
        assert status["status"] == "disabled"
        assert status["enabled"] is True

    @pytest.mark.asyncio
    async def test_idle_while_running_no_trigger(self, monkeypatch):
        FakeScheduler.sequence = [False, False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        engine = make_engine()
        try:
            engine.start()
            await asyncio.sleep(0.12)
            assert engine.get_status()["status"] == "idle"
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    @pytest.mark.asyncio
    async def test_dreaming_during_slow_session(self, monkeypatch):
        FakeScheduler.sequence = [True, True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = FakeCollector(_snapshot(), delay=0.2)
        engine = make_engine(collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.12)  # 会话仍在进行中
            assert engine.get_status()["status"] == "dreaming"
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    @pytest.mark.asyncio
    async def test_purge_scheduled_during_slow_wake_routines(self, monkeypatch):
        FakeScheduler.sequence = [True, False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        engine = make_engine(
            purge_job=FakePurgeJob(delay=0.2),
            consolidator=FakeConsolidator(),
        )
        try:
            engine.start()
            await asyncio.sleep(0.15)  # 唤醒例行任务仍在进行中
            assert engine.get_status()["status"] == "purge_scheduled"
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    @pytest.mark.asyncio
    async def test_disabled_after_stop(self, monkeypatch):
        FakeScheduler.sequence = [False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        engine = make_engine()
        try:
            engine.start()
            await asyncio.sleep(0.05)
            assert engine.get_status()["status"] == "idle"
            engine.stop()
            await asyncio.sleep(_SETTLE)
            assert engine.get_status()["status"] == "disabled"
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)


# ================================================================ 生命周期
@pytest.mark.asyncio
class TestLifecycle:
    async def test_start_idempotent(self, monkeypatch):
        FakeScheduler.sequence = [False]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        engine = make_engine(config=DreamConfig(enabled=True))
        try:
            task1 = engine.start()
            task2 = engine.start()
            assert task1 is not None
            assert task2 is None  # 已在运行
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_start_returns_none_when_disabled(self):
        engine = make_engine(config=DreamConfig(enabled=False))
        assert engine.start() is None
        assert engine.get_status()["status"] == "disabled"

    async def test_stop_when_not_started(self):
        engine = make_engine(config=DreamConfig(enabled=True))
        engine.stop()  # 不抛异常
        assert engine.get_status()["status"] == "disabled"


# ================================================================ Task 3 入睡流程（确认闸门 + 首步摘要）
class FakeSleepSensorTS:
    """可跟踪 transition_state 调用的假 SleepSensor（snapshot 恒 ASLEEP）。"""

    def __init__(self):
        self.transitions = []
        self.snapshots = 0

    def snapshot(self):
        self.snapshots += 1
        return {"state": "ASLEEP", "confidence": 0.9, "signals": [], "updated_at": ""}

    def transition_state(self, state, confidence=None, now=None):
        self.transitions.append(state)
        return {"state": state}


class FakeConfirmArbiter:
    """可配置确认结果的假 arbiter（记录调用次数）。"""

    def __init__(self, confirmed=True, exc=None):
        self.confirmed = confirmed
        self.exc = exc
        self.calls = 0

    async def should_confirm(self, snapshot):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.confirmed


class FakeAutoSummarizer:
    """记录调用次数并可配置抛异常的假摘要组件。"""

    def __init__(self, exc=None, result="自动摘要文本"):
        self.exc = exc
        self.result = result
        self.calls = 0
        self.last_agent = None

    async def summarize(self, agent_id="default"):
        self.calls += 1
        self.last_agent = agent_id
        if self.exc:
            raise self.exc
        return self.result


def make_sleep_engine(*, sensor, arbiter, summarizer, collector=None):
    """构造带 sleep_sensor + 确认闸门 + 自动摘要的 DreamEngine。"""
    return DreamEngine(
        collector=collector or FakeCollector(_snapshot()),
        generator=FakeGenerator([_candidate()]),
        dream_filter=FakeFilter(),
        buffer=FakeBuffer(),
        consolidator=FakeConsolidator(),
        purge_job=FakePurgeJob(),
        config=DreamConfig(enabled=True),
        interval_seconds=0.05,
        sleep_sensor=sensor,
        sleep_confirm_arbiter=arbiter,
        auto_summarizer=summarizer,
    )


@pytest.mark.asyncio
class TestSleepSummaryFlow:
    async def test_confirmed_runs_summary_then_session(self):
        sensor = FakeSleepSensorTS()
        arbiter = FakeConfirmArbiter(confirmed=True)
        summarizer = FakeAutoSummarizer()
        collector = FakeCollector(_snapshot())
        engine = make_sleep_engine(
            sensor=sensor, arbiter=arbiter, summarizer=summarizer, collector=collector
        )
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.08)  # 等待入睡流程（摘要 + 会话）完成

        # 确认通过 → 自动摘要执行 + run_session 进入（stats.sessions 累计）
        assert arbiter.calls == 1
        assert summarizer.calls == 1
        assert summarizer.last_agent == "default"
        assert collector.calls == 1
        assert engine.get_status()["stats"]["sessions"] == 1
        # 传感器先流转 ENTERING_SLEEP
        assert "ENTERING_SLEEP" in sensor.transitions

    async def test_confirmed_flow_called_after_returning_idle(self):
        sensor = FakeSleepSensorTS()
        arbiter = FakeConfirmArbiter(confirmed=True)
        summarizer = FakeAutoSummarizer()
        engine = make_sleep_engine(sensor=sensor, arbiter=arbiter, summarizer=summarizer)
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.08)
        # 流程结束回到 idle（非 dreaming）；直调无后台循环，故断言内部 _status
        assert engine._status == "idle"
        assert sensor.transitions[-1] == "ENTERING_SLEEP"

    async def test_rejected_skips_summary_and_session_and_returns_drowsy(self):
        sensor = FakeSleepSensorTS()
        arbiter = FakeConfirmArbiter(confirmed=False)
        summarizer = FakeAutoSummarizer()
        collector = FakeCollector(_snapshot())
        engine = make_sleep_engine(
            sensor=sensor, arbiter=arbiter, summarizer=summarizer, collector=collector
        )
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.08)

        # 确认拒绝 → 不执行摘要、不进入会话；传感器回退 DROWSY
        assert arbiter.calls == 1
        assert summarizer.calls == 0
        assert collector.calls == 0
        assert engine.get_status()["stats"]["sessions"] == 0
        assert sensor.transitions and sensor.transitions[-1] == "DROWSY"
        assert engine._status == "idle"

    async def test_summary_exception_still_proceeds_to_session(self):
        sensor = FakeSleepSensorTS()
        arbiter = FakeConfirmArbiter(confirmed=True)
        summarizer = FakeAutoSummarizer(exc=RuntimeError("summarizer down"))
        collector = FakeCollector(_snapshot())
        engine = make_sleep_engine(
            sensor=sensor, arbiter=arbiter, summarizer=summarizer, collector=collector
        )
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.08)

        # 摘要失败降级：异常被隔离、不阻断，仍最终进入 run_session
        assert summarizer.calls == 1
        assert collector.calls == 1
        assert engine.get_status()["stats"]["sessions"] == 1
        assert engine._status == "idle"

    async def test_no_auto_summarizer_zero_regression_direct_session(self):
        # 未注入 auto_summarizer → 保持原有直接触发（不经确认闸门、不自带摘要）
        sensor = FakeSleepSensorTS()
        collector = FakeCollector(_snapshot())
        engine = DreamEngine(
            collector=collector,
            generator=FakeGenerator([_candidate()]),
            dream_filter=FakeFilter(),
            buffer=FakeBuffer(),
            consolidator=FakeConsolidator(),
            purge_job=FakePurgeJob(),
            config=DreamConfig(enabled=True),
            interval_seconds=0.05,
            sleep_sensor=sensor,
            sleep_confirm_arbiter=FakeConfirmArbiter(confirmed=False),  # 即便拒绝也不走闸门
            auto_summarizer=None,
        )
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.05)
        assert collector.calls == 1
        assert engine.get_status()["stats"]["sessions"] == 1


# ================================================================ Task 3 trigger_auto_summary
@pytest.mark.asyncio
class TestTriggerAutoSummary:
    async def test_unused_summarizer_returns_none(self):
        engine = make_engine()  # 未注入 auto_summarizer
        result = await engine.trigger_auto_summary("default")
        assert result is None

    async def test_forwards_to_summarizer(self):
        summarizer = FakeAutoSummarizer(result="引擎启动摘要")
        engine = make_sleep_engine(
            sensor=FakeSleepSensorTS(),
            arbiter=FakeConfirmArbiter(confirmed=True),
            summarizer=summarizer,
        )
        result = await engine.trigger_auto_summary("default")
        assert result == "引擎启动摘要"
        assert summarizer.calls == 1
        assert summarizer.last_agent == "default"

    async def test_summary_exception_isolated_for_trigger(self):
        summarizer = FakeAutoSummarizer(exc=RuntimeError("down"))
        engine = make_sleep_engine(
            sensor=FakeSleepSensorTS(),
            arbiter=FakeConfirmArbiter(confirmed=True),
            summarizer=summarizer,
        )
        result = await engine.trigger_auto_summary("default")
        assert result is None  # 异常被隔离


# ================================================================ Task 4 触发闸门（情绪 + 概率）
class EmotionPeakCollector(FakeCollector):
    """带 collect_recent_emotion_peak 跟踪的假采集器（Task 4 闸门测试专用）。

    - collect() 行为继承 FakeCollector（会话素材采集）
    - collect_recent_emotion_peak() 返回配置的 peak/count，可注入异常；
      peak_calls 记录每次调用 (agent_id, window_hours)
    """

    def __init__(self, snapshot=None, peak=0.0, count=0, peak_exc=None, **kwargs):
        super().__init__(snapshot=snapshot, **kwargs)
        self.peak = peak
        self.count = count
        self.peak_exc = peak_exc
        self.peak_calls = []

    async def collect_recent_emotion_peak(self, agent_id, window_hours=24):
        self.peak_calls.append((agent_id, window_hours))
        if self.peak_exc:
            raise self.peak_exc
        return {"peak": self.peak, "count": self.count}


class _AsleepOnlySensor:
    """snapshot 恒 ASLEEP 的假 SleepSensor（无流转方法，闸门拦截用不到）。"""

    def snapshot(self):
        return {"state": "ASLEEP", "signals": []}


def _emotion_trigger_config(**overrides):
    """构造开启情绪闸门的 DreamTriggerConfig（其余字段用默认）。"""
    return DreamTriggerConfig(emotion_enabled=True, **overrides)


def make_gate_engine(*, config=None, collector=None, sensor=None):
    """构造 Task 4 闸门测试用 DreamEngine（enabled=True，间隔 0.05s）。"""
    return DreamEngine(
        collector=collector or EmotionPeakCollector(_snapshot()),
        generator=FakeGenerator([_candidate()]),
        dream_filter=FakeFilter(),
        buffer=FakeBuffer(),
        consolidator=FakeConsolidator(),
        purge_job=FakePurgeJob(),
        config=config or DreamConfig(enabled=True),
        interval_seconds=0.05,
        sleep_sensor=sensor,
    )


@pytest.mark.asyncio
class TestTriggerGates:
    async def test_default_config_edge_trigger_zero_regression(self, monkeypatch):
        """默认配置（emotion_enabled=False, probability=1.0）零回归：
        边沿触发照常进入会话，且不发起任何情绪峰值查询。"""
        FakeScheduler.sequence = [True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = EmotionPeakCollector(_snapshot())
        engine = make_gate_engine(collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.calls >= 1          # 会话照常触发
            assert collector.peak_calls == []    # 情绪闸门关闭 → 零查询
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_emotion_gate_pass_triggers_session(self, monkeypatch):
        """emotion_enabled=True 且 peak=0.85/count=3 ≥ threshold=0.7 → 边沿触发。"""
        FakeScheduler.sequence = [True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = EmotionPeakCollector(_snapshot(), peak=0.85, count=3)
        config = DreamConfig(enabled=True, trigger=_emotion_trigger_config())
        engine = make_gate_engine(config=config, collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.peak_calls          # 情绪峰值已被查询
            assert collector.calls >= 1          # 闸门通过 → 会话触发
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_emotion_gate_peak_below_threshold_blocks(self, monkeypatch):
        """peak=0.4 < threshold=0.7 → 不触发、状态仍 idle、_last_trigger_at 不更新。"""
        FakeScheduler.sequence = [True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = EmotionPeakCollector(_snapshot(), peak=0.4, count=3)
        config = DreamConfig(enabled=True, trigger=_emotion_trigger_config())
        engine = make_gate_engine(config=config, collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.calls == 0
            assert engine._status == "idle"
            assert engine._last_trigger_at is None
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_emotion_gate_empty_window_blocks(self, monkeypatch):
        """count=0（空窗）→ 即使 peak 达标也不触发。"""
        FakeScheduler.sequence = [True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = EmotionPeakCollector(_snapshot(), peak=0.9, count=0)
        config = DreamConfig(enabled=True, trigger=_emotion_trigger_config())
        engine = make_gate_engine(config=config, collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.calls == 0
            assert engine._status == "idle"
            assert engine._last_trigger_at is None
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_emotion_gate_query_exception_degrades(self, monkeypatch):
        """情绪查询异常 → 闸门降级 False、不触发、主循环不崩（保持运行）。"""
        FakeScheduler.sequence = [True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        collector = EmotionPeakCollector(
            _snapshot(), peak_exc=RuntimeError("emotion query down")
        )
        config = DreamConfig(enabled=True, trigger=_emotion_trigger_config())
        engine = make_gate_engine(config=config, collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.peak_calls                    # 查询已发起
            assert collector.calls == 0                    # 未触发会话
            assert engine._status == "idle"                # 主循环存活
            assert engine._task is not None and not engine._task.done()
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_probability_roll_miss_blocks_edge_trigger(self, monkeypatch):
        """probability=0.5 且 random()=0.7 → 未命中，边沿不触发（情绪闸门关闭）。"""
        FakeScheduler.sequence = [True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        monkeypatch.setattr(engine_module.random, "random", lambda: 0.7)
        collector = EmotionPeakCollector(_snapshot())
        config = DreamConfig(enabled=True, trigger=DreamTriggerConfig(probability=0.5))
        engine = make_gate_engine(config=config, collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.calls == 0
            assert engine._status == "idle"
            assert engine._last_trigger_at is None
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_probability_roll_hit_allows_edge_trigger(self, monkeypatch):
        """probability=0.5 且 random()=0.3 → 命中，边沿触发（概率独立生效）。"""
        FakeScheduler.sequence = [True]
        monkeypatch.setattr(engine_module, "CircadianScheduler", FakeScheduler)
        monkeypatch.setattr(engine_module.random, "random", lambda: 0.3)
        collector = EmotionPeakCollector(_snapshot())
        config = DreamConfig(enabled=True, trigger=DreamTriggerConfig(probability=0.5))
        engine = make_gate_engine(config=config, collector=collector)
        try:
            engine.start()
            await asyncio.sleep(0.15)
            assert collector.calls >= 1
        finally:
            engine.stop()
            await asyncio.sleep(_SETTLE)

    async def test_sensor_path_blocked_by_emotion_gate(self):
        """Sensor 路径：情绪闸门不满足（peak=0.4）→ 不触发会话、不更新触发时刻。"""
        collector = EmotionPeakCollector(_snapshot(), peak=0.4, count=2)
        config = DreamConfig(enabled=True, trigger=_emotion_trigger_config())
        engine = make_gate_engine(
            config=config, collector=collector, sensor=_AsleepOnlySensor()
        )
        # 模拟后台循环每轮评估后的缓存
        gate = await engine._passes_emotion_gate()
        assert gate is False

        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.08)

        assert collector.calls == 0                      # 未触发会话
        assert engine.get_status()["stats"]["sessions"] == 0
        assert engine._last_trigger_at is None           # 触发时刻不更新

    async def test_sensor_path_gate_after_cooldown(self):
        """闸门位于冷却之后：冷却未过时直接 return（不触发会话）。

        实现选择说明：情绪闸门评估在 _run_loop 每轮无条件进行（缓存刷新），
        故"冷却未过时 collector 零查询"不成立；本用例断言 Sensor 触发点在
        冷却未过时直接 return——即便闸门缓存为 True 也不触发。
        """
        collector = EmotionPeakCollector(_snapshot(), peak=0.9, count=5)
        config = DreamConfig(enabled=True, trigger=_emotion_trigger_config())
        engine = make_gate_engine(
            config=config, collector=collector, sensor=_AsleepOnlySensor()
        )
        gate = await engine._passes_emotion_gate()
        assert gate is True
        engine._emotion_gate_cache = True

        engine._last_trigger_at = datetime.now()  # 刚触发过 → 冷却未过
        engine._maybe_trigger_by_sensor(datetime.now(), sleeping=True)
        await asyncio.sleep(0.08)

        assert collector.calls == 0
        assert engine._status == "idle"
