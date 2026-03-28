"""
前端标记适配器 - 根据前端配置动态生成提示词
"""
import logging

logger = logging.getLogger(__name__)


class MarkerAdapter:
    _instance = None
    
    def __init__(self):
        self.client_marker_config = {}
        
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def set_client_config(self, client_id: str, supported_markers: list, marker_config: dict):
        """设置客户端的标记配置"""
        self.client_marker_config[client_id] = {
            "supported_markers": supported_markers,
            "marker_config": marker_config
        }
    
    def get_client_config(self, client_id: str) -> dict:
        """获取客户端的标记配置"""
        return self.client_marker_config.get(client_id, {
            "supported_markers": [],
            "marker_config": {}
        })
    
    def generate_marker_prompt(self, supported_markers: list, marker_config: dict, include_interrupt_rules: bool = False) -> str:
        """根据前端支持的标记类型生成对应的提示词

        Args:
            supported_markers: 支持的标记类型列表
            marker_config: 标记配置
            include_interrupt_rules: 是否包含打断判断规则（用于双工模式）
        """
        prompt_parts = []
        
        # 打断判断规则（双工模式）
        if include_interrupt_rules:
            prompt_parts.append("""
## 打断判断规则
当前 TTS 正在播报时，用户可能会说话打断。根据以下规则判断：

1. CONTINUE（用户没有说完）→ 不打断，不添加到上下文
   - 用户还在组织语言
   - 用户在思考
   - 用户在说一半的句子

2. IGNORE（不用回复）→ 不打断，但添加到上下文
   - 用户只是自言自语
   - 用户在表达情绪（如"哈哈哈"）
   - 用户在说背景对话
   - 不需要回应的内容

3. INTERRUPT（回复）→ 打断并添加到上下文
   - 用户明确提问
   - 用户在呼叫助手
   - 用户需要实质性回复

判断结果通过以下标记返回：
- ##[CONTINUE]## → 继续播报，不添加到上下文
- ##[IGNORE]## → 不回复，添加到上下文
- ##[INTERRUPT]## → 打断并回复，添加到上下文
""")
        
        # Live2D 动作标记
        if "live2d" in supported_markers:
            live2d_config = marker_config.get("live2d", {})
            actions = live2d_config.get("actions", ["wave", "jump", "dance", "idle"])
            default_duration = live2d_config.get("default_duration", 2000)
            
            prompt_parts.append(f"""
## Live2D 动作标记
你可以在回复中使用 Live2D 动作标记来控制虚拟形象的动作。

可用动作: {', '.join(actions)}
格式: ##[live2d:动作名:duration=毫秒]##
示例: ##[live2d:wave:duration={default_duration}]##你好！

注意：动作标记应该放在需要触发动作的文本之前。
""")
        
        # 情感标记
        if "emotion" in supported_markers:
            emotion_config = marker_config.get("emotion", {})
            emotions = emotion_config.get("types", ["happy", "sad", "angry"])
            default_intensity = emotion_config.get("default_intensity", 0.5)
            
            prompt_parts.append(f"""
## 情感标记
你可以在回复中使用情感标记来表达不同的情感。

可用情感: {', '.join(emotions)}
格式: ##[emotion:情感名:intensity=0.0-1.0]##
示例: ##[emotion:happy:intensity={default_intensity}]##太棒了！

注意：情感标记应该放在需要表达情感的文本之前。
""")
        
        # 前端特效标记
        if "effect" in supported_markers:
            effect_config = marker_config.get("effect", {})
            effects = effect_config.get("effects", ["fireworks", "hearts"])
            
            prompt_parts.append(f"""
## 前端特效标记
你可以在回复中使用特效标记来触发前端视觉效果。

可用特效: {', '.join(effects)}
格式: ##[effect:特效名:duration=毫秒]##
示例: ##[effect:fireworks]##生日快乐！
""")
        
        # 自定义动作标记
        if "custom" in supported_markers:
            custom_config = marker_config.get("custom", {})
            custom_actions = custom_config.get("actions", [])
            
            if custom_actions:
                prompt_parts.append(f"""
## 自定义动作标记
你可以在回复中使用自定义动作标记。

可用动作: {', '.join(custom_actions)}
格式: ##[custom:动作名:param=value]##
""")
        
        return "\n".join(prompt_parts)
