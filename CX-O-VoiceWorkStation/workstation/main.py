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
    logger.info("CX-O-VoiceWorkStation shutdown complete")


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
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from workstation.api.ref_audio import router as ref_audio_router
    from workstation.api.f5tts_finetune import router as f5tts_finetune_router
    from workstation.api.sovits_svc import router as sovits_svc_router

    app.include_router(ref_audio_router, prefix="/api/ref-audio", tags=["参考音频生成"])
    app.include_router(f5tts_finetune_router, prefix="/api/f5tts-finetune", tags=["F5-TTS 微调"])
    app.include_router(sovits_svc_router, prefix="/api/sovits-svc", tags=["So-VITS-SVC"])

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
