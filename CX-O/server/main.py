import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

import uvicorn

from server.config import load_config, get_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    logger.info("Starting CX-O Server (Monolithic Architecture)...")

    try:
        from server.services.asr import get_asr_service
        asr_service = get_asr_service()
        asr_service.load_model()
        logger.info("ASR service initialized")
    except Exception as e:
        logger.warning(f"ASR service initialization failed: {e}")

    try:
        from server.services.tts import get_tts_service
        tts_service = get_tts_service()
        tts_service.load_model()
        logger.info("TTS service initialized")
    except Exception as e:
        logger.warning(f"TTS service initialization failed: {e}")

    try:
        from server.core.llm import get_llm_client
        llm_client = get_llm_client()
        logger.info("LLM client initialized")
    except Exception as e:
        logger.warning(f"LLM client initialization failed: {e}")

    try:
        from server.core.memory import get_memory_manager
        memory_manager = get_memory_manager()
        logger.info("Memory manager initialized")
    except Exception as e:
        logger.warning(f"Memory manager initialization failed: {e}")

    try:
        from server.core.context import get_context_manager
        context_manager = get_context_manager()
        logger.info("Context manager initialized")
    except Exception as e:
        logger.warning(f"Context manager initialization failed: {e}")

    logger.info("CX-O Server started successfully")

    yield

    logger.info("Shutting down CX-O Server...")
    logger.info("CX-O Server shutdown complete")


def run():
    config = load_config()

    uvicorn.run(
        "server.main:create_app",
        host=config.server.host,
        port=config.server.port,
        reload=False,
        log_level=config.logging.level.lower()
    )


def create_app():
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from server.api.app import app as api_app

    config = get_config()

    if hasattr(api_app, 'lifespan'):
        main_app = FastAPI(
            title="CX-O Server",
            description="Monolithic AI Voice Assistant Server",
            version="1.0.0"
        )
    else:
        main_app = FastAPI(
            title="CX-O Server",
            description="Monolithic AI Voice Assistant Server",
            version="1.0.0",
            lifespan=lifespan
        )

    if config.cors.enabled:
        main_app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors.origins,
            allow_credentials=config.cors.allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    main_app.include_router(api_app.routes)

    @main_app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "service": "CX-O Server",
            "version": "1.0.0",
            "architecture": "monolithic"
        }

    return main_app


if __name__ == "__main__":
    run()
