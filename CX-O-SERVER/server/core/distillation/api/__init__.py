"""DistillationService API 子包（CX-O 迁移版）。

提供 4 个 REST API 端点路由 + 批量切分路由。

公开导出:
    - router          — 单次蒸馏 4 端点路由
    - batch_router    — 批量切分路由

@version 1.1.0
"""

from server.core.distillation.api.batch_routes import router as batch_router
from server.core.distillation.api.routes import router

__all__ = ["router", "batch_router"]

__version__ = "1.1.0"
