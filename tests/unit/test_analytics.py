"""
Unit tests for Analytics queries.

Reference: specs/architecture/AGENTS.md Section 1.6
Task: T044 - Scribe Analytics Queries

Tests verify that analytics queries:
1. Count messages correctly for a given day
2. Count new entities by type
3. Track task completion and creation
4. Find top projects discussed
5. Aggregate all statistics into DailyAnalytics model

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from klabautermann.core.models import DailyAnalytics
from klabautermann.memory.analytics import (
    get_daily_analytics,
    get_daily_entity_counts,
    get_daily_interaction_count,
    get_daily_projects_discussed,
    get_daily_task_stats,
    get_day_bounds,
)


class TestDayBounds:
    """Test suite for day boundary calculation."""

    def test_returns_midnight_to_midnight(self) -> None:
        """Should return timestamps for start and end of day."""
        date = "2026-01-15"
        start, end = get_day_bounds(date)

        # Convert back to datetime for verification
        start_dt = datetime.fromtimestamp(start)
        end_dt = datetime.fromtimestamp(end)

        # Start should be midnight
        assert start_dt.hour == 0
        assert start_dt.minute == 0
        assert start_dt.second == 0

        # End should be midnight of next day
        assert end_dt.hour == 0
        assert end_dt.minute == 0
        assert end_dt.second == 0
        assert end_dt.date() == (start_dt + timedelta(days=1)).date()

    def test_handles_different_dates(self) -> None:
        """Should correctly calculate bounds for various dates."""
        dates = ["2026-01-01", "2026-06-15", "2026-12-31"]

        for date in dates:
            start, end = get_day_bounds(date)
            assert end > start
            assert end - start == 86400  # Exactly 24 hours in seconds


class TestDailyInteractionCount:
    """Test suite for daily interaction counting."""

    @pytest.mark.asyncio
    async def test_counts_messages_in_range(self) -> None:
        """Should count all messages within the day's timestamp range."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = [{"interaction_count": 42}]

        count = await get_daily_interaction_count(
            mock_neo4j,
            "2026-01-15",
            trace_id="test-trace",
        )

        assert count == 42
        mock_neo4j.execute_query.assert_called_once()

        # Verify query uses parameterized timestamps
        call_args = mock_neo4j.execute_query.call_args
        params = call_args[0][1]
        assert "day_start" in params
        assert "day_end" in params

    @pytest.mark.asyncio
    async def test_returns_zero_for_no_messages(self) -> None:
        """Should return 0 when no messages found."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = [{"interaction_count": 0}]

        count = await get_daily_interaction_count(mock_neo4j, "2026-01-15")

        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_result(self) -> None:
        """Should return 0 when query returns empty result."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = []

        count = await get_daily_interaction_count(mock_neo4j, "2026-01-15")

        assert count == 0


class TestDailyEntityCounts:
    """Test suite for entity creation counting."""

    @pytest.mark.asyncio
    async def test_counts_entities_by_type(self) -> None:
        """Should return counts grouped by entity type."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = [
            {"type": "Person", "count": 3},
            {"type": "Organization", "count": 1},
            {"type": "Project", "count": 2},
        ]

        counts = await get_daily_entity_counts(
            mock_neo4j,
            "2026-01-15",
            trace_id="test-trace",
        )

        assert counts["Person"] == 3
        assert counts["Organization"] == 1
        assert counts["Project"] == 2

    @pytest.mark.asyncio
    async def test_excludes_system_nodes(self) -> None:
        """Should exclude Message, Thread, and Day nodes from count."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = []

        await get_daily_entity_counts(mock_neo4j, "2026-01-15")

        # Verify query excludes system nodes
        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]
        assert "NOT n:Message" in query
        assert "NOT n:Thread" in query
        assert "NOT n:Day" in query

    @pytest.mark.asyncio
    async def test_returns_empty_dict_for_no_entities(self) -> None:
        """Should return empty dict when no entities created."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = []

        counts = await get_daily_entity_counts(mock_neo4j, "2026-01-15")

        assert counts == {}


class TestDailyTaskStats:
    """Test suite for task statistics."""

    @pytest.mark.asyncio
    async def test_counts_completed_and_created_tasks(self) -> None:
        """Should return both completed and created task counts."""
        mock_neo4j = AsyncMock()
        # First query: completed tasks
        # Second query: created tasks
        mock_neo4j.execute_query.side_effect = [
            [{"count": 5}],  # completed
            [{"count": 8}],  # created
        ]

        stats = await get_daily_task_stats(
            mock_neo4j,
            "2026-01-15",
            trace_id="test-trace",
        )

        assert stats["completed"] == 5
        assert stats["created"] == 8
        assert mock_neo4j.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_uses_correct_timestamp_fields(self) -> None:
        """Should use completed_at for completed, created_at for created."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.side_effect = [
            [{"count": 0}],
            [{"count": 0}],
        ]

        await get_daily_task_stats(mock_neo4j, "2026-01-15")

        # Check both queries
        calls = mock_neo4j.execute_query.call_args_list
        completed_query = calls[0][0][0]
        created_query = calls[1][0][0]

        assert "completed_at" in completed_query
        assert "created_at" in created_query

    @pytest.mark.asyncio
    async def test_returns_zero_for_no_tasks(self) -> None:
        """Should return zeros when no tasks found."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.side_effect = [
            [{"count": 0}],
            [{"count": 0}],
        ]

        stats = await get_daily_task_stats(mock_neo4j, "2026-01-15")

        assert stats["completed"] == 0
        assert stats["created"] == 0


class TestDailyProjectsDiscussed:
    """Test suite for project discussion tracking."""

    @pytest.mark.asyncio
    async def test_returns_top_projects_by_mentions(self) -> None:
        """Should return projects ordered by mention count."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = [
            {"name": "Q1 Budget", "uuid": "uuid-1", "mentions": 5},
            {"name": "Website Redesign", "uuid": "uuid-2", "mentions": 3},
            {"name": "API Migration", "uuid": "uuid-3", "mentions": 1},
        ]

        projects = await get_daily_projects_discussed(
            mock_neo4j,
            "2026-01-15",
            limit=3,
            trace_id="test-trace",
        )

        assert len(projects) == 3
        assert projects[0]["name"] == "Q1 Budget"
        assert projects[0]["mentions"] == 5
        assert projects[1]["mentions"] == 3
        assert projects[2]["mentions"] == 1

    @pytest.mark.asyncio
    async def test_respects_limit_parameter(self) -> None:
        """Should respect the limit parameter."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = []

        await get_daily_projects_discussed(mock_neo4j, "2026-01-15", limit=5)

        call_args = mock_neo4j.execute_query.call_args
        params = call_args[0][1]
        assert params["limit"] == 5

    @pytest.mark.asyncio
    async def test_uses_day_node_relationship(self) -> None:
        """Should query through Day node [:OCCURRED_ON] relationship."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = []

        await get_daily_projects_discussed(mock_neo4j, "2026-01-15")

        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]
        assert "Day" in query
        assert "OCCURRED_ON" in query
        assert "DISCUSSED" in query

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_projects(self) -> None:
        """Should return empty list when no projects discussed."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = []

        projects = await get_daily_projects_discussed(mock_neo4j, "2026-01-15")

        assert projects == []


class TestDailySagaProgress:
    """Test suite for saga progress in daily analytics (#110)."""

    @pytest.mark.asyncio
    async def test_returns_saga_episodes_from_day(self) -> None:
        """Should return saga episodes told on the given day."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = [
            {
                "saga_id": "great-maelstrom",
                "saga_name": "The Great Maelstrom",
                "chapter": 2,
                "channel": "cli",
            },
            {
                "saga_id": "great-maelstrom",
                "saga_name": "The Great Maelstrom",
                "chapter": 3,
                "channel": "telegram",
            },
        ]

        from klabautermann.memory.analytics import get_daily_saga_progress

        progress = await get_daily_saga_progress(mock_neo4j, "2026-01-15")

        assert len(progress) == 2
        assert progress[0].saga_id == "great-maelstrom"
        assert progress[0].chapter == 2
        assert progress[0].channel == "cli"
        assert progress[1].chapter == 3
        assert progress[1].channel == "telegram"

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_tales(self) -> None:
        """Should return empty list when no tales were told."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = []

        from klabautermann.memory.analytics import get_daily_saga_progress

        progress = await get_daily_saga_progress(mock_neo4j, "2026-01-15")

        assert progress == []

    @pytest.mark.asyncio
    async def test_uses_millisecond_timestamps(self) -> None:
        """Should convert day bounds to milliseconds for told_at comparison."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = []

        from klabautermann.memory.analytics import get_daily_saga_progress

        await get_daily_saga_progress(mock_neo4j, "2026-01-15")

        call_args = mock_neo4j.execute_query.call_args
        params = call_args[0][1]
        # Timestamps should be in milliseconds (13+ digits)
        assert params["day_start_ms"] > 1000000000000
        assert params["day_end_ms"] > params["day_start_ms"]


class TestDailyAnalytics:
    """Test suite for aggregated daily analytics."""

    @pytest.mark.asyncio
    async def test_aggregates_all_statistics(self) -> None:
        """Should combine all analytics into DailyAnalytics model."""
        mock_neo4j = AsyncMock()

        # Mock all the individual query responses
        mock_neo4j.execute_query.side_effect = [
            [{"interaction_count": 25}],  # interactions
            [  # entities
                {"type": "Person", "count": 2},
                {"type": "Organization", "count": 1},
                {"type": "Note", "count": 5},
                {"type": "Event", "count": 3},
            ],
            [{"count": 4}],  # tasks completed
            [{"count": 7}],  # tasks created
            [  # projects
                {"name": "Project A", "uuid": "uuid-a", "mentions": 10},
                {"name": "Project B", "uuid": "uuid-b", "mentions": 5},
            ],
            [  # saga progress (#110)
                {
                    "saga_id": "great-maelstrom",
                    "saga_name": "The Great Maelstrom",
                    "chapter": 2,
                    "channel": "cli",
                },
            ],
        ]

        analytics = await get_daily_analytics(
            mock_neo4j,
            "2026-01-15",
            trace_id="test-trace",
        )

        assert isinstance(analytics, DailyAnalytics)
        assert analytics.date == "2026-01-15"
        assert analytics.interaction_count == 25
        assert analytics.new_entities["Person"] == 2
        assert analytics.new_entities["Organization"] == 1
        assert analytics.tasks_completed == 4
        assert analytics.tasks_created == 7
        assert analytics.notes_created == 5
        assert analytics.events_count == 3
        assert len(analytics.top_projects) == 2
        assert len(analytics.saga_progress) == 1
        assert analytics.saga_progress[0].saga_id == "great-maelstrom"
        assert analytics.saga_progress[0].chapter == 2

    @pytest.mark.asyncio
    async def test_handles_missing_entity_types(self) -> None:
        """Should handle case where Note or Event count is zero."""
        mock_neo4j = AsyncMock()

        mock_neo4j.execute_query.side_effect = [
            [{"interaction_count": 10}],
            [{"type": "Person", "count": 1}],  # No Note or Event
            [{"count": 0}],  # completed
            [{"count": 0}],  # created
            [],  # projects
            [],  # saga progress - no tales told
        ]

        analytics = await get_daily_analytics(mock_neo4j, "2026-01-15")

        assert analytics.notes_created == 0
        assert analytics.events_count == 0
        assert analytics.saga_progress == []

    @pytest.mark.asyncio
    async def test_propagates_trace_id(self) -> None:
        """Should pass trace_id to all sub-queries."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.side_effect = [
            [{"interaction_count": 0}],
            [],
            [{"count": 0}],
            [{"count": 0}],
            [],
            [],  # saga progress
        ]

        await get_daily_analytics(
            mock_neo4j,
            "2026-01-15",
            trace_id="test-trace-123",
        )

        # All calls should have the trace_id
        for call in mock_neo4j.execute_query.call_args_list:
            kwargs = call[1]
            assert kwargs.get("trace_id") == "test-trace-123"


class TestParameterizedQueries:
    """Test suite verifying queries use parameters, not f-strings."""

    @pytest.mark.asyncio
    async def test_interaction_count_uses_parameters(self) -> None:
        """Should use $day_start and $day_end parameters."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = [{"interaction_count": 0}]

        await get_daily_interaction_count(mock_neo4j, "2026-01-15")

        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        # Query should use placeholders
        assert "$day_start" in query
        assert "$day_end" in query

        # Parameters should be provided
        assert "day_start" in params
        assert "day_end" in params

    @pytest.mark.asyncio
    async def test_entity_counts_uses_parameters(self) -> None:
        """Should use parameters for timestamp range."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = []

        await get_daily_entity_counts(mock_neo4j, "2026-01-15")

        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]

        assert "$day_start" in query
        assert "$day_end" in query

    @pytest.mark.asyncio
    async def test_projects_discussed_uses_parameters(self) -> None:
        """Should use $date and $limit parameters."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_query.return_value = []

        await get_daily_projects_discussed(mock_neo4j, "2026-01-15", limit=5)

        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        assert "$date" in query
        assert "$limit" in query
        assert params["date"] == "2026-01-15"
        assert params["limit"] == 5
