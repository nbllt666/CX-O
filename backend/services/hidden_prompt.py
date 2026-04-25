"""
隐藏提示词管理模块
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class HiddenPromptManager:
    _instance = None
    
    def __init__(self):
        self.tool_instructions = ""
        self.tools_description = ""
        
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def load_from_config(self, config: dict):
        """从配置加载隐藏提示词"""
        self.tool_instructions = config.get("tool_instructions", "")
        self.tools_description = config.get("tools", "")
    
    def get_system_prompt(self, marker_prompt: str = "", user_prompt: str = "") -> str:
        """
        获取完整的系统提示词
        合并顺序：隐藏提示词 + 标记提示词 + 用户提示词
        """
        parts = []
        
        if self.tool_instructions:
            parts.append(self.tool_instructions)
        
        if self.tools_description:
            parts.append(self.tools_description)
        
        if marker_prompt:
            parts.append(marker_prompt)
        
        if user_prompt:
            parts.append(user_prompt)
        
        return "\n\n".join(parts)
    
    def get_tool_instructions(self) -> str:
        """获取工具调用指令"""
        return self.tool_instructions
    
    def get_tools_description(self) -> str:
        """获取工具说明"""
        return self.tools_description
