"""Mock 工厂包（CX-O-SERVER 测试基础设施 Phase 1）。

提供可被后续批次补测直接导入使用的 mock 工厂：
- ``mock_server``：FastAPI TestClient 封装
- ``mock_memory_store``：内存版 MemoryManager mock
- ``mock_services``：mock_tts_service / mock_asr_service

设计原则：
1. mock 使用 ``unittest.mock.Mock`` / ``MagicMock`` 或轻量自实现类
2. mock 返回符合 public/schema/ 数据契约的模拟值（注：当前 schema 多为种子阶段）
3. 不依赖外部存储（数据库、向量库、网络服务）
"""

from __future__ import annotations

from tests.mocks.mock_memory_store import InMemoryMemoryStore, create_mock_memory_store
from tests.mocks.mock_server import (
    MockServerClient,
    create_mock_app,
    create_test_client,
    get_real_app_client,
)
from tests.mocks.mock_services import (
    MockASRService,
    MockTTSService,
    create_mock_asr_service,
    create_mock_tts_service,
)

__all__ = [
    "InMemoryMemoryStore",
    "create_mock_memory_store",
    "MockServerClient",
    "create_mock_app",
    "create_test_client",
    "get_real_app_client",
    "MockASRService",
    "MockTTSService",
    "create_mock_asr_service",
    "create_mock_tts_service",
]
