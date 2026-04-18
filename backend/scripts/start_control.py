#!/usr/bin/env python3
"""
CXHMS 控制服务启动脚本
"""
import os
import sys

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import uvicorn

if __name__ == "__main__":
    print("=" * 50)
    print("CXHMS Control Service")
    print("控制服务地址: http://localhost:8765")
    print("用于控制主后端服务的启动/停止/重启")
    print("=" * 50)

    uvicorn.run("control_service:app", host="0.0.0.0", port=8765, log_level="info", reload=False)
