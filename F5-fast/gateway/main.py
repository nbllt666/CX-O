"""
FastAPI Gateway Main Entry Point.

This module provides the main FastAPI application for the TTS Gateway service,
including CORS middleware, router registration, and inference client initialization.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import tts, websocket
from services.inference_client import F5TTSClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

inference_client: F5TTSClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager for startup and shutdown events.
    
    Initializes the inference client on startup and cleans up resources on shutdown.
    """
    global inference_client
    logger.info("Initializing inference client...")
    
    try:
        inference_client = F5TTSClient()
        
        health = await inference_client.health_check()
        if health.get("service_live"):
            logger.info(f"Inference client connected successfully: {health}")
        else:
            logger.warning(f"Inference service not ready: {health}")
    except Exception as e:
        logger.error(f"Failed to initialize inference client: {e}")
        inference_client = None
    
    yield
    
    logger.info("Shutting down inference client...")
    if inference_client is not None:
        await inference_client.async_close()
    inference_client = None


app = FastAPI(
    title="TTS Gateway",
    description="FastAPI Gateway for Text-to-Speech services with inference service",
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

app.include_router(tts.router, prefix="/api/v1/tts", tags=["TTS"])
app.include_router(websocket.router, prefix="/ws", tags=["WebSocket"])


@app.get("/health", summary="Health Check", description="Check if the service is healthy")
async def health_check() -> dict[str, str]:
    """
    Health check endpoint.
    
    Returns:
        dict: Health status of the service
    """
    inference_status = "connected" if inference_client is not None else "disconnected"
    return {
        "status": "healthy",
        "inference_service": inference_status,
    }


def get_inference_client() -> F5TTSClient:
    """
    Get the global inference client instance.
    
    Returns:
        F5TTSClient: The inference client instance
    
    Raises:
        RuntimeError: If the client is not initialized
    """
    if inference_client is None:
        raise RuntimeError("Inference client not initialized")
    return inference_client


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )
