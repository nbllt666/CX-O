"""
记忆系统工具 - 提供记忆管理功能
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from .registry import tool_registry


def register_memory_tools():
    """注册记忆系统工具"""
    
    # 保存记忆工具
    tool_registry.register(
        name="save_memory",
        description="保存一条记忆到记忆系统",
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "记忆内容，要保存的信息"
                },
                "