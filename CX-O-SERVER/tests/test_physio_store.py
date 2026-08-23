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
