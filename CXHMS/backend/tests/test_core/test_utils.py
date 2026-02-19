"""Tests for core utility functions."""
import pytest
from backend.core.utils import format_messages_for_summary


class TestUtils:
    """Test utility functions."""

    def test_format_messages_for_summary_empty(self):
        """Test formatting empty message list."""
        result = format_messages_for_summary([])
        assert result == ""

    def test_format_messages_for_summary_single(self):
        """Test formatting single message."""
        messages = [{"role": "user", "content": "Hello"}]
        result = format_messages_for_summary(messages)
        assert "user" in result
        assert "Hello" in result

    def test_format_messages_for_summary_multiple(self):
        """Test formatting multiple messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = format_messages_for_summary(messages)
        assert "user" in result
        assert "assistant" in result
        assert "Hello" in result
        assert "Hi there!" in result

    def test_format_messages_for_summary_truncation(self):
        """Test that long content is truncated."""
        long_content = "x" * 1000
        messages = [{"role": "user", "content": long_content}]
        result = format_messages_for_summary(messages, max_content_length=100)
        assert len(result) < len(long_content) + 50
        assert "..." in result

    def test_format_messages_for_summary_missing_role(self):
        """Test formatting message with missing role."""
        messages = [{"content": "Hello"}]
        result = format_messages_for_summary(messages)
        assert "unknown" in result

    def test_format_messages_for_summary_missing_content(self):
        """Test formatting message with missing content."""
        messages = [{"role": "user"}]
        result = format_messages_for_summary(messages)
        assert "user" in result
