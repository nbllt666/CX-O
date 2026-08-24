"""
server/config.py 单元测试
环境变量映射、RADIX 配置 auto_fill 越界回退、模型路由、Settings 单例与保存
"""
import json

from pathlib import Path

import pytest

import server.config as config_mod
from server.config import (
    get_env_config,
    get_config,
    get_service_url,
    get_settings,
    save_config,
    reload_config,
    _auto_fill_radix_config,
    Settings,
)


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    """每个测试前重置 Settings 单例，避免跨测试污染。"""
    Settings.reset()
    yield
    Settings.reset()


# --------------------------------------------------------------------------- #
# get_env_config —— 环境变量 → 嵌套 dict 映射
# --------------------------------------------------------------------------- #
class TestGetEnvConfig:
    def test_no_env(self, monkeypatch):
        monkeypatch.delenv("CXO_SYSTEM_HOST", raising=False)
        assert get_env_config() == {}

    def test_port_converted_to_int(self, monkeypatch):
        monkeypatch.setenv("CXO_SYSTEM_PORT", "9000")
        assert get_env_config()["system"]["port"] == 9000

    def test_debug_bool(self, monkeypatch):
        monkeypatch.setenv("CXO_SYSTEM_DEBUG", "true")
        assert get_env_config()["system"]["debug"] is True

    def test_debug_false(self, monkeypatch):
        monkeypatch.setenv("CXO_SYSTEM_DEBUG", "0")
        assert get_env_config()["system"]["debug"] is False

    def test_vision_enabled_bool(self, monkeypatch):
        monkeypatch.setenv("CXO_VISION_ENABLED", "true")
        assert get_env_config()["vision_enhanced"]["enabled"] is True

    def test_vision_numeric_conversion(self, monkeypatch):
        monkeypatch.setenv("CXO_VISION_BUFFER_RETENTION_SEC", "120")
        monkeypatch.setenv("CXO_VISION_DIFF_THRESHOLD", "0.5")
        out = get_env_config()["vision_enhanced"]
        assert out["buffer_retention_sec"] == 120
        assert out["diff_threshold"] == 0.5

    def test_vision_require_vllm_bool(self, monkeypatch):
        monkeypatch.setenv("CXO_VISION_REQUIRE_VLLM", "1")
        assert get_env_config()["vision_enhanced"]["require_vllm"] is True

    def test_workers_int(self, monkeypatch):
        monkeypatch.setenv("CXO_SYSTEM_WORKERS", "4")
        assert get_env_config()["system"]["workers"] == 4

    def test_string_value(self, monkeypatch):
        monkeypatch.setenv("CXO_LLM_MODEL", "qwen3:latest")
        assert get_env_config()["llm"]["model"] == "qwen3:latest"

    def test_nested_three_level(self, monkeypatch):
        monkeypatch.setenv("CXO_ASR_URL", "http://x:8001")
        assert get_env_config()["services"]["asr"]["url"] == "http://x:8001"

    def test_empty_path_mapping_skipped(self, monkeypatch):
        monkeypatch.setenv("CXO_GATEWAY_CONFIG", "/tmp/gw.json")
        assert "gateway" not in get_env_config()


# --------------------------------------------------------------------------- #
# _auto_fill_radix_config —— 越界回退
# --------------------------------------------------------------------------- #
class TestAutoFillRadix:
    def test_empty(self, caplog):
        out = _auto_fill_radix_config({})
        assert out["distillation"] == {}
        assert out["multimodal_pipeline"] == {}
        assert out["decision_core"] == {}
        assert out["radix"] == {}

    def test_distillation_max_turns_in_range(self):
        out = _auto_fill_radix_config({"distillation": {"max_turns": 3}})
        assert out["distillation"]["max_turns"] == 3

    def test_distillation_max_turns_out_of_range(self, caplog):
        out = _auto_fill_radix_config({"distillation": {"max_turns": 200}})
        assert out["distillation"]["max_turns"] == 4

    def test_distillation_max_turns_non_int(self):
        out = _auto_fill_radix_config({"distillation": {"max_turns": "many"}})
        assert out["distillation"]["max_turns"] == 4

    def test_distillation_low_bound(self):
        out = _auto_fill_radix_config({"distillation": {"max_turns": 0}})
        assert out["distillation"]["max_turns"] == 4

    def test_session_timeout_range(self):
        out = _auto_fill_radix_config({"distillation": {"session_timeout_seconds": 59}})
        assert out["distillation"]["session_timeout_seconds"] == 1800
        out = _auto_fill_radix_config({"distillation": {"session_timeout_seconds": 7201}})
        assert out["distillation"]["session_timeout_seconds"] == 1800

    def test_port_range(self):
        out = _auto_fill_radix_config({"distillation": {"port": 1000}})
        assert out["distillation"]["port"] == 8000

    def test_worker_pool_size(self):
        out = _auto_fill_radix_config({"multimodal_pipeline": {"worker_pool_size": 0}})
        assert out["multimodal_pipeline"]["worker_pool_size"] == 4

    def test_enabled_modalities_unknown_filtered(self):
        out = _auto_fill_radix_config({"multimodal_pipeline": {"enabled_modalities": ["text", "bogus"]}})
        assert out["multimodal_pipeline"]["enabled_modalities"] == ["text"]

    def test_enabled_modalities_all_unknown(self):
        out = _auto_fill_radix_config({"multimodal_pipeline": {"enabled_modalities": ["bogus"]}})
        assert out["multimodal_pipeline"]["enabled_modalities"] == ["text"]

    def test_enabled_modalities_non_list(self):
        out = _auto_fill_radix_config({"multimodal_pipeline": {"enabled_modalities": "text"}})
        assert out["multimodal_pipeline"]["enabled_modalities"] == [
            "text", "character_card", "image", "video", "audio"]

    def test_decision_threshold(self):
        out = _auto_fill_radix_config({"decision_core": {"importance_threshold_permanent": 1.5}})
        assert out["decision_core"]["importance_threshold_permanent"] == 0.7

    def test_decision_int_field(self):
        out = _auto_fill_radix_config({"decision_core": {"max_redistill_turns": 99}})
        assert out["decision_core"]["max_redistill_turns"] == 2

    def test_vision_enhanced_missing_added(self):
        out = _auto_fill_radix_config({})
        assert out["vision_enhanced"] == {}

    def test_vision_buffer_retention_out_of_range(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"buffer_retention_sec": 99999}})
        assert out["vision_enhanced"]["buffer_retention_sec"] == 30

    def test_vision_clip_max_sec_out_of_range(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"clip_max_sec": 200}})
        assert out["vision_enhanced"]["clip_max_sec"] == 10

    def test_vision_diff_threshold_out_of_range(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"diff_threshold": 5.0}})
        assert out["vision_enhanced"]["diff_threshold"] == 0.08

    def test_vision_event_cooldown_out_of_range(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"event_cooldown_sec": 0}})
        assert out["vision_enhanced"]["event_cooldown_sec"] == 15

    def test_vision_max_clips_per_hour_out_of_range(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"max_clips_per_hour": 2000}})
        assert out["vision_enhanced"]["max_clips_per_hour"] == 12

    def test_vision_pre_roll_negative(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"pre_roll_sec": -5}})
        assert out["vision_enhanced"]["pre_roll_sec"] == 3

    def test_vision_in_clamps_missing_untouched(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"buffer_retention_sec": 60}})
        assert out["vision_enhanced"]["buffer_retention_sec"] == 60


# --------------------------------------------------------------------------- #
# ModelsConfig.get_model_config —— 模型路由
# --------------------------------------------------------------------------- #
class TestModelsConfig:
    def test_defaults_alias_to_main(self):
        # defaults: {"summary": "main", "memory": "main"} → 都归向 main 配置
        mc = config_mod.ModelsConfig()
        assert mc.get_model_config("summary") is mc.main
        assert mc.get_model_config("memory") is mc.main

    def test_unknown_returns_main(self):
        mc = config_mod.ModelsConfig()
        assert mc.get_model_config("other") is mc.main

    def test_explicit_summary_overrides_defaults(self):
        # 用户显式配置 models.summary → 不再跟随 main，返回独立配置
        summary = config_mod.ModelConfig(provider="ollama", model="summary-model")
        mc = config_mod.ModelsConfig(summary=summary)
        mc._set_explicit(["summary"])
        assert mc.resolve_target("summary") == "summary"
        assert mc.get_model_config("summary") is summary
        # memory 未显式配置，仍跟随 main
        assert mc.get_model_config("memory") is mc.main

    def test_explicit_memory_overrides_defaults(self):
        memory = config_mod.ModelConfig(provider="vllm", model="memory-model")
        mc = config_mod.ModelsConfig(memory=memory)
        mc._set_explicit(["memory"])
        assert mc.resolve_target("memory") == "memory"
        assert mc.get_model_config("memory") is memory
        # summary 未显式配置，仍跟随 main
        assert mc.get_model_config("summary") is mc.main

    def test_not_explicit_but_section_present_follows_defaults(self):
        # 仅当 _set_explicit 记录后才解除跟随；未记录时即使传入独立配置仍跟随 main
        summary = config_mod.ModelConfig(provider="ollama", model="summary-model")
        mc = config_mod.ModelsConfig(summary=summary)
        assert mc.resolve_target("summary") == "main"
        assert mc.get_model_config("summary") is mc.main

    def test_db_url(self):
        dc = config_mod.DatabaseConfig(path="data/x.db")
        # 相对路径被归一化为项目根绝对路径
        assert dc.url == f"sqlite+aiosqlite:///{config_mod._PROJECT_ROOT / 'data' / 'x.db'}"

    def test_db_paths_resolved_to_absolute(self):
        dc = config_mod.DatabaseConfig()
        assert Path(dc.path).is_absolute()
        assert Path(dc.memories_db).is_absolute()
        assert Path(dc.sessions_db).is_absolute()
        assert Path(dc.acp_db).is_absolute()


# --------------------------------------------------------------------------- #
# Settings 单例 + get_config/save_config/reload_config/get_service_url
# --------------------------------------------------------------------------- #
class TestSettings:
    def test_singleton(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_getattr_missing_raises(self):
        s = get_settings()
        with pytest.raises(AttributeError):
            s._private_thing
        with pytest.raises(AttributeError):
            s.nonexistent_attr

    def test_getattr_config_proxy(self):
        s = get_settings()
        assert s.system.host == "0.0.0.0"

    def test_get_config_defaults(self):
        c = get_config()
        assert c.system.host == "0.0.0.0"
        assert c.system.port == 8000
        # provider 由实际 config.json 决定，不断言具体值，仅验证字段存在
        assert c.llm.provider in ("ollama", "vllm", "openai")

    def test_get_service_url(self):
        c = get_config()
        c.services.asr.url = "http://test:8001"
        assert get_service_url("asr") == "http://test:8001"

    def test_get_service_url_unknown(self):
        with pytest.raises(ValueError):
            get_service_url("nonexistent")

    def test_save_config_roundtrip(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        Settings.reset()
        c = get_config()
        c.system.port = 9999
        save_config(c)
        loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert loaded["system"]["port"] == 9999

    def test_reload_config(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"system": {"port": 7777}}), encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        Settings.reset()
        c = get_config()
        assert c.system.port == 7777
        # 修改文件后 reload
        cfg_path.write_text(json.dumps({"system": {"port": 8888}}), encoding="utf-8")
        rc = reload_config()
        assert rc.system.port == 8888

    def test_env_override_merge(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"system": {"host": "1.2.3.4", "port": 5000}}), encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        monkeypatch.setenv("CXO_SYSTEM_PORT", "6000")
        Settings.reset()
        c = get_config()
        # env 覆盖 file 的 port，host 保留 file 值
        assert c.system.port == 6000
        assert c.system.host == "1.2.3.4"


# --------------------------------------------------------------------------- #
# VisionEnhancedConfig —— 默认值 / 环境变量覆盖 / 越界钳制
# --------------------------------------------------------------------------- #
class TestVisionEnhancedConfig:
    def test_defaults(self):
        ve = config_mod.UnifiedConfig().vision_enhanced
        assert ve.enabled is False
        assert ve.buffer_retention_sec == 30
        assert ve.diff_threshold == 0.08
        assert ve.event_cooldown_sec == 15
        assert ve.max_clips_per_hour == 12
        assert ve.pre_roll_sec == 3
        assert ve.post_roll_sec == 6
        assert ve.clip_max_sec == 10
        assert ve.narrative_memory_enabled is True
        assert ve.temporal_fusion_enabled is False
        assert ve.ocr_keyframe_enabled is True
        assert ve.require_vllm is True

    def test_env_override(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        monkeypatch.setenv("CXO_VISION_ENABLED", "true")
        monkeypatch.setenv("CXO_VISION_BUFFER_RETENTION_SEC", "120")
        Settings.reset()
        c = get_config()
        assert c.vision_enhanced.enabled is True
        assert c.vision_enhanced.buffer_retention_sec == 120

    def test_out_of_range_clamped_on_load(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({
            "vision_enhanced": {
                "buffer_retention_sec": 99999,
                "clip_max_sec": 200,
                "diff_threshold": 5.0,
            }
        }), encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        Settings.reset()
        c = get_config()
        assert c.vision_enhanced.buffer_retention_sec == 30
        assert c.vision_enhanced.clip_max_sec == 10
        assert c.vision_enhanced.diff_threshold == 0.08