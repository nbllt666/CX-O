"""Test vector sync functionality."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from backend.core.memory.manager import MemoryManager


class TestAutoVectorSync:
    """Test automatic vector synchronization."""

    @pytest.fixture
    def memory_manager(self, tmp_path):
        """Create a memory manager with temporary database."""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(db_path=str(db_path))
        yield manager
        manager.close_all_connections()

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        store = MagicMock()
        store.is_available = Mock(return_value=True)
        store.add_memory_vector = AsyncMock(return_value=True)
        store.delete_by_memory_id = AsyncMock(return_value=True)
        store.get_collection_info = Mock(return_value={"count": 0})
        return store

    @pytest.fixture
    def mock_embedding_model(self):
        """Create a mock embedding model."""
        model = MagicMock()
        model.dimension = 768
        model.get_embedding = AsyncMock(return_value=[0.1] * 768)
        return model

    def test_write_memory_syncs_to_vector_store(
        self, memory_manager, mock_vector_store, mock_embedding_model
    ):
        """Test that writing a memory syncs to vector store."""
        memory_manager._vector_store = mock_vector_store
        memory_manager._embedding_model = mock_embedding_model

        memory_id = memory_manager.write_memory(
            content="Test memory for vector sync", memory_type="long_term"
        )

        assert memory_id is not None
        mock_embedding_model.get_embedding.assert_called_once_with("Test memory for vector sync")
        mock_vector_store.add_memory_vector.assert_called_once()

    def test_write_memory_without_vector_store(self, memory_manager):
        """Test that writing works without vector store."""
        memory_manager._vector_store = None
        memory_manager._embedding_model = None

        memory_id = memory_manager.write_memory(
            content="Test memory without vector store", memory_type="long_term"
        )

        assert memory_id is not None

    def test_write_memory_vector_sync_failure_does_not_affect_sqlite(
        self, memory_manager, mock_vector_store, mock_embedding_model
    ):
        """Test that vector sync failure doesn't affect SQLite write."""
        mock_embedding_model.get_embedding = AsyncMock(side_effect=Exception("Embedding failed"))
        memory_manager._vector_store = mock_vector_store
        memory_manager._embedding_model = mock_embedding_model

        memory_id = memory_manager.write_memory(
            content="Test memory with sync failure", memory_type="long_term"
        )

        assert memory_id is not None
        memory = memory_manager.get_memory(memory_id)
        assert memory is not None
        assert memory["content"] == "Test memory with sync failure"

    def test_update_memory_syncs_to_vector_store(
        self, memory_manager, mock_vector_store, mock_embedding_model
    ):
        """Test that updating a memory syncs to vector store."""
        memory_manager._vector_store = mock_vector_store
        memory_manager._embedding_model = mock_embedding_model

        memory_id = memory_manager.write_memory(content="Original content", memory_type="long_term")

        mock_vector_store.reset_mock()
        mock_embedding_model.reset_mock()

        result = memory_manager.update_memory(memory_id, new_content="Updated content")

        assert result is True
        mock_embedding_model.get_embedding.assert_called_once_with("Updated content")
        mock_vector_store.delete_by_memory_id.assert_called_once()
        mock_vector_store.add_memory_vector.assert_called_once()

    def test_update_memory_without_content_change_no_vector_sync(
        self, memory_manager, mock_vector_store, mock_embedding_model
    ):
        """Test that updating without content change doesn't trigger vector sync."""
        memory_manager._vector_store = mock_vector_store
        memory_manager._embedding_model = mock_embedding_model

        memory_id = memory_manager.write_memory(content="Original content", memory_type="long_term")

        mock_vector_store.reset_mock()
        mock_embedding_model.reset_mock()

        result = memory_manager.update_memory(memory_id, new_importance=5)

        assert result is True
        mock_embedding_model.get_embedding.assert_not_called()
        mock_vector_store.add_memory_vector.assert_not_called()

    def test_delete_memory_syncs_to_vector_store(
        self, memory_manager, mock_vector_store, mock_embedding_model
    ):
        """Test that deleting a memory syncs to vector store."""
        memory_manager._vector_store = mock_vector_store
        memory_manager._embedding_model = mock_embedding_model

        memory_id = memory_manager.write_memory(content="Memory to delete", memory_type="long_term")

        mock_vector_store.reset_mock()

        result = memory_manager.delete_memory(memory_id)

        assert result is True
        mock_vector_store.delete_by_memory_id.assert_called_once_with(memory_id)

    def test_delete_memory_vector_sync_failure_does_not_affect_sqlite(
        self, memory_manager, mock_vector_store, mock_embedding_model
    ):
        """Test that vector delete failure doesn't affect SQLite delete."""
        mock_vector_store.delete_by_memory_id = AsyncMock(side_effect=Exception("Delete failed"))
        memory_manager._vector_store = mock_vector_store
        memory_manager._embedding_model = mock_embedding_model

        memory_id = memory_manager.write_memory(
            content="Memory to delete with failure", memory_type="long_term"
        )

        result = memory_manager.delete_memory(memory_id)

        assert result is True
        memory = memory_manager.get_memory(memory_id)
        assert memory is None


class TestVectorSyncHelpers:
    """Test vector sync helper methods."""

    @pytest.fixture
    def memory_manager(self, tmp_path):
        """Create a memory manager with temporary database."""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(db_path=str(db_path))
        yield manager
        manager.close_all_connections()

    def test_run_async_sync_with_no_running_loop(self, memory_manager):
        """Test _run_async_sync when no event loop is running."""

        async def async_func():
            return "async_result"

        result = memory_manager._run_async_sync(async_func())
        assert result == "async_result"

    def test_sync_vector_for_memory_returns_false_without_store(self, memory_manager):
        """Test _sync_vector_for_memory returns False without vector store."""
        memory_manager._vector_store = None
        memory_manager._embedding_model = MagicMock()

        result = memory_manager._sync_vector_for_memory(1, "test content")
        assert result is False

    def test_sync_vector_for_memory_returns_false_without_embedding(self, memory_manager):
        """Test _sync_vector_for_memory returns False without embedding model."""
        memory_manager._vector_store = MagicMock()
        memory_manager._embedding_model = None

        result = memory_manager._sync_vector_for_memory(1, "test content")
        assert result is False

    def test_update_vector_for_memory_deletes_first(self, memory_manager):
        """Test _update_vector_for_memory deletes old vector before adding new."""
        mock_store = MagicMock()
        mock_store.add_memory_vector = AsyncMock(return_value=True)
        mock_store.delete_by_memory_id = AsyncMock(return_value=True)

        mock_embedding = MagicMock()
        mock_embedding.get_embedding = AsyncMock(return_value=[0.1] * 768)

        memory_manager._vector_store = mock_store
        memory_manager._embedding_model = mock_embedding

        result = memory_manager._update_vector_for_memory(1, "new content")

        assert result is True
        mock_store.delete_by_memory_id.assert_called_once_with(1)
        mock_store.add_memory_vector.assert_called_once()

    def test_delete_vector_for_memory_returns_false_without_store(self, memory_manager):
        """Test _delete_vector_for_memory returns False without vector store."""
        memory_manager._vector_store = None

        result = memory_manager._delete_vector_for_memory(1)
        assert result is False
