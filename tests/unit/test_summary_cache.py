"""
Unit tests for thread summary caching module.

Tests cache get, set, invalidation, and get-or-compute operations.
Issue: #200 - Add thread summary caching
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.core.models import ThreadSummary
from klabautermann.memory.summary_cache import (
    CachedSummary,
    get_cache_statistics,
    get_cached_summary,
    get_or_compute_summary,
    invalidate_summary_cache,
    set_cached_summary,
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


@pytest.fixture
def sample_summary() -> ThreadSummary:
    """Create a sample ThreadSummary."""
    return ThreadSummary(
        summary="Discussion about the Q1 budget planning and allocation.",
        topics=["budget", "Q1", "planning"],
        participants=["user", "assistant"],
        action_items=[],
        new_facts=[],
        conflicts=[],
        sentiment="neutral",
    )


# =============================================================================
# Test CachedSummary Data Class
# =============================================================================


class TestCachedSummary:
    """Tests for CachedSummary dataclass."""

    def test_creation(self, sample_summary: ThreadSummary) -> None:
        """Test creating CachedSummary."""
        cached = CachedSummary(
            thread_uuid="thread-001",
            summary=sample_summary,
            cached_at=1705320000.0,
            message_count_at_cache=10,
            last_message_at_cache=1705319900.0,
        )
        assert cached.thread_uuid == "thread-001"
        assert cached.summary == sample_summary
        assert cached.message_count_at_cache == 10


# =============================================================================
# Test get_cached_summary
# =============================================================================


class TestGetCachedSummary:
    """Tests for get_cached_summary function."""

    @pytest.mark.asyncio
    async def test_returns_cached_summary_when_valid(self, mock_neo4j: MagicMock) -> None:
        """Test returning valid cached summary."""
        cached_at = time.time() - 3600  # 1 hour ago
        mock_neo4j.execute_query.return_value = [
            {
                "summary": "Test summary",
                "cached_at": cached_at,
                "message_count": 5,
                "last_message_at": cached_at - 100,
                "topics": ["test", "topic"],
                "participants": ["user"],
                "sentiment": "positive",
            }
        ]

        result = await get_cached_summary(mock_neo4j, "thread-001")

        assert result is not None
        assert result.summary.summary == "Test summary"
        assert result.summary.topics == ["test", "topic"]
        assert result.message_count_at_cache == 5

    @pytest.mark.asyncio
    async def test_returns_none_when_no_cache(self, mock_neo4j: MagicMock) -> None:
        """Test returning None when no cache exists."""
        mock_neo4j.execute_query.return_value = []

        result = await get_cached_summary(mock_neo4j, "thread-001")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_cache_invalidated(self, mock_neo4j: MagicMock) -> None:
        """Test returning None when cache is invalidated (message count mismatch)."""
        # The query won't match because current message count != cached count
        mock_neo4j.execute_query.return_value = []

        result = await get_cached_summary(mock_neo4j, "thread-001")

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_missing_fields(self, mock_neo4j: MagicMock) -> None:
        """Test handling of missing optional fields."""
        mock_neo4j.execute_query.return_value = [
            {
                "summary": "Minimal summary",
                "cached_at": time.time(),
                "message_count": 1,
                "last_message_at": time.time(),
                "topics": None,
                "participants": None,
                "sentiment": None,
            }
        ]

        result = await get_cached_summary(mock_neo4j, "thread-001")

        assert result is not None
        assert result.summary.topics == []
        assert result.summary.participants == []
        assert result.summary.sentiment == "neutral"


# =============================================================================
# Test set_cached_summary
# =============================================================================


class TestSetCachedSummary:
    """Tests for set_cached_summary function."""

    @pytest.mark.asyncio
    async def test_caches_summary(
        self, mock_neo4j: MagicMock, sample_summary: ThreadSummary
    ) -> None:
        """Test successful caching of summary."""
        mock_neo4j.execute_query.return_value = [{"t.uuid": "thread-001"}]

        result = await set_cached_summary(mock_neo4j, "thread-001", sample_summary)

        assert result is True
        # Verify query was called with correct parameters
        call_args = mock_neo4j.execute_query.call_args
        params = call_args[0][1]
        assert params["thread_uuid"] == "thread-001"
        assert params["summary"] == sample_summary.summary
        assert params["topics"] == sample_summary.topics

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(
        self, mock_neo4j: MagicMock, sample_summary: ThreadSummary
    ) -> None:
        """Test returning False when thread not found."""
        mock_neo4j.execute_query.return_value = []

        result = await set_cached_summary(mock_neo4j, "nonexistent", sample_summary)

        assert result is False


# =============================================================================
# Test invalidate_summary_cache
# =============================================================================


class TestInvalidateSummaryCache:
    """Tests for invalidate_summary_cache function."""

    @pytest.mark.asyncio
    async def test_invalidates_existing_cache(self, mock_neo4j: MagicMock) -> None:
        """Test invalidating existing cache."""
        mock_neo4j.execute_query.return_value = [{"t.uuid": "thread-001"}]

        result = await invalidate_summary_cache(mock_neo4j, "thread-001")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_cache(self, mock_neo4j: MagicMock) -> None:
        """Test returning False when no cache to invalidate."""
        mock_neo4j.execute_query.return_value = []

        result = await invalidate_summary_cache(mock_neo4j, "thread-001")

        assert result is False


# =============================================================================
# Test get_or_compute_summary
# =============================================================================


class TestGetOrComputeSummary:
    """Tests for get_or_compute_summary function."""

    @pytest.mark.asyncio
    async def test_returns_cached_on_hit(
        self, mock_neo4j: MagicMock, sample_summary: ThreadSummary
    ) -> None:
        """Test returning cached summary on cache hit."""
        # First call returns cached summary
        mock_neo4j.execute_query.return_value = [
            {
                "summary": "Cached summary",
                "cached_at": time.time(),
                "message_count": 5,
                "last_message_at": time.time(),
                "topics": [],
                "participants": [],
                "sentiment": "neutral",
            }
        ]

        compute_fn = AsyncMock(return_value=sample_summary)

        result = await get_or_compute_summary(mock_neo4j, "thread-001", compute_fn, "trace-001")

        assert result.summary == "Cached summary"
        compute_fn.assert_not_called()  # Should not compute

    @pytest.mark.asyncio
    async def test_computes_on_miss(
        self, mock_neo4j: MagicMock, sample_summary: ThreadSummary
    ) -> None:
        """Test computing summary on cache miss."""
        # First call (check cache) returns empty
        # Second call (set cache) returns success
        mock_neo4j.execute_query.side_effect = [
            [],  # Cache miss
            [{"t.uuid": "thread-001"}],  # Cache set success
        ]

        compute_fn = AsyncMock(return_value=sample_summary)

        result = await get_or_compute_summary(mock_neo4j, "thread-001", compute_fn, "trace-001")

        assert result == sample_summary
        compute_fn.assert_called_once_with("trace-001")

    @pytest.mark.asyncio
    async def test_caches_computed_summary(
        self, mock_neo4j: MagicMock, sample_summary: ThreadSummary
    ) -> None:
        """Test that computed summary is cached."""
        mock_neo4j.execute_query.side_effect = [
            [],  # Cache miss
            [{"t.uuid": "thread-001"}],  # Cache set success
        ]

        compute_fn = AsyncMock(return_value=sample_summary)

        await get_or_compute_summary(mock_neo4j, "thread-001", compute_fn, "trace-001")

        # Should have called execute_query twice (check + set)
        assert mock_neo4j.execute_query.call_count == 2


# =============================================================================
# Test get_cache_statistics
# =============================================================================


class TestGetCacheStatistics:
    """Tests for get_cache_statistics function."""

    @pytest.mark.asyncio
    async def test_returns_statistics(self, mock_neo4j: MagicMock) -> None:
        """Test returning cache statistics."""
        mock_neo4j.execute_query.return_value = [
            {
                "total_threads": 100,
                "cached_threads": 75,
                "uncached_threads": 25,
            }
        ]

        result = await get_cache_statistics(mock_neo4j)

        assert result["total_threads"] == 100
        assert result["cached_threads"] == 75
        assert result["uncached_threads"] == 25
        assert result["cache_hit_rate"] == 0.75

    @pytest.mark.asyncio
    async def test_handles_empty_result(self, mock_neo4j: MagicMock) -> None:
        """Test handling of empty result."""
        mock_neo4j.execute_query.return_value = []

        result = await get_cache_statistics(mock_neo4j)

        assert result["total_threads"] == 0
        assert result["cache_hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_handles_zero_threads(self, mock_neo4j: MagicMock) -> None:
        """Test handling of zero threads (avoid divide by zero)."""
        mock_neo4j.execute_query.return_value = [
            {
                "total_threads": 0,
                "cached_threads": 0,
                "uncached_threads": 0,
            }
        ]

        result = await get_cache_statistics(mock_neo4j)

        assert result["cache_hit_rate"] == 0.0
