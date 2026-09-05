"""CX-O-Dream 独立配置模块（server/autonomy/dream/config.py）单测。

覆盖：
1. DreamConfig 默认值（enabled=False、model="summary"、dream_temperature=0.9、
   candidates_per_session=3、material_window_days=7、max_material_items=20、
   min_lucidity=0.3、dream_ttl_hours=72、purge_threshold=0.1、
   confirmed_importance=0.4、surface_on_wake=True、surface_probability=0.5、
   max_surface_per_day=1；schedule 复用 ScheduleConfig，睡眠窗口 02:00-08:00）
2. 缺文件时 load_config 返回全默认实例
3. save_config → load_config 往返一致
4. extra 字段被 forbid（抛 pydantic ValidationError）
5. 非法 HH:MM 抛 ValueError（经 ScheduleConfig 校验）
6. trigger 触发闸门子节：默认值 / save→load 往返 / 非法值（越界与未知字段）
   抛 ValidationError / 旧配置（无 trigger 节）load 后自动补全默认（auto_fill）

运行：python -m pytest tests/test_dream_config.py -q
"""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.autonomy.config import ScheduleConfig
from server.autonomy.dream.config import (
    DreamConfig,
    DreamTriggerConfig,
    load_config,
    resolve_store_dir,
    save_config,
)


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ================================================================ 默认值
class TestDreamConfigDefaults:
    def test_defaults(self):
        cfg = DreamConfig()
        assert cfg.enabled is False
        assert cfg.model == "summary"
        assert cfg.dream_temperature == 0.9
        assert cfg.candidates_per_session == 3
        assert cfg.material_window_days == 7
        assert cfg.max_material_items == 20
        assert cfg.min_lucidity == 0.3
        assert cfg.dream_ttl_hours == 72
        assert cfg.purge_threshold == 0.1
        assert cfg.confirmed_importance == 0.4
        assert cfg.surface_on_wake is True
        assert cfg.surface_probability == 0.5
        assert cfg.max_surface_per_day == 1
        assert cfg.sleep_confirmation.enabled is True
        assert cfg.sleep_confirmation.model == "summary"
        assert cfg.sleep_confirmation.timeout_sec == 10.0
        assert cfg.sleep_confirmation.cooldown_seconds == 1800

    def test_schedule_reused_from_autonomy_config(self):
        cfg = DreamConfig()
        assert isinstance(cfg.schedule, ScheduleConfig)
        # 睡眠窗口默认 02:00-08:00（sleep_time / wake_time）
        assert cfg.schedule.sleep_time == "02:00"
        assert cfg.schedule.wake_time == "08:00"

    def test_default_instances_are_isolated(self):
        a = DreamConfig()
        b = DreamConfig()
        a.schedule.wake_time = "07:00"
        assert b.schedule.wake_time == "08:00"


# ================================================================ 缺文件回默认
class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = load_config(str(tmp_path))
        assert cfg.enabled is False
        assert cfg.dream_temperature == 0.9
        assert cfg.schedule.wake_time == "08:00"

    def test_load_file_with_partial_overrides(self, tmp_path):
        _write_json(tmp_path / "dream_config.json", {"enabled": True, "dream_ttl_hours": 24})
        cfg = load_config(str(tmp_path))
        assert cfg.enabled is True
        assert cfg.dream_ttl_hours == 24
        # 未提供的字段自动补齐默认值（auto_fill 语义）
        assert cfg.dream_temperature == 0.9
        assert cfg.schedule.wake_time == "08:00"


# ================================================================ save→load 往返
class TestSaveLoadRoundTrip:
    def test_round_trip(self, tmp_path):
        cfg = DreamConfig(
            enabled=True,
            model="qwen3",
            dream_temperature=0.7,
            schedule=ScheduleConfig(wake_time="07:30", sleep_time="01:00"),
        )
        saved = save_config(cfg, store_path=str(tmp_path))
        assert Path(saved) == tmp_path / "dream_config.json"
        assert Path(saved).exists()

        loaded = load_config(str(tmp_path))
        assert loaded == cfg
        assert loaded.enabled is True
        assert loaded.model == "qwen3"
        assert loaded.dream_temperature == 0.7
        assert loaded.schedule.wake_time == "07:30"
        assert loaded.schedule.sleep_time == "01:00"

    def test_save_writes_json_utf8_indent(self, tmp_path):
        save_config(DreamConfig(enabled=True), store_path=str(tmp_path))
        text = (tmp_path / "dream_config.json").read_text(encoding="utf-8")
        assert '"enabled": true' in text
        assert '\n  "' in text  # indent=2


# ================================================================ extra forbid
class TestExtraForbidden:
    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            DreamConfig.model_validate({"enabled": True, "unknown_field": 1})

    def test_unknown_schedule_field_rejected(self):
        with pytest.raises(ValidationError):
            DreamConfig.model_validate({"schedule": {"wake_time": "08:00", "unknown": 1}})


# ================================================================ 非法 HH:MM
class TestInvalidHHMM:
    def test_invalid_time_rejected(self):
        with pytest.raises(ValidationError):
            DreamConfig.model_validate({"schedule": {"wake_time": "25:99"}})

    def test_invalid_time_in_load_rejected(self, tmp_path):
        _write_json(tmp_path / "dream_config.json", {"schedule": {"wake_time": "8:60"}})
        with pytest.raises(ValidationError):
            load_config(str(tmp_path))


# ================================================================ 存储目录解析
class TestResolveStoreDir:
    def test_default_resolves_to_autonomy_data(self):
        expected = str(Path(__file__).resolve().parents[1] / "server" / "autonomy" / "data")
        assert resolve_store_dir() == expected

    def test_explicit_store_path_passthrough(self, tmp_path):
        assert resolve_store_dir(str(tmp_path)) == str(tmp_path)


# ================================================================ trigger 触发闸门子节
class TestDreamTriggerConfig:
    def test_trigger_defaults(self):
        """trigger 子节全默认（零回归：不做情绪查询、概率恒命中）。"""
        cfg = DreamConfig()
        assert cfg.trigger.emotion_enabled is False
        assert cfg.trigger.emotion_threshold == 0.7
        assert cfg.trigger.emotion_window_hours == 24
        assert cfg.trigger.emotion_min_events == 1
        assert cfg.trigger.probability == 1.0

    def test_default_trigger_instances_are_isolated(self):
        a = DreamConfig()
        b = DreamConfig()
        a.trigger.probability = 0.3
        assert b.trigger.probability == 1.0

    def test_round_trip_preserves_trigger(self, tmp_path):
        """save→load 往返保留 trigger 子节全部字段。"""
        cfg = DreamConfig(
            trigger=DreamTriggerConfig(
                emotion_enabled=True,
                emotion_threshold=0.8,
                emotion_window_hours=12,
                emotion_min_events=2,
                probability=0.5,
            )
        )
        save_config(cfg, store_path=str(tmp_path))
        loaded = load_config(str(tmp_path))
        assert loaded.trigger == cfg.trigger
        assert loaded.trigger.emotion_enabled is True
        assert loaded.trigger.emotion_threshold == 0.8
        assert loaded.trigger.emotion_window_hours == 12
        assert loaded.trigger.emotion_min_events == 2
        assert loaded.trigger.probability == 0.5

    @pytest.mark.parametrize(
        "payload",
        [
            {"probability": 1.5},
            {"probability": -0.1},
            {"emotion_threshold": 1.5},
            {"emotion_window_hours": 0},
            {"emotion_min_events": 0},
        ],
    )
    def test_invalid_trigger_values_rejected(self, payload):
        with pytest.raises(ValidationError):
            DreamConfig.model_validate({"trigger": payload})

    def test_trigger_unknown_field_rejected(self):
        """trigger 子节 extra="forbid"：未知字段抛 ValidationError。"""
        with pytest.raises(ValidationError):
            DreamConfig.model_validate({"trigger": {"emotion_enabled": True, "unknown": 1}})

    def test_legacy_config_without_trigger_fills_defaults(self, tmp_path):
        """旧配置文件（无 trigger 节）load 后 trigger 为全默认（auto_fill）。"""
        _write_json(tmp_path / "dream_config.json", {"enabled": True})
        cfg = load_config(str(tmp_path))
        assert cfg.enabled is True
        assert cfg.trigger.emotion_enabled is False
        assert cfg.trigger.emotion_threshold == 0.7
        assert cfg.trigger.emotion_window_hours == 24
        assert cfg.trigger.emotion_min_events == 1
        assert cfg.trigger.probability == 1.0
