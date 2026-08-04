"""DistillationService 路由聚合入口（CX-O 迁移版 B3.4）。

从 server.core.distillation.api 导入单次蒸馏 router + 批量切分 batch_router，
聚合成单一 router 暴露给 app.py。

最终路径（与 public/interface_stub/distillation_service.pyi 一致）:
    单次蒸馏 (routes.py):
        - POST /api/v1/distillation/start
        - POST /api/v1/distillation/{session_id}/advance
        - POST /api/v1/distillation/{session_id}/finalize
        - GET  /api/v1/distillation/{session_id}
    批量切分 (batch_routes.py):
        - POST /api/v1/distillation/start-batch
        - GET  /api/v1/distillation/group/{group_id}
        - POST /api/v1/distillation/{session_id}/finalize-agent
        - POST /api/v1/distillation/parse-character-card
        - POST /api/v1/distillation/start-from-character-card

注册方式: app.include_router(distillation.router)  # 不加 prefix（router 自带 /api/v1/distillation）

@version 1.1.0
"""

from fastapi import APIRouter

from server.core.distillation.api import batch_router, router as distillation_router

router = APIRouter()
router.include_router(distillation_router)
router.include_router(batch_router)

__all__ = ["router"]