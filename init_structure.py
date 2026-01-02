#!/usr/bin/env python3
"""
初始化晨曦Origins项目目录结构
"""

from pathlib import Path
import os

def create_project_structure():
    """创建项目目录结构"""
    
    base_path = Path(__file__).parent
    
    directories = [
        # 核心模块
        "core/memory",
        
        # LLM服务
        "llm",
        
        # 音频处理
        "audio",
        
        # 插件系统
        "plugins",
        
        # 数据库
        "database",
        
        # WebUI
        "webui/pages",
        "webui/components",
        
        # 数据存储
        "data/contexts/sessions",
        "data/danmaku_cache",
        "data/effects",
        
        # Qdrant向量存储
        "qdrant_storage",
    ]
    
    for dir_path in directories:
        full_path = base_path / dir_path
        full_path.mkdir(parents=True, exist_ok=True)
        print(f"创建目录: {full_path}")
    
    print("\n项目目录结构创建完成！")

if __name__ == "__main__":
    create_project_structure()
