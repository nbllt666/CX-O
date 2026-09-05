"""
server/config.py 帧过滤 + 人脸匹配配置单元测试（spec add-vlm-frame-filter-face-match Task 1）

覆盖：VisionEnhancedConfig 帧过滤 6 字段与 FaceMatchConfig 7 字段默认值、
CXO_VISION_FRAME_FILTER_* / CXO_FACE_* 环境变量映射与类型转换、
_auto_fill_radix_config 越界回退（provider/sim_threshold/max_faces_per_frame/
filter_context_messages/filter_timeout_seconds/filter_fail_mode）。
测试范式对齐既有 tests/test_config.py（get_env_config 映射 + _auto_fill_radix_config 直调）。
"""
import pytest

from server.config import (
    UnifiedConfig,
    VisionEnhancedConfig,
    FaceMatchConfig,
    get_env_config,
    _auto_fill_radix_config,
)


# --------------------------------------------------------------------------- #
# 默认值断言
# --------------------------------------------------------------------------- #
class TestDefaults:
    def test_vision_filter_defaults(self):
        ve = UnifiedConfig().vision_enhanced
        assert ve.frame_filter_enabled is False
        assert ve.filter_vlm_endpoint == ""
        assert ve.filter_vlm_model == ""
        assert ve.filter_context_messages == 6
        assert ve.filter_timeout_seconds == 8.0
        assert ve.filter_fail_mode == "passthrough"

    def test_face_match_defaults(self):
        fm = UnifiedConfig().face_match
        assert fm.enabled is False
        assert fm.provider == "local"
        assert fm.endpoint == ""
        assert fm.sim_threshold == 0.45
        assert fm.max_faces_per_frame == 4
        assert fm.model_root == ""
        assert fm.store_path == ""

    def test_section_classes_defaults(self):
        ve = VisionEnhancedConfig()
        assert ve.frame_filter_enabled is False
        assert ve.filter_context_messages == 6
        assert ve.filter_timeout_seconds == 8.0
        assert ve.filter_fail_mode == "passthrough"
        fm = FaceMatchConfig()
        assert fm.enabled is False
        assert fm.provider == "local"
        assert fm.sim_threshold == 0.45
        assert fm.max_faces_per_frame == 4

    def test_face_match_mounted_on_unified(self):
        c = UnifiedConfig()
        assert isinstance(c.vision_enhanced, VisionEnhancedConfig)
        assert isinstance(c.face_match, FaceMatchConfig)


# --------------------------------------------------------------------------- #
# get_env_config —— 环境变量映射与类型转换
# --------------------------------------------------------------------------- #
class TestEnvMapping:
    def test_face_enabled_bool(self, monkeypatch):
        monkeypatch.setenv("CXO_FACE_ENABLED", "true")
        assert get_env_config()["face_match"]["enabled"] is True

    def test_face_enabled_false(self, monkeypatch):
        monkeypatch.setenv("CXO_FACE_ENABLED", "0")
        assert get_env_config()["face_match"]["enabled"] is False

    def test_face_provider_string(self, monkeypatch):
        monkeypatch.setenv("CXO_FACE_PROVIDER", "external")
        assert get_env_config()["face_match"]["provider"] == "external"

    def test_face_endpoint_string(self, monkeypatch):
        monkeypatch.setenv("CXO_FACE_ENDPOINT", "http://127.0.0.1:8200")
        assert get_env_config()["face_match"]["endpoint"] == "http://127.0.0.1:8200"

    def test_face_sim_threshold_float(self, monkeypatch):
        monkeypatch.setenv("CXO_FACE_SIM_THRESHOLD", "0.6")
        assert get_env_config()["face_match"]["sim_threshold"] == 0.6

    def test_face_max_faces_int(self, monkeypatch):
        monkeypatch.setenv("CXO_FACE_MAX_FACES_PER_FRAME", "8")
        assert get_env_config()["face_match"]["max_faces_per_frame"] == 8

    def test_face_paths_string(self, monkeypatch):
        monkeypatch.setenv("CXO_FACE_MODEL_ROOT", "D:/models/face")
        monkeypatch.setenv("CXO_FACE_STORE_PATH", "data/face_profiles.json")
        out = get_env_config()["face_match"]
        assert out["model_root"] == "D:/models/face"
        assert out["store_path"] == "data/face_profiles.json"

    def test_vision_frame_filter_enabled_bool(self, monkeypatch):
        monkeypatch.setenv("CXO_VISION_FRAME_FILTER_ENABLED", "1")
        assert get_env_config()["vision_enhanced"]["frame_filter_enabled"] is True

    def test_vision_frame_filter_endpoint_model_string(self, monkeypatch):
        monkeypatch.setenv("CXO_VISION_FRAME_FILTER_VLM_ENDPOINT", "http://127.0.0.1:8100/v1")
        monkeypatch.setenv("CXO_VISION_FRAME_FILTER_VLM_MODEL", "qwen2.5-vl:7b")
        out = get_env_config()["vision_enhanced"]
        assert out["filter_vlm_endpoint"] == "http://127.0.0.1:8100/v1"
        assert out["filter_vlm_model"] == "qwen2.5-vl:7b"

    def test_vision_frame_filter_context_messages_int(self, monkeypatch):
        monkeypatch.setenv("CXO_VISION_FRAME_FILTER_CONTEXT_MESSAGES", "12")
        assert get_env_config()["vision_enhanced"]["filter_context_messages"] == 12

    def test_vision_frame_filter_context_messages_bad_ignored(self, monkeypatch):
        # 坏环境变量跳过该键（走默认值路径），不产生键也不抛异常；节本身 lazy 创建
        monkeypatch.setenv("CXO_VISION_FRAME_FILTER_CONTEXT_MESSAGES", "many")
        assert "filter_context_messages" not in get_env_config().get("vision_enhanced", {})

    def test_vision_frame_filter_timeout_float(self, monkeypatch):
        monkeypatch.setenv("CXO_VISION_FRAME_FILTER_TIMEOUT_SECONDS", "15.5")
        assert get_env_config()["vision_enhanced"]["filter_timeout_seconds"] == 15.5

    def test_vision_frame_filter_fail_mode_string(self, monkeypatch):
        monkeypatch.setenv("CXO_VISION_FRAME_FILTER_FAIL_MODE", "discard")
        assert get_env_config()["vision_enhanced"]["filter_fail_mode"] == "discard"


class TestEnvLoadIntoConfig:
    """环境变量经 UnifiedConfig 加载后生效（模拟 get_config 的 env 合并路径）。"""

    def test_face_and_filter_env_loaded(self, monkeypatch):
        monkeypatch.setenv("CXO_FACE_ENABLED", "true")
        monkeypatch.setenv("CXO_FACE_PROVIDER", "external")
        monkeypatch.setenv("CXO_FACE_SIM_THRESHOLD", "0.6")
        monkeypatch.setenv("CXO_VISION_FRAME_FILTER_CONTEXT_MESSAGES", "12")
        monkeypatch.setenv("CXO_VISION_FRAME_FILTER_ENABLED", "true")
        c = UnifiedConfig(**get_env_config())
        assert c.face_match.enabled is True
        assert c.face_match.provider == "external"
        assert c.face_match.sim_threshold == 0.6
        assert c.vision_enhanced.frame_filter_enabled is True
        assert c.vision_enhanced.filter_context_messages == 12


# --------------------------------------------------------------------------- #
# _auto_fill_radix_config —— 越界回退
# --------------------------------------------------------------------------- #
class TestAutoFillClamp:
    def test_face_section_setdefault_empty(self):
        out = _auto_fill_radix_config({})
        assert out["face_match"] == {}

    def test_face_provider_invalid_fallback(self):
        out = _auto_fill_radix_config({"face_match": {"provider": "oops"}})
        assert out["face_match"]["provider"] == "local"

    def test_face_provider_valid_kept(self):
        out = _auto_fill_radix_config({"face_match": {"provider": "external"}})
        assert out["face_match"]["provider"] == "external"

    def test_face_sim_threshold_out_of_range(self):
        out = _auto_fill_radix_config({"face_match": {"sim_threshold": 5}})
        assert out["face_match"]["sim_threshold"] == 0.45

    def test_face_sim_threshold_boundary_kept(self):
        out = _auto_fill_radix_config({"face_match": {"sim_threshold": 0.2}})
        assert out["face_match"]["sim_threshold"] == 0.2

    def test_face_max_faces_out_of_range(self):
        out = _auto_fill_radix_config({"face_match": {"max_faces_per_frame": 0}})
        assert out["face_match"]["max_faces_per_frame"] == 4

    def test_face_max_faces_valid_kept(self):
        out = _auto_fill_radix_config({"face_match": {"max_faces_per_frame": 8}})
        assert out["face_match"]["max_faces_per_frame"] == 8

    def test_filter_context_messages_out_of_range(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"filter_context_messages": 99}})
        assert out["vision_enhanced"]["filter_context_messages"] == 6

    def test_filter_context_messages_boundary_kept(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"filter_context_messages": 20}})
        assert out["vision_enhanced"]["filter_context_messages"] == 20

    def test_filter_context_messages_non_int_fallback(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"filter_context_messages": "many"}})
        assert out["vision_enhanced"]["filter_context_messages"] == 6

    def test_filter_timeout_out_of_range(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"filter_timeout_seconds": 1}})
        assert out["vision_enhanced"]["filter_timeout_seconds"] == 8.0

    def test_filter_timeout_valid_kept(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"filter_timeout_seconds": 30}})
        assert out["vision_enhanced"]["filter_timeout_seconds"] == 30

    def test_filter_fail_mode_invalid_fallback(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"filter_fail_mode": "x"}})
        assert out["vision_enhanced"]["filter_fail_mode"] == "passthrough"

    def test_filter_fail_mode_valid_kept(self):
        out = _auto_fill_radix_config({"vision_enhanced": {"filter_fail_mode": "discard"}})
        assert out["vision_enhanced"]["filter_fail_mode"] == "discard"

    def test_auto_fill_then_unified_config(self):
        """auto_fill 钳制后的 dict 经 UnifiedConfig 实例化，全部回退默认值生效。"""
        merged = _auto_fill_radix_config({
            "vision_enhanced": {"filter_context_messages": 99, "filter_fail_mode": "x"},
            "face_match": {"provider": "oops", "sim_threshold": 5, "max_faces_per_frame": 99},
        })
        c = UnifiedConfig(**merged)
        assert c.vision_enhanced.filter_context_messages == 6
        assert c.vision_enhanced.filter_fail_mode == "passthrough"
        assert c.face_match.provider == "local"
        assert c.face_match.sim_threshold == 0.45
        assert c.face_match.max_faces_per_frame == 4
