"""
Unit tests for context retrieval queries.

Tests all context query functions with mocked Neo4j client.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.core.models import (
    CommunityContext,
    EntityReference,
    TaskNode,
    ThreadSummary,
)
from klabautermann.memory.context_queries import (
    get_pending_tasks,
    get_recent_entities,
    get_recent_summaries,
    get_relevant_islands,
)


@pytest.fixture
def mock_neo4j_client():
    """Create a mock Neo4j client."""
    client = MagicMock()
    client.execute_query = AsyncMock()
    return client


# ===========================================================================
# get_recent_summaries Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_recent_summaries_returns_summaries(mock_neo4j_client):
    """Test retrieving recent thread summaries."""
    # Mock database response
    mock_neo4j_client.execute_query.return_value = [
        {
            "uuid": "note-1",
            "title": "Project discussion",
            "summary": "Discussed project timeline",
            "topics": ["project", "timeline"],
            "channel": "cli",
            "participants": ["Alice", "Bob"],
        },
        {
            "uuid": "note-2",
            "title": "Budget review",
            "summary": "Reviewed Q1 budget",
            "topics": ["budget", "finance"],
            "channel": "telegram",
            "participants": ["Sarah"],
        },
    ]

    # Execute query
    summaries = await get_recent_summaries(
        mock_neo4j_client,
        hours=12,
        limit=10,
        trace_id="test-123",
    )

    # Verify results
    assert len(summaries) == 2
    assert all(isinstance(s, ThreadSummary) for s in summaries)
    assert summaries[0].summary == "Discussed project timeline"
    assert summaries[0].topics == ["project", "timeline"]
    assert summaries[0].participants == ["Alice", "Bob"]
    assert summaries[1].summary == "Reviewed Q1 budget"
    assert summaries[1].participants == ["Sarah"]

    # Verify query was called with correct parameters
    mock_neo4j_client.execute_query.assert_called_once()
    call_args = mock_neo4j_client.execute_query.call_args
    assert "cutoff" in call_args[0][1]
    assert call_args[0][1]["limit"] == 10


@pytest.mark.asyncio
async def test_get_recent_summaries_empty_results(mock_neo4j_client):
    """Test that empty results return empty list."""
    mock_neo4j_client.execute_query.return_value = []

    summaries = await get_recent_summaries(mock_neo4j_client, hours=12)

    assert summaries == []
    assert isinstance(summaries, list)


@pytest.mark.asyncio
async def test_get_recent_summaries_handles_missing_fields(mock_neo4j_client):
    """Test handling of missing optional fields."""
    mock_neo4j_client.execute_query.return_value = [
        {
            "uuid": "note-1",
            "title": None,
            "summary": "Some summary",
            "topics": None,
            "channel": "cli",
            "participants": None,
        },
    ]

    summaries = await get_recent_summaries(mock_neo4j_client)

    assert len(summaries) == 1
    assert summaries[0].summary == "Some summary"
    assert summaries[0].topics == []
    assert summaries[0].participants == []


@pytest.mark.asyncio
async def test_get_recent_summaries_cutoff_calculation(mock_neo4j_client):
    """Test that cutoff timestamp is calculated correctly."""
    mock_neo4j_client.execute_query.return_value = []

    # Capture current time
    before = datetime.now(UTC)
    await get_recent_summaries(mock_neo4j_client, hours=24)

    # Verify cutoff is approximately 24 hours ago
    call_args = mock_neo4j_client.execute_query.call_args
    cutoff = call_args[0][1]["cutoff"]
    expected_cutoff = before - timedelta(hours=24)

    # Allow 1 second tolerance for test execution time
    assert abs(cutoff - expected_cutoff.timestamp()) < 1.0


# ===========================================================================
# get_relevant_islands Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_relevant_islands_returns_communities(mock_neo4j_client):
    """Test retrieving Knowledge Island summaries."""
    mock_neo4j_client.execute_query.return_value = [
        {
            "name": "Work Island",
            "theme": "professional",
            "summary": "Work-related projects and contacts",
            "pending_tasks": 5,
        },
        {
            "name": "Personal Island",
            "theme": "personal",
            "summary": "Family and personal activities",
            "pending_tasks": 2,
        },
    ]

    islands = await get_relevant_islands(
        mock_neo4j_client,
        limit=5,
        trace_id="test-123",
    )

    assert len(islands) == 2
    assert all(isinstance(i, CommunityContext) for i in islands)
    assert islands[0].name == "Work Island"
    assert islands[0].theme == "professional"
    assert islands[0].pending_tasks == 5
    assert islands[1].name == "Personal Island"
    assert islands[1].pending_tasks == 2

    # Verify query parameters
    mock_neo4j_client.execute_query.assert_called_once()
    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][1]["limit"] == 5


@pytest.mark.asyncio
async def test_get_relevant_islands_empty_results(mock_neo4j_client):
    """Test that empty results return empty list."""
    mock_neo4j_client.execute_query.return_value = []

    islands = await get_relevant_islands(mock_neo4j_client)

    assert islands == []
    assert isinstance(islands, list)


@pytest.mark.asyncio
async def test_get_relevant_islands_handles_missing_fields(mock_neo4j_client):
    """Test handling of missing optional fields."""
    mock_neo4j_client.execute_query.return_value = [
        {
            "name": None,
            "theme": "work",
            "summary": None,
            "pending_tasks": None,
        },
    ]

    islands = await get_relevant_islands(mock_neo4j_client)

    assert len(islands) == 1
    assert islands[0].name == "Unknown Island"
    assert islands[0].theme == "work"
    assert islands[0].summary == ""
    assert islands[0].pending_tasks == 0


# ===========================================================================
# get_pending_tasks Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_pending_tasks_returns_tasks(mock_neo4j_client):
    """Test retrieving pending tasks."""
    mock_neo4j_client.execute_query.return_value = [
        {
            "uuid": "task-1",
            "action": "Review PR",
            "status": "todo",
            "priority": "high",
            "due_date": 1234567890.0,
            "completed_at": None,
            "created_at": 1234567800.0,
            "updated_at": 1234567800.0,
            "assignee": "Alice",
        },
        {
            "uuid": "task-2",
            "action": "Update docs",
            "status": "in_progress",
            "priority": "medium",
            "due_date": None,
            "completed_at": None,
            "created_at": 1234567700.0,
            "updated_at": 1234567750.0,
            "assignee": None,
        },
    ]

    tasks = await get_pending_tasks(
        mock_neo4j_client,
        limit=20,
        trace_id="test-123",
    )

    assert len(tasks) == 2
    assert all(isinstance(t, TaskNode) for t in tasks)
    assert tasks[0].action == "Review PR"
    assert tasks[0].status == "todo"
    assert tasks[0].priority == "high"
    assert tasks[1].action == "Update docs"
    assert tasks[1].status == "in_progress"

    # Verify query parameters
    mock_neo4j_client.execute_query.assert_called_once()
    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][1]["limit"] == 20


@pytest.mark.asyncio
async def test_get_pending_tasks_empty_results(mock_neo4j_client):
    """Test that empty results return empty list."""
    mock_neo4j_client.execute_query.return_value = []

    tasks = await get_pending_tasks(mock_neo4j_client)

    assert tasks == []
    assert isinstance(tasks, list)


@pytest.mark.asyncio
async def test_get_pending_tasks_handles_missing_fields(mock_neo4j_client):
    """Test handling of missing required fields."""
    mock_neo4j_client.execute_query.return_value = [
        {
            "uuid": None,
            "action": "Do something",
            "status": None,
            "priority": None,
            "due_date": None,
            "completed_at": None,
            "created_at": None,
            "updated_at": None,
            "assignee": None,
        },
    ]

    tasks = await get_pending_tasks(mock_neo4j_client)

    assert len(tasks) == 1
    assert tasks[0].uuid == ""
    assert tasks[0].action == "Do something"
    assert tasks[0].status == "todo"  # Default value
    assert tasks[0].created_at == 0.0


# ===========================================================================
# get_recent_entities Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_recent_entities_returns_entities(mock_neo4j_client):
    """Test retrieving recently created entities."""
    mock_neo4j_client.execute_query.return_value = [
        {
            "uuid": "person-1",
            "name": "Alice",
            "entity_type": "Person",
            "created_at": 1234567890.0,
        },
        {
            "uuid": "org-1",
            "name": "Acme Corp",
            "entity_type": "Organization",
            "created_at": 1234567880.0,
        },
        {
            "uuid": "project-1",
            "name": "Project Phoenix",
            "entity_type": "Project",
            "created_at": 1234567870.0,
        },
    ]

    entities = await get_recent_entities(
        mock_neo4j_client,
        hours=24,
        limit=20,
        trace_id="test-123",
    )

    assert len(entities) == 3
    assert all(isinstance(e, EntityReference) for e in entities)
    assert entities[0].name == "Alice"
    assert entities[0].entity_type == "Person"
    assert entities[1].name == "Acme Corp"
    assert entities[1].entity_type == "Organization"
    assert entities[2].name == "Project Phoenix"

    # Verify query parameters
    mock_neo4j_client.execute_query.assert_called_once()
    call_args = mock_neo4j_client.execute_query.call_args
    assert "cutoff" in call_args[0][1]
    assert call_args[0][1]["limit"] == 20


@pytest.mark.asyncio
async def test_get_recent_entities_empty_results(mock_neo4j_client):
    """Test that empty results return empty list."""
    mock_neo4j_client.execute_query.return_value = []

    entities = await get_recent_entities(mock_neo4j_client)

    assert entities == []
    assert isinstance(entities, list)


@pytest.mark.asyncio
async def test_get_recent_entities_handles_missing_fields(mock_neo4j_client):
    """Test handling of missing fields."""
    mock_neo4j_client.execute_query.return_value = [
        {
            "uuid": None,
            "name": "Someone",
            "entity_type": None,
            "created_at": None,
        },
    ]

    entities = await get_recent_entities(mock_neo4j_client)

    assert len(entities) == 1
    assert entities[0].uuid == ""
    assert entities[0].name == "Someone"
    assert entities[0].entity_type == "Unknown"
    assert entities[0].created_at == 0.0


@pytest.mark.asyncio
async def test_get_recent_entities_cutoff_calculation(mock_neo4j_client):
    """Test that cutoff timestamp is calculated correctly."""
    mock_neo4j_client.execute_query.return_value = []

    before = datetime.now(UTC)
    await get_recent_entities(mock_neo4j_client, hours=48)

    # Verify cutoff is approximately 48 hours ago
    call_args = mock_neo4j_client.execute_query.call_args
    cutoff = call_args[0][1]["cutoff"]
    expected_cutoff = before - timedelta(hours=48)

    # Allow 1 second tolerance
    assert abs(cutoff - expected_cutoff.timestamp()) < 1.0


# ===========================================================================
# Parametrized Query Safety Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_all_queries_use_parameters(mock_neo4j_client):
    """Verify all queries use parametrized Cypher."""
    mock_neo4j_client.execute_query.return_value = []

    # Test all query functions
    await get_recent_summaries(mock_neo4j_client, hours=12, limit=10)
    await get_relevant_islands(mock_neo4j_client, limit=5)
    await get_pending_tasks(mock_neo4j_client, limit=20)
    await get_recent_entities(mock_neo4j_client, hours=24, limit=20)

    # Verify all calls used parameters dict
    assert mock_neo4j_client.execute_query.call_count == 4
    for call in mock_neo4j_client.execute_query.call_args_list:
        query, params = call[0][0], call[0][1]
        # Verify no user input in query string (only $params)
        assert "$" in query  # Has parameter placeholders
        assert isinstance(params, dict)  # Passes parameters dict
        assert len(params) > 0  # Actually has parameters


@pytest.mark.asyncio
async def test_queries_log_with_trace_id(mock_neo4j_client):
    """Verify queries log trace_id when provided."""
    mock_neo4j_client.execute_query.return_value = []

    with patch("klabautermann.memory.context_queries.logger") as mock_logger:
        await get_recent_summaries(mock_neo4j_client, trace_id="test-trace-123")

        # Verify logger was called with trace_id
        assert mock_logger.debug.called
        log_calls = mock_logger.debug.call_args_list
        assert any("extra" in str(call) and "test-trace-123" in str(call) for call in log_calls)
