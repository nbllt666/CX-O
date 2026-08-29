"""CX-O-Dream 生理信号衍生指标存储（server/autonomy/dream/physio/store.py）单测。

覆盖：
1. 只持久化衍生指标 {base_hr, hr_sleep_confidence, device_fingerprint, updated_at}，
   无任何原始 HR 字段；update 传入原始 HR 键抛 ValueError（隐私红线）
2. save→load 往返一致（新实例可读回）
3. clear 清空全部生理基线数据（含 base_hr 与设备指纹）
4. 默认路径基于 __file__ 绝对路径解析到 server/autonomy/data/physio_state.json

运行：python -m pytest tests/test_physio_store.py -q
"""
import json
from pathlib import Path

import pytest

from server.autonomy.dream.physio.store import PhysioSignalStore


def _derived_update(**overrides):
    data = {
        "base_hr": 72.0,
        "hr_sleep_confidence": 0.9,
        "device_fingerprint": "fp-001",
        "updated_at": "2026-01-01T00:00:00",
    }
    data.update(overrides)
    return data


# ================================================================ 只存衍生指标
class TestOnlyDerivedMetrics:
    def test_persists_only_derived_metrics(self, tmp_path):
        path = tmp_path / "physio_state.json"
        store = PhysioSignalStore(path=str(path))
        store.update(_derived_update())
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data) == {
            "base_hr",
            "hr_sleep_confidence",
            "device_fingerprint",
            "updated_at",
        }
        # 无任何原始 HR 字段
        assert not any("raw" in k or "sample" in k for k in data)

    def test_unknown_keys_ignored(self, tmp_path):
        store = PhysioSignalStore(path=str(tmp_path / "physio_state.json"))
        store.update({**_derived_update(), "unrelated": "x"})
        data = json.loads((tmp_path / "physio_state.json").read_text(encoding="utf-8"))
        assert "unrelated" not in data
        assert set(data) == {"base_hr", "hr_sleep_confidence", "device_fingerprint", "updated_at"}

    def test_update_rejects_raw_hr_keys(self, tmp_path):
        store = PhysioSignalStore(path=str(tmp_path / "physio_state.json"))
        with pytest.raises(ValueError):
            store.update({"raw_hr": [60, 61, 62]})
        with pytest.raises(ValueError):
            store.update({"samples": [60, 61, 62]})
        with pytest.raises(ValueError):
            store.update({"hr_sequence": [60, 61, 62]})

    def test_update_none_value_does_not_clear(self, tmp_path):
        store = PhysioSignalStore(path=str(tmp_path / "physio_state.json"))
        store.update({"base_hr": 75.0, "device_fingerprint": "fp-9"})
        store.update({"base_hr": None})
        assert store.get("base_hr") == 75.0
        assert store.get("device_fingerprint") == "fp-9"


# ================================================================ save→load 往返
class TestSaveLoadRoundTrip:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "physio_state.json"
        store = PhysioSignalStore(path=str(path))
        store.update(_derived_update(base_hr=73.0, hr_sleep_confidence=0.85, device_fingerprint="fp-9"))

        reloaded = PhysioSignalStore(path=str(path))
        assert reloaded.get("base_hr") == 73.0
        assert reloaded.get("hr_sleep_confidence") == 0.85
        assert reloaded.get("device_fingerprint") == "fp-9"
        assert reloaded.get("updated_at") == "2026-01-01T00:00:00"
        # 缺失键返回默认值
        assert reloaded.get("missing", "dflt") == "dflt"

    def test_missing_file_loads_empty(self, tmp_path):
        store = PhysioSignalStore(path=str(tmp_path / "physio_state.json"))
        assert store.get("base_hr") is None
        assert store.get("hr_sleep_confidence") is None


# ================================================================ clear
class TestClear:
    def test_clear_resets_base_hr_and_fingerprint(self, tmp_path):
        path = tmp_path / "physio_state.json"
        store = PhysioSignalStore(path=str(path))
        store.update({"base_hr": 70.0, "device_fingerprint": "fp-1", "hr_sleep_confidence": 0.8})
        store.clear()
        assert store.get("base_hr") is None
        assert store.get("device_fingerprint") is None
        assert store.get("hr_sleep_confidence") is None
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {}


# ================================================================ 路径解析
class TestPathResolution:
    def test_default_path_resolves_to_autonomy_data(self):
        expected = str(
            Path(__file__).resolve().parents[1]
            / "server"
            / "autonomy"
            / "data"
            / "physio_state.json"
        )
        assert PhysioSignalStore().path == expected

    def test_explicit_path_passthrough(self, tmp_path):
        store = PhysioSignalStore(path=str(tmp_path / "custom" / "state.json"))
        assert store.path == str(tmp_path / "custom" / "state.json")


# ================================================================ 落盘节流（写放大修复）
class TestThrottledPersistence:
    """update() 落盘按 _MIN_FLUSH_INTERVAL_SEC（30s）节流；flush() 强制落盘。

    用假单调时钟精确控制节流窗口；文件内容直读断言，内存 get() 断言始终最新。
    """

    @pytest.fixture
    def clock(self, monkeypatch):
        """可控单调时钟：clock["t"] 即 time.monotonic() 返回值。"""
        import server.autonomy.dream.physio.store as store_mod

        now = {"t": 1000.0}
        monkeypatch.setattr(store_mod.time, "monotonic", lambda: now["t"])
        return now

    def test_first_update_saves_immediately(self, tmp_path, clock):
        path = tmp_path / "physio_state.json"
        store = PhysioSignalStore(path=str(path))
        store.update({"base_hr": 60.0})
        # 首次 update 距节流基准（0.0）远超 30s → 立即落盘
        assert json.loads(path.read_text(encoding="utf-8"))["base_hr"] == 60.0
        assert store._dirty is False

    def test_multiple_updates_within_interval_save_once(self, tmp_path, clock):
        path = tmp_path / "physio_state.json"
        store = PhysioSignalStore(path=str(path))
        store.update({"base_hr": 60.0})  # 首次落盘
        # 10s 后再次 update：interval 内仅置脏不落盘
        clock["t"] = 1010.0
        store.update({"base_hr": 62.0})
        assert store._dirty is True
        # 落盘文件仍是旧值，内存已是最新（读取路径始终反映内存状态）
        assert json.loads(path.read_text(encoding="utf-8"))["base_hr"] == 60.0
        assert store.get("base_hr") == 62.0
        # 20s 处第三次 update：仍在 interval 内，不落盘
        clock["t"] = 1020.0
        store.update({"base_hr": 63.0})
        assert json.loads(path.read_text(encoding="utf-8"))["base_hr"] == 60.0
        # 31s 处第四次 update：超过最小间隔 → 落盘最新值并清脏
        clock["t"] = 1031.0
        store.update({"base_hr": 64.0})
        assert json.loads(path.read_text(encoding="utf-8"))["base_hr"] == 64.0
        assert store._dirty is False

    def test_flush_forces_save_of_latest_state(self, tmp_path, clock):
        path = tmp_path / "physio_state.json"
        store = PhysioSignalStore(path=str(path))
        store.update({"base_hr": 60.0})  # 首次落盘
        clock["t"] = 1005.0
        store.update({"base_hr": 71.5, "hr_sleep_confidence": 0.9})  # interval 内仅置脏
        assert store._dirty is True
        # flush 强制落盘：文件立即反映内存最新值
        store.flush()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["base_hr"] == 71.5
        assert data["hr_sleep_confidence"] == 0.9
        assert store._dirty is False

    def test_no_change_update_skips_dirty_and_save(self, tmp_path, clock):
        path = tmp_path / "physio_state.json"
        store = PhysioSignalStore(path=str(path))
        store.update({"base_hr": 60.0})  # 首次落盘
        clock["t"] = 1005.0
        # 全 None 值 → 无实际变化 → 不置脏不落盘
        store.update({"base_hr": None, "hr_sleep_confidence": None})
        assert store._dirty is False
        assert json.loads(path.read_text(encoding="utf-8"))["base_hr"] == 60.0

    def test_clear_saves_immediately_and_resets_dirty(self, tmp_path, clock):
        path = tmp_path / "physio_state.json"
        store = PhysioSignalStore(path=str(path))
        store.update({"base_hr": 60.0})
        clock["t"] = 1005.0
        store.update({"base_hr": 62.0})  # interval 内置脏
        assert store._dirty is True
        store.clear()  # 清空属低频显式操作，立即落盘
        assert store._dirty is False
        assert json.loads(path.read_text(encoding="utf-8")) == {}

    def test_flush_clears_dirty_and_persists_content(self, tmp_path, clock):
        """关闭路径 flush 接线（L-P1）语义：flush 后脏标记清除且最新内容落盘，幂等。"""
        path = tmp_path / "physio_state.json"
        store = PhysioSignalStore(path=str(path))
        store.update({"base_hr": 60.0})  # 首次落盘
        clock["t"] = 1005.0
        store.update({"base_hr": 75.0, "device_fingerprint": "fp-flush"})  # interval 内仅置脏
        assert store._dirty is True
        store.flush()
        # 脏标记清除 + 节流窗口内最新内容落盘
        assert store._dirty is False
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["base_hr"] == 75.0
        assert data["device_fingerprint"] == "fp-flush"
        # 幂等：再次 flush 不抛错且内容不变
        store.flush()
        assert json.loads(path.read_text(encoding="utf-8"))["base_hr"] == 75.0
