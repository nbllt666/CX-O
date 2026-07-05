"""契约签名匹配框架包（CX-O-SERVER 测试基础设施 Phase 1）。

提供基于 ``public/interface_stub/*.pyi`` 的签名验证工具与基于
``public/schema/*.schema.json`` 的数据校验工具，供后续批次补测直接导入使用：
- ``signature_matcher``：load_stub / match_signature / match_class_signature
- ``schema_validator``：load_schema / validate_data

契约文件根目录解析：
- 默认从 ``CXO_PUBLIC_ROOT`` 环境变量读取
- 未设置时基于 ``__file__`` 解析到 ``c:/CX-O/public``
"""

from __future__ import annotations

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
# tests/contract -> tests -> CX-O-SERVER -> CX-O（仓库根）-> public
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
_DEFAULT_PUBLIC_ROOT = os.path.join(_REPO_ROOT, "public")


def get_public_root() -> str:
    """返回 public 契约根目录绝对路径。

    优先读取 ``CXO_PUBLIC_ROOT`` 环境变量，未设置则回退到默认解析路径。
    """
    env = os.getenv("CXO_PUBLIC_ROOT")
    if env:
        return os.path.abspath(env)
    return _DEFAULT_PUBLIC_ROOT


from tests.contract.schema_validator import (
    ValidationResult,
    is_jsonschema_available,
    is_seed_stage,
    list_available_schemas,
    load_schema,
    validate_data,
)
from tests.contract.signature_matcher import (
    ClassSignatureMatchResult,
    SignatureMatchResult,
    list_available_stubs,
    load_stub,
    match_class_signature,
    match_signature,
)

__all__ = [
    "get_public_root",
    "load_stub",
    "list_available_stubs",
    "match_signature",
    "match_class_signature",
    "SignatureMatchResult",
    "ClassSignatureMatchResult",
    "load_schema",
    "list_available_schemas",
    "validate_data",
    "ValidationResult",
    "is_seed_stage",
    "is_jsonschema_available",
]
