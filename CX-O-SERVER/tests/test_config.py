"""
server/config.py 单元测试
环境变量映射、RADIX 配置 auto_fill 越界回退、模型路由、Settings 单例与保存
"""
import json
import threading
import asyncio

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
    atomic_write_json,
    Settings,
)


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    """每个测试前重置 Settings 单例，避免跨测试污染。"""
    Settings.reset()
    config_mod._last_known_config = None
    yield
    Settings.reset()
    config_mod._last_known_config = None


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


# --------------------------------------------------------------------------- #
# MeetingConfig —— 互动空间配置节默认值 / 越界回退
# --------------------------------------------------------------------------- #
class TestMeetingConfig:
    def test_defaults(self):
        m = config_mod.UnifiedConfig().meeting
        assert m.enabled is False
        assert m.audience_enabled is False
        assert m.danmaku_source.type == "none"
        assert m.speech_rate == 0.3
        assert m.agent_speech_prompt == ""
        assert m.backchannel_enabled is False  # 与协调器构造默认对齐
        assert m.max_agents == 5
        assert m.arbiter_model == "independent"
        assert m.default_mode == "moderator"

    def test_speech_rate_out_of_range(self, caplog):
        out = _auto_fill_radix_config({"meeting": {"speech_rate": 5}})
        assert out["meeting"]["speech_rate"] == 0.3

    def test_danmaku_source_type_invalid(self, caplog):
        out = _auto_fill_radix_config({"meeting": {"danmaku_source": {"type": "bogus"}}})
        assert out["meeting"]["danmaku_source"]["type"] == "none"

    def test_danmaku_source_type_valid_preserved(self):
        out = _auto_fill_radix_config({"meeting": {"danmaku_source": {"type": "bilibili", "room_id": "123"}}})
        assert out["meeting"]["danmaku_source"]["type"] == "bilibili"

    def test_out_of_range_clamped_on_load(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({
            "meeting": {"speech_rate": 9, "danmaku_source": {"type": "bogus"}}
        }), encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        Settings.reset()
        c = get_config()
        assert c.meeting.speech_rate == 0.3
        assert c.meeting.danmaku_source.type == "none"


# --------------------------------------------------------------------------- #
# 第六轮扫描批 A2：config.json 内容损坏回退 + 原子写（并发 save 后 JSON 仍合法）
# --------------------------------------------------------------------------- #
class TestAtomicWrite:
    def test_atomic_write_json_basic(self, tmp_path):
        f = tmp_path / "data.json"
        atomic_write_json(str(f), {"a": 1, "list": [1, 2]})
        assert json.loads(f.read_text(encoding="utf-8")) == {"a": 1, "list": [1, 2]}

    def test_atomic_write_creates_parent(self, tmp_path):
        f = tmp_path / "nested" / "dir" / "data.json"
        atomic_write_json(str(f), {"x": 1})
        assert json.loads(f.read_text(encoding="utf-8")) == {"x": 1}

    def test_atomic_write_no_tmp_leftovers(self, tmp_path):
        f = tmp_path / "data.json"
        atomic_write_json(str(f), {"a": 1})
        # 原子写不残留临时文件
        leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_concurrent_save_yields_valid_json(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        Settings.reset()
        c = get_config()
        errors: list = []

        def _save() -> None:
            try:
                save_config(c)
            except Exception as e:  # pragma: no cover - 失败才会走到
                errors.append(e)

        threads = [threading.Thread(target=_save) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # 并发多次 save 后文件仍为合法 JSON（不半写损坏）
        loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)
        assert "system" in loaded


class TestConfigCorruptFallback:
    def test_corrupt_config_does_not_raise(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{ this is not valid json !!!", encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        Settings.reset()
        # 内容损坏时 get_settings() 不得抛异常，回退内置默认配置
        c = get_config()
        assert c.system.host == "0.0.0.0"
        # 损坏副本已备份
        backups = list(tmp_path.glob("config.json.corrupt-*"))
        assert len(backups) >= 1

    def test_corrupt_config_falls_back_to_last_snapshot(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"system": {"port": 7777}}), encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        Settings.reset()
        assert get_config().system.port == 7777
        # 覆盖为损坏内容后重载 → 回退上一次成功快照（port=7777），不抛异常
        cfg_path.write_text("{ bad !!", encoding="utf-8")
        Settings.reset()
        c2 = get_config()
        assert c2.system.port == 7777
        backups = list(tmp_path.glob("config.json.corrupt-*"))
        assert len(backups) >= 1


class TestConfigHotReload:
    """config_hot_reload：live 节即时生效（同步运行时 UnifiedConfig）。"""

    def test_live_apply_section_syncs_runtime(self, tmp_path, monkeypatch):
        from server.config_hot_reload import apply_section

        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        Settings.reset()
        result = asyncio.run(apply_section(
            "live", {"danmaku": {"enabled": True}, "firewall": {"blocking": {"blacklist_enabled": False}}}, None
        ))
        assert result["applied"] is True
        assert result["requires_restart"] is False
        # live 节同步到运行时 UnifiedConfig，组件可即时读取
        cfg = get_settings().config
        assert getattr(cfg, "danmaku", None) == {"enabled": True}
        assert getattr(cfg, "firewall", None) == {"blocking": {"blacklist_enabled": False}}

    def test_live_requires_restart_false(self):
        from server.config_hot_reload import REQUIRES_RESTART
        assert REQUIRES_RESTART.get("live", True) is False


# --------------------------------------------------------------------------- #
# ExecutorConfig —— 环境变量坏值回退（A4 修复：不再让 Pydantic 启动崩溃）
# --------------------------------------------------------------------------- #
class TestExecutorEnvConfig:
    def test_bad_int_env_skipped_in_env_config(self, monkeypatch):
        """EXECUTOR 节坏整型环境变量：get_env_config 阶段即跳过该键，不产出字符串值。

        注：循环前置的 setdefault 会预留空 executor 节（VISION/MEETING 分支同模式），
        断言核心是该键不带字符串坏值落入配置。
        """
        monkeypatch.setenv("CXO_EXECUTOR_TTS_CONCURRENCY", "abc")
        out = get_env_config()
        assert out.get("executor", {}) == {}
        assert "tts_concurrency" not in out.get("executor", {})

    def test_bad_int_env_falls_back_to_default(self, tmp_path, monkeypatch):
        """坏整型环境变量下完整配置加载不崩溃，字段回退默认值 8。"""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        monkeypatch.setenv("CXO_EXECUTOR_TTS_CONCURRENCY", "abc")
        Settings.reset()
        c = get_config()
        assert c.executor.tts_concurrency == 8

    def test_danmaku_interrupt_concurrency_env_override(self, tmp_path, monkeypatch):
        """danmaku_concurrency / interrupt_concurrency 两个转换清单字段可正常经 env 覆盖。"""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        monkeypatch.setenv("CXO_EXECUTOR_DANMAKU_CONCURRENCY", "3")
        monkeypatch.setenv("CXO_EXECUTOR_INTERRUPT_CONCURRENCY", "5")
        Settings.reset()
        c = get_config()
        assert c.executor.danmaku_concurrency == 3
        assert c.executor.interrupt_concurrency == 5

    def test_bad_danmaku_env_falls_back_to_default(self, tmp_path, monkeypatch):
        """新增清单字段同样具备坏值回退能力。"""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
        monkeypatch.setenv("CXO_EXECUTOR_DANMAKU_CONCURRENCY", "not-a-number")
        Settings.reset()
        c = get_config()
        assert c.executor.danmaku_concurrency == 8