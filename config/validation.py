"""
配置验证模块
提供配置验证、类型检查和默认值处理
"""

import re
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Type, get_type_hints


class ValidationError(Exception):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"配置验证错误 [{field}]: {message}")


class ValidationResult:
    def __init__(self):
        self.errors: List[ValidationError] = []
        self.warnings: List[Tuple[str, str]] = []

    def add_error(self, field: str, message: str):
        self.errors.append(ValidationError(field, message))

    def add_warning(self, field: str, message: str):
        self.warnings.append((field, message))

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def __bool__(self) -> bool:
        return self.is_valid


class ConfigValidator:
    REQUIRED_FIELDS: Dict[str, Type] = {
        "server.host": str,
        "server.port": int,
        "database.path": str,
    }

    VALID_VALUES: Dict[str, Set[str]] = {
        "models.main.provider": {"ollama", "vllm", "openai", "anthropic", "deepseek", "local"},
        "memory.vector_backend": {"milvus_lite", "qdrant", "weaviate"},
        "memory.decay_model": {"exponential", "ebbinghaus"},
    }

    RANGE_CONSTRAINTS: Dict[str, Tuple[float, float]] = {
        "server.port": (1, 65535),
        "memory.max_memories": (1, 1000000),
        "memory.default_importance": (1, 5),
        "memory.decay_rate": (0, 1),
        "memory.dedup_threshold": (0, 1),
        "models.main.temperature": (0, 2),
        "models.main.max_tokens": (0, 10000000),
        "context.max_context_length": (100, 100000),
    }

    PATH_FIELDS: Set[str] = {
        "database.path",
        "database.memories_db",
        "database.sessions_db",
        "database.acp_db",
        "memory.milvus_lite.db_path",
        "logging.file",
    }

    URL_FIELDS: Set[str] = {
        "models.main.host",
        "models.summary.host",
        "models.memory.host",
    }

    HOST_FIELDS: Set[str] = {
        "memory.qdrant.host",
        "memory.weaviate.host",
    }

    URL_PATTERN = re.compile(r"^(https?://|http://localhost|http://[\d.]+)(:\d+)?(/.*)?$")

    @classmethod
    def validate(cls, config_dict: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult()

        cls._validate_required_fields(config_dict, result)
        cls._validate_types(config_dict, result)
        cls._validate_values(config_dict, result)
        cls._validate_ranges(config_dict, result)
        cls._validate_paths(config_dict, result)
        cls._validate_urls(config_dict, result)
        cls._validate_hosts(config_dict, result)
        cls._validate_dependencies(config_dict, result)

        return result

    @classmethod
    def _get_nested_value(cls, config: Dict, path: str) -> Tuple[bool, Any]:
        keys = path.split(".")
        current = config
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return False, None
            current = current[key]
        return True, current

    @classmethod
    def _validate_required_fields(cls, config: Dict, result: ValidationResult):
        for field_path, field_type in cls.REQUIRED_FIELDS.items():
            exists, value = cls._get_nested_value(config, field_path)
            if not exists or value is None:
                result.add_error(field_path, "必填字段缺失")

    @classmethod
    def _validate_types(cls, config: Dict, result: ValidationResult):
        for field_path, expected_type in cls.REQUIRED_FIELDS.items():
            exists, value = cls._get_nested_value(config, field_path)
            if exists and value is not None:
                if not isinstance(value, expected_type):
                    try:
                        expected_type(value)
                    except (ValueError, TypeError):
                        result.add_error(
                            field_path,
                            f"类型错误: 期望 {expected_type.__name__}, 实际 {type(value).__name__}",
                        )

    @classmethod
    def _validate_values(cls, config: Dict, result: ValidationResult):
        for field_path, valid_values in cls.VALID_VALUES.items():
            exists, value = cls._get_nested_value(config, field_path)
            if exists and value is not None:
                if str(value) not in valid_values:
                    result.add_error(
                        field_path, f"无效值: '{value}', 有效值: {', '.join(valid_values)}"
                    )

    @classmethod
    def _validate_ranges(cls, config: Dict, result: ValidationResult):
        for field_path, (min_val, max_val) in cls.RANGE_CONSTRAINTS.items():
            exists, value = cls._get_nested_value(config, field_path)
            if exists and value is not None:
                try:
                    num_value = float(value)
                    if not min_val <= num_value <= max_val:
                        result.add_error(
                            field_path, f"值超出范围: {value}, 有效范围: [{min_val}, {max_val}]"
                        )
                except (ValueError, TypeError):
                    pass

    @classmethod
    def _validate_paths(cls, config: Dict, result: ValidationResult):
        for field_path in cls.PATH_FIELDS:
            exists, value = cls._get_nested_value(config, field_path)
            if exists and value is not None:
                path = Path(value)
                parent = path.parent
                if not parent.exists():
                    result.add_warning(field_path, f"父目录不存在: {parent}")

    @classmethod
    def _validate_urls(cls, config: Dict, result: ValidationResult):
        for field_path in cls.URL_FIELDS:
            exists, value = cls._get_nested_value(config, field_path)
            if exists and value is not None:
                if not cls.URL_PATTERN.match(str(value)):
                    result.add_warning(field_path, f"URL格式可能无效: {value}")

    @classmethod
    def _validate_hosts(cls, config: Dict, result: ValidationResult):
        for field_path in cls.HOST_FIELDS:
            exists, value = cls._get_nested_value(config, field_path)
            if exists and value is not None:
                str_value = str(value)
                if not str_value:
                    result.add_warning(field_path, "主机名为空")

    @classmethod
    def _validate_dependencies(cls, config: Dict, result: ValidationResult):
        exists, vector_enabled = cls._get_nested_value(config, "memory.vector_enabled")
        if exists and vector_enabled:
            _, backend = cls._get_nested_value(config, "memory.vector_backend")
            if backend == "qdrant":
                _, host = cls._get_nested_value(config, "memory.qdrant.host")
                _, port = cls._get_nested_value(config, "memory.qdrant.port")
                if not host or not port:
                    result.add_error("memory.qdrant", "Qdrant后端需要配置 host 和 port")
            elif backend == "weaviate":
                _, host = cls._get_nested_value(config, "memory.weaviate.host")
                if not host:
                    result.add_error("memory.weaviate", "Weaviate后端需要配置 host")

        exists, api_key_enabled = cls._get_nested_value(config, "security.api_key_enabled")
        if exists and api_key_enabled:
            _, api_key = cls._get_nested_value(config, "security.api_key")
            if not api_key:
                result.add_error("security.api_key", "启用API密钥认证时必须设置 api_key")


def validate_config(config_dict: Dict[str, Any]) -> ValidationResult:
    return ConfigValidator.validate(config_dict)
