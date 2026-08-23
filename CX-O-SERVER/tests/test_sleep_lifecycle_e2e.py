"""CX-O-Dream 休眠系统补强跨模块端到端生命周期测试（Task 4）。

在 TestSleepSummaryFlow（test_dream_engine.py）等单测之上，用**真实**组件拼装一条
端到端链路，验证"信号达标 → LLM 确认 → 首步自动摘要 → 进入梦境会话 → 用户唤醒意图
终止休眠 → 唤醒后引擎恢复可承接"的完整生命周期：

- 真实 SleepSensor（sleep_sensor.py）：状态机与 snapshot/wake_up/transition_state
- 真实 SleepConfirmationArbiter（confirmation.py）+ fake llm（返回 "是" / "否"）
- 真实 SleepAutoSummarizer（summarizer.py）+ fake memory_manager / llm / context_manager
- 真实 DreamEngine（engine.py）注入上述三件真实组件，直接调用 _maybe_trigger_by_sensor
  （不启动后台昼夜循环，避免时钟/相位不确定），异步等待入睡流程任务完成。
- 真实 chat._maybe_wake_from_sleep（handlers/chat.py）经 monkeypatch 注入
  deps._service_state.physio_runtime.sleep_sensor，验证用户唤醒意图的终止休眠与广播。

覆盖（对齐 Task 4 目标）：
1. 信号达标（S4 短路 ASLEEP）→ LLM 确认通过 → 首步自动摘要 → 进入梦境会话；
   断言确认被调用、摘要先于会话采集执行、sensor 经 ENTERING_SLEEP 流转
2. LLM 确认拒绝：sensor 回退 DROWSY，本轮不创建梦境会话
3. 用户唤醒意图：ASLEEP/DROWSY/AWAY 任一休眠态命中 → wake_up 生效回 AWAKE、
   收到 type=system.wake 广播（previous_state 正确）
4. 唤醒后引擎继续承接：sensor 回 AWAKE 后引擎不再触发梦境会话、状态恢复 idle

注：真实 SleepSensor.snapshot() 由 evaluate() 依信号实时重算，只会产出
AWAKE/DROWSY/ASLEEP/AWAY 四态；PENDING_CONFIRMATION 与 ENTERING_SLEEP 是显式
transition_state 的中间态，snapshot() 不会自动重算得出，故场景 3 的唤醒态参数化
覆盖 evaluate 可得的三个休眠态（ASLEEP/DROWSY/AWAY），PENDING_CONFIRMATION/
ENTERING_SLEEP 的唤醒已由 test_gateway_handlers_chat.py TestWakeFromSleep 用可固定
状态的轻量 fake 覆盖，二者互补。

运行：python -m pytest tests/test_sleep_lifecycle_e2e.py -q
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import server.dependencies as deps
from server.autonomy.dream.collector import DreamMaterialSnapshot
from server.autonomy.dream.confirmation import SleepConfirmationArbiter
from server.autonomy.dream.config import DreamConfig, SleepConfirmationConfig
from server.autonomy.dream.engine import DreamEngine
from server.autonomy.dream.generator import DreamCandidate
from server.autonomy.dream.sleep_sensor import SleepSensor
from server.autonomy.dream.summarizer import SleepAutoSummarizer
from server.handlers.chat import _maybe_wake_from_sleep

# 默认测试时钟：2026-08-23 03:00（落在默认睡眠窗口内）
_BASE_NOW = datetime(2026, 8, 23, 3, 0, 0)

# 入睡流程任务（摘要 + 会话）完成的沉降时间
_SETTLE = 0.12


# ================================================================ 通用 fakes（采集/生成/缓冲）
class _Resp:
    """带 .content 的 LLM 响应壳（对齐生成器 chat(...) 返回口径）。"""

    def __init__(self, content):
        self.content = content


class _FakeLLMForConfirm:
    """供给 SleepConfirmationArbiter 的轻量 LLM：async chat(...) 返回固定判定文本。"""

    def __init__(self, content="true"):
        self.content = content
        self.calls = 0

    async def chat(self, messages, stream=False, **kw):
        self.calls += 1
        return _Resp(self.content)


class _FakeLLMForSummary:
    """供给 SleepAutoSummarizer 的轻量 LLM：async chat(...) 返回固定摘要文本。

    events 可选注入共享事件列表，用于断言"摘要 LLM 调用先于会话采集"的时序。
    """

    def __init__(self, content="今日小结：白天专注工作，傍晚散步，心情平静。", events=None):
        self.content = content
        self.calls = 0
        self.events = events

    async def chat(self, messages=None, stream=False, **kw):
        self.calls += 1
        if self.events is not None:
            self.events.append("summary")
        return _Resp(self.content)


class _FakeMemoryManager:
    """记录摘要写入并提供短程记忆查询的假记忆管理器（供真实 SleepAutoSummarizer）。"""

    def __init__(self, short_term=None):
        self.short_term = list(short_term or [])
        self.written = []

    async def search_memories_async(self, query=None, memory_type=None, limit=10,
                                    offset=0, include_deleted=False, workspace_id="default",
                                    agent_id="default"):
        if memory_type == "short_term":
            return list(self.short_term)
        return []

    async def write_memory_async(self, content, memory_type="long_term", importance=3,
                                 tags=None, metadata=None, permanent=False,
                                 emotion_score=0.0, workspace_id="default", agent_id="default"):
        self.written.append({
            "content": content,
            "memory_type": memory_type,
            "importance": importance,
            "tags": list(tags or []),
            "agent_id": agent_id,
        })
        return len(self.written)


class _FakeContextManager:
    """返回一个活跃会话及若干消息的假 ContextManager（供真实 SleepAutoSummarizer）。"""

    def __init__(self, sessions=None, messages=None):
        self.sessions = sessions or [{"id": "s1"}]
        if messages is None:
            self.messages = [
                {"role": "user", "content": "今天做了一天的梦研究"},
                {"role": "assistant", "content": "很好，我们记录一下"},
                {"role": "system", "content": "不要包含这行"},  # 默认过滤 system 角色
            ]
        else:
            self.messages = list(messages)

    def get_sessions(self, workspace_id="default", limit=20, active_only=True):
        return list(self.sessions)

    def get_recent_messages(self, session_id, limit=50):
        return list(self.messages)


class _FakeCollector:
    """供 run_session 的假采集器：记录调用次数，可选推进共享事件列表以断言时序。"""

    def __init__(self, events=None, snapshot=None):
        self.events = events
        self.snapshot = snapshot or DreamMaterialSnapshot(
            memories=[{"id": 1, "importance_score": 0.3, "permanent": False, "content": "记忆A"}],
            isolated_entities=["孤岛"],
            emotion_baseline=0.4,
            agent_id="default",
        )
        self.calls = 0

    async def collect(self, agent_id="default"):
        self.calls += 1
        if self.events is not None:
            self.events.append("collect")
        return self.snapshot


class _FakeGenerator:
    def __init__(self, candidates=None):
        self.candidates = list(candidates or [_candidate()])

    async def generate(self, snapshot):
        return list(self.candidates)


class _FakeFilter:
    def filter_candidate(self, candidate, meta, config):
        return {"approved": True, "decision": "approved", "reason": None}


class _FakeBuffer:
    def __init__(self):
        self.putted = []

    def put(self, candidate):
        self.putted.append(candidate)
        return len(self.putted)


class _FakePurgeJob:
    async def run(self, agent_id="default"):
        return {"purged_memories": 0, "purged_buffer": 0}


class _FakeConsolidator:
    async def surface(self, agent_id="default"):
        return True


def _candidate():
    return DreamCandidate(
        content="梦见一片发光的海",
        emotion_shift={"valence": 0.3, "arousal": 0.5},
        associated_entities=["海"],
        lucidity_score=0.8,
        session_id="sess-1",
    )


# ================================================================ 组装真实组件
def _make_sensor(now=None) -> SleepSensor:
    """固定时钟的 SleepSensor（now_fn 注入，确定性测试）。"""
    return SleepSensor(now_fn=lambda: now or _BASE_NOW)


def _make_arbiter(*, llm, now=None) -> SleepConfirmationArbiter:
    """真实 SleepConfirmationArbiter：注入 fake llm 与固定时钟。"""
    return SleepConfirmationArbiter(
        llm_client=llm,
        config=SleepConfirmationConfig(enabled=True, cooldown_seconds=0),
        now_fn=lambda: now or _BASE_NOW,
    )


def _make_summarizer(*, memory=None, llm=None, messages=None) -> SleepAutoSummarizer:
    """真实 SleepAutoSummarizer：注入 fake memory_manager / context_manager / llm。"""
    return SleepAutoSummarizer(
        context_manager=_FakeContextManager(messages=messages),
        memory_manager=memory if memory is not None else _FakeMemoryManager(),
        llm_client=llm,
    )


def _make_e2e_engine(*, sensor, arbiter, summarizer, collector) -> DreamEngine:
    """拼装带三件真实组件（sensor/arbiter/summarizer）的 DreamEngine。

    collector 注入事件采集器；其余采集/生成/过滤/缓冲用轻量 fake 补齐（不注入
    后台昼夜循环，直接驱动 _maybe_trigger_by_sensor，避免时钟/相位不确定）。
    """
    return DreamEngine(
        collector=collector,
        generator=_FakeGenerator(),
        dream_filter=_FakeFilter(),
        buffer=_FakeBuffer(),
        consolidator=_FakeConsolidator(),
        purge_job=_FakePurgeJob(),
        config=DreamConfig(enabled=True),
        interval_seconds=0.05,
        sleep_sensor=sensor,
        sleep_confirm_arbiter=arbiter,
        auto_summarizer=summarizer,
    )


def _set_asleep(sensor: SleepSensor) -> None:
    """把真实 SleepSensor 置为 ASLEEP（S4 显式睡眠语短路，snapshot() 可复现 ASLEEP）。"""
    sensor.set_sleep_speech(True)


# ================================================================ 场景 1：确认通过 → 摘要 → 会话
@pytest.mark.asyncio
class TestSleepLifecycle_ConfirmPass:
    async def test_confirm_pass_runs_summary_then_session(self):
        """信号达标(ASLEEP) + LLM 确认通过 → 首步自动摘要 → 进入梦境会话。

        断言：确认被调用、摘要 LLM 先于会话 collect 执行（共享事件时序）、
        sensor 经 ENTERING_SLEEP 流转、摘要已写入长期记忆（tags 自动摘要/日记）。
        """
        sensor = _make_sensor(_BASE_NOW)
        _set_asleep(sensor)
        assert sensor.snapshot()["state"] == "ASLEEP"  # 前置：信号达标

        conf_llm = _FakeLLMForConfirm(content="true")
        arbiter = _make_arbiter(llm=conf_llm, now=_BASE_NOW)

        events = []
        sum_llm = _FakeLLMForSummary(content="今日小结：充实的一天。", events=events)
        mm = _FakeMemoryManager(short_term=[{"content": "短程记忆甲"}])
        summarizer = _make_summarizer(memory=mm, llm=sum_llm)
        collector = _FakeCollector(events=events)

        engine = _make_e2e_engine(
            sensor=sensor, arbiter=arbiter, summarizer=summarizer, collector=collector
        )
        engine._maybe_trigger_by_sensor(_BASE_NOW, sleeping=True)
        await asyncio.sleep(_SETTLE)

        # 确认被调用（LLM 判定过闸）
        assert conf_llm.calls == 1
        # 首步自动摘要在会话采集之前执行（summary 事件先于 collect 事件）
        assert "summary" in events and "collect" in events
        assert events.index("summary") < events.index("collect")
        # 摘要已写入长期记忆（tags 含 自动摘要/日记）
        assert len(mm.written) == 1
        rec = mm.written[0]
        assert rec["memory_type"] == "long_term"
        assert set(rec["tags"]) == {"自动摘要", "日记"}
        assert rec["content"] == "今日小结：充实的一天。"
        # 进入梦境会话
        assert collector.calls == 1
        assert engine._stats["sessions"] == 1
        # sensor 经 ENTERING_SLEEP 流转（确认通过路径的显式中间态）
        assert sensor._state == "ENTERING_SLEEP"
        # 流程结束回到 idle（非 dreaming）
        assert engine._status == "idle"


# ================================================================ 场景 2：确认拒绝 → DROWSY + 跳过
@pytest.mark.asyncio
class TestSleepLifecycle_ConfirmReject:
    async def test_reject_returns_drowsy_and_skips_session(self):
        """LLM 确认拒绝 → sensor 回退 DROWSY，本轮不创建梦境会话。"""
        sensor = _make_sensor(_BASE_NOW)
        _set_asleep(sensor)
        assert sensor.snapshot()["state"] == "ASLEEP"

        conf_llm = _FakeLLMForConfirm(content="false")
        arbiter = _make_arbiter(llm=conf_llm, now=_BASE_NOW)

        events = []
        sum_llm = _FakeLLMForSummary(events=events)
        mm = _FakeMemoryManager()
        summarizer = _make_summarizer(memory=mm, llm=sum_llm)
        collector = _FakeCollector(events=events)

        engine = _make_e2e_engine(
            sensor=sensor, arbiter=arbiter, summarizer=summarizer, collector=collector
        )
        engine._maybe_trigger_by_sensor(_BASE_NOW, sleeping=True)
        await asyncio.sleep(_SETTLE)

        # 确认被调用但判定为否
        assert conf_llm.calls == 1
        # 未触发摘要（LLM 未被调用）、未进入会话、未落库
        assert sum_llm.calls == 0
        assert mm.written == []
        assert "summary" not in events and "collect" not in events
        assert collector.calls == 0
        assert engine._stats["sessions"] == 0
        # sensor 回退 DROWSY
        assert sensor._state == "DROWSY"
        assert engine._status == "idle"


# ================================================================ 场景 3：用户唤醒意图终止休眠
def _sensor_in_state(state):
    """把真实 SleepSensor 置于指定休眠态（snapshot() 可复现该态）。

    ASLEEP：S4 显式睡眠语短路；DROWSY：S9 心率 0.5；AWAY：S6 锁屏 + S9 长时间无样本。
    """
    clock = [_BASE_NOW]
    sensor = SleepSensor(now_fn=lambda: clock[0], away_hr_stale_min=30)
    if state == "ASLEEP":
        sensor.set_sleep_speech(True)
    elif state == "DROWSY":
        sensor.set_hr_confidence(0.5)
    elif state == "AWAY":
        sensor.set_system_idle(1200)  # S1=1.0、S6=1.0（锁屏）
        sensor.set_hr_confidence(0.1)
        clock[0] += timedelta(minutes=31)  # 超 30 分钟无 HR 样本 → AWAY
    # 前置自检：降落目标态
    assert sensor.snapshot()["state"] == state
    return sensor


class _FakeManager:
    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, message, exclude=None):
        self.broadcasts.append(message)


@pytest.mark.asyncio
class TestSleepLifecycle_UserWake:
    @pytest.mark.parametrize("state", ["ASLEEP", "DROWSY", "AWAY"])
    async def test_wake_returns_sensor_to_awake_and_broadcasts(self, monkeypatch, state):
        """任一可唤醒休眠态 + 用户唤醒关键词 → wake_up 生效回 AWAKE + system.wake 广播。"""
        sensor = _sensor_in_state(state)
        runtime = SimpleNamespace(sleep_sensor=sensor)
        monkeypatch.setattr(deps, "_service_state", SimpleNamespace(physio_runtime=runtime))
        mgr = _FakeManager()

        await _maybe_wake_from_sleep("在吗", mgr)

        # wake_up 生效：内部状态回到 AWAKE（wake_up 显式切换，注册唤醒意图落点）
        assert sensor._state == "AWAKE"
        # ASLEEP 由 S4 短路产生，wake_up 已重置 S4，故快照复算同样回到 AWAKE；
        # DROWSY/AWAY 由 S9/S6 生理信号驱动，wake_up 仅重置内部状态与 S4，不清除
        # 生理信号（符合真实语义：唤醒意图已锁定，但快照按信号实时重算）。
        if state == "ASLEEP":
            assert sensor.snapshot()["state"] == "AWAKE"
        # 收到 type=system.wake 广播，携带正确的 previous_state
        assert len(mgr.broadcasts) == 1
        msg = mgr.broadcasts[0]
        assert msg["type"] == "system.wake"
        assert msg["data"]["previous_state"] == state

    @pytest.mark.asyncio
    async def test_no_wake_when_awake(self, monkeypatch):
        """AWAKE 状态普通文本 → 不触发唤醒、不广播（状态保持）。"""
        sensor = _make_sensor(_BASE_NOW)
        assert sensor.snapshot()["state"] == "AWAKE"
        runtime = SimpleNamespace(sleep_sensor=sensor)
        monkeypatch.setattr(deps, "_service_state", SimpleNamespace(physio_runtime=runtime))
        mgr = _FakeManager()

        await _maybe_wake_from_sleep("今天天气不错", mgr)

        assert sensor.snapshot()["state"] == "AWAKE"
        assert mgr.broadcasts == []


# ================================================================ 场景 4：唤醒后引擎恢复承接
@pytest.mark.asyncio
class TestSleepLifecycle_AfterWake:
    async def test_engine_no_dream_session_after_wake(self):
        """唤醒后 sensor 回 AWAKE：引擎状态恢复，不再触发梦境会话。"""
        sensor = _make_sensor(_BASE_NOW)
        _set_asleep(sensor)
        # 用户唤醒 → sensor 强制回 AWAKE（s4 重置）
        sensor.wake_up()
        assert sensor.snapshot()["state"] == "AWAKE"

        conf_llm = _FakeLLMForConfirm(content="true")
        arbiter = _make_arbiter(llm=conf_llm, now=_BASE_NOW)
        sum_llm = _FakeLLMForSummary()
        summarizer = _make_summarizer(memory=_FakeMemoryManager(), llm=sum_llm)
        collector = _FakeCollector()

        engine = _make_e2e_engine(
            sensor=sensor, arbiter=arbiter, summarizer=summarizer, collector=collector
        )
        engine._maybe_trigger_by_sensor(_BASE_NOW, sleeping=True)
        await asyncio.sleep(_SETTLE)

        # sensor 状态已恢复 AWAKE
        assert sensor.snapshot()["state"] == "AWAKE"
        # 不再走梦境会话：无确认、无摘要、无 collect、统计未累计
        assert conf_llm.calls == 0
        assert sum_llm.calls == 0
        assert collector.calls == 0
        assert engine._stats["sessions"] == 0
        assert engine._status == "idle"