"""
环境变量支持模块
支持从环境变量加载配置，优先级高于配置文件
"""

import os
from dataclasses import fields, is_dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional, Type, get_type_hints


class EnvConfig:
    PREFIX = "CXHMS_"

    ENV_MAPPINGS: Dict[str, str] = {
        "CXHMS_HOST": "server.host",
        "CXHMS_PORT": "server.port",
        "CXHMS_DEBUG": "server.debug",
        "CXHMS_LOG_LEVEL": "logging.level",
        "CXHMS_DATABASE_PATH": "database.path",
        "CXHMS_DATABASE_MEMORIES_DB": "database.memories_db",
        "CXHMS_DATABASE_SESSIONS_DB": "database.sessions_db",
        "CXHMS_DATABASE_ACP_DB": "database.acp_db",
        "CXHMS_LLM_PROVIDER": "models.main.provider",
        "CXHMS_LLM_HOST": "models.main.host",
        "CXHMS_LLM_MODEL": "models.main.model",
        "CXHMS_LLM_API_KEY": "models.main.apiKey",
        "CXHMS_SUMMARY_MODEL": "models.summary.model",
        "CXHMS_MEMORY_MODEL": "models.memory.model",
        "CXHMS_VECTOR_ENABLED": "memory.vector_enabled",
        "CXHMS_VECTOR_BACKEND": "memory.vector_backend",
        "CXHMS_MILVUS_PATH": "memory.milvus_lite.db_path",
        "CXHMS_VECTOR_SIZE": "memory.milvus_lite.vector_size",
        "CXHMS_MEMORY_MAX": "memory.max_memories",
        "CXHMS_DECAY_ENABLED": "memory.decay_enabled",
        "CXHMS_ARCHIVE_ENABLED": "memory.archive_enabled",
        "CXHMS_ACP_ENABLED": "acp.enabled",
        "CXHMS_ACP_AGENT_ID": "acp.local_agent_id",
        "CXHMS_ACP_AGENT_NAME": "acp.local_agent_name",
        "CXHMS_TOOLS_ENABLED": "tools.enabled",
        "CXHMS_MCP_ENABLED": "tools.mcp_enabled",
        "CXHMS_API_KEY_ENABLED": "security.api_key_enabled",
        "CXHMS_API_KEY": "security.api_key",
        "CXHMS_RATE_LIMIT_ENABLED": "security.rate_limit_enabled",
        "CXHMS_RATE_LIMIT_REQUESTS": "security.rate_limit_requests",
        "CXHMS_CORS_ORIGINS": "cors.origins",
    }

    SECRET_FIELDS = {"apiKey", "api_key", "password", "secret", "token"}

    @classmethod
    def get_env_value(cls, env_key: str) -> Optional[str]:
        return os.environ.get(env_key)

    @classmethod
    def parse_value(cls, value: str, target_type: Type) -> Any:
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        elif target_type == list:
            return [item.strip() for item in value.split(",")]
        elif hasattr(target_type, "__origin__"):
            if target_type.__origin__ == list:
                return [item.strip() for item in value.split(",")]
            elif target_type.__origin__ == Optional:
                inner_type = target_type.__args__[0]
                return cls.parse_value(value, inner_type)
        return value

    @classmethod
    def set_nested_value(cls, config_dict: Dict, path: str, value: Any) -> None:
        keys = path.split(".")
        current = config_dict
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

    @classmethod
    def load_from_env(cls) -> Dict[str, Any]:
        env_config: Dict[str, Any] = {}

        for env_key, config_path in cls.ENV_MAPPINGS.items():
            value = cls.get_env_value(env_key)
            if value is not None:
                cls.set_nested_value(env_config, config_path, value)

        for key, value in os.environ.items():
            if key.startswith(cls.PREFIX) and key not in cls.ENV_MAPPINGS:
                config_key = key[len(cls.PREFIX) :].lower()
                parts = config_key.split("_")
                config_path = ".".join(parts)
                cls.set_nested_value(env_config, config_path, value)

        return env_config

    @classmethod
    def is_secret_field(cls, field_name: str) -> bool:
        return any(secret in field_name.lower() for secret in cls.SECRET_FIELDS)

    @classmethod
    def mask_secrets(cls, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        masked = {}
        for key, value in config_dict.items():
            if isinstance(value, dict):
                masked[key] = cls.mask_secrets(value)
            elif cls.is_secret_field(key) and isinstance(value, str) and value:
                masked[key] = "***MASKED***"
            else:
                masked[key] = value
        return masked


def get_env_config() -> Dict[str, Any]:
    return EnvConfig.load_from_env()
