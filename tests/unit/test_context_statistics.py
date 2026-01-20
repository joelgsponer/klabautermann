"""
Unit tests for context window statistics module.

Tests token estimation, context metrics, and overflow tracking.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.context_statistics import (
    CHARS_PER_TOKEN_ESTIMATE,
    DEFAULT_MAX_MESSAGES,
    ContextWindowMetrics,
    GlobalContextMetrics,
    estimate_message_tokens,
    estimate_tokens,
    get_global_context_metrics,
    get_thread_context_metrics,
    metrics_to_dict,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Create a mock Neo4jClient."""
    client = MagicMock()
    client.execute_query = AsyncMock()
    return client


# =============================================================================
# Test Token Estimation
# =============================================================================


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_empty_string(self) -> None:
        """Test estimating tokens for empty string."""
        assert estimate_tokens("") == 0
        assert estimate_tokens(None) == 0

    def test_short_text(self) -> None:
        """Test estimating tokens for short text."""
        # 8 characters / 4 = 2 tokens
        result = estimate_tokens("Hello!!!")  # 8 characters
        assert result == 2

    def test_longer_text(self) -> None:
        """Test estimating tokens for longer text."""
        text = "This is a longer piece of text that should have more tokens"
        expected = len(text) // CHARS_PER_TOKEN_ESTIMATE
        assert estimate_tokens(text) == expected

    def test_minimum_one_token(self) -> None:
        """Test that minimum is 1 token for non-empty text."""
        # Single character
        result = estimate_tokens("a")
        assert result == 1


class TestEstimateMessageTokens:
    """Tests for estimate_message_tokens function."""

    def test_user_message(self) -> None:
        """Test estimating tokens for user message."""
        result = estimate_message_tokens("user", "Hello, how are you?")
        # 4 (role overhead) + content tokens
        content_tokens = estimate_tokens("Hello, how are you?")
        assert result == 4 + content_tokens

    def test_assistant_message(self) -> None:
        """Test estimating tokens for assistant message."""
        result = estimate_message_tokens("assistant", "I'm doing well!")
        content_tokens = estimate_tokens("I'm doing well!")
        assert result == 4 + content_tokens

    def test_empty_content(self) -> None:
        """Test estimating tokens with empty content."""
        result = estimate_message_tokens("user", "")
        assert result == 4  # Just role overhead


# =============================================================================
# Test ContextWindowMetrics
# =============================================================================


class TestContextWindowMetrics:
    """Tests for ContextWindowMetrics dataclass."""

    def test_creation(self) -> None:
        """Test creating ContextWindowMetrics."""
        metrics = ContextWindowMetrics(
            thread_uuid="test-uuid",
            message_count=15,
            max_messages=20,
            estimated_tokens=500,
        )
        assert metrics.thread_uuid == "test-uuid"
        assert metrics.message_count == 15
        assert metrics.max_messages == 20
        assert metrics.estimated_tokens == 500

    def test_is_at_capacity_false(self) -> None:
        """Test is_at_capacity when under limit."""
        metrics = ContextWindowMetrics(
            thread_uuid="test",
            message_count=10,
            max_messages=20,
            estimated_tokens=100,
        )
        assert metrics.is_at_capacity is False

    def test_is_at_capacity_true(self) -> None:
        """Test is_at_capacity when at limit."""
        metrics = ContextWindowMetrics(
            thread_uuid="test",
            message_count=20,
            max_messages=20,
            estimated_tokens=100,
        )
        assert metrics.is_at_capacity is True

    def test_utilization_percent(self) -> None:
        """Test utilization percentage calculation."""
        metrics = ContextWindowMetrics(
            thread_uuid="test",
            message_count=10,
            max_messages=20,
            estimated_tokens=100,
        )
        assert metrics.utilization_percent == 50.0

    def test_utilization_percent_full(self) -> None:
        """Test utilization at 100%."""
        metrics = ContextWindowMetrics(
            thread_uuid="test",
            message_count=20,
            max_messages=20,
            estimated_tokens=100,
        )
        assert metrics.utilization_percent == 100.0

    def test_utilization_percent_zero_max(self) -> None:
        """Test utilization with zero max messages."""
        metrics = ContextWindowMetrics(
            thread_uuid="test",
            message_count=0,
            max_messages=0,
            estimated_tokens=0,
        )
        assert metrics.utilization_percent == 0.0


# =============================================================================
# Test GlobalContextMetrics
# =============================================================================


class TestGlobalContextMetrics:
    """Tests for GlobalContextMetrics dataclass."""

    def test_creation(self) -> None:
        """Test creating GlobalContextMetrics."""
        metrics = GlobalContextMetrics(
            total_threads=10,
            active_threads=5,
            total_estimated_tokens=5000,
            avg_tokens_per_thread=500.0,
            total_overflow_events=2,
            total_messages_dropped=10,
            threads_at_capacity=3,
            avg_compression_ratio=1.0,
        )
        assert metrics.total_threads == 10
        assert metrics.active_threads == 5
        assert metrics.total_estimated_tokens == 5000
        assert metrics.avg_tokens_per_thread == 500.0


# =============================================================================
# Test Thread Context Metrics
# =============================================================================


class TestGetThreadContextMetrics:
    """Tests for get_thread_context_metrics function."""

    @pytest.mark.asyncio
    async def test_returns_metrics(self, mock_neo4j: MagicMock) -> None:
        """Test that thread metrics are returned."""
        mock_neo4j.execute_query.return_value = [
            {"content": "Hello", "role": "user", "timestamp": 1705320000.0},
            {"content": "Hi there", "role": "assistant", "timestamp": 1705319900.0},
        ]

        result = await get_thread_context_metrics(mock_neo4j, "test-uuid")

        assert result.thread_uuid == "test-uuid"
        assert result.message_count == 2
        assert result.max_messages == DEFAULT_MAX_MESSAGES
        assert result.estimated_tokens > 0

    @pytest.mark.asyncio
    async def test_empty_thread(self, mock_neo4j: MagicMock) -> None:
        """Test metrics for empty thread."""
        mock_neo4j.execute_query.return_value = []

        result = await get_thread_context_metrics(mock_neo4j, "empty-uuid")

        assert result.message_count == 0
        assert result.estimated_tokens == 0
        assert result.overflow_events == 0

    @pytest.mark.asyncio
    async def test_overflow_detection(self, mock_neo4j: MagicMock) -> None:
        """Test overflow detection when messages exceed max."""
        # Return more messages than max_messages
        messages = [
            {"content": f"Message {i}", "role": "user", "timestamp": 1705320000.0 - i}
            for i in range(25)
        ]
        mock_neo4j.execute_query.return_value = messages

        result = await get_thread_context_metrics(mock_neo4j, "test-uuid", max_messages=20)

        assert result.overflow_events == 1
        assert result.messages_dropped == 5

    @pytest.mark.asyncio
    async def test_custom_max_messages(self, mock_neo4j: MagicMock) -> None:
        """Test with custom max_messages limit."""
        mock_neo4j.execute_query.return_value = [
            {"content": "Test", "role": "user", "timestamp": 1705320000.0},
        ]

        result = await get_thread_context_metrics(mock_neo4j, "test-uuid", max_messages=10)

        assert result.max_messages == 10


# =============================================================================
# Test Global Context Metrics
# =============================================================================


class TestGetGlobalContextMetrics:
    """Tests for get_global_context_metrics function."""

    @pytest.mark.asyncio
    async def test_returns_aggregated_metrics(self, mock_neo4j: MagicMock) -> None:
        """Test that global metrics are aggregated."""
        mock_neo4j.execute_query.return_value = [
            {
                "thread_uuid": "thread-1",
                "status": "active",
                "message_count": 10,
                "contents": ["Hello", "Hi"],
                "last_msg": 1705320000.0,
            },
            {
                "thread_uuid": "thread-2",
                "status": "archived",
                "message_count": 25,
                "contents": ["Test"] * 25,
                "last_msg": 1705310000.0,
            },
        ]

        result = await get_global_context_metrics(mock_neo4j)

        assert result.total_threads == 2
        assert result.active_threads == 1
        assert result.total_estimated_tokens > 0
        assert result.total_overflow_events == 1  # thread-2 has 25 > 20
        assert result.threads_at_capacity == 1  # thread-2 is at/over capacity

    @pytest.mark.asyncio
    async def test_empty_database(self, mock_neo4j: MagicMock) -> None:
        """Test metrics for empty database."""
        mock_neo4j.execute_query.return_value = []

        result = await get_global_context_metrics(mock_neo4j)

        assert result.total_threads == 0
        assert result.active_threads == 0
        assert result.total_estimated_tokens == 0
        assert result.avg_tokens_per_thread == 0.0


# =============================================================================
# Test Serialization
# =============================================================================


class TestMetricsToDict:
    """Tests for metrics_to_dict function."""

    def test_context_window_metrics(self) -> None:
        """Test converting ContextWindowMetrics to dict."""
        metrics = ContextWindowMetrics(
            thread_uuid="test-uuid",
            message_count=15,
            max_messages=20,
            estimated_tokens=500,
            overflow_events=0,
            messages_dropped=0,
        )

        result = metrics_to_dict(metrics)

        assert result["thread_uuid"] == "test-uuid"
        assert result["message_count"] == 15
        assert result["max_messages"] == 20
        assert result["estimated_tokens"] == 500
        assert result["is_at_capacity"] is False
        assert result["utilization_percent"] == 75.0

    def test_global_context_metrics(self) -> None:
        """Test converting GlobalContextMetrics to dict."""
        metrics = GlobalContextMetrics(
            total_threads=10,
            active_threads=5,
            total_estimated_tokens=5000,
            avg_tokens_per_thread=500.0,
            total_overflow_events=2,
            total_messages_dropped=10,
            threads_at_capacity=3,
            avg_compression_ratio=1.0,
        )

        result = metrics_to_dict(metrics)

        assert result["total_threads"] == 10
        assert result["active_threads"] == 5
        assert result["total_estimated_tokens"] == 5000
        assert result["avg_tokens_per_thread"] == 500.0
        assert "computed_at" in result
