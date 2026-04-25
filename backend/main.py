"""
CXHMS 后端服务主入口
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from config.settings import settings


def main():
    """启动后端服务"""
    host = getattr(settings.config.system, 'host', '0.0.0.0')
    port = getattr(settings.config.system, 'port', 8100)
    log_level = settings.config.system.log_level.lower()

    uvicorn.run(
        "backend.api.app:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=False,
        factory=False,
    )


if __name__ == "__main__":
    main()
