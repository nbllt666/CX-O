"""电脑控制与 CXFC 注册——Task 1 契约自检测试。

校验 public/ 下的电脑控制三层契约与错误码枚举（迁移自
.trae/specs/add-computer-control-cxfc/contracts/）：
- 三个 JSON 契约（computer_control_plugin.schema.json /
  computer_control_config.schema.json / computer_control_error_codes.json）为合法 JSON Schema；
- 必填字段存在；
- 配置默认值正确；
- run_command 护栏字段被 schema 覆盖；
- 三个工具稳定标识与错误码枚举在契约间一致。

运行：python -m pytest tests/test_contracts_computer_control.py -q
"""
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

# 契约目录（public/ 公共契约区）：c:\CX-O\public\
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"

CONTRACTS = {
    "plugin.json": "schema/computer_control_plugin.schema.json",
    "config_schema.json": "config_template/computer_control_config.schema.json",
    "error_codes.json": "schema/computer_control_error_codes.json",
    "plugin_interface.pyi": "interface_stub/computer_control.pyi",
}

# 与 spec.md 冻结决策一致的稳定工具标识
EXPECTED_TOOLS = {
    "computer_screen_control",
    "computer_keyboard_control",
    "computer_run_command",
}

# 与冻结决策一致的错误码枚举（error_codes.json 须覆盖）
EXPECTED_ERROR_CODES = {
    "UNAUTHORIZED",
    "REPLAY_DETECTED",
    "INVALID_ARGUMENT",
    "EXECUTION_FAILED",
    "TIMEOUT",
    "SYSTEM_ERROR",
    "PLUGIN_OFFLINE",
    "NOT_AUTHORIZED",
}

# 冻结决策中明确的默认值
EXPECTED_DEFAULTS = {
    "authorized": False,
    "auto_start": False,
    "run_as_admin": False,
    "run_command.timeout_ms": 30000,
    "run_command.max_output_bytes": 65536,
    "run_command.kill_process_tree": True,
}

# run_command 护栏字段（冻结决策：结构化参数/超时/进程树回收/输出截断/脱敏）
RUN_COMMAND_GUARDS = {
    "timeout_ms",
    "max_output_bytes",
    "max_output_chars",
    "redact_patterns",
    "kill_process_tree",
}


def _load(name: str) -> dict:
    rel = CONTRACTS[name]
    path = PUBLIC_DIR / rel
    assert path.exists(), f"契约文件缺失: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _stub_path() -> Path:
    return PUBLIC_DIR / CONTRACTS["plugin_interface.pyi"]


@pytest.fixture(scope="module")
def plugin() -> dict:
    return _load("plugin.json")


@pytest.fixture(scope="module")
def config() -> dict:
    return _load("config_schema.json")


@pytest.fixture(scope="module")
def error_codes() -> dict:
    return _load("error_codes.json")


# ================================================================ 合法 JSON Schema
class TestSchemasAreValid:
    @pytest.mark.parametrize("name", ["plugin.json", "config_schema.json", "error_codes.json"])
    def test_schema_is_valid_json_schema(self, name):
        doc = _load(name)
        # Draft7Validator.check_schema 对非法 JSON Schema 抛异常
        Draft7Validator.check_schema(doc)

    def test_plugin_can_validate(self, plugin):
        # 以自身为文档实例应能通过（自描述契约无强制实例校验失败）
        Draft7Validator(plugin)

    def test_config_can_validate(self, config):
        Draft7Validator(config)


# ================================================================ 必填字段
class TestRequiredFields:
    def test_plugin_registration_fields(self, plugin):
        required = {
            "name", "version", "host", "port", "capabilities",
            "tools", "token", "tls_cert_fingerprint", "tls_cert_pem",
        }
        assert required <= set(plugin["required"]), (
            f"plugin.json 缺少必填字段: {required - set(plugin['required'])}"
        )

    def test_plugin_has_authorization_field(self, plugin):
        assert "authorized" in plugin["properties"], "plugin.json 缺少授权状态字段 authorized"

    def test_config_required_fields(self, config):
        required = {
            "authorized", "token", "host", "port", "tls_cert_path",
            "tls_fingerprint", "run_command", "auto_start",
            "run_as_admin", "backend_url",
        }
        assert required <= set(config["required"]), (
            f"config_schema.json 缺少必填字段: {required - set(config['required'])}"
        )

    def test_error_code_item_required_fields(self, error_codes):
        items = error_codes["codes"]
        assert items, "error_codes.json 的 codes 列表为空"
        for item in items:
            assert {"code", "message", "http_status"} <= set(item.keys()), (
                f"错误码 {item} 缺少 code/message/http_status"
            )


# ================================================================ 默认值
class TestDefaults:
    def test_top_level_defaults(self, config):
        top = config["default"]
        for key, val in EXPECTED_DEFAULTS.items():
            if "." not in key:
                assert top.get(key) == val, f"配置默认值 {key} 应为 {val}，实际 {top.get(key)}"

    def test_run_command_defaults(self, config):
        rc_default = config["default"]["run_command"]
        assert rc_default["timeout_ms"] == EXPECTED_DEFAULTS["run_command.timeout_ms"]
        assert rc_default["max_output_bytes"] == EXPECTED_DEFAULTS["run_command.max_output_bytes"]
        assert rc_default["kill_process_tree"] is EXPECTED_DEFAULTS["run_command.kill_process_tree"]
        # O-3：脱敏默认应为非空（内置常见敏感模式），使「敏感输出脱敏」默认生效
        assert isinstance(rc_default["redact_patterns"], list)
        assert len(rc_default["redact_patterns"]) > 0, "redact_patterns 默认应为非空（默认脱敏生效）"
        assert rc_default["max_output_chars"] > 0

    def test_authorized_default_false(self, plugin, config):
        assert config["properties"]["authorized"]["default"] is False
        assert plugin["properties"]["authorized"]["default"] is False


# ================================================================ run_command 护栏覆盖
class TestRunCommandGuards:
    def test_config_run_command_guard_fields(self, config):
        rc_schema = config["properties"]["run_command"]["properties"]
        missing = RUN_COMMAND_GUARDS - set(rc_schema.keys())
        assert not missing, f"config_schema.json run_command 缺少护栏字段: {missing}"
        for field in RUN_COMMAND_GUARDS:
            assert "default" in rc_schema[field], f"run_command.{field} 缺少默认值"

    def test_plugin_command_request_guards(self, plugin):
        cmd_req = plugin["definitions"]["command_request"]["properties"]
        for field in {"command", "args", "cwd", "timeout_ms", "env"}:
            assert field in cmd_req, f"command_request 缺少字段 {field}"

    def test_plugin_command_response_guards(self, plugin):
        cmd_resp = plugin["definitions"]["command_response"]["properties"]
        for field in {"exit_code", "stdout", "stderr", "timed_out", "truncated"}:
            assert field in cmd_resp, f"command_response 缺少字段 {field}"


# ================================================================ 工具名称一致性
class TestToolConsistency:
    def test_three_tools_present(self, plugin):
        # plugin.json 为 JSON Schema，工具稳定标识通过 definitions 中 name 的 const 钉死
        names = set()
        for desc in plugin["definitions"].values():
            const = desc.get("properties", {}).get("name", {}).get("const")
            if const:
                names.add(const)
        assert names == EXPECTED_TOOLS, f"plugin.json 工具稳定标识不一致: {names}"

    def test_tool_definition_names_in_one_of(self, plugin):
        defs = plugin["definitions"]
        for tool_name in EXPECTED_TOOLS:
            # 每个工具描述中的 name 使用 const 钉死稳定标识
            found = False
            for key, desc in defs.items():
                props = desc.get("properties", {})
                if props.get("name", {}).get("const") == tool_name:
                    found = True
                    break
            assert found, f"definitions 中缺少钉死工具标识 {tool_name} 的定义"

    def test_call_tool_enum_consistent(self, plugin):
        call_req = plugin["definitions"]["call_request"]["properties"]["tool"]["enum"]
        assert set(call_req) == EXPECTED_TOOLS


# ================================================================ 错误码一致性
class TestErrorCodeConsistency:
    def test_expected_codes_present(self, error_codes):
        codes = {item["code"] for item in error_codes["codes"]}
        missing = EXPECTED_ERROR_CODES - codes
        assert not missing, f"error_codes.json 缺少错误码: {missing}"

    def test_error_codes_mirrored_in_plugin_responses(self, plugin):
        # 三工具响应与 call_response 的统一错误码 enum 必须与错误码枚举一致（含 null）
        enum = set(plugin["definitions"]["screen_response"]["properties"]["error_code"]["enum"])
        assert None in enum, "screen_response error_code enum 应允许成功时为 null"
        enum = {e for e in enum if e is not None}
        assert enum == EXPECTED_ERROR_CODES, (
            f"plugin.json 响应 error_code enum 与错误码枚举不一致: {enum}"
        )
        for resp_name in ("keyboard_response", "command_response", "call_response"):
            resp_enum = set(
                plugin["definitions"][resp_name]["properties"]["error_code"]["enum"]
            )
            resp_enum = {e for e in resp_enum if e is not None}
            assert resp_enum == EXPECTED_ERROR_CODES, (
                f"{resp_name} 的 error_code enum 不一致: {resp_enum}"
            )


# ================================================================ 接口契约(.pyi)存在性
class TestInterfaceStub:
    def test_interface_stub_exists(self):
        stub = _stub_path()
        assert stub.exists(), f"接口契约缺失: {stub}"
        text = stub.read_text(encoding="utf-8")
        # 至少声明健康检查、工具列表、技能列表与 /call 调用四类签名
        for sig in ("def health(", "def list_tools(", "def list_skills(", "def call_tool("):
            assert sig in text, f"plugin_interface.pyi 缺少签名 {sig}"
        # 覆盖要求的异常
        for exc in (
            "UnauthorizedError", "ReplayError", "InvalidArgumentError",
            "ExecutionError", "SystemError",
        ):
            assert exc in text, f"plugin_interface.pyi 缺少异常 {exc}"
