"""CX-O-Dream SleepSensor 融合状态机（server/autonomy/dream/sleep_sensor.py）单测。

覆盖：
1. S4 显式睡眠语短路 → 直接 ASLEEP、跳过动态归一（未命中不参与归一）
2. 双证=S9 心率下降 + S1 输入静默 → ASLEEP
3. 交叉验证：S9 下降但 S1 行为活跃 → 强制 AWAKE（即使 confidence 高）
4. S3/S5/S8 无源信号：available=False、weight 0，归一数学正确
5. S9 缺席（不可用）→ weight 0 自动归一，纯时间/行为判定
6. 动态归一总权重=1、置信度数学正确
7. 状态机四态：ASLEEP/DROWSY/AWAKE/AWAY（S6 锁屏 + S9 持续无样本）
8. S7 时间先验：窗口内 1.0、窗口外按距边界小时数递减（含跨午夜）
9. snapshot 结构 + wire_sleep_sensor 真实源接线

运行：python -m pytest tests/test_sleep_sensor.py -q
"""
from datetime import datetime, timedelta

import pytest

from server.autonomy.core.scheduler import CircadianScheduler
from server.autonomy.dream.config import PhysioConfig
from server.autonomy.dream.physio.estimator import HeartRateSleepEstimator
from server.autonomy.dream.sleep_sensor import (
    SleepSensor,
    SleepSignalProvider,
    wire_sleep_sensor,
)

# 默认作息（对齐 config.ScheduleConfig 默认值）：睡眠窗口 [02:00, 08:00)
DEFAULT_SCHEDULE = {
    "wake_time": "08:00",
    "sleep_time": "02:00",
    "golden_start": "19:00",
    "golden_end": "23:00",
    "diary_time": "02:00",
    "quiet_windows": [],
}

# 默认测试时钟：2026-08-23 03:00（落在默认睡眠窗口内）
_BASE_NOW = datetime(2026, 8, 23, 3, 0, 0)


def _make_sensor(now: datetime = _BASE_NOW) -> SleepSensor:
    """构造固定时钟的 SleepSensor（便于确定性测试）。"""
    return SleepSensor(now_fn=lambda: now)


def _circadian(**overrides) -> CircadianScheduler:
    return CircadianScheduler({**DEFAULT_SCHEDULE, **overrides})


def _signals(snap: dict) -> dict:
    """将 snapshot["signals"] 转为 {name: {..}} 便于断言。"""
    return {s["name"]: s for s in snap["signals"]}


# ================================================================ Provider 基础
class TestProvider:
    def test_update_clamps_and_marks_available(self):
        p = SleepSignalProvider("S9", "生理心率", 0.40)
        assert p.available is False and p.value == 0.0
        p.update(1.5)
        assert p.value == 1.0 and p.available is True
        p.update(-0.2)
        assert p.value == 0.0
        p.update("bad")  # 非法值归 0
        assert p.value == 0.0

    def test_set_source_marks_available(self):
        p = SleepSignalProvider("S3", "呼吸鼾声", 0.22)
        p.set_source(lambda: 0.8)
        assert p.available is True
        assert p.source() == 0.8


# ================================================================ S4 短路
class TestS4ShortCircuit:
    def test_s4_hit_short_circuits_skipping_normalization(self):
        """S4 命中 → 直接 ASLEEP、跳过归一化。

        若走归一化（S4 权重 1.0 + S9 0.40 + S1 0.15 + S6 0.15 均可用且值 0）：
        confidence = 1.0/1.70 ≈ 0.588 → 应为 DROWSY；短路则直接 ASLEEP 且 conf=1.0。
        """
        sensor = _make_sensor()
        sensor.set_hr_confidence(0.0)  # S9 可用但值 0
        sensor.set_system_idle(0)      # S1/S6 可用但值 0（行为活跃）
        sensor.set_sleep_speech(True)  # S4 命中
        snap = sensor.snapshot()
        assert snap["state"] == "ASLEEP"
        assert snap["confidence"] == 1.0

    def test_s4_wired_but_not_hit_no_short_circuit(self):
        """S4 源接线但未命中：不短路、不参与归一（1.0 权重不稀释其余信号）。"""
        sensor = _make_sensor()
        sensor.set_sleep_speech(False)  # 源接线但未命中
        sensor.set_hr_confidence(0.2)
        snap = sensor.snapshot()
        assert snap["state"] != "ASLEEP"
        assert "S4" not in sensor.normalized_weights()

    def test_s4_hold_decays_after_minutes(self):
        """S4 命中后短时保持：9 分钟内仍短路，11 分钟后衰减不再短路。"""
        clock = [_BASE_NOW]
        sensor = SleepSensor(now_fn=lambda: clock[0])
        sensor.set_sleep_speech(True)
        assert sensor.snapshot()["state"] == "ASLEEP"
        clock[0] += timedelta(minutes=9)
        assert sensor.snapshot()["state"] == "ASLEEP"
        clock[0] += timedelta(minutes=2)
        snap = sensor.snapshot()
        assert snap["state"] != "ASLEEP"
        assert _signals(snap)["S4"]["value"] == 0.0


# ================================================================ 双证：S9+S1
class TestDoubleEvidence:
    def test_s9_plus_s1_silent_asleep(self):
        """生理+行为双证：S9 心率下降 + S1 输入静默 → ASLEEP。"""
        sensor = _make_sensor()
        sensor.set_hr_confidence(0.9)        # 生理心率下降
        sensor.set_system_idle(1200)         # S1=1.0（静默）、S6=1.0（锁屏）
        sensor.set_time_prior(_BASE_NOW, _circadian())  # S7=1.0（窗口内）
        snap = sensor.snapshot()
        assert snap["state"] == "ASLEEP"
        # conf = (0.40*0.9 + 0.15 + 0.15 + 0.05) / 0.75 ≈ 0.9467（4 位小数舍入）
        assert snap["confidence"] == pytest.approx(0.9467)


# ================================================================ 交叉验证
class TestCrossValidation:
    def test_s9_down_but_s1_active_force_awake(self):
        """生理下降但键鼠活跃 → 强制 AWAKE（静坐看视频场景，即使 confidence 高）。"""
        sensor = _make_sensor()
        sensor.set_hr_confidence(0.9)
        sensor.set_system_idle(0)                     # S1=0（键鼠活跃）、S6=0
        sensor.set_time_prior(_BASE_NOW, _circadian())  # S7=1.0
        snap = sensor.snapshot()
        # 无交叉验证时 conf=(0.36+0.05)/0.75≈0.547>=0.5 → DROWSY；交叉验证强制 AWAKE
        assert snap["confidence"] >= 0.5
        assert snap["state"] == "AWAKE"

    def test_cross_validation_requires_s1_available(self):
        """S1 未接线（无行为数据）→ 交叉验证不触发，S9 高置信可判 ASLEEP。"""
        sensor = _make_sensor()
        sensor.set_hr_confidence(1.0)
        snap = sensor.snapshot()
        assert snap["state"] == "ASLEEP"


# ================================================================ 无源信号归一
class TestUnavailableSignals:
    def test_no_source_signals_weight_zero_math(self):
        """S3/S5/S8 无源：available=False、weight 0 不参与归一，数学正确。"""
        sensor = _make_sensor()
        sensor.set_hr_confidence(0.5)
        snap = sensor.snapshot()
        sig = _signals(snap)
        # 注册权重保留、不可用
        assert sig["S3"]["available"] is False and sig["S3"]["weight"] == 0.22
        assert sig["S5"]["available"] is False and sig["S5"]["weight"] == 0.20
        assert sig["S8"]["available"] is False and sig["S8"]["weight"] == 0.03
        # 仅 S9 可用 → 归一化后 S9 权重 1.0、confidence 恰为 S9 值
        # （若 S3 参与：conf=0.40*0.5/0.62≈0.323，非 0.5）
        nw = sensor.normalized_weights()
        assert set(nw) == {"S9"}
        assert nw["S9"] == pytest.approx(1.0)
        assert snap["confidence"] == pytest.approx(0.5)

    def test_dynamic_normalization_total_weight_one(self):
        """多信号动态归一：归一化权重总和=1。"""
        sensor = _make_sensor()
        sensor.set_hr_confidence(0.8)
        sensor.set_system_idle(1200)  # S1=1.0、S6=1.0
        sensor.set_time_prior(_BASE_NOW, _circadian())  # S7=1.0
        nw = sensor.normalized_weights()
        assert set(nw) == {"S1", "S6", "S7", "S9"}
        assert sum(nw.values()) == pytest.approx(1.0)

    def test_s9_absent_pure_time_behavior(self):
        """S9 缺席（不可用）→ weight 0 自动归一，退化为纯时间/行为判定。"""
        sensor = _make_sensor()
        sensor.set_system_idle(600)                   # S1=1.0、S6=0.667（未锁屏）
        sensor.set_time_prior(_BASE_NOW, _circadian())  # S7=1.0
        snap = sensor.snapshot()
        assert _signals(snap)["S9"]["available"] is False
        assert "S9" not in sensor.normalized_weights()
        # conf=(0.15+0.10+0.05)/0.35≈0.857 → ASLEEP
        assert snap["state"] == "ASLEEP"


# ================================================================ 状态机四态
class TestStateMachine:
    def test_drowsy_at_threshold(self):
        sensor = _make_sensor()
        sensor.set_hr_confidence(0.5)
        sensor.set_system_idle(600)  # S1=1.0、S6=0.667
        sensor.set_time_prior(_BASE_NOW, _circadian())  # S7=1.0
        snap = sensor.snapshot()
        # conf=(0.20+0.15+0.10+0.05)/0.75≈0.6667（4 位小数舍入）→ DROWSY
        assert snap["confidence"] == pytest.approx(0.6667)
        assert snap["state"] == "DROWSY"

    def test_awake_low_confidence(self):
        sensor = _make_sensor()
        sensor.set_system_idle(0)  # S1=0、S6=0
        sensor.set_time_prior(datetime(2026, 8, 23, 15, 0), _circadian())  # S7=0（远离窗口）
        snap = sensor.snapshot()
        assert snap["state"] == "AWAKE"
        assert snap["confidence"] == pytest.approx(0.0)

    def test_away_when_locked_and_hr_stale(self):
        """S6 锁屏 + S9 持续无样本超阈值 → AWAY。"""
        clock = [_BASE_NOW]
        sensor = SleepSensor(now_fn=lambda: clock[0], away_hr_stale_min=30)
        sensor.set_system_idle(1200)   # S1=1.0、S6=1.0（锁屏）
        sensor.set_hr_confidence(0.1)  # 最后 HR 样本时刻 = T0
        assert sensor.snapshot()["state"] != "AWAY"
        clock[0] += timedelta(minutes=31)  # 超 30 分钟无样本
        assert sensor.snapshot()["state"] == "AWAY"

    def test_away_requires_lock(self):
        """S6 未满锁屏阈值 → 即使 HR 陈旧也不判 AWAY。"""
        clock = [_BASE_NOW]
        sensor = SleepSensor(now_fn=lambda: clock[0], away_hr_stale_min=30)
        sensor.set_system_idle(600)   # S6=0.667（未锁屏）
        sensor.set_hr_confidence(0.1)
        clock[0] += timedelta(minutes=60)
        assert sensor.snapshot()["state"] != "AWAY"


# ================================================================ S7 时间先验
class TestTimePrior:
    def test_inside_window_value_one(self):
        sensor = _make_sensor()
        sensor.set_time_prior(datetime(2026, 8, 23, 3, 0), _circadian())
        snap = sensor.snapshot()
        assert _signals(snap)["S7"]["value"] == pytest.approx(1.0)

    def test_outside_window_decays_by_hours(self):
        sensor = _make_sensor()
        # 距入睡边界 1h → 0.75
        sensor.set_time_prior(datetime(2026, 8, 23, 1, 0), _circadian())
        assert _signals(sensor.snapshot())["S7"]["value"] == pytest.approx(0.75)
        # 距醒后边界 4h → 0
        sensor.set_time_prior(datetime(2026, 8, 23, 12, 0), _circadian())
        assert _signals(sensor.snapshot())["S7"]["value"] == pytest.approx(0.0)

    def test_cross_midnight_window(self):
        circadian = _circadian(sleep_time="22:00", wake_time="06:00")
        sensor = _make_sensor()
        # 跨午夜窗口内
        sensor.set_time_prior(datetime(2026, 8, 23, 3, 0), circadian)
        assert _signals(sensor.snapshot())["S7"]["value"] == pytest.approx(1.0)
        # 距最近窗口边界 7h → 0
        sensor.set_time_prior(datetime(2026, 8, 23, 15, 0), circadian)
        assert _signals(sensor.snapshot())["S7"]["value"] == pytest.approx(0.0)


# ================================================================ S2 语音静默
class TestVoiceActivity:
    def test_none_unavailable(self):
        sensor = _make_sensor()
        sensor.set_voice_activity(None)
        assert _signals(sensor.snapshot())["S2"]["available"] is False

    def test_value_rises_with_silence(self):
        sensor = _make_sensor()
        sensor.set_voice_activity(600)  # 超过 300s → 1.0
        assert _signals(sensor.snapshot())["S2"]["value"] == pytest.approx(1.0)
        sensor.set_voice_activity(150)  # 2.5 分钟 → 0.5
        assert _signals(sensor.snapshot())["S2"]["value"] == pytest.approx(0.5)


# ================================================================ snapshot 结构
class TestSnapshot:
    def test_snapshot_structure(self):
        sensor = _make_sensor()
        sensor.set_hr_confidence(0.3)
        snap = sensor.snapshot()
        assert set(snap) == {"state", "confidence", "signals", "updated_at"}
        assert isinstance(snap["signals"], list) and len(snap["signals"]) == 9
        for s in snap["signals"]:
            assert set(s) == {"name", "weight", "value", "available"}
            assert 0.0 <= s["value"] <= 1.0
        assert snap["updated_at"]


# ================================================================ 外部源与异常隔离
class TestExternalSource:
    def test_external_source_feeds_value(self):
        sensor = _make_sensor()
        sensor.set_external_source("S3", lambda: 0.9)
        snap = sensor.snapshot()
        assert _signals(snap)["S3"]["available"] is True
        assert _signals(snap)["S3"]["value"] == pytest.approx(0.9)

    def test_external_source_exception_isolated(self):
        """源取值异常 → 异常隔离，value 保持旧值、不崩溃主流程。"""
        sensor = _make_sensor()
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("sensor down")
            return 0.7

        sensor.set_external_source("S3", flaky)
        assert _signals(sensor.snapshot())["S3"]["value"] == 0.0  # 首次异常保持 0
        assert _signals(sensor.snapshot())["S3"]["value"] == pytest.approx(0.7)  # 恢复


# ================================================================ wire 装配
class TestWireAssembly:
    def test_wire_wires_s7_and_s9(self):
        sensor = _make_sensor()
        circadian = _circadian()
        estimator = HeartRateSleepEstimator(config=PhysioConfig(base_hr_learning=False))
        start = datetime(2026, 8, 23, 0, 0)
        for i in range(7):  # 60bpm 持续 6 分钟 → 置信度趋向 1.0
            estimator.ingest(60, start + timedelta(minutes=i))
        now = datetime(2026, 8, 23, 3, 0)  # 窗口内
        wire_sleep_sensor(sensor, circadian, estimator=estimator, idle_sec=1200, now=now)
        snap = sensor.snapshot()
        sig = _signals(snap)
        assert sig["S7"]["available"] is True and sig["S7"]["value"] == pytest.approx(1.0)
        assert sig["S9"]["available"] is True
        assert sig["S9"]["value"] == pytest.approx(estimator.get_state()["hr_sleep_confidence"])
        assert sig["S1"]["available"] is True
        assert sig["S6"]["available"] is True
        assert sig["S2"]["available"] is False  # voice_recent_sec=None → 不可用
        assert sig["S3"]["available"] is False  # 无源
        assert sig["S5"]["available"] is False
        assert sig["S8"]["available"] is False

    def test_wire_without_estimator_s9_absent(self):
        sensor = _make_sensor()
        wire_sleep_sensor(sensor, _circadian(), estimator=None, idle_sec=600, now=_BASE_NOW)
        snap = sensor.snapshot()
        assert _signals(snap)["S9"]["available"] is False

    def test_wire_sleep_speech_hit_short_circuits(self):
        sensor = _make_sensor()
        wire_sleep_sensor(
            sensor, _circadian(), sleep_speech_hit=True, idle_sec=0, now=_BASE_NOW
        )
        assert sensor.snapshot()["state"] == "ASLEEP"
