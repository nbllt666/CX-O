"""
配置管理模块（兼容性 shim）
本模块已迁移至 server.config，保留此文件作为向后兼容的代理层。
新的配置系统使用 Pydantic 模型（UnifiedConfig），通过 server.config.get_settings() 访问。
"""
from __future__ import annotations

from server.config import get_settings as _get_server_settings
from server.config import save_config as _save_server_config


class _CompatSettings:
    """向后兼容的 Settings 代理，将调用委托到 server.config 单例。"""

    def __init__(self):
        self._delegate = _get_server_settings()

    @property
    def config(self):
        return self._delegate.config

    @property
    def _config_path(self):
        return self._delegate._config_path

    def save_config(self):
        _save_server_config(self._delegate.config)

    def reload_config(self):
        self._delegate.reload_config()

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


settings = _CompatSettings()
