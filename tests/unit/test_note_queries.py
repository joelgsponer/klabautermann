"""
Unit tests for note query functions.

Tests Note node creation from thread summaries and entity linking.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.core.models import ActionItem, ActionStatus, ThreadSummary
from klabautermann.memory.neo4j_client import Neo4jClient
from klabautermann.memory.note_queries import (
    create_note_from_summary,
    create_note_with_links,
    generate_note_title,
    link_entities_to_note,
    link_note_to_thread,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_neo4j_client() -> Neo4jClient:
    """Create mock Neo4j client."""
    client = MagicMock(spec=Neo4jClient)
    client.execute_write = AsyncMock()
    client.execute_query = AsyncMock()
    return client


@pytest.fixture
def sample_thread_summary() -> ThreadSummary:
    """Create sample ThreadSummary."""
    return ThreadSummary(
        summary="Discussed Q1 planning and budget allocation. Sarah will review the proposal.",
        topics=["Q1 Planning", "Budget Review", "Resource Allocation"],
        action_items=[
            ActionItem(
                action="Review budget proposal",
                assignee="Sarah",
                status=ActionStatus.PENDING,
                confidence=0.9,
            ),
            ActionItem(
                action="Send meeting notes to team",
                assignee=None,
                status=ActionStatus.PENDING,
                confidence=0.85,
            ),
        ],
        participants=["Sarah Johnson", "John Smith", "Acme Corp"],
        sentiment="positive",
        new_facts=[],
        conflicts=[],
    )


@pytest.fixture
def sample_thread_summary_with_conflict() -> ThreadSummary:
    """Create ThreadSummary with conflicts (requires validation)."""
    from klabautermann.core.models import ConflictResolution, FactConflict

    return ThreadSummary(
        summary="Discussion about Sarah's new role.",
        topics=["Career Update"],
        action_items=[],
        participants=["Sarah Johnson"],
        sentiment="neutral",
        new_facts=[],
        conflicts=[
            FactConflict(
                existing_fact="Sarah works at Acme Corp",
                new_fact="Sarah works at NewCo",
                entity="Sarah Johnson",
                resolution=ConflictResolution.USER_REVIEW,
            )
        ],
    )


# ===========================================================================
# Title Generation Tests
# ===========================================================================


def test_generate_note_title_with_topics():
    """Test title generation from topics."""
    topics = ["Project Planning", "Budget Review"]
    title = generate_note_title(topics)
    assert title == "Project Planning / Budget Review"


def test_generate_note_title_empty_topics():
    """Test title generation with no topics."""
    title = generate_note_title([])
    assert title == "Conversation Summary"


def test_generate_note_title_many_topics():
    """Test title generation uses first 3 topics."""
    topics = ["Topic 1", "Topic 2", "Topic 3", "Topic 4", "Topic 5"]
    title = generate_note_title(topics)
    assert title == "Topic 1 / Topic 2 / Topic 3"
    assert "Topic 4" not in title


def test_generate_note_title_truncation():
    """Test title truncation at max_length."""
    topics = ["Very Long Topic Name That Exceeds Maximum Length"]
    title = generate_note_title(topics, max_length=20)
    assert len(title) == 20
    assert title.endswith("...")
    assert title == "Very Long Topic N..."


def test_generate_note_title_no_truncation_needed():
    """Test title not truncated when under max_length."""
    topics = ["Short"]
    title = generate_note_title(topics, max_length=20)
    assert title == "Short"
    assert not title.endswith("...")


# ===========================================================================
# Note Creation Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_create_note_from_summary(
    mock_neo4j_client: Neo4jClient, sample_thread_summary: ThreadSummary
):
    """Test Note node creation from ThreadSummary."""
    thread_uuid = "thread-123"

    # Mock successful Note creation
    mock_neo4j_client.execute_write.return_value = [{"uuid": "note-uuid-123"}]

    note_uuid = await create_note_from_summary(
        mock_neo4j_client, thread_uuid, sample_thread_summary, trace_id="test-trace"
    )

    # Verify Note was created
    assert note_uuid is not None
    assert isinstance(note_uuid, str)

    # Verify execute_write was called with correct query
    mock_neo4j_client.execute_write.assert_called_once()
    call_args = mock_neo4j_client.execute_write.call_args

    query = call_args[0][0]
    params = call_args[0][1]

    # Check query structure
    assert "CREATE (n:Note" in query
    assert "RETURN n.uuid" in query

    # Check parameters
    assert params["uuid"] == note_uuid
    assert params["title"] == "Q1 Planning / Budget Review / Resource Allocation"
    assert params["content_summarized"] == sample_thread_summary.summary
    assert params["topics"] == sample_thread_summary.topics
    assert params["sentiment"] == "positive"
    assert params["source"] == "thread_summary"
    assert params["requires_user_validation"] is False

    # Verify action items serialized
    action_items = json.loads(params["action_items"])
    assert len(action_items) == 2
    assert action_items[0]["action"] == "Review budget proposal"
    assert action_items[0]["assignee"] == "Sarah"


@pytest.mark.asyncio
async def test_create_note_from_summary_with_conflict(
    mock_neo4j_client: Neo4jClient, sample_thread_summary_with_conflict: ThreadSummary
):
    """Test Note creation with conflict sets requires_user_validation."""
    thread_uuid = "thread-123"
    mock_neo4j_client.execute_write.return_value = [{"uuid": "note-uuid-123"}]

    await create_note_from_summary(
        mock_neo4j_client, thread_uuid, sample_thread_summary_with_conflict
    )

    # Verify requires_user_validation is True
    call_args = mock_neo4j_client.execute_write.call_args
    params = call_args[0][1]
    assert params["requires_user_validation"] is True


@pytest.mark.asyncio
async def test_create_note_from_summary_failure(
    mock_neo4j_client: Neo4jClient, sample_thread_summary: ThreadSummary
):
    """Test Note creation handles database failure."""
    thread_uuid = "thread-123"

    # Mock empty result (creation failed)
    mock_neo4j_client.execute_write.return_value = []

    with pytest.raises(RuntimeError, match="Failed to create Note node"):
        await create_note_from_summary(mock_neo4j_client, thread_uuid, sample_thread_summary)


# ===========================================================================
# Note-Thread Linking Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_link_note_to_thread(mock_neo4j_client: Neo4jClient):
    """Test SUMMARY_OF relationship creation."""
    note_uuid = "note-123"
    thread_uuid = "thread-456"

    # Mock successful relationship creation
    mock_neo4j_client.execute_write.return_value = [
        {"note_uuid": note_uuid, "thread_uuid": thread_uuid}
    ]

    await link_note_to_thread(mock_neo4j_client, note_uuid, thread_uuid, trace_id="test-trace")

    # Verify relationship was created
    mock_neo4j_client.execute_write.assert_called_once()
    call_args = mock_neo4j_client.execute_write.call_args

    query = call_args[0][0]
    params = call_args[0][1]

    # Check query structure
    assert "MATCH (n:Note {uuid: $note_uuid})" in query
    assert "MATCH (t:Thread {uuid: $thread_uuid})" in query
    assert "CREATE (n)-[:SUMMARY_OF" in query

    # Check parameters
    assert params["note_uuid"] == note_uuid
    assert params["thread_uuid"] == thread_uuid
    assert "created_at" in params


@pytest.mark.asyncio
async def test_link_note_to_thread_not_found(mock_neo4j_client: Neo4jClient):
    """Test linking fails when Note or Thread not found."""
    note_uuid = "note-123"
    thread_uuid = "thread-456"

    # Mock empty result (nodes not found)
    mock_neo4j_client.execute_write.return_value = []

    with pytest.raises(RuntimeError, match="Note .* or Thread .* not found"):
        await link_note_to_thread(mock_neo4j_client, note_uuid, thread_uuid)


# ===========================================================================
# Entity Linking Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_link_entities_to_note(mock_neo4j_client: Neo4jClient):
    """Test linking entities to Note via MENTIONED_IN."""
    note_uuid = "note-123"
    entity_names = ["Sarah Johnson", "John Smith", "Acme Corp"]

    # Mock successful linking of 3 entities
    mock_neo4j_client.execute_write.return_value = [{"link_count": 3}]

    link_count = await link_entities_to_note(
        mock_neo4j_client, note_uuid, entity_names, trace_id="test-trace"
    )

    # Verify correct number of links
    assert link_count == 3

    # Verify query
    mock_neo4j_client.execute_write.assert_called_once()
    call_args = mock_neo4j_client.execute_write.call_args

    query = call_args[0][0]
    params = call_args[0][1]

    # Check query structure
    assert "MATCH (n:Note {uuid: $note_uuid})" in query
    assert "UNWIND $entity_names as name" in query
    assert "WHERE (e:Person OR e:Organization)" in query
    assert "toLower(e.name) = toLower(name)" in query
    assert "MERGE (e)-[r:MENTIONED_IN" in query

    # Check parameters
    assert params["note_uuid"] == note_uuid
    assert params["entity_names"] == entity_names


@pytest.mark.asyncio
async def test_link_entities_to_note_partial_match(mock_neo4j_client: Neo4jClient):
    """Test linking when only some entities are found."""
    note_uuid = "note-123"
    entity_names = ["Sarah Johnson", "Unknown Person", "Acme Corp"]

    # Mock only 2 entities found
    mock_neo4j_client.execute_write.return_value = [{"link_count": 2}]

    link_count = await link_entities_to_note(mock_neo4j_client, note_uuid, entity_names)

    # Verify only found entities were linked
    assert link_count == 2


@pytest.mark.asyncio
async def test_link_entities_to_note_empty_list(mock_neo4j_client: Neo4jClient):
    """Test linking with empty entity list."""
    note_uuid = "note-123"
    entity_names: list[str] = []

    link_count = await link_entities_to_note(mock_neo4j_client, note_uuid, entity_names)

    # Verify no query executed
    assert link_count == 0
    mock_neo4j_client.execute_write.assert_not_called()


@pytest.mark.asyncio
async def test_link_entities_to_note_case_insensitive(mock_neo4j_client: Neo4jClient):
    """Test entity linking is case-insensitive."""
    note_uuid = "note-123"
    entity_names = ["sarah johnson", "ACME CORP"]  # Different case

    mock_neo4j_client.execute_write.return_value = [{"link_count": 2}]

    await link_entities_to_note(mock_neo4j_client, note_uuid, entity_names)

    # Verify query uses toLower for case-insensitive match
    call_args = mock_neo4j_client.execute_write.call_args
    query = call_args[0][0]
    assert "toLower(e.name) = toLower(name)" in query


# ===========================================================================
# Integration Tests (create_note_with_links)
# ===========================================================================


@pytest.mark.asyncio
async def test_create_note_with_links(
    mock_neo4j_client: Neo4jClient, sample_thread_summary: ThreadSummary
):
    """Test complete Note creation with all links."""
    thread_uuid = "thread-123"

    # Mock all three operations
    mock_neo4j_client.execute_write.side_effect = [
        [{"uuid": "note-uuid-123"}],  # create_note_from_summary
        [{"note_uuid": "note-uuid-123", "thread_uuid": thread_uuid}],  # link_note_to_thread
        [{"link_count": 3}],  # link_entities_to_note
    ]

    result = await create_note_with_links(
        mock_neo4j_client, thread_uuid, sample_thread_summary, trace_id="test-trace"
    )

    # Verify result
    assert result["note_uuid"] is not None
    assert result["entity_link_count"] == 3

    # Verify all three operations were called
    assert mock_neo4j_client.execute_write.call_count == 3


@pytest.mark.asyncio
async def test_create_note_with_links_no_entities(
    mock_neo4j_client: Neo4jClient, sample_thread_summary: ThreadSummary
):
    """Test Note creation when no entities found."""
    thread_uuid = "thread-123"
    sample_thread_summary.participants = []  # No participants

    # Mock operations
    mock_neo4j_client.execute_write.side_effect = [
        [{"uuid": "note-uuid-123"}],  # create_note_from_summary
        [{"note_uuid": "note-uuid-123", "thread_uuid": thread_uuid}],  # link_note_to_thread
    ]

    result = await create_note_with_links(mock_neo4j_client, thread_uuid, sample_thread_summary)

    # Verify no entity linking attempted (empty list)
    assert result["entity_link_count"] == 0
    # Only 2 queries executed (no entity linking)
    assert mock_neo4j_client.execute_write.call_count == 2


# ===========================================================================
# Edge Cases
# ===========================================================================


def test_generate_note_title_single_long_topic():
    """Test title with single topic that needs truncation."""
    topics = ["This is a very long topic name that definitely exceeds the maximum length"]
    title = generate_note_title(topics, max_length=30)
    assert len(title) == 30
    assert title == "This is a very long topic n..."


def test_generate_note_title_exactly_max_length():
    """Test title that is exactly max_length."""
    topics = ["Exactly Twenty Chars"]  # 20 chars
    title = generate_note_title(topics, max_length=20)
    assert title == "Exactly Twenty Chars"
    assert not title.endswith("...")


@pytest.mark.asyncio
async def test_create_note_from_summary_empty_action_items(
    mock_neo4j_client: Neo4jClient,
):
    """Test Note creation with no action items."""
    thread_uuid = "thread-123"
    summary = ThreadSummary(
        summary="Simple conversation",
        topics=["General Chat"],
        action_items=[],  # Empty
        participants=[],
        sentiment="neutral",
        new_facts=[],
        conflicts=[],
    )

    mock_neo4j_client.execute_write.return_value = [{"uuid": "note-uuid-123"}]

    await create_note_from_summary(mock_neo4j_client, thread_uuid, summary)

    # Verify action_items serialized as empty array
    call_args = mock_neo4j_client.execute_write.call_args
    params = call_args[0][1]
    action_items = json.loads(params["action_items"])
    assert action_items == []
