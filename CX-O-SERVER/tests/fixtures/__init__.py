"""测试数据 fixtures 包（CX-O-SERVER 测试基础设施 Phase 1）。

本包承载标准 JSON 测试数据文件，供后续批次补测直接加载使用：
- ``mock_config.json``：标准 mock 配置（system/gateway/asr/tts/llm/database/memory/graph）
- ``mock_chat_message.json``：标准 chat message（user/assistant 角色）
- ``mock_agent_context.json``：标准 agent context（含 messages 列表）

加载方式：
    from tests.conftest import load_fixture_json
    data = load_fixture_json("mock_config.json")
"""

from __future__ import annotations

import os
import json
from typing import Any, Dict

_FIXTURES_DIR = os.path.dirname(os.path.abspath(__file__))


def load_fixture(filename: str) -> Dict[str, Any]:
    """加载本目录下的 JSON 测试数据文件。

    Args:
        filename: 文件名，如 ``mock_config.json``

    Returns:
        解析后的字典
    """
    file_path = os.path.join(_FIXTURES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


__all__ = ["load_fixture"]
