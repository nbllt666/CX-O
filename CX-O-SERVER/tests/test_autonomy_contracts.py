"""CX-O-Autonomy 三层契约自检测试。

校验 public/ 下 CX-O-Autonomy 三层契约：
- public/schema/ 下全部 autonomy_*.schema.json 均为合法 draft-07 JSON Schema，可实例化校验器；
- 每个 schema 的最小合法实例（含默认值语义）经 jsonschema.validate 通过；
- autonomy_action：合法 action 通过，非法 action（如 delete_content）失败，缺 action 失败；
- autonomy_config：无 required，缺 enabled 的核心字段子集实例可通过（自动补齐语义）；
- autonomy_state：status 枚举非法值失败；
- public/interface_stub/cxo_autonomy.pyi 可被 ast 解析，声明错误码/异常契约与关键接口签名。

运行：python -m pytest tests/test_autonomy_contracts.py -q
"""
import ast
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, ValidationError, validate

# 契约目录（public/ 公共契约区）：c:\CX-O\public\
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"

SCHEMA_DIR = PUBLIC_DIR / "schema"
SCHEMA_FILES = sorted(SCHEMA_DIR.glob("autonomy_*.schema.json"))

STUB = "interface_stub/cxo_autonomy.pyi"


def _load_schema(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _stub_text() -> str:
    path = PUBLIC_DIR / STUB
    assert path.exists(), f"接口存根缺失: {path}"
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def schemas() -> dict:
    return {p.name: _load_schema(p) for p in SCHEMA_FILES}


@pytest.fixture(scope="module")
def config_schema(schemas) -> dict:
    return schemas["autonomy_config.schema.json"]


@pytest.fixture(scope="module")
def action_schema(schemas) -> dict:
    return schemas["autonomy_action.schema.json"]


@pytest.fixture(scope="module")
def audit_schema(schemas) -> dict:
    return schemas["autonomy_audit.schema.json"]


@pytest.fixture(scope="module")
def state_schema(schemas) -> dict:
    return schemas["autonomy_state.schema.json"]


# ================================================================ 合法 JSON Schema
class TestSchemasAreValid:
    @pytest.mark.parametrize("name", [p.name for p in SCHEMA_FILES])
    def test_schema_is_valid_draft07(self, schemas, name):
        Draft7Validator.check_schema(schemas[name])

    @pytest.mark.parametrize("name", [p.name for p in SCHEMA_FILES])
    def test_schema_can_instantiate_validator(self, schemas, name):
        Draft7Validator(schemas[name])


# ================================================================ 最小合法实例（含默认值语义）
class TestMinimalValidInstances:
    def test_config_minimal_valid(self, config_schema):
        sample = {
            "enabled": True,
            "auto_start": False,
            "loop_interval_minutes": 30,
            "rss_sources": ["https://example.com/feed.xml"],
            "search": {"mcp_server_name": "free-search-mcp", "fallback_rss": True},
            "schedule": {
                "wake_time": "08:00", "sleep_time": "02:00",
                "golden_start": "19:00", "golden_end": "23:00",
                "diary_time": "02:00", "quiet_windows": ["12:00-13:00"],
            },
            "budget": {
                "daily_token_limit": 2000000, "daily_llm_calls_limit": 0,
                "cost_alert_threshold": 0.8, "overspend_mode": "sleep",
            },
            "platforms": ["weibo", "x"],
            "permissions": {
                "allowed_actions": [
                    "sleep", "wait", "read_news", "search", "write_memory",
                    "write_post", "start_live", "stop_live", "write_diary",
                ],
                "blocked_actions": [],
            },
            "safety": {
                "content_gate_enabled": True, "persona_check_enabled": True,
                "post_rate_per_hour": 5, "user_online_sleep": True,
                "leave_mode_authorize": True,
            },
            "store_path": "",
        }
        validate(instance=sample, schema=config_schema)

    def test_action_minimal_valid(self, action_schema):
        sample = {
            "action": "search", "target": "AI 新闻",
            "payload": {"query": "AI"}, "reason": "获取信息",
            "expected_outcome": "获得摘要",
        }
        validate(instance=sample, schema=action_schema)

    def test_audit_minimal_valid(self, audit_schema):
        sample = {
            "timestamp": "2026-08-22T02:00:00Z",
            "motivations": {"curiosity": 0.3, "social_need": 0.2,
                            "creative_drive": 0.4, "fatigue": 0.1},
            "action": "write_memory", "target": "今日见闻",
            "payload": {"content": "..."}, "result": "success", "error": None,
            "cost_tokens": 120, "trigger_reason": "日常记录",
            "expected_outcome": "记忆已写入",
        }
        validate(instance=sample, schema=audit_schema)

    def test_state_minimal_valid(self, state_schema):
        sample = {
            "motivations": {"curiosity": 0.3, "social_need": 0.2,
                            "creative_drive": 0.4, "fatigue": 0.1},
            "status": "running", "last_action": "read_news",
            "last_cycle_at": "2026-08-22T02:00:00Z",
            "daily_budget_used_tokens": 1000, "budget_reset_date": "2026-08-22",
            "diary_last_at": "2026-08-21T02:00:00Z",
        }
        validate(instance=sample, schema=state_schema)


# ================================================================ autonomy_action 契约
class TestAutonomyActionContract:
    def test_valid_action_passes(self, action_schema):
        validate(instance={"action": "write_post", "target": "weibo"}, schema=action_schema)

    def test_invalid_action_fails(self, action_schema):
        with pytest.raises(ValidationError):
            validate(instance={"action": "delete_content"}, schema=action_schema)

    def test_missing_action_fails(self, action_schema):
        with pytest.raises(ValidationError):
            validate(instance={"target": "weibo"}, schema=action_schema)


# ================================================================ autonomy_config 契约
class TestAutonomyConfigContract:
    def test_missing_enabled_passes_no_required(self, config_schema):
        # 无 required：仅填核心字段子集即可通过，缺 enabled 不报错（auto_fill 补齐语义）
        sample = {"loop_interval_minutes": 15, "platforms": ["weibo"]}
        validate(instance=sample, schema=config_schema)

    def test_empty_object_passes(self, config_schema):
        # additionalProperties=false 且无 required：空对象合法（全部字段可自动补齐）
        validate(instance={}, schema=config_schema)

    def test_unknown_field_rejected(self, config_schema):
        with pytest.raises(ValidationError):
            validate(instance={"enabled": True, "unknown_field": 1}, schema=config_schema)


# ================================================================ autonomy_state 契约
class TestAutonomyStateContract:
    def test_invalid_status_enum_fails(self, state_schema):
        with pytest.raises(ValidationError):
            validate(instance={"status": "gone_wrong"}, schema=state_schema)

    def test_nullable_last_action_passes(self, state_schema):
        validate(instance={"status": "paused", "last_action": None,
                           "last_cycle_at": None}, schema=state_schema)


# ================================================================ 接口契约 (.pyi)
class TestAutonomyStub:
    def test_stub_parses(self):
        ast.parse(_stub_text())

    def test_error_code_and_exception_contract_present(self):
        text = _stub_text()
        for code in ("AUTONOMY_DISABLED", "AUTONOMY_BUDGET_EXCEEDED",
                     "AUTONOMY_ACTION_BLOCKED", "AUTONOMY_CONTENT_REJECTED",
                     "AUTONOMY_RATE_LIMITED", "AUTONOMY_PLATFORM_NOT_WHITELISTED",
                     "AUTONOMY_PERSIST_ERROR"):
            assert code in text, f"cxo_autonomy.pyi 缺少错误码 {code}"
        for cls in ("class AutonomyError", "class AutonomyDisabledError",
                    "class AutonomyBudgetExceededError", "class AutonomyActionBlockedError",
                    "class AutonomyContentRejectedError", "class AutonomyRateLimitedError",
                    "class AutonomyPlatformNotWhitelistedError", "class AutonomyPersistError"):
            assert cls in text, f"cxo_autonomy.pyi 缺少 {cls}"

    def test_plugin_tool_signatures_present(self):
        text = _stub_text()
        for sig in ("def autonomy_get_status(", "def autonomy_read_news(",
                    "def autonomy_search(", "def autonomy_write_memory(",
                    "def autonomy_retrieve_memory(", "def autonomy_write_post(",
                    "def autonomy_start_live(", "def autonomy_stop_live(",
                    "def autonomy_write_diary("):
            assert sig in text, f"cxo_autonomy.pyi 缺少签名 {sig}"

    def test_rest_endpoint_signatures_present(self):
        text = _stub_text()
        for sig in ("def get_status(", "def control(", "def list_audit(",
                    "def get_config(", "def update_config("):
            assert sig in text, f"cxo_autonomy.pyi 缺少端点签名 {sig}"


# ================================================================ 三层一致性（rules-3 §五）
class TestCrossLayerConsistency:
    """固化 action 枚举 ↔ config.allowed_actions 默认集 ↔ .pyi 工具签名 的一致性。"""

    def test_action_enum_matches_allowed_actions_default(self, action_schema, config_schema):
        action_enum = action_schema["properties"]["action"]["enum"]
        allowed_default = config_schema["properties"]["permissions"]["properties"]["allowed_actions"]["default"]
        assert action_enum == allowed_default, (
            f"action 枚举 {action_enum} 与 allowed_actions 默认集 {allowed_default} 不一致"
        )

    def test_tools_cover_all_actionable_actions(self, action_schema):
        # 动作枚举中 sleep/wait 为引擎内部原语（映射声明见 .pyi），其余 7 项须有对应工具签名
        internal_primitives = {"sleep", "wait"}
        tool_map = {
            "read_news": "def autonomy_read_news(",
            "search": "def autonomy_search(",
            "write_memory": "def autonomy_write_memory(",
            "write_post": "def autonomy_write_post(",
            "start_live": "def autonomy_start_live(",
            "stop_live": "def autonomy_stop_live(",
            "write_diary": "def autonomy_write_diary(",
        }
        text = _stub_text()
        for action in action_schema["properties"]["action"]["enum"]:
            if action in internal_primitives:
                continue
            assert action in tool_map, f"动作 {action} 缺少工具映射声明"
            assert tool_map[action] in text, f"动作 {action} 缺少对应工具签名 {tool_map[action]}"

    def test_error_codes_one_to_one_with_exceptions(self):
        text = _stub_text()
        codes = set(re.findall(r"AUTONOMY_[A-Z_]+", text))
        classes = set(re.findall(r"class (Autonomy\w+Error)", text))
        # 每个错误码应有一个同名异常类（AutonomyPersistError ↔ AUTONOMY_PERSIST_ERROR）
        assert len(codes) == len(classes), f"错误码 {codes} 与异常类 {classes} 数量不一致"
        for code in codes:
            suffix = code[len("AUTONOMY_"):]
            if suffix.endswith("_ERROR"):  # 错误码尾部 _ERROR 对应异常类名尾部 Error
                suffix = suffix[: -len("_ERROR")]
            cls = "Autonomy" + suffix.title().replace("_", "") + "Error"
            assert cls in classes, f"错误码 {code} 缺少对应异常类 {cls}"
