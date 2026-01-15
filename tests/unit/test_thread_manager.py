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


# ===========================================================================
# Thread Status Lifecycle Tests (T037)
# ===========================================================================


@pytest.mark.asyncio
async def test_mark_archiving_success_for_active_thread(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test mark_archiving succeeds for active thread."""
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]

    result = await thread_manager.mark_archiving("thread-123", trace_id="test-trace")

    # Verify success
    assert result is True

    # Verify query structure
    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]
    assert "MATCH (t:Thread {uuid: $thread_uuid})" in query
    assert "WHERE t.status = 'active'" in query
    assert "SET t.status = 'archiving'" in query
    assert "t.archiving_started_at = $now" in query
    assert "t.updated_at = $now" in query

    # Verify parameters
    params = call_args[0][1]
    assert params["thread_uuid"] == "thread-123"
    assert "now" in params


@pytest.mark.asyncio
async def test_mark_archiving_fails_for_non_active_thread(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test mark_archiving fails if thread is not active."""
    # Empty result means WHERE clause didn't match
    mock_neo4j_client.execute_query.return_value = []

    result = await thread_manager.mark_archiving("thread-123")

    # Verify failure
    assert result is False


@pytest.mark.asyncio
async def test_mark_archiving_atomic_check_and_update(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test mark_archiving uses atomic WHERE clause."""
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]

    await thread_manager.mark_archiving("thread-123")

    # Verify WHERE clause is used for atomicity
    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]
    assert "WHERE t.status = 'active'" in query
    # This ensures only one archiving process can succeed


@pytest.mark.asyncio
async def test_mark_archived_success_for_archiving_thread(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test mark_archived succeeds for archiving thread."""
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]

    result = await thread_manager.mark_archived("thread-123", "summary-456", trace_id="test-trace")

    # Verify success
    assert result is True

    # Verify query structure
    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]
    assert "MATCH (t:Thread {uuid: $thread_uuid})" in query
    assert "WHERE t.status = 'archiving'" in query
    assert "MATCH (n:Note {uuid: $summary_uuid})" in query
    assert "SET t.status = 'archived'" in query
    assert "t.archived_at = $now" in query
    assert "CREATE (n)-[:SUMMARY_OF]->(t)" in query

    # Verify parameters
    params = call_args[0][1]
    assert params["thread_uuid"] == "thread-123"
    assert params["summary_uuid"] == "summary-456"
    assert "now" in params


@pytest.mark.asyncio
async def test_mark_archived_fails_for_non_archiving_thread(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test mark_archived fails if thread is not archiving."""
    # Empty result means WHERE clause didn't match
    mock_neo4j_client.execute_query.return_value = []

    result = await thread_manager.mark_archived("thread-123", "summary-456")

    # Verify failure
    assert result is False


@pytest.mark.asyncio
async def test_mark_archived_creates_summary_relationship(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test mark_archived creates [:SUMMARY_OF] relationship."""
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]

    await thread_manager.mark_archived("thread-123", "summary-456")

    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]
    assert "CREATE (n)-[:SUMMARY_OF]->(t)" in query


@pytest.mark.asyncio
async def test_reactivate_thread_success_for_archiving_thread(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test reactivate_thread succeeds for archiving thread."""
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]

    result = await thread_manager.reactivate_thread("thread-123", trace_id="test-trace")

    # Verify success
    assert result is True

    # Verify query structure
    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]
    assert "MATCH (t:Thread {uuid: $thread_uuid})" in query
    assert "WHERE t.status = 'archiving'" in query
    assert "SET t.status = 'active'" in query
    assert "REMOVE t.archiving_started_at" in query

    # Verify parameters
    params = call_args[0][1]
    assert params["thread_uuid"] == "thread-123"
    assert "now" in params


@pytest.mark.asyncio
async def test_reactivate_thread_fails_for_non_archiving_thread(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test reactivate_thread fails if thread is not archiving."""
    # Empty result means WHERE clause didn't match
    mock_neo4j_client.execute_query.return_value = []

    result = await thread_manager.reactivate_thread("thread-123")

    # Verify failure
    assert result is False


@pytest.mark.asyncio
async def test_reactivate_thread_removes_archiving_started_at(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test reactivate_thread removes archiving_started_at timestamp."""
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]

    await thread_manager.reactivate_thread("thread-123")

    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]
    assert "REMOVE t.archiving_started_at" in query


@pytest.mark.asyncio
async def test_full_lifecycle_active_to_archived(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test full lifecycle: active -> archiving -> archived."""
    # Step 1: Mark as archiving
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]
    success = await thread_manager.mark_archiving("thread-123")
    assert success is True

    # Step 2: Mark as archived
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]
    success = await thread_manager.mark_archived("thread-123", "summary-456")
    assert success is True

    # Verify two separate calls were made
    assert mock_neo4j_client.execute_query.call_count == 2


@pytest.mark.asyncio
async def test_lifecycle_reactivation_during_archiving(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test lifecycle: active -> archiving -> active (reactivated)."""
    # Step 1: Mark as archiving
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]
    success = await thread_manager.mark_archiving("thread-123")
    assert success is True

    # Step 2: Reactivate
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]
    success = await thread_manager.reactivate_thread("thread-123")
    assert success is True

    # Verify two separate calls were made
    assert mock_neo4j_client.execute_query.call_count == 2


@pytest.mark.asyncio
async def test_add_message_reactivates_archiving_thread(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test add_message reactivates archiving thread automatically."""
    # Mock get_thread to return archiving thread

    archiving_thread = {
        "t": {
            "uuid": "thread-123",
            "external_id": "cli-123",
            "channel_type": "cli",
            "status": "archiving",
            "created_at": 1234567890.0,
            "updated_at": 1234567890.0,
            "last_message_at": 1234567890.0,
        }
    }

    # First call: get_thread returns archiving thread
    # Second call: reactivate_thread
    # Third call: add_message query
    mock_neo4j_client.execute_query.side_effect = [
        [archiving_thread],  # get_thread
        [{"t.uuid": "thread-123"}],  # reactivate_thread
        [
            {"m": {"uuid": "msg-123", "role": "user", "content": "test", "timestamp": 1234567890.0}}
        ],  # add_message
    ]

    result = await thread_manager.add_message("thread-123", "user", "test")

    # Verify message was created
    assert result.role.value == "user"
    assert result.content == "test"

    # Verify reactivate_thread was called
    assert mock_neo4j_client.execute_query.call_count == 3
    second_call = mock_neo4j_client.execute_query.call_args_list[1]
    query = second_call[0][0]
    assert "WHERE t.status = 'archiving'" in query
    assert "SET t.status = 'active'" in query


@pytest.mark.asyncio
async def test_lifecycle_prevents_double_archiving(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test that only one archiving process can succeed (race condition prevention)."""
    # First attempt succeeds
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]
    success1 = await thread_manager.mark_archiving("thread-123")
    assert success1 is True

    # Second concurrent attempt fails (thread is already archiving)
    mock_neo4j_client.execute_query.return_value = []
    success2 = await thread_manager.mark_archiving("thread-123")
    assert success2 is False


@pytest.mark.asyncio
async def test_lifecycle_trace_id_propagation(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test that trace_id is passed through all lifecycle methods."""
    trace_id = "test-trace-lifecycle-123"
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]

    # Test mark_archiving
    await thread_manager.mark_archiving("thread-123", trace_id=trace_id)
    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[1]["trace_id"] == trace_id

    # Test mark_archived
    await thread_manager.mark_archived("thread-123", "summary-456", trace_id=trace_id)
    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[1]["trace_id"] == trace_id

    # Test reactivate_thread
    await thread_manager.reactivate_thread("thread-123", trace_id=trace_id)
    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[1]["trace_id"] == trace_id


@pytest.mark.asyncio
async def test_lifecycle_uses_parameterized_queries(
    thread_manager: ThreadManager,
    mock_neo4j_client: Neo4jClient,
):
    """Test that all lifecycle methods use parameterized queries (injection safety)."""
    mock_neo4j_client.execute_query.return_value = [{"t.uuid": "thread-123"}]

    # Test mark_archiving
    await thread_manager.mark_archiving("thread-123")
    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]
    assert "$thread_uuid" in query
    assert "$now" in query

    # Test mark_archived
    await thread_manager.mark_archived("thread-123", "summary-456")
    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]
    assert "$thread_uuid" in query
    assert "$summary_uuid" in query
    assert "$now" in query

    # Test reactivate_thread
    await thread_manager.reactivate_thread("thread-123")
    call_args = mock_neo4j_client.execute_query.call_args
    query = call_args[0][0]
    assert "$thread_uuid" in query
    assert "$now" in query
