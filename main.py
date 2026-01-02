#!/usr/bin/env python3
"""
晨曦Origins Agent后端主程序入口

功能：
- Gradio WebUI界面（独立启动）
- 后端服务启动（在WebUI中触发）
- FastAPI主控路由
- WebSocket流式响应
- 插件系统
- 长期记忆系统
- 弹幕监听

作者：ai猫娘晨曦团队
版本：1.0.0
"""

import asyncio
import json
import logging
import sys
import threading
import uvicorn
from pathlib import Path
from typing import Dict, Any, Optional

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 自动创建必要的目录
logs_dir = Path(__file__).parent / "logs"
logs_dir.mkdir(parents=True, exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(logs_dir / 'app.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 全局状态
backend_thread: Optional[threading.Thread] = None
backend_server = None
is_backend_running = False


class BackendManager:
    """后端服务管理器"""
    
    @staticmethod
    def start_backend(port: int = 8000):
        """启动后端服务"""
        global backend_thread, backend_server, is_backend_running
        
        if is_backend_running:
            logger.warning("后端服务已在运行")
            return False
        
        def run_server():
            global backend_server, is_backend_running
            is_backend_running = True
            
            from fastapi import FastAPI
            from fastapi.middleware.cors import CORSMiddleware
            from core.router import router as api_router
            
            app = FastAPI(title="晨曦Origins API", version="1.0.0")
            
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
            
            app.include_router(api_router, prefix="/api/v1")
            
            @app.get("/")
            async def root():
                return {"status": "running", "service": "晨曦Origins Backend"}
            
            @app.get("/health")
            async def health():
                return {"status": "healthy", "backend": is_backend_running}
            
            config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
            backend_server = uvicorn.Server(config)
            
            try:
                backend_server.run()
            except Exception as e:
                logger.error(f"后端服务错误: {e}")
            finally:
                is_backend_running = False
        
        backend_thread = threading.Thread(target=run_server, daemon=True)
        backend_thread.start()
        
        logger.info(f"后端服务启动中: 端口 {port}")
        return True
    
    @staticmethod
    def stop_backend():
        """停止后端服务"""
        global backend_server, is_backend_running
        
        if backend_server and is_backend_running:
            backend_server.should_exit = True
            logger.info("后端服务停止中...")
            return True
        return False
    
    @staticmethod
    def get_status() -> Dict:
        """获取后端状态"""
        return {
            "is_running": is_backend_running
        }


# 启动后端（默认不启动，由WebUI控制）
def start_backend_only(port: int = 8000):
    """仅启动后端服务（无WebUI）"""
    BackendManager.start_backend(port)
    
    # 保持主线程运行
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        BackendManager.stop_backend()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="晨曦Origins Agent")
    parser.add_argument("--nui", action="store_true", help="不启动WebUI界面")
    parser.add_argument("--port", type=int, default=8000, help="后端服务端口")
    parser.add_argument("--webui-port", type=int, default=7860, help="WebUI端口")
    
    args = parser.parse_args()
    
    if not args.nui:
        # 启动WebUI（默认）
        from webui.app import create_gradio_app_with_backend
        
        config = {}
        
        app = create_gradio_app_with_backend(config, args.webui_port)
        app.launch(host="0.0.0.0", port=args.webui_port, share=True)
    else:
        # 仅启动后端
        start_backend_only(args.port)
