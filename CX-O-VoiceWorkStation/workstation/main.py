"""
CX-O-VoiceWorkStation 语音工作站
提供参考音频生成、F5-TTS 微调、So-VITS-SVC 训练/推理功能
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
    settings = get_settings()
    logger.info("Starting CX-O-VoiceWorkStation...")
    logger.info("CX-O-VoiceWorkStation started successfully")
    yield
    logger.info("Shutting down CX-O-VoiceWorkStation...")
    await _shutdown_resources()
    logger.info("CX-O-VoiceWorkStation shutdown complete")


async def _shutdown_resources():
    """关闭/停止所有后台训练子进程、HTTP 客户端单例与 IndexTTS 服务，
    避免服务重启后残留孤儿进程与 GPU 显存占用。每个清理步骤独立
    try/except，确保单点失败不阻塞后续清理。"""
    # 1. 停止 F5-TTS 训练子进程
    try:
        from workstation.api import f5tts_finetune as f5tts_api
        service = f5tts_api._service_instance
        if service is not None:
            await service.stop_training()
    except Exception as e:
        logger.warning(f"Shutdown: failed to stop F5-TTS training: {e}")

    # 2. 停止 So-VITS-SVC 训练子进程
    try:
        from workstation.api import sovits_svc as sovits_api
        trainer = sovits_api._trainer_instance
        if trainer is not None:
            await trainer.stop_training()
    except Exception as e:
        logger.warning(f"Shutdown: failed to stop So-VITS-SVC training: {e}")

    # 3. 关闭 CosyVoice HTTP 客户端单例
    try:
        from workstation.services import cosyvoice_client
        client = cosyvoice_client._client_instance
        if client is not None:
            await client.close()
    except Exception as e:
        logger.warning(f"Shutdown: failed to close CosyVoice client: {e}")

    # 4. 停止 IndexTTS 服务子进程
    try:
        from workstation.services import index_tts_manager
        manager = index_tts_manager._manager_instance
        if manager is not None:
            await manager.stop()
    except Exception as e:
        logger.warning(f"Shutdown: failed to stop IndexTTS manager: {e}")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="CX-O-VoiceWorkStation",
        description="CX-O 语音工作站 - 参考音频生成、F5-TTS 微调、So-VITS-SVC 训练/推理",
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

    from workstation.api.ref_audio import router as ref_audio_router
    from workstation.api.f5tts_finetune import router as f5tts_finetune_router
    from workstation.api.sovits_svc import router as sovits_svc_router
    from workstation.api.voxcpm import router as voxcpm_router
    from workstation.api.workflow import router as workflow_router

    app.include_router(ref_audio_router, prefix="/api/ref-audio", tags=["参考音频生成"])
    app.include_router(f5tts_finetune_router, prefix="/api/f5tts-finetune", tags=["F5-TTS 微调"])
    app.include_router(sovits_svc_router, prefix="/api/sovits-svc", tags=["So-VITS-SVC"])
    app.include_router(voxcpm_router, prefix="/api/voxcpm", tags=["VoxCPM 参考音频生成"])
    app.include_router(workflow_router, prefix="/api/workflow", tags=["工作流"])

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "CX-O-VoiceWorkStation"}

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
