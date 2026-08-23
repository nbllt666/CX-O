"""CX-O-Dream 生理信号配置节（server/autonomy/dream/config.py PhysioConfig）单测。

覆盖：
1. PhysioConfig 默认值（enabled=False、backend="noble" 信息性登记键、
   device_name_hint=""、device_fingerprint=None、scan_timeout_sec=15、
   reconnect_interval_sec=30、base_drop_ratio=0.88、base_drop_confirm_min=5、
   hr_stability_threshold=6、base_hr_learning=True、store_raw_hr=False）
2. store_raw_hr=True 抛 pydantic ValidationError（隐私红线硬约束）
3. DreamConfig 新增 physio 子节可读、可整体校验
4. PhysioConfig extra 字段被 forbid

运行：python -m pytest tests/test_physio_config.py -q
"""
import pytest
from pydantic import ValidationError

from server.autonomy.dream.config import DreamConfig, PhysioConfig


# ================================================================ 默认值
class TestPhysioConfigDefaults:
    def test_defaults(self):
        cfg = PhysioConfig()
        assert cfg.enabled is False
        assert cfg.backend == "noble"
        assert cfg.device_name_hint == ""
        assert cfg.device_fingerprint is None
        assert cfg.scan_timeout_sec == 15
        assert cfg.reconnect_interval_sec == 30
        assert cfg.base_drop_ratio == 0.88
        assert cfg.base_drop_confirm_min == 5
        assert cfg.hr_stability_threshold == 6
        assert cfg.base_hr_learning is True
        assert cfg.store_raw_hr is False

    def test_backend_documented_as_informational(self):
        # backend 为信息性登记键：标注采集路线由前端 Electron noble 承担，
        # 后端无对应实现、不参与逻辑（docstring 已注明）
        cfg = PhysioConfig(backend="noble")
        assert cfg.backend == "noble"


# ================================================================ store_raw_hr 强制 false
class TestStoreRawHrForced:
    def test_store_raw_hr_true_rejected(self):
        with pytest.raises(ValidationError):
            PhysioConfig(store_raw_hr=True)

    def test_store_raw_hr_true_rejected_via_model_validate(self):
        with pytest.raises(ValidationError):
            PhysioConfig.model_validate({"store_raw_hr": True})


# ================================================================ DreamConfig.physio 子节
class TestDreamConfigPhysio:
    def test_physio_subsection_defaults(self):
        cfg = DreamConfig()
        assert isinstance(cfg.physio, PhysioConfig)
        assert cfg.physio.enabled is False
        assert cfg.physio.store_raw_hr is False

    def test_physio_subsection_readable_via_model_validate(self):
        cfg = DreamConfig.model_validate(
            {"physio": {"enabled": True, "device_name_hint": "MiBand"}}
        )
        assert cfg.physio.enabled is True
        assert cfg.physio.device_name_hint == "MiBand"
        # 未提供的 physio 字段自动补齐默认值
        assert cfg.physio.backend == "noble"
        assert cfg.physio.store_raw_hr is False

    def test_physio_store_raw_hr_true_rejected_in_dream_config(self):
        with pytest.raises(ValidationError):
            DreamConfig.model_validate({"physio": {"store_raw_hr": True}})

    def test_default_instances_are_isolated(self):
        a = DreamConfig()
        b = DreamConfig()
        a.physio.enabled = True
        assert b.physio.enabled is False


# ================================================================ extra forbid
class TestPhysioExtraForbidden:
    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            PhysioConfig.model_validate({"enabled": True, "unknown_field": 1})

    def test_unknown_field_rejected_in_dream_config_physio(self):
        with pytest.raises(ValidationError):
            DreamConfig.model_validate({"physio": {"enabled": True, "unknown_field": 1}})
