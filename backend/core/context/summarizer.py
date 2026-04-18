import json
from typing import Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class ContextSummarizer:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def set_llm_client(self, llm_client):
        self.llm_client = llm_client

    async def summarize(
        self, messages: List[Dict], max_length: int = 500, style: str = "concise"
    ) -> Dict[str, any]:
        if not messages:
            return {"summary": "", "key_points": [], "success": True}

        if self.llm_client is None:
            return self._rule_based_summary(messages, max_length, style)

        try:
            conversation_text = self._format_conversation(messages)

            prompt = f"""请对以下对话进行摘要：

{conversation_text}

要求：
1. 摘要长度不超过{max_length}字
2. 提取关键要点（3-5个）
3. 保持对话的核心内容和意图

请以JSON格式返回：
{{
    "summary": "对话摘要",
    "key_points": ["要点1", "要点2", "要点3"]
}}
"""

            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}], stream=False
            )

            import json as json_parser

            result = json_parser.loads(response)

            return {
                "summary": result.get("summary", ""),
                "key_points": result.get("key_points", []),
                "success": True,
            }

        except Exception as e:
            logger.error(f"LLM摘要生成失败: {e}")
            return self._rule_based_summary(messages, max_length, style)

    def _rule_based_summary(
        self, messages: List[Dict], max_length: int = 500, style: str = "concise"
    ) -> Dict[str, any]:
        if not messages:
            return {"summary": "", "key_points": [], "success": True}

        user_messages = [m for m in messages if m.get("role") == "user"]
        assistant_messages = [m for m in messages if m.get("role") == "assistant"]

        total_messages = len(messages)
        user_count = len(user_messages)
        assistant_count = len(assistant_messages)

        topics = []
        for msg in user_messages:
            content = msg.get("content", "")[:100]
            if content:
                topics.append(content)

        key_points = topics[:5] if topics else []

        if style == "concise":
            summary = f"对话共{total_messages}轮，包含{user_count}次用户提问和{assistant_count}次助手回复。"
        else:
            summary = f"这是一个包含{total_messages}轮对话的会话，其中用户发起了{user_count}次对话，助手做出了{assistant_count}次回应。"

        if key_points:
            summary += f" 讨论的话题包括：{'; '.join(key_points[:3])}。"

        if len(summary) > max_length:
            summary = summary[: max_length - 3] + "..."

        return {"summary": summary, "key_points": key_points, "success": True}

    def _format_conversation(self, messages: List[Dict]) -> str:
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    async def extract_key_points(self, messages: List[Dict]) -> List[str]:
        if not messages:
            return []

        try:
            if self.llm_client is None:
                return self._rule_based_key_points(messages)

            conversation_text = self._format_conversation(messages)

            prompt = f"""从以下对话中提取关键要点（不超过5个）：

{conversation_text}

请以JSON数组格式返回：
["要点1", "要点2", "要点3"]
"""

            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}], stream=False
            )

            import json as json_parser

            key_points = json_parser.loads(response)

            if isinstance(key_points, list):
                return key_points[:5]
            return []

        except Exception as e:
            logger.error(f"关键点提取失败: {e}")
            return self._rule_based_key_points(messages)

    def _rule_based_key_points(self, messages: List[Dict]) -> List[str]:
        key_points = []

        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if len(content) > 10:
                    key_points.append(content[:100])

        return key_points[:5]
