"""
Unit tests for Day Node Management.

Reference: specs/architecture/MEMORY.md Section 5 (Day Nodes)
Task: T042 - Day Node Management (Temporal Spine)

Day nodes form the chronological backbone of the knowledge graph,
anchoring all time-bound entities via [:OCCURRED_ON] relationships.

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.day_nodes import (
    get_daily_summary,
    get_day_contents,
    get_days_in_range,
    get_or_create_day,
    link_note_to_day,
    link_to_day,
)
from klabautermann.memory.neo4j_client import Neo4jClient


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_neo4j_client() -> Neo4jClient:
    """Create mock Neo4j client."""
    client = MagicMock(spec=Neo4jClient)
    client.execute_write = AsyncMock()
    client.execute_read = AsyncMock()
    return client


@pytest.fixture
def sample_date() -> datetime:
    """Sample date for testing (Wednesday, 2025-01-15)."""
    return datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)


@pytest.fixture
def sample_weekend_date() -> datetime:
    """Sample weekend date for testing (Saturday, 2025-01-18)."""
    return datetime(2025, 1, 18, 14, 0, 0, tzinfo=UTC)


# ===========================================================================
# get_or_create_day Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_or_create_day_basic(
    mock_neo4j_client: Neo4jClient,
    sample_date: datetime,
):
    """Test basic Day node creation."""
    mock_neo4j_client.execute_write.return_value = [{"date": "2025-01-15"}]

    result = await get_or_create_day(mock_neo4j_client, sample_date)

    # Verify query structure
    mock_neo4j_client.execute_write.assert_called_once()
    call_args = mock_neo4j_client.execute_write.call_args
    query = call_args[0][0]
    params = call_args[0][1]

    # Verify MERGE is used (idempotent)
    assert "MERGE (d:Day {date: $date})" in query
    assert "ON CREATE SET" in query

    # Verify parameters
    assert params["date"] == "2025-01-15"
    assert params["day_of_week"] == "Wednesday"
    assert params["is_weekend"] is False

    # Verify result
    assert result == "2025-01-15"


@pytest.mark.asyncio
async def test_get_or_create_day_weekend(
    mock_neo4j_client: Neo4jClient,
    sample_weekend_date: datetime,
):
    """Test Day node creation for weekend."""
    mock_neo4j_client.execute_write.return_value = [{"date": "2025-01-18"}]

    result = await get_or_create_day(mock_neo4j_client, sample_weekend_date)

    call_args = mock_neo4j_client.execute_write.call_args
    params = call_args[0][1]

    # Verify weekend detection
    assert params["day_of_week"] == "Saturday"
    assert params["is_weekend"] is True

    assert result == "2025-01-18"


@pytest.mark.asyncio
async def test_get_or_create_day_idempotent(
    mock_neo4j_client: Neo4jClient,
    sample_date: datetime,
):
    """Test that calling get_or_create_day multiple times is safe."""
    mock_neo4j_client.execute_write.return_value = [{"date": "2025-01-15"}]

    # Call twice
    result1 = await get_or_create_day(mock_neo4j_client, sample_date)
    result2 = await get_or_create_day(mock_neo4j_client, sample_date)

    # Both should return same result
    assert result1 == result2
    assert result1 == "2025-01-15"

    # Verify MERGE was used both times (safe to repeat)
    assert mock_neo4j_client.execute_write.call_count == 2


@pytest.mark.asyncio
async def test_get_or_create_day_with_trace_id(
    mock_neo4j_client: Neo4jClient,
    sample_date: datetime,
):
    """Test that trace_id is passed through correctly."""
    mock_neo4j_client.execute_write.return_value = [{"date": "2025-01-15"}]
    trace_id = "test-trace-123"

    await get_or_create_day(mock_neo4j_client, sample_date, trace_id=trace_id)

    call_args = mock_neo4j_client.execute_write.call_args
    assert call_args[1]["trace_id"] == trace_id


# ===========================================================================
# link_to_day Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_link_to_day_basic(
    mock_neo4j_client: Neo4jClient,
    sample_date: datetime,
):
    """Test linking a Note to a Day node."""
    note_uuid = "note-uuid-123"

    await link_to_day(mock_neo4j_client, note_uuid, "Note", sample_date)

    # Verify query structure
    mock_neo4j_client.execute_write.assert_called_once()
    call_args = mock_neo4j_client.execute_write.call_args
    query = call_args[0][0]
    params = call_args[0][1]

    # Verify label is interpolated (safe)
    assert "MATCH (n:Note {uuid: $node_uuid})" in query
    # Verify Day MERGE (creates if needed)
    assert "MERGE (d:Day {date: $date})" in query
    # Verify relationship MERGE (idempotent)
    assert "MERGE (n)-[:OCCURRED_ON]->(d)" in query

    # Verify parameters (user data is parametrized)
    assert params["node_uuid"] == note_uuid
    assert params["date"] == "2025-01-15"


@pytest.mark.asyncio
async def test_link_to_day_event(
    mock_neo4j_client: Neo4jClient,
    sample_date: datetime,
):
    """Test linking an Event to a Day node."""
    event_uuid = "event-uuid-456"

    await link_to_day(mock_neo4j_client, event_uuid, "Event", sample_date)

    call_args = mock_neo4j_client.execute_write.call_args
    query = call_args[0][0]

    # Verify Event label is used
    assert "MATCH (n:Event {uuid: $node_uuid})" in query


@pytest.mark.asyncio
async def test_link_to_day_journal_entry(
    mock_neo4j_client: Neo4jClient,
    sample_date: datetime,
):
    """Test linking a JournalEntry to a Day node."""
    journal_uuid = "journal-uuid-789"

    await link_to_day(mock_neo4j_client, journal_uuid, "JournalEntry", sample_date)

    call_args = mock_neo4j_client.execute_write.call_args
    query = call_args[0][0]

    # Verify JournalEntry label is used
    assert "MATCH (n:JournalEntry {uuid: $node_uuid})" in query


# ===========================================================================
# link_note_to_day Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_link_note_to_day_with_date(
    mock_neo4j_client: Neo4jClient,
    sample_date: datetime,
):
    """Test link_note_to_day with explicit date."""
    note_uuid = "note-uuid-abc"

    await link_note_to_day(mock_neo4j_client, note_uuid, date=sample_date)

    # Verify it calls link_to_day with correct parameters
    mock_neo4j_client.execute_write.assert_called_once()
    call_args = mock_neo4j_client.execute_write.call_args
    params = call_args[0][1]

    assert params["node_uuid"] == note_uuid
    assert params["date"] == "2025-01-15"


@pytest.mark.asyncio
async def test_link_note_to_day_default_date(
    mock_neo4j_client: Neo4jClient,
):
    """Test link_note_to_day uses current date when not specified."""
    note_uuid = "note-uuid-def"

    await link_note_to_day(mock_neo4j_client, note_uuid)

    # Verify it was called
    mock_neo4j_client.execute_write.assert_called_once()
    call_args = mock_neo4j_client.execute_write.call_args
    params = call_args[0][1]

    # Verify note UUID is correct
    assert params["node_uuid"] == note_uuid

    # Verify date is today (YYYY-MM-DD format)
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    assert params["date"] == today_str


# ===========================================================================
# get_day_contents Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_day_contents_basic(
    mock_neo4j_client: Neo4jClient,
):
    """Test retrieving contents of a Day node."""
    mock_neo4j_client.execute_read.return_value = [
        {
            "type": "Note",
            "uuid": "note-1",
            "title": "Meeting notes",
            "summary": "Discussed project X",
            "created_at": 1736937000.0,
        },
        {
            "type": "Event",
            "uuid": "event-1",
            "title": "Team sync",
            "summary": None,
            "created_at": 1736940000.0,
        },
    ]

    result = await get_day_contents(mock_neo4j_client, "2025-01-15")

    # Verify query structure
    mock_neo4j_client.execute_read.assert_called_once()
    call_args = mock_neo4j_client.execute_read.call_args
    query = call_args[0][0]
    params = call_args[0][1]

    # Verify query uses OCCURRED_ON relationship
    assert "MATCH (d:Day {date: $date})<-[:OCCURRED_ON]-(item)" in query
    assert "ORDER BY item.created_at" in query
    assert params["date"] == "2025-01-15"

    # Verify result is grouped by type
    assert "Note" in result
    assert "Event" in result
    assert len(result["Note"]) == 1
    assert len(result["Event"]) == 1

    # Verify Note data
    assert result["Note"][0]["uuid"] == "note-1"
    assert result["Note"][0]["title"] == "Meeting notes"
    assert result["Note"][0]["summary"] == "Discussed project X"

    # Verify Event data
    assert result["Event"][0]["uuid"] == "event-1"
    assert result["Event"][0]["title"] == "Team sync"


@pytest.mark.asyncio
async def test_get_day_contents_empty(
    mock_neo4j_client: Neo4jClient,
):
    """Test retrieving contents when Day has no linked entities."""
    mock_neo4j_client.execute_read.return_value = []

    result = await get_day_contents(mock_neo4j_client, "2025-01-15")

    # Verify empty result
    assert result == {}


@pytest.mark.asyncio
async def test_get_day_contents_multiple_same_type(
    mock_neo4j_client: Neo4jClient,
):
    """Test grouping multiple items of same type."""
    mock_neo4j_client.execute_read.return_value = [
        {
            "type": "Note",
            "uuid": "note-1",
            "title": "Note 1",
            "summary": "Summary 1",
            "created_at": 1736937000.0,
        },
        {
            "type": "Note",
            "uuid": "note-2",
            "title": "Note 2",
            "summary": "Summary 2",
            "created_at": 1736937100.0,
        },
        {
            "type": "Note",
            "uuid": "note-3",
            "title": "Note 3",
            "summary": "Summary 3",
            "created_at": 1736937200.0,
        },
    ]

    result = await get_day_contents(mock_neo4j_client, "2025-01-15")

    # Verify all notes are grouped together
    assert "Note" in result
    assert len(result["Note"]) == 3
    assert result["Note"][0]["uuid"] == "note-1"
    assert result["Note"][1]["uuid"] == "note-2"
    assert result["Note"][2]["uuid"] == "note-3"


# ===========================================================================
# get_days_in_range Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_days_in_range_basic(
    mock_neo4j_client: Neo4jClient,
):
    """Test retrieving Day nodes in a date range."""
    mock_neo4j_client.execute_read.return_value = [
        {
            "date": "2025-01-13",
            "day_of_week": "Monday",
            "is_weekend": False,
            "note_count": 2,
            "event_count": 1,
            "journal_count": 0,
        },
        {
            "date": "2025-01-14",
            "day_of_week": "Tuesday",
            "is_weekend": False,
            "note_count": 1,
            "event_count": 0,
            "journal_count": 0,
        },
        {
            "date": "2025-01-15",
            "day_of_week": "Wednesday",
            "is_weekend": False,
            "note_count": 3,
            "event_count": 2,
            "journal_count": 1,
        },
    ]

    result = await get_days_in_range(mock_neo4j_client, "2025-01-13", "2025-01-15")

    # Verify query structure
    mock_neo4j_client.execute_read.assert_called_once()
    call_args = mock_neo4j_client.execute_read.call_args
    query = call_args[0][0]
    params = call_args[0][1]

    # Verify date range filtering
    assert "WHERE d.date >= $start_date AND d.date <= $end_date" in query
    assert "ORDER BY d.date" in query
    assert params["start_date"] == "2025-01-13"
    assert params["end_date"] == "2025-01-15"

    # Verify OPTIONAL MATCH for counts (day might have no entities)
    assert "OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(note:Note)" in query
    assert "OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(event:Event)" in query
    assert "OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(journal:JournalEntry)" in query

    # Verify result
    assert len(result) == 3
    assert result[0]["date"] == "2025-01-13"
    assert result[0]["note_count"] == 2
    assert result[1]["date"] == "2025-01-14"
    assert result[2]["date"] == "2025-01-15"
    assert result[2]["note_count"] == 3


@pytest.mark.asyncio
async def test_get_days_in_range_empty(
    mock_neo4j_client: Neo4jClient,
):
    """Test retrieving days when no Day nodes exist in range."""
    mock_neo4j_client.execute_read.return_value = []

    result = await get_days_in_range(mock_neo4j_client, "2025-12-01", "2025-12-31")

    # Verify empty result
    assert result == []


@pytest.mark.asyncio
async def test_get_days_in_range_weekend_included(
    mock_neo4j_client: Neo4jClient,
):
    """Test that weekend days are properly marked."""
    mock_neo4j_client.execute_read.return_value = [
        {
            "date": "2025-01-17",
            "day_of_week": "Friday",
            "is_weekend": False,
            "note_count": 1,
            "event_count": 0,
            "journal_count": 0,
        },
        {
            "date": "2025-01-18",
            "day_of_week": "Saturday",
            "is_weekend": True,
            "note_count": 0,
            "event_count": 0,
            "journal_count": 0,
        },
        {
            "date": "2025-01-19",
            "day_of_week": "Sunday",
            "is_weekend": True,
            "note_count": 0,
            "event_count": 1,
            "journal_count": 0,
        },
    ]

    result = await get_days_in_range(mock_neo4j_client, "2025-01-17", "2025-01-19")

    # Verify weekend flags
    assert result[0]["is_weekend"] is False  # Friday
    assert result[1]["is_weekend"] is True  # Saturday
    assert result[2]["is_weekend"] is True  # Sunday


# ===========================================================================
# get_daily_summary Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_daily_summary_basic(
    mock_neo4j_client: Neo4jClient,
):
    """Test retrieving daily summary statistics."""
    mock_neo4j_client.execute_read.return_value = [
        {
            "date": "2025-01-15",
            "day_of_week": "Wednesday",
            "is_weekend": False,
            "note_count": 5,
            "event_count": 2,
            "journal_count": 1,
        }
    ]

    result = await get_daily_summary(mock_neo4j_client, "2025-01-15")

    # Verify query structure
    mock_neo4j_client.execute_read.assert_called_once()
    call_args = mock_neo4j_client.execute_read.call_args
    query = call_args[0][0]
    params = call_args[0][1]

    # Verify query targets specific day
    assert "MATCH (d:Day {date: $date})" in query
    assert params["date"] == "2025-01-15"

    # Verify result structure
    assert result["date"] == "2025-01-15"
    assert result["day_of_week"] == "Wednesday"
    assert result["is_weekend"] is False
    assert result["note_count"] == 5
    assert result["event_count"] == 2
    assert result["journal_count"] == 1


@pytest.mark.asyncio
async def test_get_daily_summary_no_day_node(
    mock_neo4j_client: Neo4jClient,
):
    """Test daily summary when Day node doesn't exist yet."""
    mock_neo4j_client.execute_read.return_value = []

    result = await get_daily_summary(mock_neo4j_client, "2025-01-15")

    # Verify graceful handling of missing Day node
    assert result["date"] == "2025-01-15"
    assert result["day_of_week"] is None
    assert result["is_weekend"] is False
    assert result["note_count"] == 0
    assert result["event_count"] == 0
    assert result["journal_count"] == 0


@pytest.mark.asyncio
async def test_get_daily_summary_zero_counts(
    mock_neo4j_client: Neo4jClient,
):
    """Test daily summary for a day with no linked entities."""
    mock_neo4j_client.execute_read.return_value = [
        {
            "date": "2025-01-15",
            "day_of_week": "Wednesday",
            "is_weekend": False,
            "note_count": 0,
            "event_count": 0,
            "journal_count": 0,
        }
    ]

    result = await get_daily_summary(mock_neo4j_client, "2025-01-15")

    # Verify counts are zero (not None)
    assert result["note_count"] == 0
    assert result["event_count"] == 0
    assert result["journal_count"] == 0
