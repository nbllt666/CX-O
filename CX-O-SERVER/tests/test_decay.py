"""server.core.memory.decay (DecayCalculator) 单元测试。

覆盖重要性分档、时间差计算（含时区修复）、双阶段指数衰减、
艾宾浩斯衰减、永久记忆（零衰减）等纯逻辑。

运行：python -m pytest tests/test_decay.py -v
"""
from datetime import datetime, timedelta, timezone

import pytest

from server.core.memory.decay import DecayCalculator


@pytest.fixture
def calc():
    c = DecayCalculator()
    c.set_current_time(datetime(2026, 1, 1, 12, 0, 0))
    return c


# ---------------------------------------------------------------- 重要性分档
class TestImportanceLevel:
    def test_high_importance_permanent(self, calc):
        assert calc.get_level_from_importance(0.99).decay_type == "zero"
        assert calc.get_level_from_importance(0.95).permanent is True

    def test_level_boundaries(self, calc):
        assert calc.get_level_from_importance(0.85).params["lambda1"] == 0.01
        assert calc.get_level_from_importance(0.70).params["lambda1"] == 0.08
        assert calc.get_level_from_importance(0.50).params["lambda1"] == 0.25
        assert calc.get_level_from_importance(0.30).params["lambda1"] == 0.45
        assert calc.get_level_from_importance(0.0).params["lambda1"] == 0.8


# ---------------------------------------------------------------- 时间差
class TestDaysElapsed:
    def test_positive_days(self, calc):
        created = "2025-12-31T12:00:00"
        days = calc.calculate_days_elapsed(created)
        assert days == pytest.approx(1.0)

    def test_future_gives_negative(self, calc):
        created = "2026-01-02T12:00:00"
        assert calc.calculate_days_elapsed(created) < 0

    def test_naive_aware_timezone_fix(self, calc):
        # created 带 +00:00（aware），current 为 naive → 统一视为 UTC
        created = "2025-12-31T12:00:00+00:00"
        days = calc.calculate_days_elapsed(created)
        assert days == pytest.approx(1.0)

    def test_invalid_date_returns_zero(self, calc):
        assert calc.calculate_days_elapsed("not-a-date") == 0.0


# ---------------------------------------------------------------- 双阶段指数衰减
class TestExponentialDecay:
    def test_zero_days_returns_importance(self, calc):
        assert calc.calculate_exponential_decay(0.6, 0) == 0.6

    def test_decay_monotonic_decreasing(self, calc):
        d0 = calc.calculate_exponential_decay(0.6, 0.1)
        d1 = calc.calculate_exponential_decay(0.6, 10)
        d2 = calc.calculate_exponential_decay(0.6, 30)
        assert d0 > d1 > d2

    def test_decay_factor_in_range(self, calc):
        score = calc.calculate_exponential_decay(0.6, 30)
        assert 0 < score < 0.6

    def test_caps_at_one(self, calc):
        assert calc.calculate_exponential_decay(1.0, 0) == 1.0


# ---------------------------------------------------------------- 艾宾浩斯衰减
class TestEbbinghausDecay:
    def test_zero_days(self, calc):
        assert calc.calculate_ebbinghaus_decay(0.6, 0) == 0.6

    def test_t50_half_value(self, calc):
        # t50=30, days=30 → factor = 1/(1+1) = 0.5
        score = calc.calculate_ebbinghaus_decay(1.0, 30, t50=30)
        assert score == pytest.approx(0.5)

    def test_invalid_t50_returns_importance(self, calc):
        assert calc.calculate_ebbinghaus_decay(0.6, 10, t50=0) == 0.6


# ---------------------------------------------------------------- 永久记忆
class TestPermanentDecay:
    def test_returns_one(self, calc):
        assert calc.calculate_permanent_decay(0.6) == 1.0


# ---------------------------------------------------------------- 综合 calculate_decay
class TestCalculateDecay:
    def test_zero_type_returns_permanent(self, calc):
        assert calc.calculate_decay(0.6, "2025-12-31", decay_type="zero") == 1.0

    def test_high_importance_permanent(self, calc):
        assert calc.calculate_decay(0.99, "2025-12-31") == 1.0

    def test_permanent_flag(self, calc):
        assert calc.calculate_decay(0.6, "2025-12-31", permanent=True) == 1.0

    def test_exponential_with_params(self, calc):
        score = calc.calculate_decay(
            0.6, "2025-12-31", decay_params={"alpha": 0.6, "lambda1": 0.25, "lambda2": 0.04}
        )
        assert 0 < score < 0.6

    def test_ebbinghaus_type(self, calc):
        score = calc.calculate_decay(
            0.6, "2025-12-31", decay_type="ebbinghaus", decay_params={"t50": 30, "k": 2}
        )
        assert 0 < score < 0.6

    def test_default_uses_level_params(self, calc):
        # 无 decay_params 时按重要性分档取参数
        score = calc.calculate_decay(0.6, "2025-12-31")
        assert 0 < score < 0.6