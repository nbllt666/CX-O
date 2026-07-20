"""
标记适配器
将内部标记格式转换为统一的消息格式
"""
import logging
import re

from server.services.emotion_parser import EMOTION_PATTERN
from server.services.effect_parser import EFFECT_PATTERN

logger = logging.getLogger(__name__)

ACTION_PATTERN = re.compile(r'\[action:([^\]]+)\]')


class MarkerAdapter:
    def __init__(self):
        self._supported_markers = [
            "emotion", "effect", "action", "danmaku",
            "gift", "enter", "system"
        ]

    def process_danmaku(self, danmaku_data: dict) -> dict:
        result = {
            "type": "danmaku",
            "user": danmaku_data.get("user", {}),
            "content": danmaku_data.get("content", ""),
            "timestamp": danmaku_data.get("timestamp", 0),
            "markers": []
        }

        content = result["content"]

        if "[" in content and "]" in content:
            for match in EMOTION_PATTERN.finditer(content):
                result["markers"].append({
                    "type": "emotion",
                    "name": match.group(1),
                    "position": match.start()
                })

            for match in EFFECT_PATTERN.finditer(content):
                result["markers"].append({
                    "type": "effect",
                    "name": match.group(1),
                    "position": match.start()
                })

        return result

    def process_message(self, message: dict) -> dict:
        msg_type = message.get("type", "text")
        content = message.get("content", "")

        result = {
            "type": msg_type,
            "content": content,
            "markers": []
        }

        if "[" in content and "]" in content:
            for match in EMOTION_PATTERN.finditer(content):
                result["markers"].append({
                    "type": "emotion",
                    "name": match.group(1),
                    "position": match.start()
                })

            for match in EFFECT_PATTERN.finditer(content):
                result["markers"].append({
                    "type": "effect",
                    "name": match.group(1),
                    "position": match.start()
                })

            for match in ACTION_PATTERN.finditer(content):
                result["markers"].append({
                    "type": "action",
                    "name": match.group(1),
                    "position": match.start()
                })

        return result

    def get_supported_markers(self) -> list[str]:
        return self._supported_markers.copy()
