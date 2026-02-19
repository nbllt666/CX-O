"""
CXHMS 启动脚本
支持从前端启动或独立启动
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

from backend.core.logging_config import setup_logging
from config.settings import settings


def main():
    """主函数"""
    # 初始化日志配置
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
        backup_count=(
            log_file_config.get("backup_count", 5) if isinstance(log_file_config, dict) else 5
        ),
        structured=False,
        console_colors=True,
    )

    host = settings.config.system.host
    port = settings.config.system.port
    debug = settings.config.system.debug

    print(
        f"""
╔══════════════════════════════════════════════════════╗
║              CXHMS - 晨曦人格化记忆系统                     ║
╠════════════════════════════════════════════════════════╣
║  FastAPI服务: http://{host}:{port}                       ║
║  API文档:     http://{host}:{port}/docs                  ║
║  健康检查:    http://{host}:{port}/health                 ║
╚══════════════════════════════════════════════════════════╝
    """
    )

    uvicorn.run(
        "backend.api.app:app",
        host=host,
        port=port,
        reload=debug,
        log_level=settings.config.system.log_level.lower(),
    )


if __name__ == "__main__":
    main()
