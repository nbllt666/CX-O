from typing import Any, Dict, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class PluginContext:
    def __init__(self, plugin_id: str, plugin_name: str, config: Dict[str, Any] = None):
        self.plugin_id = plugin_id
        self.plugin_name = plugin_name
        self.config = config or {}
        self._memory_manager = None
        self._context_manager = None
        self._llm_client = None
        self._tool_registry = None
        self._ws_manager = None
        self._custom_data: Dict[str, Any] = {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set_config(self, key: str, value: Any):
        self.config[key] = value

    @property
    def memory_manager(self):
        return self._memory_manager

    @property
    def context_manager(self):
        return self._context_manager

    @property
    def llm_client(self):
        return self._llm_client

    @property
    def tool_registry(self):
        return self._tool_registry

    @property
    def ws_manager(self):
        return self._ws_manager

    def set(self, key: str, value: Any):
        self._custom_data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._custom_data.get(key, default)

    def log_info(self, message: str):
        logger.info(f"[{self.plugin_name}] {message}")

    def log_error(self, message: str):
        logger.error(f"[{self.plugin_name}] {message}")

    def log_warning(self, message: str):
        logger.warning(f"[{self.plugin_name}] {message}")