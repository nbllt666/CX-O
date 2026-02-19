from typing import Dict, List


def format_messages_for_summary(messages: List[Dict], max_content_length: int = 500) -> str:
    lines = []
    for i, msg in enumerate(messages, 1):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if len(content) > max_content_length:
            content = content[:max_content_length] + "..."
        lines.append(f"[{i}] {role}: {content}")
    return "\n".join(lines)
