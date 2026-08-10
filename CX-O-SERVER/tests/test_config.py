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