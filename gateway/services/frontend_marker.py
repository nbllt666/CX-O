"""
前端标记解析器 - 解析 LLM 输出中的标记
"""
import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class FrontendMarkerParser:
    """解析 LLM 输出中的前端标记"""
    
    MARKER_PATTERN = re.compile(r'##\[([^\]]+)\]##')
    
    @classmethod
    def parse(cls, text: str) -> List[Dict[str, Any]]:
        """
        解析文本中的标记
        返回: [
            {"type": "text", "content": "文本内容"},
            {"type": "marker", "marker_type": "live2d", "action": "wave", "params": {...}},
            {"type": "text", "content": "文本内容"},
            ...
        ]
        """
        segments = []
        last_end = 0
        
        for match in cls.MARKER_PATTERN.finditer(text):
            # 添加标记前的文本
            if match.start() > last_end:
                content = text[last_end:match.start()]
                if content:
                    segments.append({
                        "type": "text",
                        "content": content
                    })
            
            # 解析标记
            marker_content = match.group(1)
            marker_info = cls._parse_marker(marker_content)
            
            if marker_info:
                segments.append({
                    "type": "marker",
                    "marker_type": marker_info["marker_type"],
                    "action": marker_info["action"],
                    "params": marker_info["params"]
                })
            
            last_end = match.end()
        
        # 添加剩余文本
        if last_end < len(text):
            remaining = text[last_end:]
            if remaining:
                segments.append({
                    "type": "text",
                    "content": remaining
                })
        
        return segments
    
    @classmethod
    def _parse_marker(cls, marker_content: str) -> Dict[str, Any]:
        """解析单个标记内容"""
        parts = marker_content.split(":")
        
        if len(parts) < 2:
            logger.warning(f"Invalid marker format: {marker_content}")
            return None
        
        marker_type = parts[0]
        action = parts[1]
        params = {}
        
        # 解析参数
        for part in parts[2:]:
            if "=" in part:
                key, value = part.split("=", 1)
                # 尝试转换数值类型
                try:
                    if "." in value:
                        value = float(value)
                    else:
                        value = int(value)
                except ValueError:
                    pass
                params[key] = value
        
        return {
            "marker_type": marker_type,
            "action": action,
            "params": params
        }
    
    @classmethod
    def extract_markers(cls, text: str) -> List[Dict[str, Any]]:
        """提取所有标记"""
        segments = cls.parse(text)
        return [s for s in segments if s.get("type") == "marker"]
    
    @classmethod
    def remove_markers(cls, text: str) -> str:
        """移除文本中的标记（保留纯文本）"""
        return cls.MARKER_PATTERN.sub("", text)
    
    @classmethod
    def split_for_tts(cls, text: str) -> List[Dict[str, Any]]:
        """
        分割文本用于 TTS 播报
        返回: [
            {"text": "文本", "marker": 标记或None},
            ...
        ]
        """
        segments = cls.parse(text)
        result = []
        
        for segment in segments:
            if segment["type"] == "text" and segment["content"].strip():
                result.append({
                    "text": segment["content"],
                    "marker": None
                })
            elif segment["type"] == "marker":
                # 将标记附加到前一个文本段
                if result:
                    result[-1]["marker"] = segment
                else:
                    # 开头就是标记，创建一个空文本段
                    result.append({
                        "text": "",
                        "marker": segment
                    })
        
        return result
