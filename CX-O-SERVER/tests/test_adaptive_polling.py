"""
server/services/adaptive_polling.py 回归测试
自适应频率轮询管理器：滑动窗口延迟记录 + 动态间隔
"""
import pytest

from server.services.adaptive_polling import (
    AdaptivePollingManager,
    get_adaptive_polling_manager,
    init_adaptive_polling_manager,
)


class _Clock:
    """可变的假时钟，用于控制 time.time()。"""

    def __init__(self, start: float = 0.0):
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float):
        self._now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr("server.services.adaptive_polling.time.time", c)
    return c


@pytest.fixture
def mgr():
    return AdaptivePollingManager(window_size=3)


class TestRecordPacket:
    def test_first_call_returns_zero(self, clock, mgr):
        assert mgr.record_packet() == 0.0
        assert mgr._last_packet_time == 0.0

    def test_second_call_records_interval(self, clock, mgr):
        mgr.record_packet()
        clock.advance(0.05)  # 50ms
        assert mgr.record_packet() == pytest.approx(50.0, abs=0.1)

    def test_latencies_accumulate(self, clock, mgr):
        mgr.record_packet()
        for _ in range(3):
            clock.advance(0.02)
            mgr.record_packet()
        assert len(mgr._latencies) == 3


class TestIntervalUpdate:
    def test_low_latency_uses_50(self, clock, mgr):
        # 平均 <100ms → base 50
        mgr._latencies.append(50.0)
        mgr._update_interval()
        assert mgr.get_poll_interval() == 50

    def test_medium_latency_scaled(self, clock, mgr):
        # 平均 200ms → base 160
        mgr._latencies.append(200.0)
        mgr._update_interval()
        assert mgr.get_poll_interval() == 160

    def test_high_latency_scaled(self, clock, mgr):
        # 平均 800ms → base 400
        mgr._latencies.append(800.0)
        mgr._update_interval()
        assert mgr.get_poll_interval() == 400

    def test_interval_clamped_to_max(self, clock):
        m = AdaptivePollingManager(max_interval_ms=100)
        m._latencies.append(100000.0)
        m._update_interval()
        assert m.get_poll_interval() == 100

    def test_interval_clamped_to_min(self, clock):
        m = AdaptivePollingManager(min_interval_ms=200)
        m._latencies.append(1.0)
        m._update_interval()
        assert m.get_poll_interval() == 200

    def test_zero_avg_returns(self, clock, mgr):
        mgr._latencies.append(0.0)
        mgr._update_interval()  # 不报错，保持默认
        assert mgr.get_poll_interval() == 100


class TestAverageLatency:
    def test_empty_returns_zero(self, mgr):
        assert mgr.get_average_latency() == 0.0

    def test_average(self, mgr):
        mgr._latencies.extend([10.0, 20.0, 30.0])
        assert mgr.get_average_latency() == 20.0


class TestSetters:
    def test_set_offset_clamped(self, mgr):
        mgr.set_offset(9999)
        assert mgr._offset_ms == 500
        mgr.set_offset(-9999)
        assert mgr._offset_ms == -500

    def test_set_offset_applies(self, clock, mgr):
        mgr._latencies.append(100.0)
        mgr.set_offset(20)
        # avg=100（<500）→ base=80；+offset 20 = 100
        assert mgr.get_poll_interval() == 100

    def test_set_window_size_clamped(self, mgr):
        mgr.set_window_size(99)
        assert mgr._window_size == 10
        mgr.set_window_size(0)
        assert mgr._window_size == 1

    def test_set_window_size_truncates(self, mgr):
        mgr._latencies.extend([1.0, 2.0, 3.0, 4.0, 5.0])
        mgr.set_window_size(2)
        assert list(mgr._latencies) == [4.0, 5.0]


class TestResetAndStats:
    def test_reset(self, clock, mgr):
        mgr.record_packet()
        clock.advance(0.01)
        mgr.record_packet()
        mgr.reset()
        assert list(mgr._latencies) == []
        assert mgr._last_packet_time is None
        assert mgr.get_poll_interval() == 100

    def test_get_stats(self, mgr):
        mgr._latencies.append(10.0)
        stats = mgr.get_stats()
        assert stats["average_latency_ms"] == 10.0
        assert stats["latency_count"] == 1
        assert stats["config"]["window_size"] == 3


class TestSingleton:
    def test_get_manager_singleton(self):
        assert get_adaptive_polling_manager() is get_adaptive_polling_manager()

    def test_init_replaces_singleton(self):
        init_adaptive_polling_manager(window_size=5)
        m = get_adaptive_polling_manager()
        assert m._window_size == 5