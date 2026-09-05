"""
CX-O-VoiceWorkStation 作曲/翻唱CXFC 服务

瘦身后职责（spec：split-audio-workstation-cxfc-modelstation）：
- 作曲/歌曲合成：/api/music/*（score/validate、import-musicxml、synthesize、tasks、songs、drafts）
- 翻唱变声：/api/sovits-svc/infer（推理）与 /api/sovits-svc/models（模型列表，只读）
- 受控上传：POST /api/audio-uploads（翻唱音频入口，落盘 infer 白名单根）
- 音频文件服务：/api/audio-files/*（songs + svc-results）
- CXFC 插件：/tools /skills /call（面向 agent 的作曲演唱工具面）

训练全链路（preprocess/train/stop/status）、数据集、批量语料与 workflow API
已迁至 CXO-ModelStation（端口 8300）。
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
    logger.info("Starting CX-O-VoiceWorkStation (作曲/翻唱CXFC)...")
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
    """关闭后台 HTTP 客户端单例等资源。每个清理步骤独立 try/except，
    确保单点失败不阻塞后续清理。（训练子进程清理已随训练域迁出）"""
    # 停止 CXFC 心跳并向 CX-O-SERVER 注销插件
    try:
        from workstation.services import cxfc_registration
        await cxfc_registration.stop_registration()
    except Exception as e:
        logger.warning(f"Shutdown: failed to stop CXFC registration: {e}")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="CX-O-VoiceWorkStation 作曲/翻唱CXFC",
        description="CX-O 作曲/翻唱CXFC服务 - 歌谱编辑、歌曲合成、SVC 翻唱变声推理、CXFC 演唱工具",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS 白名单从配置读取（默认前端管理界面来源 + file:// 源，可用
    # CXO_VWS_CORS_ORIGINS 覆盖）；不再放开 "*"——服务含文件/上传接口，
    # 任意源可读会造成跨站读取风险。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from workstation.api.sovits_svc import router as sovits_svc_router
    from workstation.api.audio_files import router as audio_files_router
    from workstation.api.audio_uploads import router as audio_uploads_router
    from workstation.api.music import router as music_router
    from workstation.api.cxfc_plugin import router as cxfc_plugin_router

    app.include_router(sovits_svc_router, prefix="/api/sovits-svc", tags=["So-VITS-SVC 推理"])
    app.include_router(audio_files_router, prefix="/api/audio-files", tags=["音频文件服务"])
    app.include_router(audio_uploads_router, prefix="/api/audio-uploads", tags=["受控音频上传"])
    app.include_router(music_router, prefix="/api/music", tags=["音乐作曲与演唱"])
    # CXFC 插件端点挂在根路径（/tools、/skills、/call），CX-O-SERVER 按 host:port 直连抓取
    app.include_router(cxfc_plugin_router, tags=["CXFC 插件"])

    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "service": "CX-O-VoiceWorkStation 作曲/翻唱CXFC",
            "name": settings.cxfc.plugin_name,
            "version": "1.0.0",
        }

    return app


app = create_app()


def main():
    settings = get_settings()
    host = getattr(settings.server, 'host', '127.0.0.1')
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
