"""
CXHMS 配置管理包（兼容性 shim）
已迁移至 server.config，本包保留向后兼容的 settings 导出。
"""
from .settings import settings

__all__ = ["settings"]
