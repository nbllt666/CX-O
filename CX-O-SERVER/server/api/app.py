import asyncio
import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from server.api.exceptions import (
    ServiceError,
    service_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from server.api.middleware.performance import PerformanceMiddleware
from server.api.response import APIResponse, HealthResponse
from server.api.routers import (
    acp,
    admin,
    agents,
    archive,
    audio,
    avatars,
    backup,
    chat,
    config,
    context,
    cxfc,
    graph,
    memory,
    memory_chat,
    service,
    stats,
    tools,
    vector,
    websocket,
)
from server.config import get_settings
from server.dependencies import ServiceState

from server.core.logging_config import LogContext, get_contextual_logger, setup_logging

settings = get_settings()

log_file_config = getattr(settings.config, "logging", {})
log_file = (
    log_file_config.get("file", "logs/app.log")
    if isinstance(log_file_config, dict)
    else "logs/app.log"
)

setup_logging(
    level=settings.config.system.log_level,
    log_file=log_file,
    max_bytes=(
        log_file_config.get("max_bytes", 10 * 1024 * 1024)
        if isinstance(log_file_config, dict)
        else 10 * 1024 * 1024
    ),
    backup_count=log_file_config.get("backup_count", 5) if isinstance(log_file_config, dict) else 5,
    structured=False,
    console_colors=True,
)

logger = get_contextual_logger(__name__)


def register_api_routes(app: FastAPI):
    """Register API routes onto an existing FastAPI app"""
    app.add_middleware(PerformanceMiddleware)

    app.include_router(chat.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.include_router(memory.router, prefix="/api")
    app.include_router(memory_chat.router, prefix="/api")
    app.include_router(context.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(acp.router, prefix="/api")
    app.include_router(service.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(websocket.router, prefix="/api")
    app.include_router(graph.router, prefix="/api/graph")
    app.include_router(agents.router, prefix="/api")
    app.include_router(archive.router, prefix="/api")
    app.include_router(audio.router, prefix="/api")
    app.include_router(avatars.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(backup.router, prefix="/api")
    app.include_router(cxfc.router, prefix="/api")
    app.include_router(vector.router, prefix="/api")

    app.add_exception_handler(ServiceError, service_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    @app.get("/health", response_model=HealthResponse)
    async def health_check(request: Request):
        services: ServiceState = request.app.state.services
        components = {
            "memory_manager": services.memory_manager is not None,
            "context_manager": services.context_manager is not None,
            "acp_manager": services.acp_manager is not None,
            "llm_client": services.llm_client is not None,
            "model_router": services.model_router is not None,
            "asr_service": services.asr_service is not None,
            "tts_service": services.tts_service is not None,
        }
        return HealthResponse(
            status="healthy" if all(components.values()) else "degraded",
            version="1.0.0",
            components=components,
        )

    @app.get("/")
    async def root():
        return {
            "service": "CX-O-SERVER",
            "version": "1.0.0",
            "description": "CX-O Server",
            "docs": "/docs",
            "redoc": "/redoc",
        }
