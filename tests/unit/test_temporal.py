"""Unit tests for memory/temporal.py - time expression parsing and temporal queries.

Issue: #21 - [AGT-P-014] Implement time-filtered temporal queries
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from klabautermann.memory.temporal import (
    TimeExpressionType,
    TimeRange,
    execute_temporal_query,
    get_historical_relationships,
    parse_time_expression,
)


# =============================================================================
# TimeRange Tests
# =============================================================================


class TestTimeRange:
    """Tests for TimeRange dataclass."""

    def test_start_ms_conversion(self):
        """Test conversion to milliseconds."""
        dt = datetime(2026, 1, 22, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
        time_range = TimeRange(start=dt)

        assert time_range.start_ms is not None
        assert time_range.start_ms == int(dt.timestamp() * 1000)

    def test_none_values(self):
        """Test that None values return None for ms conversions."""
        time_range = TimeRange()

        assert time_range.start_ms is None
        assert time_range.end_ms is None
        assert time_range.as_of_ms is None

    def test_to_dict(self):
        """Test conversion to dictionary."""
        dt = datetime(2026, 1, 22, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
        time_range = TimeRange(
            start=dt,
            expression_type=TimeExpressionType.ABSOLUTE,
            original_expression="in 2026",
        )

        result = time_range.to_dict()

        assert result["start"] == dt.isoformat()
        assert result["end"] is None
        assert result["expression_type"] == "absolute"
        assert result["original_expression"] == "in 2026"
        assert result["start_ms"] is not None


class TestTimeExpressionType:
    """Tests for TimeExpressionType enum."""

    def test_enum_values(self):
        """Test enum values."""
        assert TimeExpressionType.RELATIVE_PAST == "relative_past"
        assert TimeExpressionType.RELATIVE_FUTURE == "relative_future"
        assert TimeExpressionType.ABSOLUTE == "absolute"
        assert TimeExpressionType.RANGE == "range"
        assert TimeExpressionType.AS_OF == "as_of"
        assert TimeExpressionType.NONE == "none"


# =============================================================================
# parse_time_expression Tests
# =============================================================================


class TestParseTimeExpression:
    """Tests for parse_time_expression function."""

    @pytest.fixture
    def fixed_reference(self):
        """Fixed reference time for consistent tests."""
        return datetime(2026, 1, 22, 12, 0, 0, tzinfo=ZoneInfo("UTC"))

    def test_parse_yesterday(self, fixed_reference):
        """Test parsing 'yesterday'."""
        result = parse_time_expression("meetings yesterday", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.RELATIVE_PAST
        assert result.original_expression == "yesterday"
        assert result.start is not None
        # Start should be Jan 21
        assert result.start.day == 21

    def test_parse_today(self, fixed_reference):
        """Test parsing 'today'."""
        result = parse_time_expression("what's happening today", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.RELATIVE_PAST
        assert result.original_expression == "today"
        assert result.start is not None
        assert result.start.day == 22

    def test_parse_last_week(self, fixed_reference):
        """Test parsing 'last week'."""
        result = parse_time_expression("events last week", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.RELATIVE_PAST
        assert result.original_expression == "last week"
        assert result.start is not None
        # end may be None if the implementation uses start-only ranges

    def test_parse_next_week(self, fixed_reference):
        """Test parsing 'next week'."""
        result = parse_time_expression("meetings next week", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.RELATIVE_FUTURE
        assert result.original_expression == "next week"

    def test_parse_last_month(self, fixed_reference):
        """Test parsing 'last month'."""
        result = parse_time_expression("tasks from last month", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.RELATIVE_PAST
        assert result.original_expression == "last month"

    def test_parse_last_year(self, fixed_reference):
        """Test parsing 'last year'."""
        result = parse_time_expression(
            "who did Sarah work for last year", reference_time=fixed_reference
        )

        assert result.expression_type == TimeExpressionType.RELATIVE_PAST
        assert result.original_expression == "last year"

    def test_parse_n_days_ago(self, fixed_reference):
        """Test parsing 'N days ago'."""
        result = parse_time_expression("3 days ago", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.RELATIVE_PAST
        assert result.original_expression == "3 days ago"
        assert result.start is not None
        # Should be 3 days before Jan 22 = Jan 19
        assert result.start.day == 19

    def test_parse_n_weeks_ago(self, fixed_reference):
        """Test parsing 'N weeks ago'."""
        result = parse_time_expression("2 weeks ago", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.RELATIVE_PAST
        assert result.original_expression == "2 weeks ago"

    def test_parse_in_n_days(self, fixed_reference):
        """Test parsing 'in N days'."""
        result = parse_time_expression("in 5 days", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.RELATIVE_FUTURE
        assert result.original_expression == "in 5 days"

    def test_parse_year_absolute(self, fixed_reference):
        """Test parsing year like 'in 2025' or just '2024'."""
        result = parse_time_expression(
            "who did Sarah work for in 2024", reference_time=fixed_reference
        )

        assert result.expression_type == TimeExpressionType.ABSOLUTE
        assert result.start is not None
        assert result.start.year == 2024
        assert result.end is not None
        assert result.end.year == 2024
        assert result.end.month == 12

    def test_parse_year_standalone(self, fixed_reference):
        """Test parsing standalone year."""
        result = parse_time_expression("events in 2025", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.ABSOLUTE
        assert result.start.year == 2025

    def test_parse_as_of_last_year(self, fixed_reference):
        """Test parsing 'as of last year'."""
        result = parse_time_expression("as of last year", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.AS_OF
        assert result.as_of is not None
        # Should be end of 2025
        assert result.as_of.year == 2025
        assert result.as_of.month == 12

    def test_parse_recently(self, fixed_reference):
        """Test parsing 'recently'."""
        result = parse_time_expression("recently added contacts", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.RELATIVE_PAST
        assert result.original_expression == "recently"

    def test_parse_no_temporal_expression(self, fixed_reference):
        """Test that queries without time expressions return NONE type."""
        result = parse_time_expression("what is Sarah's email", reference_time=fixed_reference)

        assert result.expression_type == TimeExpressionType.NONE
        assert result.start is None
        assert result.end is None

    def test_case_insensitive(self, fixed_reference):
        """Test that parsing is case-insensitive."""
        result1 = parse_time_expression("LAST WEEK", reference_time=fixed_reference)
        result2 = parse_time_expression("Last Week", reference_time=fixed_reference)

        assert result1.expression_type == result2.expression_type


# =============================================================================
# execute_temporal_query Tests
# =============================================================================


class TestExecuteTemporalQuery:
    """Tests for execute_temporal_query function."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_query_with_range(self, mock_client):
        """Test executing query with time range."""
        mock_client.execute_query.return_value = [
            {
                "type": "Event",
                "uuid": "event-1",
                "name": "Team Meeting",
                "created_at": 1705900000000,
                "expired_at": None,
            }
        ]

        time_range = TimeRange(
            start=datetime(2026, 1, 15, tzinfo=ZoneInfo("UTC")),
            end=datetime(2026, 1, 22, tzinfo=ZoneInfo("UTC")),
            expression_type=TimeExpressionType.RELATIVE_PAST,
        )

        result = await execute_temporal_query(
            client=mock_client,
            query="meeting",
            time_range=time_range,
        )

        assert result.records_found == 1
        assert result.records[0]["name"] == "Team Meeting"
        # Verify the query used time range
        call_args = mock_client.execute_query.call_args
        params = call_args[0][1]
        assert "start_ms" in params
        assert "end_ms" in params

    @pytest.mark.asyncio
    async def test_query_with_as_of(self, mock_client):
        """Test executing query with as_of point in time."""
        mock_client.execute_query.return_value = []

        time_range = TimeRange(
            as_of=datetime(2025, 12, 31, tzinfo=ZoneInfo("UTC")),
            expression_type=TimeExpressionType.AS_OF,
        )

        await execute_temporal_query(
            client=mock_client,
            query="sarah",
            time_range=time_range,
        )

        # Verify the query used as_of filter
        call_args = mock_client.execute_query.call_args
        query = call_args[0][0]
        assert "as_of_ms" in query or "$as_of_ms" in str(call_args)

    @pytest.mark.asyncio
    async def test_query_with_no_temporal(self, mock_client):
        """Test executing query without temporal filter."""
        mock_client.execute_query.return_value = []

        time_range = TimeRange(expression_type=TimeExpressionType.NONE)

        await execute_temporal_query(
            client=mock_client,
            query="john",
            time_range=time_range,
        )

        # Verify no temporal filter in query
        call_args = mock_client.execute_query.call_args
        params = call_args[0][1]
        assert "start_ms" not in params
        assert "as_of_ms" not in params

    @pytest.mark.asyncio
    async def test_result_to_dict(self, mock_client):
        """Test that result can be converted to dict."""
        mock_client.execute_query.return_value = []

        time_range = TimeRange(expression_type=TimeExpressionType.NONE)

        result = await execute_temporal_query(
            client=mock_client,
            query="test",
            time_range=time_range,
        )

        result_dict = result.to_dict()

        assert "records" in result_dict
        assert "time_range" in result_dict
        assert "query_time_ms" in result_dict
        assert "records_found" in result_dict


# =============================================================================
# get_historical_relationships Tests
# =============================================================================


class TestGetHistoricalRelationships:
    """Tests for get_historical_relationships function."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_get_works_at_historical(self, mock_client):
        """Test getting historical WORKS_AT relationships."""
        mock_client.execute_query.return_value = [
            {
                "person": "Sarah",
                "relationship": "WORKS_AT",
                "target_type": "Organization",
                "target_name": "Acme Corp",
                "since": 1609459200000,  # 2021-01-01
                "until": 1640995200000,  # 2022-01-01
                "properties": {"title": "Engineer"},
            }
        ]

        as_of = datetime(2021, 6, 15, tzinfo=ZoneInfo("UTC"))

        result = await get_historical_relationships(
            client=mock_client,
            person_name="Sarah",
            relationship_type="WORKS_AT",
            as_of=as_of,
        )

        assert len(result) == 1
        assert result[0]["target_name"] == "Acme Corp"

        # Verify query used correct as_of timestamp
        call_args = mock_client.execute_query.call_args
        params = call_args[0][1]
        assert params["rel_type"] == "WORKS_AT"
        assert "as_of_ms" in params

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_matches(self, mock_client):
        """Test that empty list is returned when no relationships match."""
        mock_client.execute_query.return_value = []

        as_of = datetime(2020, 1, 1, tzinfo=ZoneInfo("UTC"))

        result = await get_historical_relationships(
            client=mock_client,
            person_name="Unknown Person",
            relationship_type="WORKS_AT",
            as_of=as_of,
        )

        assert result == []


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that module exports are accessible."""

    def test_exports_from_memory_module(self):
        """Test that temporal exports are available from memory module."""
        from klabautermann.memory import (
            TemporalQueryResult,
            TimeExpressionType,
            TimeRange,
            execute_temporal_query,
            get_historical_relationships,
            parse_time_expression,
        )

        # Verify imports succeeded
        assert TimeRange is not None
        assert TimeExpressionType is not None
        assert TemporalQueryResult is not None
        assert parse_time_expression is not None
        assert execute_temporal_query is not None
        assert get_historical_relationships is not None
