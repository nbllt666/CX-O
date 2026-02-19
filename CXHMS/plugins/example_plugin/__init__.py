"""
示例插件

展示了如何创建一个CXHMS插件
"""
from typing import Dict, Any
from backend.core.plugins.models import HookType, PluginEvent, PluginResult
from backend.core.plugins.context import PluginContext


class Plugin:
    """插件主类"""
    
    def __init__(self):
        self.context: PluginContext = None
        self.enabled_features = []
        self.log_level = "info"
    
    def initialize(self, context: PluginContext):
        """插件初始化"""
        self.context = context
        
        # 读取配置
        self.enabled_features = context.get_config("enabled_features", [])
        self.log_level = context.get_config("log_level", "info")
        
        context.log_info(f"示例插件已初始化")
        context.log_info(f"启用功能: {self.enabled_features}")
    
    def shutdown(self):
        """插件关闭"""
        if self.context:
            self.context.log_info("示例插件已关闭")
    
    def on_config_change(self, new_config: Dict[str, Any]):
        """配置变更通知"""
        if "log_level" in new_config:
            self.log_level = new_config["log_level"]
            self.context.log_info(f"日志级别已更新: {self.log_level}")
    
    def get_hooks(self) -> Dict[HookType, Any]:
        """返回钩子处理函数"""
        return {
            HookType.MEMORY_CREATED: self.on_memory_created,
            HookType.CHAT_AFTER: self.on_chat_after,
            HookType.SESSION_CREATED: self.on_session_created,
        }
    
    async def on_memory_created(self, event: PluginEvent) -> PluginResult:
        """记忆创建钩子"""
        memory_data = event.data
        
        if "logging" in self.enabled_features:
            self.context.log_info(f"新记忆已创建: {memory_data.get('content', '')[:50]}...")
        
        # 可以修改数据
        return PluginResult(
            success=True,
            data={"processed": True},
            modified=False
        )
    
    async def on_chat_after(self, event: PluginEvent) -> PluginResult:
        """聊天结束后钩子"""
        chat_data = event.data
        
        if "notification" in self.enabled_features:
            self.context.log_info(f"聊天完成，Token使用: {chat_data.get('tokens_used', 0)}")
        
        return PluginResult(success=True)
    
    async def on_session_created(self, event: PluginEvent) -> PluginResult:
        """会话创建钩子"""
        session_data = event.data
        self.context.log_info(f"新会话已创建: {session_data.get('session_id', 'unknown')}")
        
        return PluginResult(success=True)
