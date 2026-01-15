"""
Calendar Tool Handlers - Natural language time parsing and conflict detection.

Provides sophisticated calendar handling utilities for the Executor agent:
1. TimeParser: Parse natural language time expressions to datetime
2. CalendarFormatter: Format events for display
3. ConflictChecker: Detect scheduling conflicts and find free slots

Reference: specs/architecture/AGENTS.md Section 1.4
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from klabautermann.mcp.google_workspace import CalendarEvent


# ===========================================================================
# TimeParser - Natural Language Time Parsing
# ===========================================================================


class TimeParser:
    """
    Parse natural language time expressions to datetime.

    Examples:
        >>> TimeParser.parse("tomorrow at 2pm")
        datetime.datetime(2026, 1, 16, 14, 0)

        >>> TimeParser.parse("next Monday")
        datetime.datetime(2026, 1, 20, 9, 0)

        >>> TimeParser.parse("in 30 minutes")
        datetime.datetime(2026, 1, 15, 14, 30)

        >>> TimeParser.parse_range("3pm to 4pm")
        (datetime.datetime(2026, 1, 15, 15, 0), datetime.datetime(2026, 1, 15, 16, 0))
    """

    # Day name mapping (English)
    DAYS = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
    }

    # Relative day patterns (ordered by length, longest first to avoid substring matching)
    RELATIVE_DAYS = {
        "day after tomorrow": 2,
        "next week": 7,
        "tomorrow": 1,
        "today": 0,
    }

    @classmethod
    def parse(
        cls,
        text: str,
        reference: datetime | None = None,
        timezone: str = "UTC",
    ) -> datetime | None:
        """
        Parse natural language time to datetime.

        Args:
            text: Natural language time expression (e.g., "tomorrow at 2pm").
            reference: Reference datetime for relative expressions (default: now).
            timezone: Timezone string (default: "UTC").

        Returns:
            Parsed datetime or None if unparseable.
        """
        tz = ZoneInfo(timezone)
        now = reference or datetime.now(tz)
        text = text.lower().strip()

        # Try various patterns in order of specificity
        result = (
            cls._parse_relative_day(text, now)
            or cls._parse_day_name(text, now)
            or cls._parse_time_only(text, now)
            or cls._parse_relative_duration(text, now)
        )

        if result:
            # Ensure timezone is set
            if result.tzinfo is None:
                return result.replace(tzinfo=tz)
            return result

        return None

    @classmethod
    def parse_range(
        cls,
        text: str,
        reference: datetime | None = None,
        default_duration: timedelta = timedelta(hours=1),
        timezone: str = "UTC",
    ) -> tuple[datetime | None, datetime | None]:
        """
        Parse time range (start and end).

        Args:
            text: Natural language time range (e.g., "3pm to 4pm", "tomorrow at 2pm").
            reference: Reference datetime for relative expressions.
            default_duration: Duration to use if no end time specified (default: 1 hour).
            timezone: Timezone string (default: "UTC").

        Returns:
            Tuple of (start, end) datetimes. Both are None if unparseable.
        """
        # Look for explicit range patterns
        range_match = re.search(
            r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:to|-)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
            text,
            re.IGNORECASE,
        )

        if range_match:
            start_str, end_str = range_match.groups()
            now = reference or datetime.now(ZoneInfo(timezone))
            start = cls._parse_time_str(start_str, now)
            end = cls._parse_time_str(end_str, now)
            return start, end

        # Otherwise, parse single time and add default duration
        start = cls.parse(text, reference, timezone)
        if start:
            return start, start + default_duration

        return None, None

    @classmethod
    def _parse_relative_day(cls, text: str, now: datetime) -> datetime | None:
        """Parse relative day expressions (today, tomorrow, etc.)."""
        for pattern, days in cls.RELATIVE_DAYS.items():
            if pattern in text:
                target_date = now + timedelta(days=days)
                # Extract time if present
                time_match = re.search(
                    r"at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", text, re.IGNORECASE
                )
                if time_match:
                    return cls._parse_time_str(time_match.group(1), target_date)
                # Default to 9am for future days
                return target_date.replace(hour=9, minute=0, second=0, microsecond=0)
        return None

    @classmethod
    def _parse_day_name(cls, text: str, now: datetime) -> datetime | None:
        """Parse day name expressions (next Monday, etc.)."""
        for day_name, day_num in cls.DAYS.items():
            if day_name in text:
                days_ahead = day_num - now.weekday()

                # Handle "next" keyword explicitly
                if "next" in text:
                    # "next Monday" means the Monday of next week, not this week
                    if days_ahead <= 0:
                        days_ahead += 7
                    else:
                        # Even if Monday is ahead this week, "next Monday" means next week's Monday
                        days_ahead += 7
                else:
                    # Without "next", use the next occurrence (could be this week or next)
                    if days_ahead <= 0:
                        days_ahead += 7

                target_date = now + timedelta(days=days_ahead)
                # Extract time if present
                time_match = re.search(
                    r"at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", text, re.IGNORECASE
                )
                if time_match:
                    return cls._parse_time_str(time_match.group(1), target_date)
                # Default to 9am
                return target_date.replace(hour=9, minute=0, second=0, microsecond=0)
        return None

    @classmethod
    def _parse_time_only(cls, text: str, now: datetime) -> datetime | None:
        """Parse time-only expressions (2pm, 14:30, etc.)."""
        time_match = re.search(r"^(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)$", text, re.IGNORECASE)
        if time_match:
            return cls._parse_time_str(time_match.group(1), now)
        return None

    @classmethod
    def _parse_relative_duration(cls, text: str, now: datetime) -> datetime | None:
        """Parse relative duration (in 30 minutes, in 2 hours, etc.)."""
        duration_match = re.search(r"in\s+(\d+)\s+(minute|hour|day)s?", text, re.IGNORECASE)
        if duration_match:
            amount = int(duration_match.group(1))
            unit = duration_match.group(2).lower()
            if unit == "minute":
                return now + timedelta(minutes=amount)
            elif unit == "hour":
                return now + timedelta(hours=amount)
            elif unit == "day":
                return now + timedelta(days=amount)
        return None

    @classmethod
    def _parse_time_str(cls, time_str: str, date: datetime) -> datetime:
        """
        Parse time string and apply to date.

        Args:
            time_str: Time string like "2pm", "14:30", "9:15am"
            date: Base date to apply time to

        Returns:
            Datetime with parsed time applied
        """
        time_str = time_str.lower().strip()

        # Extract hour, minute, and meridiem (am/pm)
        parts = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", time_str)
        if not parts:
            # Fallback to 9am
            return date.replace(hour=9, minute=0, second=0, microsecond=0)

        hour = int(parts.group(1))
        minute = int(parts.group(2) or 0)
        meridiem = parts.group(3)

        # Handle 12-hour format
        if meridiem:
            if meridiem == "pm" and hour != 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0

        return date.replace(hour=hour, minute=minute, second=0, microsecond=0)


# ===========================================================================
# CalendarFormatter - Event Display Formatting
# ===========================================================================


class CalendarFormatter:
    """
    Format calendar events for display.

    Provides methods to format event lists and schedule summaries in a
    user-friendly format with proper time grouping and duration formatting.
    """

    @classmethod
    def format_event_list(
        cls,
        events: list[CalendarEvent],
        max_display: int = 10,
    ) -> str:
        """
        Format list of events for display.

        Args:
            events: List of CalendarEvent instances to format
            max_display: Maximum number of events to display (default: 10)

        Returns:
            Formatted event list string with date headers and event details
        """
        if not events:
            return "No events scheduled."

        lines: list[str] = []
        current_date = None

        for event in events[:max_display]:
            # Add date header if new day
            event_date = event.start.date()
            if event_date != current_date:
                current_date = event_date
                lines.append(f"\n{event_date.strftime('%A, %B %d')}:")

            # Format event
            time_str = event.start.strftime("%H:%M")
            duration = event.end - event.start
            duration_str = cls._format_duration(duration)

            line = f"  {time_str} - {event.title} ({duration_str})"
            if event.location:
                line += f"\n         @ {event.location}"
            lines.append(line)

        if len(events) > max_display:
            lines.append(f"\n... and {len(events) - max_display} more events")

        return "\n".join(lines)

    @classmethod
    def format_schedule_summary(cls, events: list[CalendarEvent]) -> str:
        """
        Format a brief schedule summary.

        Args:
            events: List of CalendarEvent instances

        Returns:
            Brief summary string (e.g., "You have 3 event(s) scheduled, totaling 4.5 hours.")
        """
        if not events:
            return "Your schedule is clear."

        total_hours = sum((e.end - e.start).total_seconds() / 3600 for e in events)

        return f"You have {len(events)} event(s) scheduled, " f"totaling {total_hours:.1f} hours."

    @classmethod
    def _format_duration(cls, duration: timedelta) -> str:
        """
        Format duration for display.

        Args:
            duration: timedelta to format

        Returns:
            Formatted duration string (e.g., "30min", "1h 30min", "2h")
        """
        total_minutes = int(duration.total_seconds() / 60)
        if total_minutes < 60:
            return f"{total_minutes}min"
        hours = total_minutes // 60
        minutes = total_minutes % 60
        if minutes:
            return f"{hours}h {minutes}min"
        return f"{hours}h"


# ===========================================================================
# ConflictChecker - Conflict Detection and Free Slot Finding
# ===========================================================================


class ConflictChecker:
    """
    Check for calendar conflicts and find free time slots.

    Provides methods to detect scheduling conflicts with existing events
    and find available time slots for scheduling new events.
    """

    @classmethod
    def check_conflicts(
        cls,
        new_start: datetime,
        new_end: datetime,
        existing_events: list[CalendarEvent],
    ) -> list[CalendarEvent]:
        """
        Check for conflicts with existing events.

        Two events conflict if they overlap in time:
        - new_start < existing_end AND new_end > existing_start

        Args:
            new_start: Start time of proposed event
            new_end: End time of proposed event
            existing_events: List of existing calendar events

        Returns:
            List of conflicting events (empty if no conflicts)
        """
        conflicts: list[CalendarEvent] = []

        for event in existing_events:
            # Check for time overlap
            if (new_start < event.end) and (new_end > event.start):
                conflicts.append(event)

        return conflicts

    @classmethod
    def find_free_slots(
        cls,
        date: datetime,
        duration: timedelta,
        existing_events: list[CalendarEvent],
        work_start: int = 9,
        work_end: int = 17,
    ) -> list[tuple[datetime, datetime]]:
        """
        Find free time slots on a given day.

        Args:
            date: The day to search for free slots
            duration: Minimum duration required for the slot
            existing_events: List of existing calendar events
            work_start: Start of work day in hours (default: 9 = 9am)
            work_end: End of work day in hours (default: 17 = 5pm)

        Returns:
            List of (start, end) tuples for available slots that fit the duration
        """
        # Define work day boundaries
        day_start = date.replace(hour=work_start, minute=0, second=0, microsecond=0)
        day_end = date.replace(hour=work_end, minute=0, second=0, microsecond=0)

        # Filter and sort events for this day
        day_events = sorted(
            [e for e in existing_events if e.start.date() == date.date()],
            key=lambda e: e.start,
        )

        free_slots: list[tuple[datetime, datetime]] = []
        current = day_start

        for event in day_events:
            if event.start > current:
                # Gap before this event
                gap = event.start - current
                if gap >= duration:
                    free_slots.append((current, event.start))
            current = max(current, event.end)

        # Check time after last event
        if current < day_end:
            if day_end - current >= duration:
                free_slots.append((current, day_end))

        return free_slots


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "TimeParser",
    "CalendarFormatter",
    "ConflictChecker",
]
