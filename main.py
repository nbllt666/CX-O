"""
CX-O 项目根后端入口

真实后端运行于 CX-O-SERVER（模块包 ``server.main``），本文件仅是项目根的
便捷启动入口：将 CX-O-SERVER 加入 import 路径后，委托 ``server.main:app``
启动。不再引用已失效的 ``backend.api.app:app``，也不依赖 legacy config.settings
兼容层（直接读取 server.config 的统一配置单例）。
"""

import os
import sys

# 项目根与 CX-O-SERVER 加入 import 路径，使 server 包可导入
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_SERVER_DIR = os.path.join(_PROJECT_ROOT, "CX-O-SERVER")
sys.path.insert(0, _SERVER_DIR)
sys.path.insert(0, _PROJECT_ROOT)

import uvicorn

from server.config import get_settings


def main():
    """启动后端服务（委托真实入口 server.main:app）。"""
    settings = get_settings()
    host = getattr(settings.system, 'host', '0.0.0.0')
    port = getattr(settings.system, 'port', 8000)
    log_level = settings.system.log_level.lower()

    print(f"Starting CX-O Backend on {host}:{port}")

    uvicorn.run(
        "server.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=False,
        factory=False,
    )


if __name__ == "__main__":
    main()