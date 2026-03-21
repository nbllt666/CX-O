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
    
    def generate_marker_prompt(self, supported_markers: list, marker_config: dict) -> str:
        """根据前端支持的标记类型生成对应的提示词"""
        prompt_parts = []
        
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
