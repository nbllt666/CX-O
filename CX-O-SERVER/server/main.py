"""
CX-O-SERVER 统一入口
整合 Gateway + Backend + ASR + TTS 为单体服务
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting CX-O-SERVER...")

    from server.services.asr_service import get_asr_service
    from server.services.tts_service import get_tts_service
    from server.gateway.health import health_checker

    app.state.asr_status = "uninitialized"
    app.state.tts_status = "uninitialized"
    app.state.asr_error = None
    app.state.tts_error = None

    asr_mode = getattr(settings, 'asr', None) and getattr(settings.asr, 'mode', 'remote')
    tts_mode = getattr(settings, 'tts', None) and getattr(settings.tts, 'mode', 'remote')

    if asr_mode == "embedded":
        try:
            asr_service = get_asr_service()
            await asr_service.initialize()
            app.state.asr_status = "healthy"
            health_checker.update_status("asr", "healthy")
            logger.info("Embedded ASR (SenseVoice) initialized successfully")
        except Exception as e:
            error_msg = f"Failed to initialize embedded ASR: {e}"
            logger.error(error_msg)
            app.state.asr_status = "error"
            app.state.asr_error = str(e)
            health_checker.update_status("asr", "unhealthy", error=str(e))
            
            try:
                logger.info("Attempting to fallback to remote ASR mode...")
                asr_service = get_asr_service()
                asr_service._mode = "remote"
                asr_service._initialized = True
                app.state.asr_status = "degraded"
                health_checker.update_status("asr", "degraded", error="Fallback to remote mode")
                logger.warning("ASR service degraded: using remote mode as fallback")
            except Exception as fallback_error:
                logger.error(f"ASR fallback to remote mode failed: {fallback_error}")
                app.state.asr_status = "unavailable"
                health_checker.update_status("asr", "unavailable", error=str(fallback_error))
    else:
        app.state.asr_status = "remote"
        health_checker.update_status("asr", "remote")

    if tts_mode == "embedded":
        try:
            tts_service = get_tts_service()
            await tts_service.initialize()
            app.state.tts_status = "healthy"
            health_checker.update_status("tts", "healthy")
            logger.info("Embedded TTS (F5-TTS) initialized successfully")
        except Exception as e:
            error_msg = f"Failed to initialize embedded TTS: {e}"
            logger.error(error_msg)
            app.state.tts_status = "error"
            app.state.tts_error = str(e)
            health_checker.update_status("tts", "unhealthy", error=str(e))
            
            try:
                logger.info("Attempting to fallback to remote TTS mode...")
                tts_service = get_tts_service()
                tts_service._mode = "remote"
                tts_service._initialized = True
                app.state.tts_status = "degraded"
                health_checker.update_status("tts", "degraded", error="Fallback to remote mode")
                logger.warning("TTS service degraded: using remote mode as fallback")
            except Exception as fallback_error:
                logger.error(f"TTS fallback to remote mode failed: {fallback_error}")
                app.state.tts_status = "unavailable"
                health_checker.update_status("tts", "unavailable", error=str(fallback_error))
    else:
        app.state.tts_status = "remote"
        health_checker.update_status("tts", "remote")

    logger.info(f"CX-O-SERVER started successfully (ASR: {app.state.asr_status}, TTS: {app.state.tts_status})")

    from server.api.app import lifespan as api_lifespan
    async with api_lifespan(app):
        yield

    logger.info("Shutting down CX-O-SERVER...")
    try:
        asr_service = get_asr_service()
        await asr_service.shutdown()
        logger.info("ASR service shutdown complete")
    except Exception as e:
        logger.error(f"Error during ASR shutdown: {e}")
    
    try:
        tts_service = get_tts_service()
        await tts_service.shutdown()
        logger.info("TTS service shutdown complete")
    except Exception as e:
        logger.error(f"Error during TTS shutdown: {e}")
    
    logger.info("CX-O-SERVER shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="CX-O-SERVER",
        description="CX-O 统一服务端 - Gateway + Backend + ASR + TTS",
        version="1.0.0",
        lifespan=lifespan,
    )

    cors_config = getattr(settings, 'cors', None)
    if cors_config and getattr(cors_config, 'enabled', False):
        app.add_middleware(
            CORSMiddleware,
            allow_origins=getattr(cors_config, 'origins', ['*']),
            allow_credentials=getattr(cors_config, 'allow_credentials', True),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    from server.api.app import register_api_routes
    register_api_routes(app)

    from server.gateway.server import register_gateway_routes
    register_gateway_routes(app)

    return app


app = create_app()


def main():
    settings = get_settings()
    host = getattr(settings.system, 'host', '0.0.0.0')
    port = getattr(settings.system, 'port', 8100)
    log_level = getattr(settings.system, 'log_level', 'info').lower()

    uvicorn.run(
        "server.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
