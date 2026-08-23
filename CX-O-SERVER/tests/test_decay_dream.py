"""server.core.memory.decay (DecayCalculator) dream 衰减曲线单元测试。

覆盖 decay_type='dream'：pending/surfaced 快速衰减（λ=0.8，3 天趋近 10% 及以下）、
confirmed 放缓（λ=0.25）、默认 pending、decay_params.lambda1 回退、高重要性/永久早退、
以及非 dream 类型不受 metadata 影响。

运行：python -m pytest tests/test_decay_dream.py -v
"""
import math
from datetime import datetime, timedelta

import pytest

from server.core.memory.decay import DecayCalculator


@pytest.fixture
def calc():
    c = DecayCalculator()
    c.set_current_time(datetime(2026, 1, 1, 12, 0, 0))
    return c


def _three_days_ago():
    return (datetime(2026, 1, 1, 12, 0, 0) - timedelta(days=3)).isoformat()


class TestDreamDecay:
    def test_pending_3_days_below_10pct(self, calc):
        # pending λ=0.8：T(3)=e^(-0.8*3)≈0.0907 ≤ 10%
        score = calc.calculate_decay(
            0.6,
            _three_days_ago(),
            decay_type="dream",
            metadata={"consolidation_state": "pending"},
        )
        assert score == pytest.approx(0.6 * math.exp(-0.8 * 3), rel=1e-6)
        assert score / 0.6 <= 0.10

    def test_confirmed_slows_decay(self, calc):
        # confirmed λ=0.25：T(3)=e^(-0.25*3)≈0.472，显著高于 pending
        confirmed = calc.calculate_decay(
            0.6,
            _three_days_ago(),
            decay_type="dream",
            metadata={"consolidation_state": "confirmed"},
        )
        pending = calc.calculate_decay(
            0.6,
            _three_days_ago(),
            decay_type="dream",
            metadata={"consolidation_state": "pending"},
        )
        assert confirmed == pytest.approx(0.6 * math.exp(-0.25 * 3), rel=1e-6)
        assert confirmed > pending

    def test_default_pending_without_metadata(self, calc):
        # 无 metadata 时默认 pending λ=0.8
        score = calc.calculate_decay(0.6, _three_days_ago(), decay_type="dream")
        assert score == pytest.approx(0.6 * math.exp(-0.8 * 3), rel=1e-6)

    def test_surfaced_same_as_pending(self, calc):
        score = calc.calculate_decay(
            0.6,
            _three_days_ago(),
            decay_type="dream",
            metadata={"consolidation_state": "surfaced"},
        )
        assert score == pytest.approx(0.6 * math.exp(-0.8 * 3), rel=1e-6)

    def test_unknown_state_defaults_pending(self, calc):
        score = calc.calculate_decay(
            0.6,
            _three_days_ago(),
            decay_type="dream",
            metadata={"consolidation_state": "unknown"},
        )
        assert score == pytest.approx(0.6 * math.exp(-0.8 * 3), rel=1e-6)

    def test_decay_params_lambda1_fallback(self, calc):
        # 无 metadata 时回退 decay_params.lambda1
        score = calc.calculate_decay(
            0.6,
            _three_days_ago(),
            decay_type="dream",
            decay_params={"alpha": 1.0, "lambda1": 0.25},
        )
        assert score == pytest.approx(0.6 * math.exp(-0.25 * 3), rel=1e-6)

    def test_zero_days_returns_importance(self, calc):
        created = "2026-01-01T12:00:00"
        score = calc.calculate_decay(
            0.6,
            created,
            decay_type="dream",
            metadata={"consolidation_state": "confirmed"},
        )
        assert score == pytest.approx(0.6)

    def test_high_importance_no_decay(self, calc):
        # importance>=0.95 对 dream 仍早退返回 1.0
        assert (
            calc.calculate_decay(
                0.99,
                _three_days_ago(),
                decay_type="dream",
                metadata={"consolidation_state": "confirmed"},
            )
            == 1.0
        )

    def test_permanent_no_decay(self, calc):
        assert calc.calculate_decay(0.6, _three_days_ago(), decay_type="dream", permanent=True) == 1.0


class TestNonDreamUnaffected:
    def test_exponential_ignores_metadata(self, calc):
        with_meta = calc.calculate_decay(
            0.6,
            "2025-12-31",
            decay_params={"alpha": 0.6, "lambda1": 0.25, "lambda2": 0.04},
            metadata={"consolidation_state": "confirmed"},
        )
        without_meta = calc.calculate_decay(
            0.6,
            "2025-12-31",
            decay_params={"alpha": 0.6, "lambda1": 0.25, "lambda2": 0.04},
        )
        assert with_meta == without_meta

    def test_ebbinghaus_ignores_metadata(self, calc):
        with_meta = calc.calculate_decay(
            0.6,
            "2025-12-31",
            decay_type="ebbinghaus",
            decay_params={"t50": 30, "k": 2},
            metadata={"consolidation_state": "confirmed"},
        )
        without_meta = calc.calculate_decay(
            0.6,
            "2025-12-31",
            decay_type="ebbinghaus",
            decay_params={"t50": 30, "k": 2},
        )
        assert with_meta == without_meta

    def test_calculate_time_score_threads_metadata(self, calc):
        # calculate_time_score 透传 metadata，dream confirmed 应放缓
        memory = {
            "importance_score": 0.6,
            "created_at": _three_days_ago(),
            "decay_type": "dream",
            "metadata": {"consolidation_state": "confirmed"},
        }
        score = calc.calculate_time_score(memory)
        assert score == pytest.approx(0.6 * math.exp(-0.25 * 3), rel=1e-6)
