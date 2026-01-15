"""
Unit tests for Calendar Tool Handlers.

Tests natural language time parsing, event formatting, and conflict detection.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from klabautermann.agents.calendar_handlers import (
    CalendarFormatter,
    ConflictChecker,
    TimeParser,
)
from klabautermann.mcp.google_workspace import CalendarEvent


# ===========================================================================
# Test TimeParser
# ===========================================================================


class TestTimeParser:
    """Test natural language time parsing."""

    @pytest.fixture
    def reference_time(self) -> datetime:
        """Reference time for testing: 2026-01-15 14:00:00 UTC (Thursday)."""
        return datetime(2026, 1, 15, 14, 0, 0, tzinfo=ZoneInfo("UTC"))

    def test_parse_tomorrow_at_time(self, reference_time):
        """Test parsing 'tomorrow at 2pm'."""
        result = TimeParser.parse("tomorrow at 2pm", reference_time)
        assert result is not None
        assert result.date() == datetime(2026, 1, 16).date()
        assert result.hour == 14
        assert result.minute == 0

    def test_parse_today(self, reference_time):
        """Test parsing 'today'."""
        result = TimeParser.parse("today", reference_time)
        assert result is not None
        assert result.date() == datetime(2026, 1, 15).date()
        assert result.hour == 9  # Default to 9am

    def test_parse_tomorrow_default_time(self, reference_time):
        """Test parsing 'tomorrow' without explicit time."""
        result = TimeParser.parse("tomorrow", reference_time)
        assert result is not None
        assert result.date() == datetime(2026, 1, 16).date()
        assert result.hour == 9  # Default to 9am

    def test_parse_next_monday(self, reference_time):
        """Test parsing 'next Monday' from Thursday."""
        result = TimeParser.parse("next Monday", reference_time)
        assert result is not None
        # From Thursday Jan 15: this coming Monday is Jan 19
        # "Next Monday" means the Monday after that = Jan 26
        assert result.date() == datetime(2026, 1, 26).date()
        assert result.hour == 9  # Default to 9am

    def test_parse_next_monday_with_time(self, reference_time):
        """Test parsing 'next Monday at 3pm'."""
        result = TimeParser.parse("next Monday at 3pm", reference_time)
        assert result is not None
        assert result.date() == datetime(2026, 1, 26).date()
        assert result.hour == 15

    def test_parse_in_30_minutes(self, reference_time):
        """Test parsing 'in 30 minutes'."""
        result = TimeParser.parse("in 30 minutes", reference_time)
        assert result is not None
        assert result == reference_time + timedelta(minutes=30)

    def test_parse_in_2_hours(self, reference_time):
        """Test parsing 'in 2 hours'."""
        result = TimeParser.parse("in 2 hours", reference_time)
        assert result is not None
        assert result == reference_time + timedelta(hours=2)

    def test_parse_in_3_days(self, reference_time):
        """Test parsing 'in 3 days'."""
        result = TimeParser.parse("in 3 days", reference_time)
        assert result is not None
        assert result == reference_time + timedelta(days=3)

    def test_parse_time_only_2pm(self, reference_time):
        """Test parsing '2pm' as time only."""
        result = TimeParser.parse("2pm", reference_time)
        assert result is not None
        assert result.date() == reference_time.date()
        assert result.hour == 14
        assert result.minute == 0

    def test_parse_time_only_14_30(self, reference_time):
        """Test parsing '14:30' as time only."""
        result = TimeParser.parse("14:30", reference_time)
        assert result is not None
        assert result.date() == reference_time.date()
        assert result.hour == 14
        assert result.minute == 30

    def test_parse_time_only_9_15am(self, reference_time):
        """Test parsing '9:15am'."""
        result = TimeParser.parse("9:15am", reference_time)
        assert result is not None
        assert result.date() == reference_time.date()
        assert result.hour == 9
        assert result.minute == 15

    def test_parse_day_after_tomorrow(self, reference_time):
        """Test parsing 'day after tomorrow'."""
        result = TimeParser.parse("day after tomorrow", reference_time)
        assert result is not None
        assert result.date() == datetime(2026, 1, 17).date()
        assert result.hour == 9

    def test_parse_next_week(self, reference_time):
        """Test parsing 'next week'."""
        result = TimeParser.parse("next week", reference_time)
        assert result is not None
        assert result.date() == datetime(2026, 1, 22).date()
        assert result.hour == 9

    def test_parse_invalid_returns_none(self, reference_time):
        """Test that unparseable strings return None."""
        result = TimeParser.parse("some random text", reference_time)
        assert result is None

    def test_parse_with_timezone(self):
        """Test parsing with different timezone."""
        reference = datetime(2026, 1, 15, 14, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        result = TimeParser.parse("tomorrow at 2pm", reference, timezone="America/New_York")
        assert result is not None
        assert result.tzinfo == ZoneInfo("America/New_York")
        assert result.date() == datetime(2026, 1, 16).date()
        assert result.hour == 14

    def test_parse_range_explicit(self, reference_time):
        """Test parsing explicit time range '3pm to 4pm'."""
        start, end = TimeParser.parse_range("3pm to 4pm", reference_time)
        assert start is not None
        assert end is not None
        assert start.hour == 15
        assert end.hour == 16
        assert end - start == timedelta(hours=1)

    def test_parse_range_with_dash(self, reference_time):
        """Test parsing time range with dash '2:30pm - 3:30pm'."""
        start, end = TimeParser.parse_range("2:30pm - 3:30pm", reference_time)
        assert start is not None
        assert end is not None
        assert start.hour == 14
        assert start.minute == 30
        assert end.hour == 15
        assert end.minute == 30

    def test_parse_range_default_duration(self, reference_time):
        """Test parsing single time with default duration."""
        start, end = TimeParser.parse_range("tomorrow at 2pm", reference_time)
        assert start is not None
        assert end is not None
        assert end - start == timedelta(hours=1)  # Default duration

    def test_parse_range_custom_duration(self, reference_time):
        """Test parsing single time with custom duration."""
        start, end = TimeParser.parse_range(
            "tomorrow at 2pm", reference_time, default_duration=timedelta(minutes=30)
        )
        assert start is not None
        assert end is not None
        assert end - start == timedelta(minutes=30)

    def test_parse_range_invalid_returns_none(self, reference_time):
        """Test that unparseable range returns (None, None)."""
        start, end = TimeParser.parse_range("invalid text", reference_time)
        assert start is None
        assert end is None

    def test_parse_12am(self, reference_time):
        """Test parsing midnight (12am)."""
        result = TimeParser.parse("12am", reference_time)
        assert result is not None
        assert result.hour == 0

    def test_parse_12pm(self, reference_time):
        """Test parsing noon (12pm)."""
        result = TimeParser.parse("12pm", reference_time)
        assert result is not None
        assert result.hour == 12

    def test_parse_day_name_without_next(self, reference_time):
        """Test parsing day name without 'next' keyword."""
        # From Thursday Jan 15, "Monday" (without "next") means this coming Monday = Jan 19
        result = TimeParser.parse("Monday", reference_time)
        assert result is not None
        assert result.date() == datetime(2026, 1, 19).date()

    def test_parse_day_abbreviation(self, reference_time):
        """Test parsing day abbreviation 'fri'."""
        result = TimeParser.parse("fri at 3pm", reference_time)
        assert result is not None
        # From Thursday Jan 15, next Friday is Jan 16
        assert result.date() == datetime(2026, 1, 16).date()
        assert result.hour == 15


# ===========================================================================
# Test CalendarFormatter
# ===========================================================================


class TestCalendarFormatter:
    """Test event formatting for display."""

    @pytest.fixture
    def sample_events(self) -> list[CalendarEvent]:
        """Sample calendar events for testing."""
        return [
            CalendarEvent(
                id="event-1",
                title="Team Meeting",
                start=datetime(2026, 1, 15, 9, 0, 0, tzinfo=ZoneInfo("UTC")),
                end=datetime(2026, 1, 15, 10, 0, 0, tzinfo=ZoneInfo("UTC")),
                location="Conference Room A",
            ),
            CalendarEvent(
                id="event-2",
                title="Lunch",
                start=datetime(2026, 1, 15, 12, 0, 0, tzinfo=ZoneInfo("UTC")),
                end=datetime(2026, 1, 15, 13, 0, 0, tzinfo=ZoneInfo("UTC")),
            ),
            CalendarEvent(
                id="event-3",
                title="Client Call",
                start=datetime(2026, 1, 15, 14, 0, 0, tzinfo=ZoneInfo("UTC")),
                end=datetime(2026, 1, 15, 15, 30, 0, tzinfo=ZoneInfo("UTC")),
                location="Zoom",
            ),
            CalendarEvent(
                id="event-4",
                title="Planning Session",
                start=datetime(2026, 1, 16, 10, 0, 0, tzinfo=ZoneInfo("UTC")),
                end=datetime(2026, 1, 16, 11, 30, 0, tzinfo=ZoneInfo("UTC")),
            ),
        ]

    def test_format_empty_list(self):
        """Test formatting empty event list."""
        result = CalendarFormatter.format_event_list([])
        assert result == "No events scheduled."

    def test_format_event_list(self, sample_events):
        """Test formatting list of events."""
        result = CalendarFormatter.format_event_list(sample_events)

        # Check for date headers (Jan 15 is Thursday, Jan 16 is Friday)
        assert "Thursday, January 15:" in result
        assert "Friday, January 16:" in result

        # Check for event details
        assert "09:00 - Team Meeting (1h)" in result
        assert "12:00 - Lunch (1h)" in result
        assert "14:00 - Client Call (1h 30min)" in result
        assert "10:00 - Planning Session (1h 30min)" in result

        # Check for locations
        assert "@ Conference Room A" in result
        assert "@ Zoom" in result

    def test_format_event_list_max_display(self, sample_events):
        """Test formatting with max_display limit."""
        result = CalendarFormatter.format_event_list(sample_events, max_display=2)

        # Should show first 2 events
        assert "Team Meeting" in result
        assert "Lunch" in result

        # Should not show others
        assert "Client Call" not in result
        assert "Planning Session" not in result

        # Should show count of remaining events
        assert "... and 2 more events" in result

    def test_format_schedule_summary_empty(self):
        """Test summary for empty schedule."""
        result = CalendarFormatter.format_schedule_summary([])
        assert result == "Your schedule is clear."

    def test_format_schedule_summary(self, sample_events):
        """Test schedule summary with multiple events."""
        result = CalendarFormatter.format_schedule_summary(sample_events)

        # Check event count
        assert "4 event(s)" in result

        # Check total hours (1 + 1 + 1.5 + 1.5 = 5.0)
        assert "5.0 hours" in result

    def test_format_duration_minutes(self):
        """Test formatting duration in minutes."""
        duration = timedelta(minutes=30)
        result = CalendarFormatter._format_duration(duration)
        assert result == "30min"

    def test_format_duration_hours(self):
        """Test formatting duration in whole hours."""
        duration = timedelta(hours=2)
        result = CalendarFormatter._format_duration(duration)
        assert result == "2h"

    def test_format_duration_hours_minutes(self):
        """Test formatting duration with hours and minutes."""
        duration = timedelta(hours=1, minutes=30)
        result = CalendarFormatter._format_duration(duration)
        assert result == "1h 30min"

    def test_format_duration_zero_minutes(self):
        """Test formatting duration with exact hours."""
        duration = timedelta(hours=3, minutes=0)
        result = CalendarFormatter._format_duration(duration)
        assert result == "3h"


# ===========================================================================
# Test ConflictChecker
# ===========================================================================


class TestConflictChecker:
    """Test conflict detection and free slot finding."""

    @pytest.fixture
    def existing_events(self) -> list[CalendarEvent]:
        """Sample existing events for conflict testing."""
        return [
            CalendarEvent(
                id="event-1",
                title="Morning Meeting",
                start=datetime(2026, 1, 15, 9, 0, 0, tzinfo=ZoneInfo("UTC")),
                end=datetime(2026, 1, 15, 10, 0, 0, tzinfo=ZoneInfo("UTC")),
            ),
            CalendarEvent(
                id="event-2",
                title="Lunch",
                start=datetime(2026, 1, 15, 12, 0, 0, tzinfo=ZoneInfo("UTC")),
                end=datetime(2026, 1, 15, 13, 0, 0, tzinfo=ZoneInfo("UTC")),
            ),
            CalendarEvent(
                id="event-3",
                title="Afternoon Call",
                start=datetime(2026, 1, 15, 14, 0, 0, tzinfo=ZoneInfo("UTC")),
                end=datetime(2026, 1, 15, 15, 0, 0, tzinfo=ZoneInfo("UTC")),
            ),
        ]

    def test_check_conflicts_no_conflict(self, existing_events):
        """Test checking for conflicts when none exist."""
        new_start = datetime(2026, 1, 15, 10, 30, 0, tzinfo=ZoneInfo("UTC"))
        new_end = datetime(2026, 1, 15, 11, 30, 0, tzinfo=ZoneInfo("UTC"))

        conflicts = ConflictChecker.check_conflicts(new_start, new_end, existing_events)
        assert len(conflicts) == 0

    def test_check_conflicts_exact_overlap(self, existing_events):
        """Test detecting conflict with exact time overlap."""
        new_start = datetime(2026, 1, 15, 9, 0, 0, tzinfo=ZoneInfo("UTC"))
        new_end = datetime(2026, 1, 15, 10, 0, 0, tzinfo=ZoneInfo("UTC"))

        conflicts = ConflictChecker.check_conflicts(new_start, new_end, existing_events)
        assert len(conflicts) == 1
        assert conflicts[0].title == "Morning Meeting"

    def test_check_conflicts_partial_overlap_start(self, existing_events):
        """Test detecting conflict when new event overlaps at start."""
        new_start = datetime(2026, 1, 15, 8, 30, 0, tzinfo=ZoneInfo("UTC"))
        new_end = datetime(2026, 1, 15, 9, 30, 0, tzinfo=ZoneInfo("UTC"))

        conflicts = ConflictChecker.check_conflicts(new_start, new_end, existing_events)
        assert len(conflicts) == 1
        assert conflicts[0].title == "Morning Meeting"

    def test_check_conflicts_partial_overlap_end(self, existing_events):
        """Test detecting conflict when new event overlaps at end."""
        new_start = datetime(2026, 1, 15, 9, 30, 0, tzinfo=ZoneInfo("UTC"))
        new_end = datetime(2026, 1, 15, 10, 30, 0, tzinfo=ZoneInfo("UTC"))

        conflicts = ConflictChecker.check_conflicts(new_start, new_end, existing_events)
        assert len(conflicts) == 1
        assert conflicts[0].title == "Morning Meeting"

    def test_check_conflicts_contains_existing(self, existing_events):
        """Test detecting conflict when new event contains existing event."""
        new_start = datetime(2026, 1, 15, 8, 0, 0, tzinfo=ZoneInfo("UTC"))
        new_end = datetime(2026, 1, 15, 11, 0, 0, tzinfo=ZoneInfo("UTC"))

        conflicts = ConflictChecker.check_conflicts(new_start, new_end, existing_events)
        assert len(conflicts) == 1
        assert conflicts[0].title == "Morning Meeting"

    def test_check_conflicts_multiple(self, existing_events):
        """Test detecting multiple conflicts."""
        new_start = datetime(2026, 1, 15, 11, 30, 0, tzinfo=ZoneInfo("UTC"))
        new_end = datetime(2026, 1, 15, 14, 30, 0, tzinfo=ZoneInfo("UTC"))

        conflicts = ConflictChecker.check_conflicts(new_start, new_end, existing_events)
        assert len(conflicts) == 2
        titles = {c.title for c in conflicts}
        assert "Lunch" in titles
        assert "Afternoon Call" in titles

    def test_check_conflicts_adjacent_no_conflict(self, existing_events):
        """Test that adjacent events (end == start) don't conflict."""
        new_start = datetime(2026, 1, 15, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
        new_end = datetime(2026, 1, 15, 11, 0, 0, tzinfo=ZoneInfo("UTC"))

        conflicts = ConflictChecker.check_conflicts(new_start, new_end, existing_events)
        assert len(conflicts) == 0

    def test_find_free_slots_basic(self, existing_events):
        """Test finding free slots in a day with events."""
        date = datetime(2026, 1, 15, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        duration = timedelta(hours=1)

        slots = ConflictChecker.find_free_slots(date, duration, existing_events)

        # Should find slots: 10-12, 13-14, 15-17
        assert len(slots) == 3

        # Check first slot (after morning meeting)
        assert slots[0][0].hour == 10
        assert slots[0][1].hour == 12

        # Check second slot (after lunch)
        assert slots[1][0].hour == 13
        assert slots[1][1].hour == 14

        # Check third slot (after afternoon call)
        assert slots[2][0].hour == 15
        assert slots[2][1].hour == 17

    def test_find_free_slots_no_events(self):
        """Test finding free slots when no events exist."""
        date = datetime(2026, 1, 15, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        duration = timedelta(hours=1)

        slots = ConflictChecker.find_free_slots(date, duration, [])

        # Should return entire work day (9-17)
        assert len(slots) == 1
        assert slots[0][0].hour == 9
        assert slots[0][1].hour == 17

    def test_find_free_slots_custom_work_hours(self, existing_events):
        """Test finding free slots with custom work hours."""
        date = datetime(2026, 1, 15, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        duration = timedelta(hours=1)

        slots = ConflictChecker.find_free_slots(
            date, duration, existing_events, work_start=8, work_end=18
        )

        # Should include earlier and later slots
        assert slots[0][0].hour == 8  # Starts at 8am
        assert slots[-1][1].hour == 18  # Ends at 6pm

    def test_find_free_slots_longer_duration(self, existing_events):
        """Test finding free slots with longer duration requirement."""
        date = datetime(2026, 1, 15, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        duration = timedelta(hours=2)

        slots = ConflictChecker.find_free_slots(date, duration, existing_events)

        # Only slots that are >= 2 hours
        assert len(slots) == 2  # 10-12 (2h), 15-17 (2h)
        assert all(slot[1] - slot[0] >= duration for slot in slots)

    def test_find_free_slots_insufficient_gaps(self, existing_events):
        """Test when no gaps are large enough for duration."""
        date = datetime(2026, 1, 15, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        duration = timedelta(hours=3)

        slots = ConflictChecker.find_free_slots(date, duration, existing_events)

        # No 3-hour gaps exist
        assert len(slots) == 0

    def test_find_free_slots_different_day(self, existing_events):
        """Test finding free slots on a different day."""
        date = datetime(2026, 1, 16, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        duration = timedelta(hours=1)

        slots = ConflictChecker.find_free_slots(date, duration, existing_events)

        # No events on Jan 16, so entire work day is free
        assert len(slots) == 1
        assert slots[0][0].date() == datetime(2026, 1, 16).date()


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestCalendarHandlersIntegration:
    """Integration tests combining multiple handlers."""

    def test_parse_and_check_conflicts(self):
        """Test parsing a time and checking for conflicts."""
        reference = datetime(2026, 1, 15, 14, 0, 0, tzinfo=ZoneInfo("UTC"))

        # Parse "tomorrow at 2pm"
        start, end = TimeParser.parse_range("tomorrow at 2pm", reference)
        assert start is not None
        assert end is not None

        # Create existing event that conflicts
        existing = [
            CalendarEvent(
                id="conflict",
                title="Existing Meeting",
                start=datetime(2026, 1, 16, 14, 30, 0, tzinfo=ZoneInfo("UTC")),
                end=datetime(2026, 1, 16, 15, 30, 0, tzinfo=ZoneInfo("UTC")),
            )
        ]

        # Check for conflicts
        conflicts = ConflictChecker.check_conflicts(start, end, existing)
        assert len(conflicts) == 1

    def test_find_free_slot_and_format(self):
        """Test finding free slots and formatting them."""
        date = datetime(2026, 1, 15, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        existing = [
            CalendarEvent(
                id="event",
                title="Busy Time",
                start=datetime(2026, 1, 15, 10, 0, 0, tzinfo=ZoneInfo("UTC")),
                end=datetime(2026, 1, 15, 11, 0, 0, tzinfo=ZoneInfo("UTC")),
            )
        ]

        # Find free slots
        slots = ConflictChecker.find_free_slots(date, timedelta(hours=1), existing)
        assert len(slots) > 0

        # Create event for first free slot
        free_start, free_end = slots[0]
        new_event = CalendarEvent(
            id="new",
            title="New Meeting",
            start=free_start,
            end=free_end,
        )

        # Format the event
        formatted = CalendarFormatter.format_event_list([new_event])
        assert "New Meeting" in formatted
