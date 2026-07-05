"""数据契约校验工具（CX-O-SERVER 测试基础设施 Phase 1）。

基于 ``public/schema/*.schema.json`` 校验数据是否符合数据契约。

核心能力：
- ``load_schema(schema_name)`` —— 加载 JSON Schema
- ``validate_data(data, schema_name)`` —— 校验数据符合 schema

校验策略：
- 优先使用 ``jsonschema`` 库（如已安装）做完整 draft-07 校验
- 未安装 ``jsonschema`` 时降级为基础 dict 校验：
  1. ``type`` 校验（object/array/string/number/integer/boolean/null）
  2. ``required`` 字段存在性校验
  3. ``properties`` 字段类型校验（一层）
- 自动检测种子阶段 schema（``_seedStage`` 标记或 ``properties`` 为空），
  此时校验通过但结果标记 ``seed_stage=True``，便于后续批次按需启用严格校验

注意：当前 ``public/schema/`` 多为种子阶段（仅含源真理指针，无完整字段定义），
本工具在 schema 未补全时会清晰标记种子状态，不误报失败。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tests.contract import get_public_root

# ---------------------------------------------------------------------------
# 尝试导入 jsonschema（可选依赖）
# ---------------------------------------------------------------------------
try:
    import jsonschema  # type: ignore

    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False


# ---------------------------------------------------------------------------
# 结果数据类
# ---------------------------------------------------------------------------
@dataclass
class ValidationResult:
    """数据校验结果。"""

    valid: bool
    """是否通过校验"""
    schema_name: str
    schema_found: bool
    """schema 文件是否存在"""
    seed_stage: bool = False
    """是否为种子阶段 schema（无完整字段定义，校验为 trivial 通过）"""
    errors: List[str] = field(default_factory=list)
    """校验错误列表"""
    used_jsonschema: bool = False
    """是否使用了 jsonschema 库（True）或基础 dict 校验（False）"""

    def assert_valid(self) -> None:
        """断言校验通过，否则抛出 AssertionError 并附错误。"""
        assert self.valid, (
            f"数据校验失败（schema={self.schema_name}, "
            f"engine={'jsonschema' if self.used_jsonschema else 'basic'}）: {self.errors}"
        )


# ---------------------------------------------------------------------------
# Schema 加载
# ---------------------------------------------------------------------------
def _schema_dir() -> str:
    """返回 schema 目录绝对路径。"""
    return os.path.join(get_public_root(), "schema")


def _schema_path(schema_name: str) -> str:
    """返回 schema 文件绝对路径。

    Args:
        schema_name: schema 名，如 ``agent`` / ``chat_message`` / ``memory``
                     （可含或不含 ``.schema.json`` 后缀）
    """
    name = schema_name
    if not name.endswith(".schema.json"):
        if name.endswith(".json"):
            name = name[:-5]
        name = f"{name}.schema.json"
    return os.path.join(_schema_dir(), name)


def load_schema(schema_name: str) -> Optional[Dict[str, Any]]:
    """加载 JSON Schema 文件。

    Args:
        schema_name: schema 名，如 ``agent`` / ``chat_message``

    Returns:
        解析后的 schema 字典；文件不存在时返回 None
    """
    path = _schema_path(schema_name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_available_schemas() -> List[str]:
    """列出 ``public/schema/`` 下所有可用的 schema 名（去掉 .schema.json 后缀）。"""
    schema_dir = _schema_dir()
    if not os.path.isdir(schema_dir):
        return []
    names: List[str] = []
    for f in os.listdir(schema_dir):
        if f.endswith(".schema.json"):
            names.append(f[: -len(".schema.json")])
    return sorted(names)


# ---------------------------------------------------------------------------
# 种子阶段检测
# ---------------------------------------------------------------------------
def is_seed_stage(schema: Dict[str, Any]) -> bool:
    """检测 schema 是否处于种子阶段。

    判据：
    - 显式标记 ``_seedStage == true``
    - 或 ``properties`` 为空字典 / 不存在 且 ``required`` 为空
    """
    if schema.get("_seedStage") is True:
        return True
    properties = schema.get("properties")
    required = schema.get("required", [])
    if (not properties or properties == {}) and (not required):
        return True
    return False


# ---------------------------------------------------------------------------
# 基础 dict 校验（jsonschema 不可用时的降级路径）
# ---------------------------------------------------------------------------
_PY_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _check_type(value: Any, type_str: str) -> bool:
    expected = _PY_TYPE_MAP.get(type_str)
    if expected is None:
        return True  # 未知类型不校验
    # 注意：bool 是 int 的子类，JSON Schema 中 integer 不应接受 bool
    if type_str == "integer" and isinstance(value, bool):
        return False
    if type_str == "number" and isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _basic_validate(data: Any, schema: Dict[str, Any], errors: List[str], path: str = "") -> None:
    """基础 dict 校验（递归一层 properties）。"""
    type_str = schema.get("type")
    if type_str and not _check_type(data, type_str):
        errors.append(f"{path or '(root)'}: 期望类型 {type_str}，实际 {type(data).__name__}")
        return

    if type_str == "object" and isinstance(data, dict):
        # required 字段
        for req in schema.get("required", []):
            if req not in data:
                errors.append(f"{path or '(root)'}: 缺少必填字段 '{req}'")
        # properties 类型校验（一层）
        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            if prop_name in data:
                sub_path = f"{path}.{prop_name}" if path else prop_name
                prop_type = prop_schema.get("type")
                if prop_type and not _check_type(data[prop_name], prop_type):
                    errors.append(
                        f"{sub_path}: 期望类型 {prop_type}，"
                        f"实际 {type(data[prop_name]).__name__}"
                    )
    elif type_str == "array" and isinstance(data, list):
        items = schema.get("items")
        if items and isinstance(items, dict):
            item_type = items.get("type")
            if item_type:
                for idx, item in enumerate(data):
                    if not _check_type(item, item_type):
                        errors.append(
                            f"{path}[{idx}]: 期望类型 {item_type}，"
                            f"实际 {type(item).__name__}"
                        )


# ---------------------------------------------------------------------------
# 公共校验 API
# ---------------------------------------------------------------------------
def validate_data(data: Any, schema_name: str) -> ValidationResult:
    """校验数据是否符合 schema。

    Args:
        data: 待校验的数据
        schema_name: schema 名，如 ``agent`` / ``chat_message``

    Returns:
        ValidationResult
    """
    schema = load_schema(schema_name)
    if schema is None:
        return ValidationResult(
            valid=False,
            schema_name=schema_name,
            schema_found=False,
            errors=[f"Schema 文件不存在: {schema_name}.schema.json"],
        )

    seed = is_seed_stage(schema)

    # 种子阶段：schema 无字段定义，校验 trivial 通过
    if seed:
        return ValidationResult(
            valid=True,
            schema_name=schema_name,
            schema_found=True,
            seed_stage=True,
            errors=[],
            used_jsonschema=False,
        )

    errors: List[str] = []

    if _HAS_JSONSCHEMA:
        try:
            jsonschema.validate(instance=data, schema=schema)
            return ValidationResult(
                valid=True,
                schema_name=schema_name,
                schema_found=True,
                seed_stage=False,
                errors=[],
                used_jsonschema=True,
            )
        except jsonschema.ValidationError as exc:
            errors.append(str(exc.message))
            return ValidationResult(
                valid=False,
                schema_name=schema_name,
                schema_found=True,
                seed_stage=False,
                errors=errors,
                used_jsonschema=True,
            )

    # 降级：基础 dict 校验
    _basic_validate(data, schema, errors)
    return ValidationResult(
        valid=len(errors) == 0,
        schema_name=schema_name,
        schema_found=True,
        seed_stage=False,
        errors=errors,
        used_jsonschema=False,
    )


def is_jsonschema_available() -> bool:
    """返回 jsonschema 库是否可用。"""
    return _HAS_JSONSCHEMA
