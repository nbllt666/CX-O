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
    """标记适配器——将弹幕/消息中的情感、音效与动作标记提取为统一格式。"""

    def _extract_markers(self, content: str) -> list[dict]:
        """提取文本内的情感/音效标记（含起止位置）。

        process_danmaku 与 process_message 共用，消除重复的情感/音效遍历逻辑。
        """
        markers = []
        if "[" not in content or "]" not in content:
            return markers
        for match in EMOTION_PATTERN.finditer(content):
            markers.append({
                "type": "emotion",
                "name": match.group(1),
                "position": match.start(),
            })
        for match in EFFECT_PATTERN.finditer(content):
            markers.append({
                "type": "effect",
                "name": match.group(1),
                "position": match.start(),
            })
        return markers

    def process_danmaku(self, danmaku_data: dict) -> dict:
        result = {
            "type": "danmaku",
            "user": danmaku_data.get("user", {}),
            "content": danmaku_data.get("content", ""),
            "timestamp": danmaku_data.get("timestamp", 0),
            "markers": self._extract_markers(danmaku_data.get("content", "")),
        }

        return result

    def process_message(self, message: dict) -> dict:
        msg_type = message.get("type", "text")
        content = message.get("content", "")

        result = {
            "type": msg_type,
            "content": content,
            "markers": self._extract_markers(content),
        }

        if "[" in content and "]" in content:
            for match in ACTION_PATTERN.finditer(content):
                result["markers"].append({
                    "type": "action",
                    "name": match.group(1),
                    "position": match.start()
                })

        return result
