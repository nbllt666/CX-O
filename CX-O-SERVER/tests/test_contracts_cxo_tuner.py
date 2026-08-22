"""CXO-Tuner 统一契约自检测试。

校验 public/ 下 CXO-Tuner 三层契约（spec `cxo-tuner` 冻结）：
- 2 份 JSON 数据契约 + 1 份配置契约（schema 目录）+ 1 份配置模板（config_template 目录）
  为合法 JSON Schema，且两处配置契约保持一致；
- 合法 / 非法样例经 jsonschema.validate 验证：合法通过，缺必填 / 类型错误抛 ValidationError；
- 配置默认值与取值范围正确（anchor_ratio=0.2、scheduler.idle_start=02:00、
  trainer.max_memory_fraction=0.8、online_dpo 默认关闭等）；
- 1 份 .pyi 接口存根存在、可被 ast 解析、声明 __all__ 与关键类名与异常契约。

运行：python -m pytest tests/test_contracts_cxo_tuner.py -q
"""
import ast
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, ValidationError, validate

# 契约目录（public/ 公共契约区）：c:\CX-O\public\
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"

SCHEMA_FILES = {
    "feedback": "schema/cxo_tuner_feedback.schema.json",
    "dpo_dataset": "schema/cxo_tuner_dpo_dataset.schema.json",
    "config": "schema/cxo_tuner_config.schema.json",
}

# config_template 镜像配置契约，须与 schema/config 逐字段一致
CONFIG_TEMPLATE_REL = "config_template/cxo_tuner_config.schema.json"

STUB = "interface_stub/cxo_tuner.pyi"


def _load(rel: str) -> dict:
    path = PUBLIC_DIR / rel
    assert path.exists(), f"契约文件缺失: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _stub_text() -> str:
    path = PUBLIC_DIR / STUB
    assert path.exists(), f"接口存根缺失: {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def feedback_schema() -> dict:
    return _load(SCHEMA_FILES["feedback"])


@pytest.fixture(scope="module")
def dpo_schema() -> dict:
    return _load(SCHEMA_FILES["dpo_dataset"])


@pytest.fixture(scope="module")
def config_schema() -> dict:
    return _load(SCHEMA_FILES["config"])


@pytest.fixture(scope="module")
def config_template_schema() -> dict:
    return _load(CONFIG_TEMPLATE_REL)


# ================================================================ 合法 JSON Schema
class TestSchemasAreValid:
    @pytest.mark.parametrize("name", list(SCHEMA_FILES.keys()) + ["config_template"])
    def test_schema_is_valid_json_schema(self, name):
        rel = CONFIG_TEMPLATE_REL if name == "config_template" else SCHEMA_FILES[name]
        Draft7Validator.check_schema(_load(rel))

    @pytest.mark.parametrize("name", list(SCHEMA_FILES.keys()))
    def test_schema_can_instantiate_validator(self, name):
        Draft7Validator(_load(SCHEMA_FILES[name]))


# ================================================================ config 与 config_template 一致性
class TestConfigMirrorConsistency:
    def test_config_and_template_same_properties(self, config_schema, config_template_schema):
        assert config_schema["properties"] == config_template_schema["properties"]
        assert config_schema["required"] == config_template_schema["required"]


# ================================================================ 必填字段
class TestRequiredFields:
    def test_feedback_required_fields(self, feedback_schema):
        required = {"prompt", "response_chosen", "response_rejected", "source", "timestamp"}
        assert required <= set(feedback_schema["required"]), (
            f"cxo_tuner_feedback 缺少必填字段: {required - set(feedback_schema['required'])}"
        )

    def test_feedback_source_enum(self, feedback_schema):
        enum = set(feedback_schema["properties"]["source"]["enum"])
        assert {"live_danmaku", "judge", "distillation"} == enum

    def test_dpo_required_fields(self, dpo_schema):
        required = {"id", "prompt", "chosen", "rejected", "source", "anchor", "created_at"}
        assert required <= set(dpo_schema["required"]), (
            f"cxo_tuner_dpo_dataset 缺少必填字段: {required - set(dpo_schema['required'])}"
        )

    def test_additional_properties_closed(self, feedback_schema):
        # root 明确声明 additionalProperties=false（单条记录契约）
        assert feedback_schema.get("additionalProperties") is False


# ================================================================ 合法 / 非法样例校验
class TestFeedbackValidation:
    def test_valid_feedback_passes(self, feedback_schema):
        sample = {
            "prompt": "hello",
            "response_chosen": "good answer",
            "response_rejected": "bad answer",
            "source": "live_danmaku",
            "timestamp": "2026-08-22T02:00:00Z",
            "session_id": "s1",
            "quality_score": 0.8,
            "metadata": {"sentiment": "positive", "keywords": ["greeting"], "scene_type": "chat"},
        }
        validate(instance=sample, schema=feedback_schema)

    def test_extra_root_field_rejected(self, feedback_schema):
        sample = {
            "prompt": "hello",
            "response_chosen": "good answer",
            "response_rejected": "bad answer",
            "source": "judge",
            "timestamp": "2026-08-22T02:00:00Z",
            "unexpected_field": 1,
        }
        with pytest.raises(ValidationError):
            validate(instance=sample, schema=feedback_schema)

    def test_missing_required_field_raises(self, feedback_schema):
        sample = {
            "prompt": "hello",
            "response_chosen": "good answer",
            # response_rejected 缺失
            "source": "judge",
            "timestamp": "2026-08-22T02:00:00Z",
        }
        with pytest.raises(ValidationError):
            validate(instance=sample, schema=feedback_schema)

    def test_bad_type_raises(self, feedback_schema):
        sample = {
            "prompt": "hello",
            "response_chosen": "good answer",
            "response_rejected": "bad answer",
            "source": "judge",
            "timestamp": "2026-08-22T02:00:00Z",
            "quality_score": "high",  # 类型错误：应为 number
        }
        with pytest.raises(ValidationError):
            validate(instance=sample, schema=feedback_schema)

    def test_bad_enum_raises(self, feedback_schema):
        sample = {
            "prompt": "hello",
            "response_chosen": "good answer",
            "response_rejected": "bad answer",
            "source": "unknown_source",  # 非法枚举
            "timestamp": "2026-08-22T02:00:00Z",
        }
        with pytest.raises(ValidationError):
            validate(instance=sample, schema=feedback_schema)

    def test_quality_score_out_of_range_raises(self, feedback_schema):
        sample = {
            "prompt": "hello",
            "response_chosen": "good answer",
            "response_rejected": "bad answer",
            "source": "judge",
            "timestamp": "2026-08-22T02:00:00Z",
            "quality_score": 1.5,  # 越界（>1）
        }
        with pytest.raises(ValidationError):
            validate(instance=sample, schema=feedback_schema)


class TestDpoDatasetValidation:
    def test_valid_dpo_record_passes(self, dpo_schema):
        sample = {
            "id": "dpo_001",
            "prompt": "hello",
            "chosen": "good answer",
            "rejected": "bad answer",
            "source": "judge",
            "anchor": True,
            "created_at": "2026-08-22T02:00:00Z",
            "anchor_ratio": 0.2,
            "session_id": "s1",
            "judge_model": "qwen3-judge",
            "metadata": {"scene_type": "distillation"},
        }
        validate(instance=sample, schema=dpo_schema)

    def test_missing_anchor_raises(self, dpo_schema):
        sample = {
            "id": "dpo_002",
            "prompt": "hello",
            "chosen": "good answer",
            "rejected": "bad answer",
            "source": "judge",
            # anchor 缺失
            "created_at": "2026-08-22T02:00:00Z",
        }
        with pytest.raises(ValidationError):
            validate(instance=sample, schema=dpo_schema)

    def test_bad_source_raises(self, dpo_schema):
        sample = {
            "id": "dpo_003",
            "prompt": "hello",
            "chosen": "good answer",
            "rejected": "bad answer",
            "source": "web",  # 非法枚举
            "anchor": False,
            "created_at": "2026-08-22T02:00:00Z",
        }
        with pytest.raises(ValidationError):
            validate(instance=sample, schema=dpo_schema)


# ================================================================ 配置默认值 / 取值范围
class TestConfigDefaults:
    def test_anchor_ratio_default(self, config_schema):
        assert config_schema["properties"]["anchor_ratio"]["default"] == 0.2
        assert config_schema["properties"]["anchor_ratio"]["minimum"] == 0
        assert config_schema["properties"]["anchor_ratio"]["maximum"] == 1

    def test_trainer_max_memory_default(self, config_schema):
        trainer = config_schema["properties"]["trainer"]["properties"]
        assert trainer["max_memory_fraction"]["default"] == 0.8
        assert trainer["max_memory_fraction"]["maximum"] == 1

    def test_trainer_cuda_devices_default_empty(self, config_schema):
        trainer = config_schema["properties"]["trainer"]["properties"]
        assert trainer["CUDA_VISIBLE_DEVICES"]["default"] == ""

    def test_scheduler_defaults(self, config_schema):
        scheduler = config_schema["properties"]["scheduler"]["properties"]
        assert scheduler["enabled"]["default"] is True
        assert scheduler["idle_start"]["default"] == "02:00"
        assert scheduler["idle_end"]["default"] == "05:00"
        assert scheduler["min_dataset_size"]["default"] == 100

    def test_online_dpo_defaults(self, config_schema):
        online_dpo = config_schema["properties"]["online_dpo"]["properties"]
        assert online_dpo["enabled"]["default"] is False
        assert online_dpo["max_lr"]["default"] == 0.000001  # 1e-6

    def test_vllm_lora_disabled_by_default(self, config_schema):
        assert config_schema["properties"]["vllm_lora_enabled"]["default"] is False

    def test_config_valid_document_passes(self, config_schema):
        defaults = {
            "judge_model": "qwen3-judge",
            "base_model": "qwen3-7b",
            "trainer": {"CUDA_VISIBLE_DEVICES": "", "max_memory_fraction": 0.8},
            "scheduler": {"enabled": True, "idle_start": "02:00", "idle_end": "05:00", "min_dataset_size": 100},
            "online_dpo": {"enabled": False, "max_lr": 1e-6},
            "dataset_dir": "/data/ds",
            "lora_dir": "/data/lora",
            "vllm_url": "http://127.0.0.1:8091",
        }
        # 缺省/默认字段可被自动补齐：仅提供最小必填集也应通过校验
        validate(instance={**defaults, "anchor_ratio": 0.2, "vllm_lora_enabled": False}, schema=config_schema)


# ================================================================ 接口契约(.pyi)
class TestCXOTunerStub:
    def test_stub_parses_and_declares_all(self):
        text = _stub_text()
        ast.parse(text)  # 可被 ast 解析
        assert "__all__" in text, "cxo_tuner.pyi 缺少 __all__"

    def test_key_classes_present(self):
        text = _stub_text()
        for cls in (
            "class FeedbackIn",
            "class FeedbackResponse",
            "class DatasetStats",
            "class TrainTriggerRequest",
            "class TrainStatus",
            "class AdapterInfo",
            "class ApplyAdapterResponse",
            "class CXOTunerAPI",
        ):
            assert cls in text, f"cxo_tuner.pyi 缺少 {cls}"

    def test_api_methods_present(self):
        text = _stub_text()
        for sig in (
            "def health(",
            "def submit_feedback(",
            "def get_dataset_stats(",
            "def trigger_train(",
            "def get_train_status(",
            "def list_adapters(",
            "def delete_adapter(",
            "def apply_adapter(",
        ):
            assert sig in text, f"cxo_tuner.pyi 缺少签名 {sig}"

    def test_exception_contract_present(self):
        text = _stub_text()
        for exc in ("ConnectionError_503", "ValueError_422", "RuntimeError_500"):
            assert exc in text, f"cxo_tuner.pyi 缺少异常契约 {exc}"

    def test_status_enum_documented(self):
        text = _stub_text()
        assert "idle / running / completed / failed" in text