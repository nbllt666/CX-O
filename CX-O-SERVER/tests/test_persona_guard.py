"""server.core.memory.persona_guard 单元测试。

覆盖人格保护闸门判定规则（按顺序）：永久记忆拒绝、高情感印记拒绝（含归档
建议）、高频再激活拒绝、普通记忆放行、阈值配置生效与 None/缺失字段安全处理。
阈值通过 monkeypatch persona_guard.get_settings 注入，验证"每次调用时读取
配置、不模块级缓存"的行为。

运行：python -m pytest tests/test_persona_guard.py -v
"""
import pytest

import server.core.memory.persona_guard as pg


# ---------------------------------------------------------------- 依赖替身
class FakeMemoryConfig:
    """可定制阈值的记忆配置替身"""

    def __init__(self, emotion_threshold=0.6, reactivation_threshold=3):
        self.persona_guard_emotion_threshold = emotion_threshold
        self.persona_guard_reactivation_threshold = reactivation_threshold


class FakeConfig:
    def __init__(self, emotion_threshold=0.6, reactivation_threshold=3):
        self.memory = FakeMemoryConfig(emotion_threshold, reactivation_threshold)


class FakeSettings:
    def __init__(self, emotion_threshold=0.6, reactivation_threshold=3):
        self.config = FakeConfig(emotion_threshold, reactivation_threshold)


@pytest.fixture
def guard_settings(monkeypatch):
    """注入可定制阈值的配置替身；返回工厂便于逐用例调整阈值。"""

    def _install(emotion_threshold=0.6, reactivation_threshold=3):
        monkeypatch.setattr(
            pg,
            "get_settings",
            lambda: FakeSettings(emotion_threshold, reactivation_threshold),
        )
        return emotion_threshold, reactivation_threshold

    return _install


# ---------------------------------------------------------------- 规则1：永久记忆
class TestPermanentMemoryRejected:
    def test_permanent_true_rejected(self, guard_settings):
        guard_settings()
        r = pg.evaluate_persona_guard({"id": 1, "permanent": True})
        assert r["allowed"] is False
        assert "人格核心" in r["reason"]
        assert "永久记忆" in r["reason"]
        assert "REST API" in r["reason"]
        assert "soft_delete=false" in r["reason"]

    def test_permanent_int_one_rejected(self, guard_settings):
        """SQLite 布尔以 0/1 存储，1 同样视为人格核心。"""
        guard_settings()
        r = pg.evaluate_persona_guard({"id": 1, "permanent": 1})
        assert r["allowed"] is False

    def test_permanent_check_precedes_threshold_read(self, guard_settings):
        """规则顺序：永久记忆判定优先于阈值读取。"""
        guard_settings(emotion_threshold=0.0, reactivation_threshold=0)
        r = pg.evaluate_persona_guard({"id": 1, "permanent": 1, "emotion_score": 0.0})
        assert r["allowed"] is False
        assert "人格核心" in r["reason"]

    def test_permanent_none_not_rejected_by_rule1(self, guard_settings):
        """permanent 缺失或 None 不触发规则1。"""
        guard_settings()
        assert pg.evaluate_persona_guard({"id": 1, "permanent": None})["allowed"] is True


# ---------------------------------------------------------------- 规则2：情感/再激活
class TestEmotionProtection:
    def test_high_emotion_rejected_with_archive_hint(self, guard_settings):
        guard_settings(emotion_threshold=0.6)
        r = pg.evaluate_persona_guard({"id": 1, "emotion_score": 0.7})
        assert r["allowed"] is False
        assert "情感印记" in r["reason"]
        assert "归档" in r["reason"]

    def test_emotion_at_threshold_rejected(self, guard_settings):
        """等于阈值即受保护（>= 判定）。"""
        guard_settings(emotion_threshold=0.6)
        r = pg.evaluate_persona_guard({"id": 1, "emotion_score": 0.6})
        assert r["allowed"] is False

    def test_low_emotion_allowed(self, guard_settings):
        guard_settings(emotion_threshold=0.6)
        r = pg.evaluate_persona_guard({"id": 1, "emotion_score": 0.5})
        assert r == {"allowed": True, "reason": ""}


class TestReactivationProtection:
    def test_high_reactivation_rejected_with_archive_hint(self, guard_settings):
        guard_settings(reactivation_threshold=3)
        r = pg.evaluate_persona_guard({"id": 1, "reactivation_count": 3})
        assert r["allowed"] is False
        assert "再激活" in r["reason"]
        assert "归档" in r["reason"]

    def test_low_reactivation_allowed(self, guard_settings):
        guard_settings(reactivation_threshold=3)
        r = pg.evaluate_persona_guard({"id": 1, "reactivation_count": 2})
        assert r["allowed"] is True

    def test_both_dimensions_reported(self, guard_settings):
        """情感与再激活同时超标时，两类原因均在 reason 中体现。"""
        guard_settings(emotion_threshold=0.6, reactivation_threshold=3)
        r = pg.evaluate_persona_guard(
            {"id": 1, "emotion_score": 0.9, "reactivation_count": 5}
        )
        assert r["allowed"] is False
        assert "情感印记" in r["reason"]
        assert "再激活" in r["reason"]


# ---------------------------------------------------------------- 阈值配置生效
class TestThresholdConfigEffective:
    def test_custom_emotion_threshold(self, guard_settings):
        guard_settings(emotion_threshold=0.9)
        assert pg.evaluate_persona_guard({"id": 1, "emotion_score": 0.7})["allowed"] is True
        assert pg.evaluate_persona_guard({"id": 1, "emotion_score": 0.95})["allowed"] is False

    def test_custom_reactivation_threshold(self, guard_settings):
        guard_settings(reactivation_threshold=5)
        assert pg.evaluate_persona_guard({"id": 1, "reactivation_count": 4})["allowed"] is True
        assert pg.evaluate_persona_guard({"id": 1, "reactivation_count": 5})["allowed"] is False

    def test_threshold_read_per_call(self, guard_settings, monkeypatch):
        """阈值在每次调用时读取：调用间隙修改配置立即生效（无模块级缓存）。"""
        holder = {"emotion": 0.6}

        class DynamicMemory:
            persona_guard_reactivation_threshold = 3

            @property
            def persona_guard_emotion_threshold(self):
                return holder["emotion"]

        class DynamicConfig:
            memory = DynamicMemory()

        class DynamicSettings:
            config = DynamicConfig()

        monkeypatch.setattr(pg, "get_settings", lambda: DynamicSettings())

        assert pg.evaluate_persona_guard({"id": 1, "emotion_score": 0.7})["allowed"] is False
        holder["emotion"] = 0.8  # 运行中调高阈值
        assert pg.evaluate_persona_guard({"id": 1, "emotion_score": 0.7})["allowed"] is True


# ---------------------------------------------------------------- None/缺失安全处理
class TestSafeDefaults:
    def test_empty_memory_allowed(self, guard_settings):
        guard_settings()
        assert pg.evaluate_persona_guard({}) == {"allowed": True, "reason": ""}

    def test_missing_fields_allowed(self, guard_settings):
        guard_settings()
        r = pg.evaluate_persona_guard({"id": 1, "content": "普通记忆"})
        assert r == {"allowed": True, "reason": ""}

    def test_none_numeric_fields_treated_as_zero(self, guard_settings):
        """emotion_score / reactivation_count 为 None 时按 0 处理，正常放行。"""
        guard_settings()
        r = pg.evaluate_persona_guard(
            {"id": 1, "emotion_score": None, "reactivation_count": None}
        )
        assert r == {"allowed": True, "reason": ""}

    def test_none_emotion_with_zero_threshold_rejected(self, guard_settings):
        """None 视为 0：阈值为 0 时 0 >= 0 成立，仍受保护（语义一致）。"""
        guard_settings(emotion_threshold=0.0)
        r = pg.evaluate_persona_guard({"id": 1, "emotion_score": None})
        assert r["allowed"] is False
