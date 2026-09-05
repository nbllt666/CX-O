"""server/core/metrics/voice_latency.py 语音链路延迟采集器测试（spec Task 4）。

覆盖六项闭合信号：
① 环形缓冲上限：250 轮入 → 保留 200
② 已知数据 P50/P95 正确（线性插值）
③ record 注入异常不抛出（零阻断红线）
④ turn 超时作废（120s 无事件进展）
⑤ WS metrics.get 响应含 voice_latency 键（ADDITIVE，既有键不动）
⑥ REST GET /api/stats/voice-latency TestClient 冒烟

运行：python -m pytest tests/test_voice_latency_metrics.py -v
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.core.metrics.voice_latency import VoiceLatencyTracker


class FakeClock:
    """可控假时钟：测试中按事件顺序推进，保证 ts 与超时清扫的 now 一致。"""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _feed_turn(tracker: VoiceLatencyTracker, clock: FakeClock, client_id: str = "c1",
               asr_s: float = 0.1, ttft_s: float = 0.08, tts_s: float = 0.12) -> None:
    """喂入一轮完整语音 turn（事件顺序与真实双流式链路一致）。

    段延迟（秒→毫秒）：asr=asr_s*1000，ttft=ttft_s*1000，
    tts_first=tts_s*1000，e2e=(asr_s+tts_s)*1000。
    """
    tracker.record(client_id, "speech_end")
    clock.advance(asr_s)
    tracker.record(client_id, "asr_final")
    tracker.record(client_id, "llm_start")
    clock.advance(ttft_s)
    tracker.record(client_id, "llm_first_token")
    clock.advance(max(0.0, tts_s - ttft_s))
    tracker.record(client_id, "tts_first_chunk")
    clock.advance(0.05)
    tracker.record(client_id, "turn_done")


class TestRingBufferCap:
    """① 缓冲上限：250 轮入 → 保留最近 200。"""

    def test_250_turns_keeps_200(self):
        clock = FakeClock()
        tracker = VoiceLatencyTracker(clock=clock)  # 注入时钟：保证 ts 与清扫 now 一致
        for i in range(250):
            _feed_turn(tracker, clock, client_id="cap-client", asr_s=0.01)
        assert tracker.buffer_size() == 200
        assert len(tracker.recent(300)) == 200
        # 每轮 asr 段均有值 → 聚合 count 亦为 200
        assert tracker.summary()["asr"]["count"] == 200
        # 活跃轮已全部结算，无残留
        assert tracker.active_turn_count == 0


class TestPercentile:
    """② 已知数据 P50/P95 正确。"""

    def test_known_values_p50_p95(self):
        clock = FakeClock()
        tracker = VoiceLatencyTracker(clock=clock)  # 注入时钟（漏传会退化为真实 wall clock）
        # 4 轮 asr = 100/200/300/400 ms；ttft/tts_first 恒定
        for i in range(1, 5):
            _feed_turn(tracker, clock, client_id="p-client", asr_s=0.1 * i)
        summary = tracker.summary()
        # 线性插值：sorted=[100,200,300,400] → p50 k=1.5 → 250；p95 k=2.85 → 385
        assert summary["asr"]["p50"] == 250.0
        assert summary["asr"]["p95"] == 385.0
        assert summary["asr"]["max"] == 400.0
        assert summary["asr"]["count"] == 4
        # 恒定值段：p50 == p95 == max == 80
        assert summary["ttft"]["p50"] == 80.0
        assert summary["ttft"]["p95"] == 80.0
        assert summary["tts_first"]["p50"] == 120.0
        # e2e = asr + tts_first = [220,320,420,520] → p50=370
        assert summary["e2e"]["p50"] == 370.0

    def test_recent_detail_shape(self):
        clock = FakeClock()
        tracker = VoiceLatencyTracker(clock=clock)  # 注入时钟
        _feed_turn(tracker, clock, client_id="shape-client", asr_s=0.3)
        records = tracker.recent(1)
        assert len(records) == 1
        rec = records[0]
        assert rec["client_id"] == "shape-client"
        assert rec["segments"]["asr"] == 300.0
        assert rec["segments"]["e2e"] == 420.0
        assert "speech_end" in rec["events"]
        assert "turn_done" in rec["events"]

    def test_empty_summary_all_none(self):
        tracker = VoiceLatencyTracker()
        summary = tracker.summary()
        for seg in ("asr", "ttft", "tts_first", "e2e"):
            assert summary[seg] == {"p50": None, "p95": None, "max": None, "count": 0}


class TestRecordNeverRaises:
    """③ record 注入异常不抛出（零阻断红线）。"""

    def test_internal_exception_swallowed(self, monkeypatch):
        tracker = VoiceLatencyTracker()

        def boom(*args, **kwargs):
            raise RuntimeError("注入异常：内部实现崩溃")

        monkeypatch.setattr(tracker, "_record_impl", boom)
        # 不应向调用方抛出任何异常
        tracker.record("c1", "speech_end")
        tracker.record("c1", "turn_done")
        tracker.record_current("llm_first_token")
        assert tracker.buffer_size() == 0

    def test_invalid_event_name_swallowed(self):
        tracker = VoiceLatencyTracker()
        tracker.record("c1", "不存在的.事件!")  # 枚举校验失败 → 静默丢弃
        assert tracker.active_turn_count == 0
        assert tracker.buffer_size() == 0

    def test_record_current_contextvar_fallback_default(self):
        # 非语音路径（无 set_active_client_id）→ contextvar 默认 "default" 键
        tracker = VoiceLatencyTracker()
        tracker.record_current("llm_first_token")
        assert tracker.active_turn_count == 1
        assert tracker.recent(1) == []  # 未结算不落缓冲


class TestTurnTimeout:
    """④ turn 超时作废（120s 无事件进展自动丢弃，不入缓冲）。"""

    def test_timeout_discards_turn(self):
        clock = FakeClock(start=1000.0)
        tracker = VoiceLatencyTracker(clock=clock)
        tracker.record("c1", "speech_end")  # ts=1000
        clock.advance(130.0)  # 超过 120s 无进展
        tracker.record("c1", "asr_final")  # 懒清扫 → 旧轮作废，隐式开新轮
        tracker.record("c1", "turn_done")  # 新轮无 speech_end → 段全 None → 不入缓冲
        assert tracker.buffer_size() == 0
        assert tracker.active_turn_count == 0
        assert tracker.summary()["asr"]["count"] == 0

    def test_fresh_turn_survives_and_settles(self):
        clock = FakeClock(start=1000.0)
        tracker = VoiceLatencyTracker(clock=clock)
        tracker.record("c1", "speech_end")
        clock.advance(10.0)
        tracker.record("c1", "asr_final")
        tracker.record("c1", "llm_start")
        clock.advance(0.08)
        tracker.record("c1", "llm_first_token")
        clock.advance(0.05)
        tracker.record("c1", "tts_first_chunk")
        tracker.record("c1", "turn_done")
        assert tracker.buffer_size() == 1
        assert tracker.summary()["asr"]["count"] == 1
        assert tracker.summary()["asr"]["p50"] == 10000.0  # 10s 间隔如实记录


# ----------------------------------------------------------------------
# ⑤ WS metrics.get 含 voice_latency 键（范式对齐 test_gateway_handlers_metrics.py）
# ----------------------------------------------------------------------
from types import SimpleNamespace  # noqa: E402

import server.handlers.metrics as metrics_mod  # noqa: E402
from server.handlers.metrics import register_metrics_handlers  # noqa: E402
from server.protocol.actions import MetricsActions  # noqa: E402


class FakeManager:
    def __init__(self):
        self.handlers = {}
        self.sent = []
        self.stats = {"connections": 5}

    def register_handler(self, action, handler):
        self.handlers[action] = handler

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))

    def get_stats(self):
        return self.stats


def _async(value):
    async def inner():
        return value
    return inner


class TestMetricsGetVoiceLatency:
    @pytest.mark.asyncio
    async def test_metrics_get_contains_voice_latency_additive(self, monkeypatch):
        mgr = FakeManager()
        register_metrics_handlers(mgr)
        handler = mgr.handlers[MetricsActions.GET]

        # 打桩既有依赖（与既有回归测试同范式），voice_latency 用真实单例
        import server.dependencies as deps
        monkeypatch.setattr(deps, "get_memory_manager", lambda: SimpleNamespace(get_statistics=lambda: {"m": 1}))
        monkeypatch.setattr(deps, "get_acp_manager", lambda: SimpleNamespace(**{"get_statistics": _async({"a": 1})}))
        monkeypatch.setattr(deps, "get_mcp_manager", lambda: SimpleNamespace(get_stats=lambda: {"mc": 1}))
        import server.core.tools
        monkeypatch.setattr(server.core.tools, "tool_registry", SimpleNamespace(get_tool_stats=lambda: {"t": 1}))
        import server.core.plugins.manager as pm
        monkeypatch.setattr(pm, "get_plugin_manager", lambda: SimpleNamespace(get_stats=lambda: {"p": 1}))

        await handler(None, {"request_id": "r1"}, "c1")
        data = mgr.sent[-1][1]["data"]

        # ADDITIVE：既有键全部健在
        for key in ("memory", "acp", "mcp", "tools", "plugins", "gateway"):
            assert key in data
        # 新增键：结构完整（真实单例聚合，无样本时段值为 None）
        vl = data["voice_latency"]
        for seg in ("asr", "ttft", "tts_first", "e2e"):
            assert seg in vl
            assert {"p50", "p95", "max", "count"} <= set(vl[seg].keys())


# ----------------------------------------------------------------------
# ⑥ REST 端点 TestClient 冒烟（范式对齐 test_stats_interrupt.py）
# ----------------------------------------------------------------------
from server.api.routers import stats as stats_router_mod  # noqa: E402
from server.core.metrics.voice_latency import get_voice_latency_tracker  # noqa: E402


@pytest.fixture
def rest_client():
    app = FastAPI()
    app.include_router(stats_router_mod.router, prefix="/api")
    return TestClient(app, raise_server_exceptions=False)


class TestVoiceLatencyRestEndpoint:
    def test_smoke_empty_shape(self, rest_client):
        r = rest_client.get("/api/stats/voice-latency")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        data = body["data"]
        assert {"summary", "recent", "buffer_size"} <= set(data.keys())
        assert isinstance(data["recent"], list)
        assert isinstance(data["buffer_size"], int)
        for seg in ("asr", "ttft", "tts_first", "e2e"):
            assert {"p50", "p95", "max", "count"} <= set(data["summary"][seg].keys())

    def test_smoke_with_sample(self, rest_client):
        # 向真实单例喂一轮样本（真实墙钟，事件间隔为真实微秒级，段值≈0 但非 None）
        # → 端点可读到 count >= 1
        tracker = get_voice_latency_tracker()
        for ev in ("speech_end", "asr_final", "llm_start", "llm_first_token",
                   "tts_first_chunk", "turn_done"):
            tracker.record("rest-smoke-client", ev)
        r = rest_client.get("/api/stats/voice-latency")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["summary"]["asr"]["count"] >= 1
        assert data["buffer_size"] >= 1
        recent_ids = [rec["client_id"] for rec in data["recent"]]
        assert "rest-smoke-client" in recent_ids
