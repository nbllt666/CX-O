"""
CX-O-VoiceWorkStation 语音工作站
提供 So-VITS-SVC 训练/推理与 SVC 训练数据批量生成功能
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from workstation.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting CX-O-VoiceWorkStation...")
    # CXFC 插件注册与心跳（cxfc.enabled=false 时内部空转，零副作用；失败不影响自身服务）
    try:
        from workstation.services import cxfc_registration
        await cxfc_registration.start_registration()
    except Exception as e:
        logger.warning(f"Startup: CXFC 注册服务启动失败（不影响 VoiceWorkStation 自身服务）: {e}")
    logger.info("CX-O-VoiceWorkStation started successfully")
    yield
    logger.info("Shutting down CX-O-VoiceWorkStation...")
    await _shutdown_resources()
    logger.info("CX-O-VoiceWorkStation shutdown complete")


async def _shutdown_resources():
    """关闭/停止所有后台训练子进程与 HTTP 客户端单例，
    避免服务重启后残留孤儿进程与 GPU 显存占用。每个清理步骤独立
    try/except，确保单点失败不阻塞后续清理。"""
    # 1. 停止 So-VITS-SVC 训练子进程
    try:
        from workstation.api import sovits_svc as sovits_api
        trainer = sovits_api._trainer_instance
        if trainer is not None:
            await trainer.stop_training()
    except Exception as e:
        logger.warning(f"Shutdown: failed to stop So-VITS-SVC training: {e}")

    # 2. 停止 CXFC 心跳并向 CX-O-SERVER 注销插件
    try:
        from workstation.services import cxfc_registration
        await cxfc_registration.stop_registration()
    except Exception as e:
        logger.warning(f"Shutdown: failed to stop CXFC registration: {e}")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="CX-O-VoiceWorkStation",
        description="CX-O 语音工作站 - So-VITS-SVC 训练/推理、SVC 训练数据批量生成",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from workstation.api.sovits_svc import router as sovits_svc_router
    from workstation.api.workflow import router as workflow_router
    from workstation.api.audio_files import router as audio_files_router
    from workstation.api.music import router as music_router
    from workstation.api.cxfc_plugin import router as cxfc_plugin_router
    from workstation.api.datasets import batch_router as voxcpm_batch_router
    from workstation.api.datasets import datasets_router as svc_datasets_router

    app.include_router(sovits_svc_router, prefix="/api/sovits-svc", tags=["So-VITS-SVC"])
    app.include_router(workflow_router, prefix="/api/workflow", tags=["工作流"])
    app.include_router(audio_files_router, prefix="/api/audio-files", tags=["音频文件服务"])
    app.include_router(music_router, prefix="/api/music", tags=["音乐作曲与演唱"])
    app.include_router(voxcpm_batch_router, prefix="/api/voxcpm", tags=["VoxCPM 批量数据集"])
    app.include_router(svc_datasets_router, prefix="/api/sovits-svc", tags=["SVC 数据集管理"])
    # CXFC 插件端点挂在根路径（/tools、/skills、/call），CX-O-SERVER 按 host:port 直连抓取
    app.include_router(cxfc_plugin_router, tags=["CXFC 插件"])

    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "service": "CX-O-VoiceWorkStation",
            "name": settings.cxfc.plugin_name,
            "version": "1.0.0",
        }

    return app


app = create_app()


def main():
    settings = get_settings()
    host = getattr(settings.server, 'host', '0.0.0.0')
    port = getattr(settings.server, 'port', 8200)
    log_level = getattr(settings.server, 'log_level', 'info').lower()

    uvicorn.run(
        "workstation.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
