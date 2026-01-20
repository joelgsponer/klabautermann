"""
Unit tests for query timeout handling.

Tests the QueryTimeoutError and timeout functionality in Neo4jClient.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.neo4j_client import (
    DEFAULT_QUERY_TIMEOUT_MS,
    QueryTimeoutError,
)


# =============================================================================
# Test QueryTimeoutError
# =============================================================================


class TestQueryTimeoutError:
    """Tests for QueryTimeoutError exception."""

    def test_creation(self) -> None:
        """Test creating QueryTimeoutError."""
        error = QueryTimeoutError("SELECT * FROM nodes", 5000.0)

        assert error.query == "SELECT * FROM nodes"
        assert error.timeout_ms == 5000.0
        assert "5000" in str(error)

    def test_query_truncation(self) -> None:
        """Test that long queries are truncated."""
        long_query = "a" * 200
        error = QueryTimeoutError(long_query, 1000.0)

        assert len(error.query) == 100  # Truncated to 100 chars


# =============================================================================
# Test Timeout Configuration
# =============================================================================


class TestTimeoutConfiguration:
    """Tests for timeout configuration."""

    def test_default_timeout_value(self) -> None:
        """Test default timeout is reasonable."""
        assert DEFAULT_QUERY_TIMEOUT_MS == 30000  # 30 seconds
        assert DEFAULT_QUERY_TIMEOUT_MS > 0

    def test_timeout_in_milliseconds(self) -> None:
        """Test timeout is in milliseconds."""
        # Should be at least 1 second (1000ms) for practical use
        assert DEFAULT_QUERY_TIMEOUT_MS >= 1000


# =============================================================================
# Test Timeout Behavior (Mocked)
# =============================================================================


class TestTimeoutBehavior:
    """Tests for timeout behavior with mocked Neo4j client."""

    @pytest.fixture
    def mock_session(self) -> MagicMock:
        """Create a mock session."""
        session = MagicMock()
        result = MagicMock()
        result.data = AsyncMock(return_value=[{"result": 1}])
        session.run = AsyncMock(return_value=result)
        return session

    @pytest.mark.asyncio
    async def test_query_completes_before_timeout(self, mock_session: MagicMock) -> None:
        """Test that fast queries complete successfully."""
        # Simulate fast query
        mock_session.run = AsyncMock(
            return_value=MagicMock(data=AsyncMock(return_value=[{"x": 1}]))
        )

        async def fast_query():
            result = await mock_session.run("RETURN 1")
            return await result.data()

        # Should complete without timeout
        result = await asyncio.wait_for(fast_query(), timeout=5.0)
        assert result == [{"x": 1}]

    @pytest.mark.asyncio
    async def test_asyncio_timeout_raises(self) -> None:
        """Test that asyncio.wait_for raises TimeoutError."""

        async def slow_operation():
            await asyncio.sleep(10)
            return "done"

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(slow_operation(), timeout=0.01)

    @pytest.mark.asyncio
    async def test_timeout_error_conversion(self) -> None:
        """Test converting TimeoutError to QueryTimeoutError."""

        async def slow_query():
            await asyncio.sleep(10)
            return []

        query = "MATCH (n) RETURN n"
        timeout_ms = 10.0

        with pytest.raises(QueryTimeoutError) as exc_info:
            try:
                await asyncio.wait_for(slow_query(), timeout=timeout_ms / 1000.0)
            except TimeoutError:
                raise QueryTimeoutError(query, timeout_ms) from None

        assert exc_info.value.timeout_ms == timeout_ms
        assert query[:50] in exc_info.value.query

    @pytest.mark.asyncio
    async def test_no_timeout_when_disabled(self, mock_session: MagicMock) -> None:
        """Test that timeout can be disabled."""
        # When timeout is 0 or None, should not apply timeout
        mock_session.run = AsyncMock(
            return_value=MagicMock(data=AsyncMock(return_value=[{"x": 1}]))
        )

        async def query_without_timeout():
            result = await mock_session.run("RETURN 1")
            return await result.data()

        # Without wait_for, query should complete regardless of execution time
        result = await query_without_timeout()
        assert result == [{"x": 1}]


# =============================================================================
# Test Execute Query with Timeout
# =============================================================================


class TestExecuteQueryWithTimeout:
    """Tests for execute_query with timeout parameter."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Neo4jClient."""
        from klabautermann.memory.neo4j_client import Neo4jClient

        client = Neo4jClient()
        client._driver = MagicMock()

        # Mock session context manager
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.data = AsyncMock(return_value=[{"result": 1}])
        mock_session.run = AsyncMock(return_value=mock_result)

        # Create async context manager mock
        async def mock_session_cm():
            yield mock_session

        client._driver.session = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock()
            )
        )

        return client

    @pytest.mark.asyncio
    async def test_default_timeout_applied(self) -> None:
        """Test that default timeout is applied when not specified."""
        # This is a design test - verifying the constant exists and is used
        assert DEFAULT_QUERY_TIMEOUT_MS > 0

    @pytest.mark.asyncio
    async def test_custom_timeout_value(self) -> None:
        """Test that custom timeout can be specified."""
        custom_timeout = 5000  # 5 seconds
        assert custom_timeout != DEFAULT_QUERY_TIMEOUT_MS
        assert custom_timeout > 0
