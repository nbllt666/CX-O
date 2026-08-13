"""统一 Qwen3 TTS 迁移——Task 1 契约自检测试。

校验 public/ 下的统一 Qwen3 TTS 三层契约（spec `unify-qwen3-tts-migration`
Task 1 冻结决策，抽象层冻结）：
- 6 份 JSON 数据契约 + 1 份配置契约 + 1 份错误码枚举为合法 JSON Schema；
- 必填字段存在、默认值正确、采样率一致性（合成链路 const 24000，asset 输入范围）；
- 参考音频资产双来源（prompt/file）shape 一致；
- 4 份 .pyi 接口存根存在且声明关键签名与异常；
- 错误码枚举与 .pyi 异常类逐一对应。

运行：python -m pytest tests/test_contracts_qwen3_tts.py -q
"""
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

# 契约目录（public/ 公共契约区）：c:\CX-O\public\
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"

SCHEMA_FILES = {
    "request": "schema/speech_synthesis_request.schema.json",
    "response": "schema/speech_synthesis_response.schema.json",
    "chunk": "schema/speech_audio_chunk.schema.json",
    "asset": "schema/ref_audio_asset.schema.json",
    "emotion": "schema/emotion_instruction.schema.json",
    "error_codes": "schema/qwen3_tts_error_codes.json",
    "config": "config_template/qwen3_tts_config.schema.json",
}

STUBS = {
    "provider": "interface_stub/qwen3_tts_provider.pyi",
    "ref_audio_store": "interface_stub/ref_audio_store.pyi",
    "emotion_service": "interface_stub/emotion_instruction_service.pyi",
    "orchestrator": "interface_stub/speech_orchestrator.pyi",
}

# 与冻结决策一致的统一错误码枚举（qwen3_tts_error_codes.json 须覆盖）
EXPECTED_ERROR_CODES = {
    "INVALID_REQUEST",
    "INVALID_REF_AUDIO",
    "REF_AUDIO_NOT_FOUND",
    "EMOTION_INSTRUCTION_INVALID",
    "RUNTIME_UNAVAILABLE",
    "RUNTIME_UNSUPPORTED",
    "STREAM_ABORTED",
    "LEGACY_ENGINE_REMOVED",
    "SYSTEM_ERROR",
}

# 与 error codes 一一对应的 .pyi 异常类
EXPECTED_EXCEPTION_CLASSES = {
    "InvalidRequestError",
    "InvalidRefAudioError",
    "RefAudioNotFoundError",
    "EmotionInstructionInvalidError",
    "RuntimeUnavailableError",
    "RuntimeUnsupportedError",
    "StreamAbortedError",
    "LegacyEngineRemovedError",
    "SystemError",
}

# 合成链路统一的固定输出采样率；asset 为输入采样率范围
SYNTH_SAMPLE_RATE = 24000
ASSET_SAMPLE_RATE_MIN = 8000
ASSET_SAMPLE_RATE_MAX = 48000


def _load(name: str) -> dict:
    rel = SCHEMA_FILES[name]
    path = PUBLIC_DIR / rel
    assert path.exists(), f"契约文件缺失: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _stub_text(name: str) -> str:
    path = PUBLIC_DIR / STUBS[name]
    assert path.exists(), f"接口存根缺失: {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def request_schema() -> dict:
    return _load("request")


@pytest.fixture(scope="module")
def response_schema() -> dict:
    return _load("response")


@pytest.fixture(scope="module")
def chunk_schema() -> dict:
    return _load("chunk")


@pytest.fixture(scope="module")
def asset_schema() -> dict:
    return _load("asset")


@pytest.fixture(scope="module")
def emotion_schema() -> dict:
    return _load("emotion")


@pytest.fixture(scope="module")
def error_codes() -> dict:
    return _load("error_codes")


@pytest.fixture(scope="module")
def config_schema() -> dict:
    return _load("config")


# ================================================================ 合法 JSON Schema
class TestSchemasAreValid:
    @pytest.mark.parametrize("name", list(SCHEMA_FILES.keys()))
    def test_schema_is_valid_json_schema(self, name):
        doc = _load(name)
        Draft7Validator.check_schema(doc)

    @pytest.mark.parametrize("name", ["request", "response", "chunk", "asset", "emotion", "error_codes", "config"])
    def test_schema_can_instantiate_validator(self, name):
        Draft7Validator(_load(name))


# ================================================================ 必填字段
class TestRequiredFields:
    def test_request_requires_text(self, request_schema):
        assert "text" in request_schema["required"], "speech_synthesis_request 缺少必填 text"

    def test_response_required_fields(self, response_schema):
        required = {"audio", "format", "sample_rate", "runtime"}
        assert required <= set(response_schema["required"]), (
            f"speech_synthesis_response 缺少必填字段: {required - set(response_schema['required'])}"
        )

    def test_asset_required_fields(self, asset_schema):
        required = {"id", "source", "checksum", "status", "created_at"}
        assert required <= set(asset_schema["required"]), (
            f"ref_audio_asset 缺少必填字段: {required - set(asset_schema['required'])}"
        )

    def test_emotion_required_fields(self, emotion_schema):
        required = {"text", "neutral"}
        assert required <= set(emotion_schema["required"]), (
            f"emotion_instruction 缺少必填字段: {required - set(emotion_schema['required'])}"
        )

    def test_error_code_item_required_fields(self, error_codes):
        items = error_codes["codes"]
        assert items, "qwen3_tts_error_codes 的 codes 列表为空"
        for item in items:
            assert {"code", "message", "http_status"} <= set(item.keys()), (
                f"错误码 {item} 缺少 code/message/http_status"
            )

    def test_config_required_fields(self, config_schema):
        required = {"enabled", "runtime"}
        assert required <= set(config_schema["required"]), (
            f"qwen3_tts_config 缺少必填字段: {required - set(config_schema['required'])}"
        )


# ================================================================ 采样率一致性
class TestSampleRateConsistency:
    def test_synthesis_link_all_const_24000(self, request_schema, response_schema, chunk_schema, config_schema):
        # 合成链路 request/response/chunk/config.vllm 全部 const 24000
        assert request_schema["properties"]["sample_rate"]["const"] == SYNTH_SAMPLE_RATE
        assert response_schema["properties"]["sample_rate"]["const"] == SYNTH_SAMPLE_RATE
        assert chunk_schema["properties"]["sample_rate"]["const"] == SYNTH_SAMPLE_RATE
        assert config_schema["properties"]["vllm"]["properties"]["sample_rate"]["const"] == SYNTH_SAMPLE_RATE

    def test_asset_input_sample_rate_is_range(self, asset_schema):
        # asset 为输入采样率范围 [8000,48000]，非 const
        sr = asset_schema["properties"]["sample_rate"]
        assert "const" not in sr
        assert sr["minimum"] == ASSET_SAMPLE_RATE_MIN
        assert sr["maximum"] == ASSET_SAMPLE_RATE_MAX


# ================================================================ 参考音频资产双来源
class TestRefAudioAssetDualSource:
    def test_source_enum_has_prompt_and_file(self, asset_schema):
        enum = set(asset_schema["properties"]["source"]["enum"])
        assert {"prompt", "file"} <= enum

    def test_asset_id_pattern_matches_request_refs(self, asset_schema, request_schema):
        # 命名一致性：asset.id 与 request.refs[] 使用相同 pattern
        asset_pattern = asset_schema["properties"]["id"]["pattern"]
        refs_pattern = request_schema["properties"]["refs"]["items"]["pattern"]
        assert asset_pattern == refs_pattern == "^ref_[a-zA-Z0-9_-]+$"

    def test_request_refs_present(self, request_schema):
        assert "refs" in request_schema["properties"]
        assert request_schema["properties"]["refs"]["items"]["type"] == "string"


# ================================================================ 情感指令
class TestEmotionInstruction:
    def test_emotion_has_neutral_fallback(self, emotion_schema):
        assert emotion_schema["properties"]["neutral"]["default"] is False
        assert emotion_schema["required"] == ["text", "neutral"]

    def test_no_legacy_marker_in_text(self, emotion_schema):
        # 情感指令不做旧标签规范，但 text 字段明确定义为自然语言表达
        assert emotion_schema["properties"]["text"]["type"] == "string"

    def test_request_embeds_instruction_subset(self, request_schema):
        # request 内嵌 emotionInstruction 为降维投影：required 仅 text
        inst = request_schema["definitions"]["emotionInstruction"]
        assert inst["required"] == ["text"]
        assert {"text", "intensity", "confidence", "neutral"} <= set(inst["properties"].keys())


# ================================================================ 错误码与异常契约
class TestErrorCodeConsistency:
    def test_expected_codes_present(self, error_codes):
        codes = {item["code"] for item in error_codes["codes"]}
        missing = EXPECTED_ERROR_CODES - codes
        assert not missing, f"qwen3_tts_error_codes 缺少错误码: {missing}"

    def test_http_status_mapping_present(self, error_codes):
        for item in error_codes["codes"]:
            assert isinstance(item["http_status"], int)

    def test_legacy_engine_removed_present(self, error_codes):
        codes = {item["code"] for item in error_codes["codes"]}
        assert "LEGACY_ENGINE_REMOVED" in codes, "缺少 LEGACY_ENGINE_REMOVED 错误码（旧引擎移除标记）"


# ================================================================ 接口契约(.pyi)存在性
class TestInterfaceStub:
    def test_provider_stub(self):
        text = _stub_text("provider")
        for sig in ("def synthesize(", "def synthesize_stream(", "def health_check(", "def close("):
            assert sig in text, f"qwen3_tts_provider.pyi 缺少签名 {sig}"
        for exc in EXPECTED_EXCEPTION_CLASSES:
            assert exc in text, f"qwen3_tts_provider.pyi 缺少异常类 {exc}"

    def test_ref_audio_store_stub(self):
        text = _stub_text("ref_audio_store")
        for sig in (
            "def register_from_prompt(", "def register_from_file(", "def resolve(",
            "def list(", "def update_note(", "def delete(", "def exists(",
            "def set_current(", "def get_current(", "def clear_current(",
        ):
            assert sig in text, f"ref_audio_store.pyi 缺少签名 {sig}"
        for exc in ("InvalidRefAudioError", "RefAudioNotFoundError"):
            assert exc in text, f"ref_audio_store.pyi 缺少异常 {exc}"

    def test_emotion_service_stub(self):
        text = _stub_text("emotion_service")
        for sig in ("def generate_instruction(", "def convert_legacy_marker("):
            assert sig in text, f"emotion_instruction_service.pyi 缺少签名 {sig}"
        assert "EmotionInstructionInvalidError" in text

    def test_orchestrator_stub(self):
        text = _stub_text("orchestrator")
        for sig in (
            "def synthesize_text(", "def synthesize_stream_text(",
            "def interrupt(", "def close(",
        ):
            assert sig in text, f"speech_orchestrator.pyi 缺少签名 {sig}"
        assert "class SpeechOrchestrator" in text