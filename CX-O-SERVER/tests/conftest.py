"""共享 pytest fixtures（CX-O-SERVER 测试基础设施 Phase 1）。

本文件为后续 4 批补测提供可复用的 fixtures：
- ``tmp_config_dir``：基于 tmp_path 的临时配置目录
- ``mock_config``：标准 mock 配置字典（覆盖 system/gateway/asr/tts/llm/database/memory/graph 等）
- ``mock_env_clean``：autouse，清理 CXO_ 前缀环境变量，保证测试隔离
- ``mock_agent_context_manager``：基于 tmp_path 的独立 AgentContextManager 实例
- ``mock_chat_message``：标准 chat message 字典（role/content/metadata）

设计约束：
1. 不修改 ``server/`` 下任何业务代码
2. 不破坏现有 ``test_agent_context_manager.py`` / ``test_emotion_parser.py``
3. server 相关导入采用懒加载，避免在收集阶段强制拉起完整服务
4. 使用 pytest 标准 fixtures（tmp_path / monkeypatch 等）

路径解析遵循 AC范式 rules（基于 ``os.path.dirname(os.path.abspath(__file__))`` 解析，禁止相对路径字面量）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# 路径常量（基于 __file__ 解析，禁止 "../../" 字面量）
# ---------------------------------------------------------------------------
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_FIXTURES_DIR = os.path.join(_TESTS_DIR, "fixtures")


# ---------------------------------------------------------------------------
# 1. mock_env_clean —— autouse，清理 CXO_ 前缀环境变量
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mock_env_clean(monkeypatch: pytest.MonkeyPatch):
    """清理所有 CXO_ 前缀环境变量，保证测试隔离。

    autouse 作用于全部测试。使用 monkeypatch 自动还原，不影响外部真实环境。
    现有两个测试文件均不依赖 CXO_ 环境变量，故不会回归。
    """
    for key in list(os.environ.keys()):
        if key.startswith("CXO_"):
            monkeypatch.delenv(key, raising=False)
    yield


# ---------------------------------------------------------------------------
# 2. tmp_config_dir —— 临时配置目录
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """返回基于 tmp_path 的临时配置目录（已创建）。

    可用于写入临时 config.json 或作为存储目录。
    """
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir


# ---------------------------------------------------------------------------
# 3. mock_config —— 标准 mock 配置字典
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_config() -> Dict[str, Any]:
    """返回标准 mock 配置字典。

    覆盖 system/gateway/asr/tts/llm/database/memory/graph 等基础字段，
    可作为 ``UnifiedConfig`` 的输入或写入临时 config.json。
    字段与 ``server/config.py`` 的配置模型对齐。
    """
    return {
        "system": {
            "host": "127.0.0.1",
            "port": 8000,
            "debug": False,
            "log_level": "INFO",
            "workers": 1,
        },
        "gateway": {
            "host": "127.0.0.1",
            "port": 8000,
            "cors": {
                "allow_origins": ["*"],
                "allow_methods": ["*"],
                "allow_headers": ["*"],
                "allow_credentials": True,
            },
        },
        "asr": {
            "mode": "remote",
            "model_dir": "SenseVoiceSmall",
            "device": "cpu",
            "remote_url": "http://127.0.0.1:8001",
            "language": "auto",
        },
        "tts": {
            "mode": "remote",
            "model_dir": "F5TTS_v1_Base",
            "device": "cpu",
            "remote_url": "http://127.0.0.1:5000",
            "ref_audio_path": "",
            "ref_text": "",
            "speed": 1.0,
            "cross_fade_duration": 0.15,
            "emotion_enabled": True,
            "effects_enabled": True,
        },
        "llm": {
            "provider": "ollama",
            "host": "http://localhost:11434",
            "model": "qwen3:latest",
            "temperature": 0.7,
            "max_tokens": 32768,
            "stream": True,
            "api_key": None,
        },
        "database": {
            "path": "data/test_cxo.db",
            "memories_db": "data/test_memories.db",
            "sessions_db": "data/test_sessions.db",
            "acp_db": "data/test_acp",
            "pool_size": 5,
            "max_overflow": 10,
        },
        "memory": {
            "decay_enabled": True,
            "batch_interval": 3600,
            "permanent_threshold": 0.95,
            "max_short_term_age_days": 7,
            "max_long_term_age_days": 365,
            "vector_enabled": False,
            "vector_backend": "weaviate",
            "embedding_provider": "ollama",
            "embedding_model": "nomic-embed-text",
            "embedding_api_base": "",
            "embedding_api_key": None,
            "archive_enabled": True,
            "dedup_threshold": 0.85,
            "archive_compression_enabled": True,
        },
        "graph": {
            "enabled": False,
            "database_path": "data/test_graph.db",
            "auto_create_schema": True,
            "pool_size": 5,
            "timeout": 30,
        },
        "cors": {
            "enabled": True,
            "origins": ["*"],
            "allow_credentials": True,
        },
        "vector": {
            "enabled": False,
            "host": "localhost",
            "port": 6333,
            "collection_name": "cxo_memories",
            "embedding_model": "nomic-embed-text",
            "embedding_dimension": 768,
            "api_key": None,
        },
        "logging": {
            "level": "INFO",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "file": None,
            "max_bytes": 10485760,
            "backup_count": 5,
        },
    }


@pytest.fixture
def mock_config_file(tmp_config_dir: Path, mock_config: Dict[str, Any]) -> Path:
    """将 mock_config 写入临时 config.json 并返回路径。

    可配合 ``CXO_CONFIG`` 环境变量指向该文件以测试 ``Settings`` 加载逻辑。
    """
    cfg_path = tmp_config_dir / "config.json"
    cfg_path.write_text(
        json.dumps(mock_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cfg_path


# ---------------------------------------------------------------------------
# 4. mock_agent_context_manager —— 独立 AgentContextManager 实例
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_agent_context_manager(tmp_path: Path):
    """返回基于 tmp_path 的独立 AgentContextManager 实例。

    与现有 ``test_agent_context_manager.py`` 中的 ``manager`` fixture 同模式，
    命名区分以避免冲突。懒加载 server 模块，避免收集阶段强制导入。
    """
    from server.core.context.agent_context_manager import AgentContextManager

    storage = tmp_path / "agent_contexts"
    return AgentContextManager(storage_dir=str(storage))


# ---------------------------------------------------------------------------
# 5. mock_chat_message —— 标准 chat message 字典
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_chat_message() -> Dict[str, Any]:
    """返回标准 chat message 字典（user 角色）。

    结构与 ``AgentContextManager.append_message`` 写入的消息一致，
    含 role/content/metadata/created_at 字段。
    """
    return {
        "role": "user",
        "content": "你好，请介绍一下自己",
        "metadata": {"session_id": "test-session-001", "source": "test"},
        "created_at": "2026-07-02T10:00:00",
    }


@pytest.fixture
def mock_chat_message_assistant() -> Dict[str, Any]:
    """返回标准 chat message 字典（assistant 角色）。"""
    return {
        "role": "assistant",
        "content": "你好，我是 CX-O 智能助手，很高兴为你服务。",
        "metadata": {"session_id": "test-session-001", "model": "qwen3:latest"},
        "created_at": "2026-07-02T10:00:01",
    }


# ---------------------------------------------------------------------------
# 辅助：加载 fixtures 目录下的 JSON 测试数据
# ---------------------------------------------------------------------------
def load_fixture_json(filename: str) -> Dict[str, Any]:
    """加载 ``tests/fixtures/`` 下的 JSON 测试数据文件。

    Args:
        filename: 文件名，如 ``mock_config.json``

    Returns:
        解析后的字典
    """
    file_path = os.path.join(_FIXTURES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)
