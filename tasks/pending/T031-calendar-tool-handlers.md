# Add Calendar Tool Handlers

## Metadata
- **ID**: T031
- **Priority**: P1
- **Category**: subagent
- **Effort**: M
- **Status**: pending
- **Assignee**: @integration-engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.4
- Related: [PRD.md](../../specs/PRD.md) Section 6

## Dependencies
- [ ] T029 - Executor agent
- [ ] T028 - Google Workspace MCP bridge

## Context
This task extends the Executor agent with sophisticated Calendar handling. While T028 provides the basic MCP bridge, this task adds higher-level functionality like natural language time parsing, conflict detection, and intelligent scheduling.

## Requirements
- [ ] Extend Calendar capabilities in Executor:

### Time Parsing
- [ ] Natural language to datetime conversion
- [ ] Common patterns:
  - "tomorrow at 2pm" -> datetime
  - "next Monday" -> datetime
  - "in 30 minutes" -> datetime
  - "3pm to 4pm" -> start + end datetime
- [ ] Timezone handling (default to user's timezone)

### Event Creation
- [ ] Parse event details from natural language
- [ ] Default duration if not specified (1 hour)
- [ ] Attendee extraction from context
- [ ] Location suggestions from context

### Conflict Detection
- [ ] Check for existing events in time slot
- [ ] Suggest alternative times if conflict
- [ ] Double-booking warning

### Schedule Views
- [ ] Today's schedule
- [ ] Tomorrow's schedule
- [ ] This week's schedule
- [ ] Free time finder

### Response Formatting
- [ ] Clear event display format
- [ ] Time relative to now ("in 2 hours")
- [ ] Conflict warnings

## Acceptance Criteria
- [ ] "Schedule meeting tomorrow at 2pm" creates event correctly
- [ ] "What's on my calendar today?" shows events
- [ ] Conflict detection warns about double-booking
- [ ] Time parsing handles common patterns
- [ ] Events created with correct timezone

## Implementation Notes

```python
from typing import Optional, List, Tuple
from datetime import datetime, timedelta, time
from pydantic import BaseModel
import re
from zoneinfo import ZoneInfo

from klabautermann.mcp.google_workspace import GoogleWorkspaceBridge, CalendarEvent


class TimeParser:
    """
    Parse natural language time expressions to datetime.
    """

    # Day name mapping
    DAYS = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3,
        "fri": 4, "sat": 5, "sun": 6,
    }

    # Relative day patterns
    RELATIVE_DAYS = {
        "today": 0,
        "tomorrow": 1,
        "day after tomorrow": 2,
        "next week": 7,
    }

    @classmethod
    def parse(
        cls,
        text: str,
        reference: Optional[datetime] = None,
        timezone: str = "UTC",
    ) -> Optional[datetime]:
        """
        Parse natural language time to datetime.

        Args:
            text: Natural language time expression.
            reference: Reference datetime (default: now).
            timezone: Timezone string.

        Returns:
            Parsed datetime or None if unparseable.
        """
        tz = ZoneInfo(timezone)
        now = reference or datetime.now(tz)
        text = text.lower().strip()

        # Try various patterns
        result = (
            cls._parse_relative_day(text, now) or
            cls._parse_day_name(text, now) or
            cls._parse_time_only(text, now) or
            cls._parse_relative_duration(text, now)
        )

        if result:
            return result.replace(tzinfo=tz)

        return None

    @classmethod
    def parse_range(
        cls,
        text: str,
        reference: Optional[datetime] = None,
        default_duration: timedelta = timedelta(hours=1),
        timezone: str = "UTC",
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Parse time range (start and end).

        Returns:
            Tuple of (start, end) datetimes.
        """
        # Look for explicit range patterns
        range_match = re.search(
            r'(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:to|-)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)',
            text,
            re.IGNORECASE
        )

        if range_match:
            start_str, end_str = range_match.groups()
            start = cls._parse_time_str(start_str, reference or datetime.now())
            end = cls._parse_time_str(end_str, reference or datetime.now())
            return start, end

        # Otherwise, parse single time and add default duration
        start = cls.parse(text, reference, timezone)
        if start:
            return start, start + default_duration

        return None, None

    @classmethod
    def _parse_relative_day(cls, text: str, now: datetime) -> Optional[datetime]:
        """Parse relative day expressions."""
        for pattern, days in cls.RELATIVE_DAYS.items():
            if pattern in text:
                target_date = now + timedelta(days=days)
                # Extract time if present
                time_match = re.search(r'at\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)', text, re.IGNORECASE)
                if time_match:
                    return cls._parse_time_str(time_match.group(1), target_date)
                return target_date.replace(hour=9, minute=0, second=0, microsecond=0)
        return None

    @classmethod
    def _parse_day_name(cls, text: str, now: datetime) -> Optional[datetime]:
        """Parse day name expressions (next Monday, etc.)."""
        for day_name, day_num in cls.DAYS.items():
            if day_name in text:
                days_ahead = day_num - now.weekday()
                if days_ahead <= 0 or "next" in text:
                    days_ahead += 7
                target_date = now + timedelta(days=days_ahead)
                # Extract time if present
                time_match = re.search(r'at\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)', text, re.IGNORECASE)
                if time_match:
                    return cls._parse_time_str(time_match.group(1), target_date)
                return target_date.replace(hour=9, minute=0, second=0, microsecond=0)
        return None

    @classmethod
    def _parse_time_only(cls, text: str, now: datetime) -> Optional[datetime]:
        """Parse time-only expressions (2pm, 14:30)."""
        time_match = re.search(r'^(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)$', text, re.IGNORECASE)
        if time_match:
            return cls._parse_time_str(time_match.group(1), now)
        return None

    @classmethod
    def _parse_relative_duration(cls, text: str, now: datetime) -> Optional[datetime]:
        """Parse relative duration (in 30 minutes, in 2 hours)."""
        duration_match = re.search(r'in\s*(\d+)\s*(minute|hour|day)s?', text, re.IGNORECASE)
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
        """Parse time string and apply to date."""
        time_str = time_str.lower().strip()

        # Extract hour and minute
        parts = re.match(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str)
        if not parts:
            return date.replace(hour=9, minute=0)

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


class CalendarFormatter:
    """
    Format calendar events for display.
    """

    @classmethod
    def format_event_list(
        cls,
        events: List[CalendarEvent],
        max_display: int = 10,
    ) -> str:
        """Format list of events for display."""
        if not events:
            return "No events scheduled."

        lines = []
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
    def format_schedule_summary(cls, events: List[CalendarEvent]) -> str:
        """Format a brief schedule summary."""
        if not events:
            return "Your schedule is clear."

        total_hours = sum((e.end - e.start).total_seconds() / 3600 for e in events)

        return (
            f"You have {len(events)} event(s) scheduled, "
            f"totaling {total_hours:.1f} hours."
        )

    @classmethod
    def _format_duration(cls, duration: timedelta) -> str:
        """Format duration for display."""
        total_minutes = int(duration.total_seconds() / 60)
        if total_minutes < 60:
            return f"{total_minutes}min"
        hours = total_minutes // 60
        minutes = total_minutes % 60
        if minutes:
            return f"{hours}h {minutes}min"
        return f"{hours}h"


class ConflictChecker:
    """
    Check for calendar conflicts.
    """

    @classmethod
    def check_conflicts(
        cls,
        new_start: datetime,
        new_end: datetime,
        existing_events: List[CalendarEvent],
    ) -> List[CalendarEvent]:
        """
        Check for conflicts with existing events.

        Returns:
            List of conflicting events.
        """
        conflicts = []

        for event in existing_events:
            # Check for overlap
            if (new_start < event.end) and (new_end > event.start):
                conflicts.append(event)

        return conflicts

    @classmethod
    def find_free_slots(
        cls,
        date: datetime,
        duration: timedelta,
        existing_events: List[CalendarEvent],
        work_start: int = 9,
        work_end: int = 17,
    ) -> List[Tuple[datetime, datetime]]:
        """
        Find free time slots on a given day.

        Returns:
            List of (start, end) tuples for available slots.
        """
        # Start with full work day
        day_start = date.replace(hour=work_start, minute=0, second=0, microsecond=0)
        day_end = date.replace(hour=work_end, minute=0, second=0, microsecond=0)

        # Sort events by start time
        day_events = sorted(
            [e for e in existing_events if e.start.date() == date.date()],
            key=lambda e: e.start
        )

        free_slots = []
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


# Add to Executor agent methods:

async def handle_calendar_create(
    self,
    action: str,
    context: dict,
    trace_id: str,
) -> ActionResult:
    """Handle calendar event creation with parsing."""
    # Parse time
    start, end = TimeParser.parse_range(action)

    if not start:
        return ActionResult(
            success=False,
            message="I couldn't understand the time. Please specify when, like 'tomorrow at 2pm' or '3pm to 4pm'.",
        )

    # Check for conflicts
    existing = await self.google.list_events(
        start=start.replace(hour=0, minute=0),
        end=start.replace(hour=23, minute=59),
        context=ToolInvocationContext(trace_id=trace_id, agent_name=self.name),
    )

    conflicts = ConflictChecker.check_conflicts(start, end, existing)

    if conflicts:
        conflict_names = ", ".join(c.title for c in conflicts)
        return ActionResult(
            success=False,
            message=f"That time conflicts with: {conflict_names}. Would you like me to find a free slot?",
            needs_confirmation=True,
            details={"conflicts": [c.title for c in conflicts]},
        )

    # Extract title from action
    title = cls._extract_event_title(action) or "New Event"

    # Create the event
    result = await self.google.create_event(
        title=title,
        start=start,
        end=end,
        context=ToolInvocationContext(trace_id=trace_id, agent_name=self.name),
    )

    if result.success:
        return ActionResult(
            success=True,
            message=f"Created '{title}' on {start.strftime('%A at %H:%M')}.",
            details={"event_id": result.event_id},
        )

    return ActionResult(success=False, message=f"Failed to create event: {result.error}")
```

These helpers are integrated into the Executor agent to provide sophisticated calendar handling with natural language time parsing and conflict detection.
