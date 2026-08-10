"""server.core.multimodal.multimodal_pipeline (MultimodalPipeline) 单元测试。

通过注入显式 config + mock worker 实现，隔离外部依赖（PaddleOCR / vLLM HTTP /
配置模板 / server.config），覆盖：
配置合并优先级与 auto_fill、模板默认值提取与降级、provider 检测、
preprocess 参数校验、模态分发路由、文本/角色卡装配、
图片 vision 降级、vLLM 原生视频/音频 decision 与降级、artifact 装配。

运行：python -m pytest tests/test_multimodal_pipeline.py -v
"""
from types import SimpleNamespace

import pytest

from server.core.multimodal.multimodal_pipeline import (
    MultimodalArtifact,
    MultimodalPipeline,
    OCRBlock,
    CharacterCardFields,
)


def _make_pipeline(monkeypatch, config=None):
    """构造隔离的 pipeline。显式 config 拥有最高优先级，覆盖模板/实例配置。"""
    cfg = {
        "worker_pool_size": 2,
        "task_timeout_seconds": 120,
        "enabled_modalities": ["text", "character_card", "image", "video", "audio"],
        "ocr_language": "ch",
        "vision_model": "test-vision",
    }
    if config:
        cfg.update(config)
    pipeline = MultimodalPipeline(config=cfg)
    # 关闭线程池，避免测试结束后 atexit 干扰
    pipeline._executor.shutdown(wait=False, cancel_futures=True)
    return pipeline


# ================================================================ 配置合并
class TestConfigMerge:
    def test_merge_nested_flat_and_vllm(self):
        target = {"worker_pool_size": 4, "vllm_base_url": "x"}
        source = {
            "multimodal_pipeline": {"worker_pool_size": 8, "ocr_language": "en"},
            "vllm": {"base_url": "http://v:8000", "timeout_seconds": 60},
            "task_timeout_seconds": 30,
        }
        MultimodalPipeline._merge_nested_config(target, source)
        assert target["worker_pool_size"] == 8
        assert target["ocr_language"] == "en"
        assert target["vllm_base_url"] == "http://v:8000"
        assert target["vision_timeout_seconds"] == 60
        assert target["vllm_timeout_seconds"] == 60

    def test_explicit_config_beats_defaults(self, monkeypatch):
        p = _make_pipeline(monkeypatch, {"worker_pool_size": 7})
        assert p._worker_pool_size == 7
        assert p._ocr_language == "ch"

    def test_auto_fill_missing_fields(self, monkeypatch):
        p = _make_pipeline(monkeypatch, {"worker_pool_size": 3})
        # 未显式传入的字段应自动补齐 jsonschema 默认值
        assert p._task_timeout == 120
        assert p._vllm_native_enabled is True
        assert p._vllm_base_url != ""

    def test_extract_defaults_from_template_missing_file(self, monkeypatch):
        monkeypatch.setattr(
            "server.core.multimodal.multimodal_pipeline._CONFIG_TEMPLATE_PATH",
            "/nonexistent/radix_config.json",
        )
        assert MultimodalPipeline._extract_defaults_from_template() == {}

    def test_load_server_config_no_settings(self, monkeypatch):
        monkeypatch.setattr(
            MultimodalPipeline, "_load_server_config", staticmethod(lambda: None)
        )
        assert MultimodalPipeline._load_server_config() is None

    def test_load_instance_config_missing(self, monkeypatch):
        monkeypatch.setattr(
            "server.core.multimodal.multimodal_pipeline._SERVER_ROOT", "/nonexistent"
        )
        monkeypatch.setattr(
            "server.core.multimodal.multimodal_pipeline._PUBLIC_CONFIG_TEMPLATE_DIR",
            "/nonexistent",
        )
        # 候选路径均不存在 → 返回 None
        assert MultimodalPipeline._load_instance_config() is None


class TestProvider:
    def test_get_llm_provider_unknown_when_no_settings(self, monkeypatch):
        monkeypatch.setattr(
            MultimodalPipeline, "_get_llm_provider", staticmethod(lambda: "unknown")
        )
        assert MultimodalPipeline._get_llm_provider() == "unknown"


# ================================================================ artifact 装配
class TestBuildArtifact:
    def test_build_artifact_defaults(self):
        a = MultimodalPipeline._build_artifact(
            "text", "src", {"text_content": "hi"}
        )
        assert isinstance(a, MultimodalArtifact)
        assert a.type == "text"
        assert a.text_content == "hi"
        assert a.native_decode_used is False
        assert a.vision_degraded is False
        assert a.confidence == 1.0
        assert a.extra_metadata == {}
        assert a.created_at

    def test_build_artifact_extracts_native_flag(self):
        a = MultimodalPipeline._build_artifact(
            "video", "v.mp4",
            {"text_content": "desc", "native_decode_used": True,
             "vision_degraded": True, "confidence": 0.88},
        )
        assert a.native_decode_used is True
        assert a.vision_degraded is True
        assert a.confidence == 0.88


# ================================================================ preprocess 校验
class TestPreprocessValidation:
    def test_unsupported_source_type(self, monkeypatch):
        p = _make_pipeline(monkeypatch)
        with pytest.raises(ValueError):
            p.preprocess("unknown_type", "x")

    def test_empty_source_ref(self, monkeypatch):
        p = _make_pipeline(monkeypatch)
        with pytest.raises(ValueError):
            p.preprocess("text", "")

    def test_disabled_modality(self, monkeypatch):
        p = _make_pipeline(monkeypatch, {"enabled_modalities": ["text"]})
        with pytest.raises(ValueError):
            p.preprocess("image", "img.png")


# ================================================================ 分发路由
class TestDispatch:
    def test_dispatch_text(self, monkeypatch):
        p = _make_pipeline(monkeypatch)
        p._text_worker_impl = SimpleNamespace(
            process=lambda ref: {"text_content": f"加工:{ref}"}
        )
        a = p._dispatch("text", "hello")
        assert a.type == "text"
        assert a.text_content == "加工:hello"

    def test_dispatch_character_card(self, monkeypatch):
        p = _make_pipeline(monkeypatch)
        p._character_card_worker_impl = SimpleNamespace(
            process=lambda ref: {"text_content": "卡片", "extra_metadata": {"name": "n"}}
        )
        a = p._dispatch("character_card", "card.json")
        assert a.type == "character_card"
        assert a.extra_metadata["name"] == "n"

    def test_dispatch_image(self, monkeypatch):
        p = _make_pipeline(monkeypatch)
        p._image_worker_impl = SimpleNamespace(
            ocr=lambda ref: ([{"text": "OCR", "bbox": [0, 0, 1, 1]}], 0.9),
            vision=lambda ref: "视觉描述",
            merge=lambda blocks, v: {"text_content": v, "extra_metadata": {"blocks": blocks}},
        )
        a = p._dispatch("image", "img.png")
        assert a.type == "image"
        assert a.text_content == "视觉描述"

    def test_dispatch_video_routes_to_vllm_native(self, monkeypatch):
        p = _make_pipeline(monkeypatch)
        p._vllm_native_worker_impl = SimpleNamespace(
            process=lambda **kw: {"text_content": "native", "native_decode_used": True,
                                  "vision_degraded": False, "confidence": 0.88}
        )
        monkeypatch.setattr(
            MultimodalPipeline, "_get_llm_provider", staticmethod(lambda: "vllm")
        )
        a = p._dispatch("video", "v.mp4")
        assert a.type == "video"
        assert a.native_decode_used is True


class TestDispatchImageVisionDegrade:
    def test_vision_connection_error_degrades(self, monkeypatch):
        p = _make_pipeline(monkeypatch)

        class _Impl:
            def ocr(self, ref):
                return ([{"text": "t", "bbox": [0, 0, 1, 1]}], 0.9)

            def vision(self, ref):
                raise ConnectionError("vLLM 不可达")

            def merge(self, blocks, v):
                return {"text_content": "OCR only", "extra_metadata": {"blocks": blocks},
                        "vision_degraded": True, "confidence": 0.7}

        p._image_worker_impl = _Impl()
        a = p._dispatch("image", "img.png")
        assert a.vision_degraded is True
        assert a.text_content == "OCR only"


# ================================================================ vLLM 原生
class TestVLLMNativeWorker:
    def test_invalid_modality(self, monkeypatch):
        p = _make_pipeline(monkeypatch)
        with pytest.raises(ValueError):
            p._vllm_native_worker("x", "text")

    def test_non_vllm_provider_degrades(self, monkeypatch):
        p = _make_pipeline(monkeypatch)
        p._vllm_native_worker_impl = SimpleNamespace(
            process=lambda **kw: {
                "text_content": "降级提示", "native_decode_used": False,
                "vision_degraded": True, "confidence": 0.5,
            }
        )
        monkeypatch.setattr(
            MultimodalPipeline, "_get_llm_provider", staticmethod(lambda: "ollama")
        )
        a = p._vllm_native_worker("v.mp4", "video")
        assert a.native_decode_used is False
        assert a.vision_degraded is True
        assert a.confidence == 0.5

    def test_vllm_provider_native_path(self, monkeypatch):
        p = _make_pipeline(monkeypatch)
        p._vllm_native_worker_impl = SimpleNamespace(
            process=lambda **kw: {
                "text_content": "native desc", "native_decode_used": True,
                "vision_degraded": False, "confidence": 0.88,
            }
        )
        monkeypatch.setattr(
            MultimodalPipeline, "_get_llm_provider", staticmethod(lambda: "vllm")
        )
        a = p._vllm_native_worker("v.mp4", "video")
        assert a.native_decode_used is True
        assert a.vision_degraded is False
        assert a.confidence == 0.88

    def test_vllm_native_disabled_degrades(self, monkeypatch):
        p = _make_pipeline(monkeypatch, {"vllm_native_enabled": False})
        p._vllm_native_worker_impl = SimpleNamespace(
            process=lambda **kw: {
                "text_content": "disabled", "native_decode_used": False,
                "vision_degraded": True, "confidence": 0.5,
            }
        )
        monkeypatch.setattr(
            MultimodalPipeline, "_get_llm_provider", staticmethod(lambda: "vllm")
        )
        a = p._vllm_native_worker("a.wav", "audio")
        assert a.native_decode_used is False
        assert a.vision_degraded is True


# ================================================================ 数据模型
class TestDataModels:
    def test_artifact_defaults(self):
        a = MultimodalArtifact(
            artifact_id="1", type="text", source="s", text_content="c",
            created_at="2026-08-07T00:00:00+00:00",
        )
        assert a.native_decode_used is False
        assert a.confidence == 1.0
        assert a.extra_metadata == {}

    def test_ocr_block(self):
        b = OCRBlock(text="t", bbox=[0, 1, 2, 3])
        assert b.bbox == [0, 1, 2, 3]

    def test_character_card_fields_defaults(self):
        f = CharacterCardFields(name="n")
        assert f.description == ""
        assert f.personality == ""