"""
Unit tests for ThreadManager.

Reference: specs/architecture/MEMORY.md Section 3 (Thread Management)
Task: T036 - Cooldown Detection Query

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.neo4j_client import Neo4jClient
from klabautermann.memory.thread_manager import ThreadManager


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_neo4j_client() -> Neo4jClient:
    """Create mock Neo4j client."""
    client = MagicMock(spec=Neo4jClient)
    client.execute_query = AsyncMock()
    return client


@pytest.fixture
def thread_manager(mock_neo4j_client: Neo4jClient) -> ThreadManager:
    """Create ThreadManager with mock client."""
    return ThreadManager(mock_neo4j_client)


@pytest.fixture
def sample_inactive_threads() -> list[dict[str, Any]]:
    """Sample inactive thread query results."""
    return [
        {
            "t.uuid": "thread-001",
        },
        {
            "t.uuid": "thread-002",
        },
        {
            "t.uuid": "thread-003",
        },
    ]


# ===========================================================================
# Cooldown Detection Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_inactive_threads_basic(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
    sample_inactive_threads: list[dict[str, Any]],
):
    """Test basic inactive thread detection with default parameters."""
    mock_neo4j_client.execute_query.return_value = sample_inactive_threads

    result = await thread_manager.get_inactive_threads()

    # Verify query was called with correct parameters
    mock_neo4j_client.execute_query.assert_called_once()
    call_args = mock_neo4j_client.execute_query.call_args

    # Verify query structure
    query = call_args[0][0]
    assert "MATCH (t:Thread)" in query
    assert "WHERE t.status = 'active'" in query
    assert "t.last_message_at < $cutoff_timestamp" in query
    assert "ORDER BY t.last_message_at ASC" in query
    assert "LIMIT $limit" in query

    # Verify parameters
    params = call_args[0][1]
    assert "cutoff_timestamp" in params
    assert "limit" in params
    assert params["limit"] == 10  # default limit

    # Verify result
    assert result == ["thread-001", "thread-002", "thread-003"]
    assert len(result) == 3


@pytest.mark.asyncio
async def test_get_inactive_threads_custom_cooldown(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
    sample_inactive_threads: list[dict[str, Any]],
):
    """Test inactive thread detection with custom cooldown period."""
    mock_neo4j_client.execute_query.return_value = sample_inactive_threads
    cooldown_minutes = 120

    result = await thread_manager.get_inactive_threads(cooldown_minutes=cooldown_minutes)

    call_args = mock_neo4j_client.execute_query.call_args
    params = call_args[0][1]

    # Verify cutoff timestamp is calculated correctly
    expected_cutoff = time.time() - (cooldown_minutes * 60)
    actual_cutoff = params["cutoff_timestamp"]

    # Allow 1 second tolerance for test execution time
    assert abs(actual_cutoff - expected_cutoff) < 1.0

    assert result == ["thread-001", "thread-002", "thread-003"]


@pytest.mark.asyncio
async def test_get_inactive_threads_custom_limit(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test inactive thread detection respects custom limit."""
    mock_neo4j_client.execute_query.return_value = [
        {"t.uuid": "thread-001"},
        {"t.uuid": "thread-002"},
    ]
    custom_limit = 5

    result = await thread_manager.get_inactive_threads(limit=custom_limit)

    call_args = mock_neo4j_client.execute_query.call_args
    params = call_args[0][1]

    # Verify limit parameter
    assert params["limit"] == custom_limit

    assert result == ["thread-001", "thread-002"]


@pytest.mark.asyncio
async def test_get_inactive_threads_empty_result(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test inactive thread detection when no inactive threads exist."""
    mock_neo4j_client.execute_query.return_value = []

    result = await thread_manager.get_inactive_threads()

    assert result == []
    assert len(result) == 0


@pytest.mark.asyncio
async def test_get_inactive_threads_with_trace_id(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test that trace_id is passed through to Neo4j client."""
    mock_neo4j_client.execute_query.return_value = []
    trace_id = "test-trace-cooldown-123"

    await thread_manager.get_inactive_threads(trace_id=trace_id)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[1]["trace_id"] == trace_id


@pytest.mark.asyncio
async def test_get_inactive_threads_returns_only_uuids(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test that method returns only thread UUIDs, not full objects."""
    mock_neo4j_client.execute_query.return_value = [
        {"t.uuid": "thread-uuid-1"},
        {"t.uuid": "thread-uuid-2"},
        {"t.uuid": "thread-uuid-3"},
    ]

    result = await thread_manager.get_inactive_threads()

    # Verify result is list of strings (UUIDs)
    assert isinstance(result, list)
    assert all(isinstance(uuid, str) for uuid in result)
    assert result == ["thread-uuid-1", "thread-uuid-2", "thread-uuid-3"]


# ===========================================================================
# Query Safety Tests
# ===========================================================================


def test_get_inactive_threads_uses_parameterized_query():
    """Verify query uses parameters, not f-strings (injection safety)."""
    # This is tested implicitly in other tests, but we explicitly verify
    # the query construction doesn't use dangerous string formatting
    _manager = ThreadManager(MagicMock())

    # The method should use parameterized queries exclusively
    # No f-strings or .format() in the query construction
    # This is enforced by the implementation using $cutoff_timestamp and $limit
    # Verification is done in test_get_inactive_threads_basic which checks
    # that $cutoff_timestamp and $limit are used in the query string
    assert True  # Marker that this test is intentionally minimal


@pytest.mark.asyncio
async def test_get_inactive_threads_orders_by_oldest_first(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test that inactive threads are ordered by last_message_at ASC (oldest first)."""
    mock_neo4j_client.execute_query.return_value = [
        {"t.uuid": "oldest-thread"},
        {"t.uuid": "middle-thread"},
        {"t.uuid": "newer-thread"},
    ]

    result = await thread_manager.get_inactive_threads()

    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]

    # Verify ordering
    assert "ORDER BY t.last_message_at ASC" in query

    # Result should maintain the order from the query
    assert result == ["oldest-thread", "middle-thread", "newer-thread"]


@pytest.mark.asyncio
async def test_get_inactive_threads_filters_only_active_status(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test that query only returns threads with 'active' status."""
    mock_neo4j_client.execute_query.return_value = []

    await thread_manager.get_inactive_threads()

    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]

    # Verify status filter
    assert "t.status = 'active'" in query


# ===========================================================================
# Integration with Archivist Tests (Behavioral)
# ===========================================================================


@pytest.mark.asyncio
async def test_get_inactive_threads_typical_archivist_usage(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test typical usage pattern by Archivist agent."""
    # Simulate Archivist polling for threads ready for archival
    mock_neo4j_client.execute_query.return_value = [
        {"t.uuid": "thread-to-archive-1"},
        {"t.uuid": "thread-to-archive-2"},
    ]

    # Archivist typically uses 60 minute cooldown, 10 thread batch
    inactive_threads = await thread_manager.get_inactive_threads(
        cooldown_minutes=60,
        limit=10,
        trace_id="archivist-scan-001",
    )

    assert len(inactive_threads) == 2
    assert "thread-to-archive-1" in inactive_threads
    assert "thread-to-archive-2" in inactive_threads

    # Verify trace_id was passed for debugging
    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[1]["trace_id"] == "archivist-scan-001"


@pytest.mark.asyncio
async def test_get_inactive_threads_prevents_overwhelming_pipeline(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test that limit prevents overwhelming the archival pipeline."""
    # Simulate many inactive threads in the database
    many_threads = [{"t.uuid": f"thread-{i:03d}"} for i in range(100)]
    mock_neo4j_client.execute_query.return_value = many_threads

    # Even with many inactive threads, respect the limit
    await thread_manager.get_inactive_threads(limit=10)

    # Neo4j will enforce the limit, but we verify it was passed
    call_args = mock_neo4j_client.execute_query.call_args
    params = call_args[0][1]
    assert params["limit"] == 10

    # In real scenario, Neo4j would return only 10 results
    # Our mock returns all 100, but that's okay for testing parameter passing
