"""
CXO-ModelStation：SVC 模型训练工作站

承接 So-VITS-SVC 训练全链路：数据集管理、VoxCPM 批量语料、预处理、训练、试听推理、工作流编排。
自 CX-O-VoiceWorkStation 拆分（change-id: split-audio-workstation-cxfc-modelstation），
端点路径与原 VWS 保持一致，消费方改连 8300 即可。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from modelstation.config import get_settings

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent  # CXO-ModelStation


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting CXO-ModelStation...")
    logger.info("CXO-ModelStation started successfully")
    yield
    logger.info("Shutting down CXO-ModelStation...")
    _shutdown_resources()
    logger.info("CXO-ModelStation shutdown complete")


def _shutdown_resources():
    """关停时停止后台训练子进程，避免残留孤儿进程与 GPU 显存占用。"""
    try:
        from modelstation.api import sovits_svc as sovits_api
        trainer = sovits_api._trainer_instance
        if trainer is not None:
            import asyncio
            asyncio.get_event_loop().run_until_complete(trainer.stop_training())
    except Exception as e:
        logger.warning(f"Shutdown: failed to stop So-VITS-SVC training: {e}")
    try:
        from modelstation.services import melotts_trainer as melotts_trainer_module
        melotts_trainer = melotts_trainer_module._trainer_instance
        if melotts_trainer is not None:
            import asyncio
            asyncio.get_event_loop().run_until_complete(melotts_trainer.stop_training())
    except Exception as e:
        logger.warning(f"Shutdown: failed to stop MeloTTS training: {e}")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="CXO-ModelStation",
        description="CXO-ModelStation - So-VITS-SVC 模型训练工作站（数据集/批量语料/训练/试听/工作流）",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS 白名单从配置读取（默认 ModelStation 前端 3300 + 主前端 3100 来源）；
    # 不放开 "*"——服务含训练/文件接口，任意源可读会造成跨站读取风险。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from modelstation.api.sovits_svc import router as sovits_svc_router
    from modelstation.api.workflow import router as workflow_router
    from modelstation.api.audio_files import router as audio_files_router
    from modelstation.api.datasets import batch_router as datasets_generate_router
    from modelstation.api.datasets import datasets_router as svc_datasets_router
    from modelstation.api.melotts import router as melotts_router

    # 路由前缀（契约变更 change-id: extend-modelstation-standalone-melotts-datasets：
    # 批量生成端点由 /api/voxcpm/batch-dataset 改名 /api/datasets/batch-generate，旧路由移除）
    app.include_router(sovits_svc_router, prefix="/api/sovits-svc", tags=["So-VITS-SVC"])
    app.include_router(workflow_router, prefix="/api/workflow", tags=["工作流"])
    app.include_router(audio_files_router, prefix="/api/audio-files", tags=["音频文件服务"])
    app.include_router(datasets_generate_router, prefix="/api/datasets", tags=["数据集批量生成"])
    app.include_router(svc_datasets_router, prefix="/api/sovits-svc", tags=["SVC 数据集管理"])
    app.include_router(melotts_router, prefix="/api/melotts", tags=["MeloTTS 训练"])

    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "service": "CXO-ModelStation",
            "version": "1.0.0",
        }

    _mount_frontend(app)

    return app


def _mount_frontend(app: FastAPI) -> None:
    """挂载前端生产构建产物（frontend/dist），不存在时跳过（Task 3 产出后自动生效）。

    - /assets → StaticFiles（Vite 构建的静态资源目录）；
    - 其余 GET 路径 → SPA fallback（返回 index.html，前端路由接管）。
    注意：catch-all 注册在所有 API 路由与 /health 之后，不会遮蔽 API。
    """
    dist = _BASE_DIR / "frontend" / "dist"
    if not dist.is_dir():
        logger.info("frontend/dist 不存在，跳过静态托管挂载")
        return

    dist_resolved = dist.resolve()
    assets_dir = dist_resolved / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path:
            candidate = (dist_resolved / full_path).resolve()
            # 防路径穿越：仅允许 dist 目录内的文件
            if candidate.is_relative_to(dist_resolved) and candidate.is_file():
                return FileResponse(path=str(candidate))
        return FileResponse(path=str(dist_resolved / "index.html"))


app = create_app()


def main():
    settings = get_settings()
    host = settings.server.host
    port = settings.server.port
    log_level = settings.server.log_level

    # 单 worker 部署（训练状态进程内缓存，多 worker 会导致状态不一致）
    uvicorn.run(
        "modelstation.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=False,
        workers=1,
    )


if __name__ == "__main__":
    main()
