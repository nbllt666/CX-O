"""
CX-O Gateway 主入口
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager

import uvicorn

from gateway.config import get_config, load_config
from gateway.server import create_app, manager
from gateway.health import health_checker
from services.cxhms_client import CXHMSClient
from services.asr_client import ASRClient
from services.tts_client import TTSClient
from handlers import register_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

cxhms_client: CXHMSClient | None = None
asr_client: ASRClient | None = None
tts_client: TTSClient | None = None


@asynccontextmanager
async def lifespan(app):
    global cxhms_client, asr_client, tts_client
    
    config = get_config()
    
    logger.info("Starting CX-O Gateway...")
    
    cxhms_client = CXHMSClient(config.services.cxhms.url)
    asr_client = ASRClient(config.services.asr.url)
    
    tts_config = config.services.tts
    tts_client = TTSClient(
        base_url=tts_config.url,
        ref_audio_path=getattr(tts_config, 'ref_audio_path', ''),
        ref_text=getattr(tts_config, 'ref_text', ''),
        timeout=tts_config.timeout
    )
    
    await cxhms_client.connect()
    health_checker.update_status("cxhms", "healthy")
    
    register_handlers(manager, cxhms_client, asr_client, tts_client)
    
    logger.info("CX-O Gateway started successfully")
    
    yield
    
    logger.info("Shutting down CX-O Gateway...")
    
    if cxhms_client:
        await cxhms_client.disconnect()
    if asr_client:
        await asr_client.close()
    if tts_client:
        await tts_client.close()
    
    logger.info("CX-O Gateway shutdown complete")


app = create_app()


def run():
    config = load_config()
    uvicorn.run(
        "main:app",
        host=config.gateway.host,
        port=config.gateway.port,
        reload=False,
        log_level=config.logging.level.lower()
    )


if __name__ == "__main__":
    run()
