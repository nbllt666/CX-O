"""Test hybrid search fallback behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.memory.hybrid_search import HybridSearch, HybridSearchOptions, SearchResult
from backend.core.memory.manager import MemoryManager


class TestHybridSearchFallback:
    """Test hybrid search fallback to keyword search."""

    @pytest.fixture
    def memory_manager(self, tmp_path):
        """Create a memory manager with temporary database."""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(db_path=str(db_path))
        yield manager
        manager.close_all_connections()

    def test_hybrid_search_returns_fallback_true_when_vector_disabled(self, memory_manager):
        """Test that hybrid_search returns fallback=True when vector search is disabled."""
        import asyncio

        memory_manager._vector_store = None
        memory_manager._hybrid_search = None

        memory_manager.write_memory(content="Test memory for search")

        result = asyncio.run(memory_manager.hybrid_search(query="Test"))

        assert len(result) > 0
        assert result[0].get("fallback") is True

    def test_hybrid_search_returns_fallback_false_on_success(self, memory_manager):
        """Test that hybrid_search returns fallback=False on successful vector search."""
        import asyncio

        mock_hybrid_search = MagicMock()
        mock_hybrid_search.search = AsyncMock(
            return_value=[SearchResult(memory_id=1, content="Test", score=0.9, source="vector")]
        )

        memory_manager._hybrid_search = mock_hybrid_search
        memory_manager._vector_store = MagicMock()
        memory_manager._vector_store.is_available = MagicMock(return_value=True)

        result = asyncio.run(memory_manager.hybrid_search(query="Test"))

        assert len(result) > 0
        assert result[0].get("fallback") is False

    def test_hybrid_search_returns_fallback_true_on_exception(self, memory_manager):
        """Test that hybrid_search returns fallback=True when vector search throws exception."""
        import asyncio

        mock_hybrid_search = MagicMock()
        mock_hybrid_search.search = AsyncMock(side_effect=Exception("Vector search failed"))

        memory_manager._hybrid_search = mock_hybrid_search
        memory_manager._vector_store = MagicMock()
        memory_manager._vector_store.is_available = MagicMock(return_value=True)

        memory_manager.write_memory(content="Test memory for fallback")

        result = asyncio.run(memory_manager.hybrid_search(query="Test"))

        assert len(result) > 0
        assert result[0].get("fallback") is True


class TestHybridSearchOptions:
    """Test HybridSearchOptions dataclass."""

    def test_default_options(self):
        """Test default HybridSearchOptions values."""
        options = HybridSearchOptions(query="test")
        assert options.query == "test"
        assert options.memory_type is None
        assert options.tags is None
        assert options.limit == 10
        assert options.vector_weight == 0.6
        assert options.keyword_weight == 0.4
        assert options.min_score == 0.3
        assert options.use_vector is True
        assert options.use_keyword is True

    def test_custom_options(self):
        """Test custom HybridSearchOptions values."""
        options = HybridSearchOptions(
            query="test", memory_type="long_term", limit=20, vector_weight=0.8, keyword_weight=0.2
        )
        assert options.memory_type == "long_term"
        assert options.limit == 20
        assert options.vector_weight == 0.8
        assert options.keyword_weight == 0.2


class TestSearchResult:
    """Test SearchResult dataclass."""

    def test_search_result_creation(self):
        """Test creating a SearchResult."""
        result = SearchResult(
            memory_id=1,
            content="Test content",
            score=0.95,
            source="vector",
            metadata={"type": "long_term"},
        )
        assert result.memory_id == 1
        assert result.content == "Test content"
        assert result.score == 0.95
        assert result.source == "vector"
        assert result.metadata == {"type": "long_term"}

    def test_search_result_default_metadata(self):
        """Test SearchResult with default metadata."""
        result = SearchResult(memory_id=1, content="Test", score=0.5, source="keyword")
        assert result.metadata is None
