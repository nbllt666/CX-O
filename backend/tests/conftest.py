import asyncio
import atexit
import os
import shutil
from typing import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from backend.api.app import app
from config.settings import settings

AGENTS_CONFIG_PATH = "data/agents.json"
AGENTS_BACKUP_PATH = "data/agents.json.backup"
_backup_created = False


def _restore_agents():
    """Restore agents.json from backup if exists."""
    global _backup_created
    if _backup_created and os.path.exists(AGENTS_BACKUP_PATH):
        try:
            shutil.copy2(AGENTS_BACKUP_PATH, AGENTS_CONFIG_PATH)
            os.remove(AGENTS_BACKUP_PATH)
        except Exception:
            pass
        _backup_created = False


def _cleanup_alarm_manager():
    """Cleanup alarm manager to prevent logging errors after tests."""
    try:
        from backend.core.alarm.manager import reset_alarm_manager

        reset_alarm_manager()
    except Exception:
        pass


atexit.register(_restore_agents)
atexit.register(_cleanup_alarm_manager)


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    """Create a test client for the FastAPI app."""
    global _backup_created

    os.makedirs("data", exist_ok=True)

    if os.path.exists(AGENTS_CONFIG_PATH):
        shutil.copy2(AGENTS_CONFIG_PATH, AGENTS_BACKUP_PATH)
        _backup_created = True

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        _restore_agents()


@pytest.fixture(scope="session")
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture(scope="function")
def mock_settings():
    """Provide test settings."""
    return {
        "llm": {
            "main": {"model": "test-model", "api_key": "test-key"},
            "embedding": {"model": "test-embedding", "api_key": "test-key"},
        },
        "memory": {"db_path": ":memory:", "vector_store_type": "memory"},
    }
