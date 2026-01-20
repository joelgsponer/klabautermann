"""
Unit tests for temporal spine queries module.

Tests Day node management and date-based queries.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.temporal_spine import (
    DayActivity,
    DayNode,
    DaySummary,
    WeeklySummary,
    find_entities_by_date,
    find_entities_in_range,
    get_active_days_in_range,
    get_date_range_activities,
    get_day_activities,
    get_day_statistics,
    get_or_create_day,
    get_weekly_summary,
    link_to_day,
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
# Test Data Classes
# =============================================================================


class TestDayNode:
    """Tests for DayNode dataclass."""

    def test_creation(self) -> None:
        """Test creating DayNode."""
        day = DayNode(
            date="2024-01-15",
            day_of_week="Monday",
            is_weekend=False,
            event_count=3,
            note_count=2,
            journal_count=1,
        )
        assert day.date == "2024-01-15"
        assert day.day_of_week == "Monday"
        assert day.is_weekend is False
        assert day.event_count == 3


class TestDayActivity:
    """Tests for DayActivity dataclass."""

    def test_creation(self) -> None:
        """Test creating DayActivity."""
        activity = DayActivity(
            uuid="event-001",
            item_type="Event",
            title="Team Meeting",
            start_time=1705320000.0,
            properties={"location": "Room 101"},
        )
        assert activity.uuid == "event-001"
        assert activity.item_type == "Event"
        assert activity.title == "Team Meeting"


class TestDaySummary:
    """Tests for DaySummary dataclass."""

    def test_creation(self) -> None:
        """Test creating DaySummary."""
        summary = DaySummary(
            date="2024-01-15",
            day_of_week="Monday",
            is_weekend=False,
            activities=["Meeting", "Lunch"],
        )
        assert summary.date == "2024-01-15"
        assert len(summary.activities) == 2


class TestWeeklySummary:
    """Tests for WeeklySummary dataclass."""

    def test_creation(self) -> None:
        """Test creating WeeklySummary."""
        day = DaySummary(
            date="2024-01-15",
            day_of_week="Monday",
            is_weekend=False,
            activities=["Meeting"],
        )
        summary = WeeklySummary(
            start_date="2024-01-15",
            end_date="2024-01-21",
            days=[day],
            total_events=5,
            total_notes=3,
        )
        assert summary.start_date == "2024-01-15"
        assert summary.total_events == 5
        assert len(summary.days) == 1


# =============================================================================
# Test Day Node Management
# =============================================================================


class TestGetOrCreateDay:
    """Tests for get_or_create_day function."""

    @pytest.mark.asyncio
    async def test_creates_day_from_string(self, mock_neo4j: MagicMock) -> None:
        """Test creating day from date string."""
        mock_neo4j.execute_query.return_value = [{"date": "2024-01-15"}]

        result = await get_or_create_day(mock_neo4j, "2024-01-15")

        assert result == "2024-01-15"
        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["date"] == "2024-01-15"
        assert call_args[0][1]["day_of_week"] == "Monday"
        assert call_args[0][1]["is_weekend"] is False

    @pytest.mark.asyncio
    async def test_creates_day_from_date(self, mock_neo4j: MagicMock) -> None:
        """Test creating day from date object."""
        mock_neo4j.execute_query.return_value = [{"date": "2024-01-20"}]
        target = date(2024, 1, 20)

        result = await get_or_create_day(mock_neo4j, target)

        assert result == "2024-01-20"
        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["day_of_week"] == "Saturday"
        assert call_args[0][1]["is_weekend"] is True

    @pytest.mark.asyncio
    async def test_creates_day_from_datetime(self, mock_neo4j: MagicMock) -> None:
        """Test creating day from datetime object."""
        mock_neo4j.execute_query.return_value = [{"date": "2024-01-21"}]
        target = datetime(2024, 1, 21, 10, 30, 0)

        result = await get_or_create_day(mock_neo4j, target)

        assert result == "2024-01-21"
        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["day_of_week"] == "Sunday"
        assert call_args[0][1]["is_weekend"] is True


class TestLinkToDay:
    """Tests for link_to_day function."""

    @pytest.mark.asyncio
    async def test_links_node_to_day(self, mock_neo4j: MagicMock) -> None:
        """Test linking a node to a day."""
        mock_neo4j.execute_query.side_effect = [
            [{"date": "2024-01-15"}],  # get_or_create_day
            [{"uuid": "event-001"}],  # link query
        ]

        result = await link_to_day(mock_neo4j, "event-001", "Event", "2024-01-15")

        assert result is True
        assert mock_neo4j.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_false_when_node_not_found(self, mock_neo4j: MagicMock) -> None:
        """Test returns False when node doesn't exist."""
        mock_neo4j.execute_query.side_effect = [
            [{"date": "2024-01-15"}],  # get_or_create_day
            [],  # link query - no match
        ]

        result = await link_to_day(mock_neo4j, "nonexistent", "Event", "2024-01-15")

        assert result is False


# =============================================================================
# Test Day-Based Queries
# =============================================================================


class TestGetDayActivities:
    """Tests for get_day_activities function."""

    @pytest.mark.asyncio
    async def test_returns_activities(self, mock_neo4j: MagicMock) -> None:
        """Test getting activities for a day."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "event-001",
                "item_type": "Event",
                "title": "Morning Standup",
                "start_time": 1705320000.0,
                "properties": {"location": "Zoom"},
            },
            {
                "uuid": "note-001",
                "item_type": "Note",
                "title": "Meeting Notes",
                "start_time": None,
                "properties": {},
            },
        ]

        results = await get_day_activities(mock_neo4j, "2024-01-15")

        assert len(results) == 2
        assert results[0].item_type == "Event"
        assert results[1].item_type == "Note"

    @pytest.mark.asyncio
    async def test_empty_day(self, mock_neo4j: MagicMock) -> None:
        """Test getting activities for empty day."""
        mock_neo4j.execute_query.return_value = []

        results = await get_day_activities(mock_neo4j, "2024-01-15")

        assert len(results) == 0


class TestGetDateRangeActivities:
    """Tests for get_date_range_activities function."""

    @pytest.mark.asyncio
    async def test_returns_activities_by_date(self, mock_neo4j: MagicMock) -> None:
        """Test getting activities for date range."""
        mock_neo4j.execute_query.return_value = [
            {
                "date": "2024-01-15",
                "activities": [
                    {
                        "uuid": "e1",
                        "item_type": "Event",
                        "title": "Meeting",
                        "start_time": None,
                        "properties": {},
                    },
                ],
            },
            {
                "date": "2024-01-16",
                "activities": [
                    {
                        "uuid": "e2",
                        "item_type": "Event",
                        "title": "Call",
                        "start_time": None,
                        "properties": {},
                    },
                    {
                        "uuid": "n1",
                        "item_type": "Note",
                        "title": "Notes",
                        "start_time": None,
                        "properties": {},
                    },
                ],
            },
        ]

        results = await get_date_range_activities(mock_neo4j, "2024-01-15", "2024-01-16")

        assert "2024-01-15" in results
        assert "2024-01-16" in results
        assert len(results["2024-01-15"]) == 1
        assert len(results["2024-01-16"]) == 2

    @pytest.mark.asyncio
    async def test_filters_empty_activities(self, mock_neo4j: MagicMock) -> None:
        """Test that activities without uuid are filtered."""
        mock_neo4j.execute_query.return_value = [
            {
                "date": "2024-01-15",
                "activities": [
                    {
                        "uuid": None,
                        "item_type": None,
                        "title": None,
                        "start_time": None,
                        "properties": {},
                    },
                    {
                        "uuid": "e1",
                        "item_type": "Event",
                        "title": "Meeting",
                        "start_time": None,
                        "properties": {},
                    },
                ],
            },
        ]

        results = await get_date_range_activities(mock_neo4j, "2024-01-15", "2024-01-15")

        assert len(results["2024-01-15"]) == 1


class TestGetWeeklySummary:
    """Tests for get_weekly_summary function."""

    @pytest.mark.asyncio
    async def test_returns_summary(self, mock_neo4j: MagicMock) -> None:
        """Test getting weekly summary."""
        mock_neo4j.execute_query.return_value = [
            {
                "date": "2024-01-15",
                "day_of_week": "Monday",
                "is_weekend": False,
                "activity_titles": ["Meeting", "Call"],
                "event_count": 2,
                "note_count": 1,
            },
            {
                "date": "2024-01-16",
                "day_of_week": "Tuesday",
                "is_weekend": False,
                "activity_titles": ["Workshop"],
                "event_count": 1,
                "note_count": 0,
            },
        ]

        result = await get_weekly_summary(mock_neo4j, "2024-01-15")

        assert result.start_date == "2024-01-15"
        assert result.end_date == "2024-01-21"
        assert len(result.days) == 2
        assert result.total_events == 3
        assert result.total_notes == 1

    @pytest.mark.asyncio
    async def test_filters_none_activities(self, mock_neo4j: MagicMock) -> None:
        """Test that None activity titles are filtered."""
        mock_neo4j.execute_query.return_value = [
            {
                "date": "2024-01-15",
                "day_of_week": "Monday",
                "is_weekend": False,
                "activity_titles": [None, "Meeting", None],
                "event_count": 1,
                "note_count": 0,
            },
        ]

        result = await get_weekly_summary(mock_neo4j, "2024-01-15")

        assert len(result.days[0].activities) == 1
        assert result.days[0].activities[0] == "Meeting"


# =============================================================================
# Test Entity Lookup by Date
# =============================================================================


class TestFindEntitiesByDate:
    """Tests for find_entities_by_date function."""

    @pytest.mark.asyncio
    async def test_returns_entities(self, mock_neo4j: MagicMock) -> None:
        """Test finding entities by date."""
        mock_neo4j.execute_query.return_value = [
            {"uuid": "event-001", "entity_type": "Event", "properties": {"title": "Meeting"}},
            {"uuid": "note-001", "entity_type": "Note", "properties": {"title": "Notes"}},
        ]

        results = await find_entities_by_date(mock_neo4j, "2024-01-15")

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_with_entity_type_filter(self, mock_neo4j: MagicMock) -> None:
        """Test filtering by entity type."""
        mock_neo4j.execute_query.return_value = []

        await find_entities_by_date(mock_neo4j, "2024-01-15", entity_type="Event")

        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]
        assert "item:Event" in query


class TestFindEntitiesInRange:
    """Tests for find_entities_in_range function."""

    @pytest.mark.asyncio
    async def test_returns_entities(self, mock_neo4j: MagicMock) -> None:
        """Test finding entities in date range."""
        mock_neo4j.execute_query.return_value = [
            {"uuid": "e1", "entity_type": "Event", "occurred_on": "2024-01-15", "properties": {}},
            {"uuid": "e2", "entity_type": "Event", "occurred_on": "2024-01-16", "properties": {}},
        ]

        results = await find_entities_in_range(mock_neo4j, "2024-01-15", "2024-01-16")

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_respects_limit(self, mock_neo4j: MagicMock) -> None:
        """Test that limit is respected."""
        mock_neo4j.execute_query.return_value = []

        await find_entities_in_range(mock_neo4j, "2024-01-15", "2024-01-16", limit=50)

        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["limit"] == 50


# =============================================================================
# Test Day Statistics
# =============================================================================


class TestGetDayStatistics:
    """Tests for get_day_statistics function."""

    @pytest.mark.asyncio
    async def test_returns_statistics(self, mock_neo4j: MagicMock) -> None:
        """Test getting day statistics."""
        mock_neo4j.execute_query.return_value = [
            {
                "date": "2024-01-15",
                "day_of_week": "Monday",
                "is_weekend": False,
                "event_count": 3,
                "note_count": 2,
                "journal_count": 1,
            }
        ]

        result = await get_day_statistics(mock_neo4j, "2024-01-15")

        assert result is not None
        assert result.date == "2024-01-15"
        assert result.event_count == 3
        assert result.note_count == 2
        assert result.journal_count == 1

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_day(self, mock_neo4j: MagicMock) -> None:
        """Test returns None when day doesn't exist."""
        mock_neo4j.execute_query.return_value = []

        result = await get_day_statistics(mock_neo4j, "2024-01-15")

        assert result is None


class TestGetActiveDaysInRange:
    """Tests for get_active_days_in_range function."""

    @pytest.mark.asyncio
    async def test_returns_active_days(self, mock_neo4j: MagicMock) -> None:
        """Test getting days with activities."""
        mock_neo4j.execute_query.return_value = [
            {"date": "2024-01-15"},
            {"date": "2024-01-17"},
            {"date": "2024-01-19"},
        ]

        results = await get_active_days_in_range(mock_neo4j, "2024-01-15", "2024-01-21")

        assert len(results) == 3
        assert "2024-01-15" in results
        assert "2024-01-16" not in results  # Not active

    @pytest.mark.asyncio
    async def test_empty_range(self, mock_neo4j: MagicMock) -> None:
        """Test when no days have activities."""
        mock_neo4j.execute_query.return_value = []

        results = await get_active_days_in_range(mock_neo4j, "2024-01-15", "2024-01-21")

        assert len(results) == 0


# =============================================================================
# Test Date Handling
# =============================================================================


class TestDateNormalization:
    """Tests for date input normalization."""

    @pytest.mark.asyncio
    async def test_string_date(self, mock_neo4j: MagicMock) -> None:
        """Test handling string date input."""
        mock_neo4j.execute_query.return_value = []

        await get_day_activities(mock_neo4j, "2024-01-15")

        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["date"] == "2024-01-15"

    @pytest.mark.asyncio
    async def test_date_object(self, mock_neo4j: MagicMock) -> None:
        """Test handling date object input."""
        mock_neo4j.execute_query.return_value = []
        target = date(2024, 1, 15)

        await get_day_activities(mock_neo4j, target)

        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["date"] == "2024-01-15"

    @pytest.mark.asyncio
    async def test_datetime_object(self, mock_neo4j: MagicMock) -> None:
        """Test handling datetime object input."""
        mock_neo4j.execute_query.return_value = []
        target = datetime(2024, 1, 15, 14, 30, 0)

        await get_day_activities(mock_neo4j, target)

        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["date"] == "2024-01-15"
