"""Memory manager unit tests."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest

from backend.core.memory.manager import MemoryManager


class TestMemoryManager:
    """Test memory manager functionality."""

    @pytest.fixture
    def memory_manager(self, tmp_path):
        """Create a memory manager with temporary database."""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(db_path=str(db_path))
        yield manager
        manager.close_all_connections()

    def test_initialization(self, memory_manager):
        """Test memory manager initialization."""
        assert memory_manager.db_path is not None
        assert memory_manager._connection_pool is not None

    def test_write_memory(self, memory_manager):
        """Test writing a memory."""
        memory_id = memory_manager.write_memory(
            content="Test memory", memory_type="long_term", importance=3
        )
        assert memory_id is not None
        assert isinstance(memory_id, int)

    def test_get_memory(self, memory_manager):
        """Test getting a memory by ID."""
        # Write a memory first
        memory_id = memory_manager.write_memory(content="Test memory", memory_type="long_term")

        # Retrieve it
        memory = memory_manager.get_memory(memory_id)
        assert memory is not None
        assert memory["content"] == "Test memory"

    def test_get_memory_not_found(self, memory_manager):
        """Test getting a non-existent memory."""
        memory = memory_manager.get_memory(999999)
        assert memory is None

    def test_update_memory(self, memory_manager):
        """Test updating a memory."""
        # Write a memory
        memory_id = memory_manager.write_memory(content="Original content", memory_type="long_term")

        # Update it
        updated = memory_manager.update_memory(memory_id, new_content="Updated content")
        assert updated is True

        # Verify update
        memory = memory_manager.get_memory(memory_id)
        assert memory["content"] == "Updated content"

    def test_delete_memory(self, memory_manager):
        """Test deleting a memory."""
        # Write a memory
        memory_id = memory_manager.write_memory(content="To be deleted", memory_type="short_term")

        # Delete it
        result = memory_manager.delete_memory(memory_id)
        assert result is True

        # Verify it's gone (soft delete)
        memory = memory_manager.get_memory(memory_id)
        assert memory is None

    def test_search_memories(self, memory_manager):
        """Test searching memories."""
        # Write memories
        memory_manager.write_memory(content="Python programming")
        memory_manager.write_memory(content="JavaScript coding")
        memory_manager.write_memory(content="Machine learning")

        # Search
        results = memory_manager.search_memories("python")
        assert isinstance(results, list)

    def test_memory_importance_levels(self, memory_manager):
        """Test different importance levels."""
        for importance in range(1, 6):
            memory_id = memory_manager.write_memory(
                content=f"Importance {importance}", importance=importance
            )
            assert memory_id is not None
            memory = memory_manager.get_memory(memory_id)
            assert memory["importance"] == importance

    def test_memory_timestamps(self, memory_manager):
        """Test memory timestamps."""
        memory_id = memory_manager.write_memory(content="Test")
        memory = memory_manager.get_memory(memory_id)

        assert "created_at" in memory

        # Parse timestamp
        created = datetime.fromisoformat(memory["created_at"])
        assert isinstance(created, datetime)

    def test_get_memory_statistics(self, memory_manager):
        """Test getting memory statistics."""
        # Write memories of different types
        memory_manager.write_memory(content="Long", memory_type="long_term")
        memory_manager.write_memory(content="Short", memory_type="short_term")
        memory_manager.write_memory(content="Permanent", memory_type="permanent")

        stats = memory_manager.get_memory_statistics()
        assert "total_memories" in stats
        assert stats["total_memories"] >= 3
