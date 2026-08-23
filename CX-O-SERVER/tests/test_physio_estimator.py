"""CX-O-Dream 后端心率睡眠估计器（server/autonomy/dream/physio/estimator.py）单测。

覆盖：
1. 无效样本（None / <=0 / >220）标记丢弃，不进入窗口、不影响置信度
2. 滑动窗口按时间戳裁剪（默认 10 分钟）+ 上限 5000 样本防内存
3. 心率下降持续 5 分钟且稳定 → 置信度趋向 1.0
4. 基线学习（base_hr_learning）：窗口高百分位缓慢更新 base_hr 并持久化
5. store 持久化 base_hr 可被估计器加载
6. 置信度始终 [0,1]

运行：python -m pytest tests/test_physio_estimator.py -q
"""
from datetime import datetime, timedelta

from server.autonomy.dream.config import PhysioConfig
from server.autonomy.dream.physio.estimator import HeartRateSleepEstimator
from server.autonomy.dream.physio.store import PhysioSignalStore

_START = datetime(2026, 1, 1, 0, 0, 0)


def _est(**cfg_overrides):
    """构造估计器（默认关闭基线学习，便于确定性测试）。"""
    overrides = {"base_hr_learning": False}
    overrides.update(cfg_overrides)
    cfg = PhysioConfig(**overrides)
    return HeartRateSleepEstimator(config=cfg)


# ================================================================ 无效样本丢弃
class TestInvalidSamples:
    def test_invalid_samples_dropped(self):
        est = _est()
        assert est.ingest(None, _START) == 0.0
        assert est.ingest(0, _START) == 0.0
        assert est.ingest(-5, _START) == 0.0
        assert est.ingest(250, _START) == 0.0
        # 全部无效 → 窗口为空，置信度 0
        assert est.get_state()["window_size"] == 0
        assert est.get_state()["hr_sleep_confidence"] == 0.0

    def test_invalid_samples_do_not_affect_existing_confidence(self):
        est = _est()
        est.ingest(60, _START)
        est.ingest(60, _START + timedelta(minutes=1))
        est.ingest(60, _START + timedelta(minutes=2))
        est.ingest(60, _START + timedelta(minutes=3))
        before = est.get_state()["hr_sleep_confidence"]
        # 无效样本不影响当前置信度
        assert est.ingest(None, _START + timedelta(minutes=4)) == before
        assert est.ingest(0, _START + timedelta(minutes=5)) == before
        assert est.get_state()["window_size"] == 4


# ================================================================ 滑动窗口
class TestSlidingWindow:
    def test_window_trims_older_samples_by_time(self):
        est = _est()
        # 0..15 分钟每分钟 1 样本；窗口 10 分钟 → 保留 5..15 共 11 样本
        for i in range(16):
            est.ingest(80, _START + timedelta(minutes=i))
        assert est.get_state()["window_size"] == 11

    def test_window_capped_at_5000_samples(self):
        est = _est()
        # 5100 样本密集落入 10 分钟窗口内 → 封顶 5000
        for i in range(5100):
            est.ingest(80, _START + timedelta(seconds=i * 0.1))
        assert est.get_state()["window_size"] == 5000


# ================================================================ 置信度计算
class TestConfidence:
    def test_sustained_drop_reaches_high_confidence(self):
        # 60 < 70×0.88=61.6，持续 6 分钟（>= confirm_min=5）且 std=0 < 6 → 趋向 1.0
        est = _est()
        for i in range(7):  # 0..6 分钟
            est.ingest(60, _START + timedelta(minutes=i))
        assert est.get_state()["hr_sleep_confidence"] >= 0.99

    def test_drop_just_started_gives_intermediate_confidence(self):
        # 仅 2 分钟低于阈值，未满 confirm_min=5 → 中间值且 < 1.0
        est = _est()
        for i in range(3):
            est.ingest(60, _START + timedelta(minutes=i))
        conf = est.get_state()["hr_sleep_confidence"]
        assert 0.0 <= conf < 1.0

    def test_high_hr_gives_low_confidence(self):
        # 80 >= 61.6，未下降 → 低置信度
        est = _est()
        for i in range(7):
            est.ingest(80, _START + timedelta(minutes=i))
        assert est.get_state()["hr_sleep_confidence"] < 0.5

    def test_confidence_within_bounds(self):
        est = _est()
        # 混合样本：置信度始终在 [0,1]
        for i, bpm in enumerate([60, 70, 80, 90, 55, 88]):
            est.ingest(bpm, _START + timedelta(seconds=i * 30))
        conf = est.get_state()["hr_sleep_confidence"]
        assert 0.0 <= conf <= 1.0

    def test_get_state_shape(self):
        est = _est()
        est.ingest(75, _START)
        state = est.get_state()
        assert set(state) == {"base_hr", "hr_sleep_confidence", "window_size", "updated_at"}
        assert state["window_size"] == 1
        assert state["base_hr"] == 70.0
        assert state["updated_at"] == "2026-01-01T00:00:00"


# ================================================================ 基线学习
class TestBaseHrLearning:
    def test_base_hr_learned_upward_and_persisted(self, tmp_path):
        store = PhysioSignalStore(path=str(tmp_path / "physio_state.json"))
        cfg = PhysioConfig(base_hr_learning=True)
        est = HeartRateSleepEstimator(config=cfg, store=store)
        # 20 个 80bpm 样本（窗口内）→ 高百分位 80 → base_hr 缓慢更新上移
        for i in range(20):
            est.ingest(80, _START + timedelta(seconds=i * 10))
        base_hr = est.get_state()["base_hr"]
        assert base_hr > 70.0
        # 衍生指标已持久化到 store
        assert store.get("base_hr") == base_hr

    def test_learning_disabled_keeps_base_hr(self):
        est = _est(base_hr_learning=False)
        for i in range(20):
            est.ingest(80, _START + timedelta(seconds=i * 10))
        assert est.get_state()["base_hr"] == 70.0

    def test_base_hr_loaded_from_store(self, tmp_path):
        store = PhysioSignalStore(path=str(tmp_path / "physio_state.json"))
        store.update({"base_hr": 78.0})
        est = HeartRateSleepEstimator(store=store)
        assert est.get_state()["base_hr"] == 78.0


# ================================================================ 时间戳格式兼容（GN-004 F1 回归）
class TestTimestampFormats:
    """F1 修复回归：数值毫秒 / 数值秒 / ISO 字符串 / datetime 四类 ts 均可解析入库且窗口正确。

    前端曾以 epoch 毫秒上送（Date.now()），后端按秒解析导致 OSError [Errno 22]；
    _parse_ts 现兼容 >1e11 毫秒自动转秒，无法解析的时间戳由 ingest 吞掉返回当前置信度。
    """

    def test_numeric_seconds_ts(self):
        est = _est()
        conf = est.ingest(60, _START.timestamp())
        assert est.get_state()["window_size"] == 1
        assert est.get_state()["updated_at"] == "2026-01-01T00:00:00"
        assert 0.0 <= conf <= 1.0

    def test_numeric_milliseconds_ts(self):
        # 毫秒级时间戳（>1e11）→ 自动 /1000 转秒，不再抛 OSError
        est = _est()
        conf = est.ingest(60, _START.timestamp() * 1000)
        assert est.get_state()["window_size"] == 1
        assert est.get_state()["updated_at"] == "2026-01-01T00:00:00"
        assert 0.0 <= conf <= 1.0

    def test_iso_string_ts(self):
        est = _est()
        est.ingest(60, _START.isoformat())
        assert est.get_state()["window_size"] == 1
        assert est.get_state()["updated_at"] == "2026-01-01T00:00:00"

    def test_datetime_ts(self):
        est = _est()
        est.ingest(60, _START)
        assert est.get_state()["window_size"] == 1
        assert est.get_state()["updated_at"] == "2026-01-01T00:00:00"

    def test_mixed_formats_window_consistent(self):
        # 四类格式混用且都落在同一 10 分钟窗口内 → 窗口正确容纳全部样本
        est = _est()
        t = _START
        est.ingest(60, t)                    # datetime
        est.ingest(60, t.isoformat())        # ISO 字符串
        est.ingest(60, t.timestamp())        # epoch 秒
        est.ingest(60, t.timestamp() * 1000)  # epoch 毫秒
        assert est.get_state()["window_size"] == 4

    def test_invalid_ts_swallowed_returns_current_confidence(self):
        # 无法解析的时间戳 → ingest 吞掉 ValueError，返回当前置信度（不抛异常）
        est = _est()
        est.ingest(60, _START)
        before = est.get_state()["hr_sleep_confidence"]
        assert est.ingest(60, object()) == before
        assert est.ingest(60, None) == before  # None ts 同样按无效处理
        assert est.get_state()["window_size"] == 1  # 无效 ts 不入窗口
