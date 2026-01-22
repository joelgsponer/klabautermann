"""
Unit tests for OfficerOfTheWatch agent.

Tests proactive alert functionality including deadline warnings,
meeting reminders, deep work detection, and alert filtering.

Issues: #59, #60, #61
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.agents.officer import (
    Alert,
    AlertCheckResult,
    AlertPriority,
    AlertType,
    CalendarEventSummary,
    MorningBriefing,
    OfficerConfig,
    OfficerOfTheWatch,
    TaskSummary,
)
from klabautermann.core.models import AgentMessage


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Create a mock Neo4j client."""
    mock = MagicMock()
    mock.execute_query = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def officer(mock_neo4j: MagicMock) -> OfficerOfTheWatch:
    """Create an OfficerOfTheWatch instance with mock dependencies."""
    config = OfficerConfig(
        deadline_warning_hours=24,
        meeting_reminder_minutes=15,
        alert_debounce_minutes=60,
    )
    return OfficerOfTheWatch(neo4j_client=mock_neo4j, config=config)


@pytest.fixture
def now_ms() -> int:
    """Get current timestamp in milliseconds."""
    return int(time.time() * 1000)


# =============================================================================
# Basic Tests
# =============================================================================


class TestOfficerOfTheWatchInit:
    """Tests for OfficerOfTheWatch initialization."""

    def test_init_default_config(self, mock_neo4j: MagicMock) -> None:
        """OfficerOfTheWatch should initialize with default config."""
        officer = OfficerOfTheWatch(neo4j_client=mock_neo4j)

        assert officer.name == "officer_of_the_watch"
        assert officer.officer_config.deadline_warning_hours == 24
        assert officer.officer_config.meeting_reminder_minutes == 15

    def test_init_custom_config(self, mock_neo4j: MagicMock) -> None:
        """OfficerOfTheWatch should accept custom config."""
        config = OfficerConfig(
            deadline_warning_hours=48,
            meeting_reminder_minutes=30,
        )
        officer = OfficerOfTheWatch(neo4j_client=mock_neo4j, config=config)

        assert officer.officer_config.deadline_warning_hours == 48
        assert officer.officer_config.meeting_reminder_minutes == 30


# =============================================================================
# Deep Work Detection Tests
# =============================================================================


class TestDeepWorkDetection:
    """Tests for deep work time detection."""

    @pytest.mark.asyncio
    async def test_not_deep_work_when_no_events(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should return False when no deep work events."""
        mock_neo4j.execute_query.return_value = []

        is_deep_work = await officer.is_deep_work_time()

        assert is_deep_work is False
        assert officer._current_deep_work_event is None

    @pytest.mark.asyncio
    async def test_deep_work_when_event_active(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should return True when deep work event is active."""
        mock_neo4j.execute_query.return_value = [{"uuid": "event-123", "title": "Deep Work Block"}]

        is_deep_work = await officer.is_deep_work_time()

        assert is_deep_work is True
        assert officer._current_deep_work_event == "Deep Work Block"

    @pytest.mark.asyncio
    async def test_deep_work_focus_keyword(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should detect deep work with 'Focus' keyword."""
        mock_neo4j.execute_query.return_value = [{"uuid": "event-456", "title": "Focus Time"}]

        is_deep_work = await officer.is_deep_work_time()

        assert is_deep_work is True
        assert officer._current_deep_work_event == "Focus Time"


# =============================================================================
# Deadline Alert Tests (#60)
# =============================================================================


class TestDeadlineAlerts:
    """Tests for deadline warning alerts."""

    @pytest.mark.asyncio
    async def test_no_deadlines_returns_empty(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should return empty list when no upcoming deadlines."""
        mock_neo4j.execute_query.return_value = []

        alerts = await officer.check_upcoming_deadlines()

        assert alerts == []

    @pytest.mark.asyncio
    async def test_deadline_within_window(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return alert for task due within 24 hours."""
        due_in_12_hours = now_ms + (12 * 60 * 60 * 1000)
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "task-123",
                "action": "Review PR",
                "due_date": due_in_12_hours,
                "priority": "high",
                "status": "todo",
                "project_name": "Backend",
            }
        ]

        alerts = await officer.check_upcoming_deadlines()

        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.alert_type == AlertType.DEADLINE_WARNING
        assert alert.priority == AlertPriority.WARNING  # high priority task
        assert "Review PR" in alert.message
        assert alert.entity_uuid == "task-123"
        assert alert.entity_type == "Task"

    @pytest.mark.asyncio
    async def test_deadline_low_priority_task(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return INFO priority for low priority tasks."""
        due_in_6_hours = now_ms + (6 * 60 * 60 * 1000)
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "task-456",
                "action": "Update docs",
                "due_date": due_in_6_hours,
                "priority": "low",
                "status": "todo",
                "project_name": None,
            }
        ]

        alerts = await officer.check_upcoming_deadlines()

        assert len(alerts) == 1
        assert alerts[0].priority == AlertPriority.INFO

    @pytest.mark.asyncio
    async def test_deadline_custom_hours(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should respect custom hours parameter."""
        await officer.check_upcoming_deadlines(hours=48)

        # Verify the query was called with 48 hours in milliseconds
        call_args = mock_neo4j.execute_query.call_args
        params = call_args[0][1]
        expected_ms = 48 * 60 * 60 * 1000
        assert params["hours_ms"] == expected_ms


# =============================================================================
# Meeting Reminder Tests (#61)
# =============================================================================


class TestMeetingReminders:
    """Tests for meeting reminder alerts."""

    @pytest.mark.asyncio
    async def test_no_meetings_returns_empty(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should return empty list when no upcoming meetings."""
        mock_neo4j.execute_query.return_value = []

        alerts = await officer.check_upcoming_meetings()

        assert alerts == []

    @pytest.mark.asyncio
    async def test_meeting_within_window(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return alert for meeting within 15 minutes."""
        start_in_10_min = now_ms + (10 * 60 * 1000)
        end_in_70_min = now_ms + (70 * 60 * 1000)
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "event-123",
                "title": "Team Standup",
                "start_time": start_in_10_min,
                "end_time": end_in_70_min,
                "location": "Zoom",
                "description": "Daily standup meeting",
            }
        ]

        alerts = await officer.check_upcoming_meetings()

        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.alert_type == AlertType.MEETING_REMINDER
        assert alert.priority == AlertPriority.INFO
        assert "Team Standup" in alert.message
        assert "Zoom" in alert.message
        assert alert.entity_uuid == "event-123"
        assert alert.entity_type == "Event"

    @pytest.mark.asyncio
    async def test_meeting_no_location(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should handle meeting without location."""
        start_in_5_min = now_ms + (5 * 60 * 1000)
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "event-456",
                "title": "Quick Sync",
                "start_time": start_in_5_min,
                "end_time": start_in_5_min + (30 * 60 * 1000),
                "location": None,
                "description": None,
            }
        ]

        alerts = await officer.check_upcoming_meetings()

        assert len(alerts) == 1
        assert "Quick Sync" in alerts[0].message
        assert "at" not in alerts[0].message  # No location clause

    @pytest.mark.asyncio
    async def test_meeting_custom_minutes(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should respect custom minutes parameter."""
        await officer.check_upcoming_meetings(minutes=30)

        # Verify the query was called with 30 minutes in milliseconds
        call_args = mock_neo4j.execute_query.call_args
        params = call_args[0][1]
        expected_ms = 30 * 60 * 1000
        assert params["minutes_ms"] == expected_ms


# =============================================================================
# Overdue Task Tests
# =============================================================================


class TestOverdueTasks:
    """Tests for overdue task alerts."""

    @pytest.mark.asyncio
    async def test_no_overdue_returns_empty(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should return empty list when no overdue tasks."""
        mock_neo4j.execute_query.return_value = []

        alerts = await officer.check_overdue_tasks()

        assert alerts == []

    @pytest.mark.asyncio
    async def test_overdue_task_returns_error_alert(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return ERROR priority for overdue tasks."""
        overdue_by_2_hours = now_ms - (2 * 60 * 60 * 1000)
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "task-789",
                "action": "Deploy to production",
                "due_date": overdue_by_2_hours,
                "priority": "urgent",
                "status": "in_progress",
                "project_name": "Release",
            }
        ]

        alerts = await officer.check_overdue_tasks()

        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.alert_type == AlertType.OVERDUE_TASK
        assert alert.priority == AlertPriority.ERROR
        assert "Deploy to production" in alert.message
        assert "overdue" in alert.message.lower()


# =============================================================================
# Alert Filtering and Debouncing Tests
# =============================================================================


class TestAlertFiltering:
    """Tests for alert filtering and debouncing."""

    def test_should_notify_normal_conditions(self, officer: OfficerOfTheWatch) -> None:
        """Should allow notification under normal conditions."""
        alert = Alert(
            alert_type=AlertType.DEADLINE_WARNING,
            priority=AlertPriority.WARNING,
            message="Test alert",
            entity_uuid="task-123",
        )

        officer._quiet_mode = False
        should_notify = officer._should_notify(alert)

        assert should_notify is True

    def test_quiet_mode_blocks_non_critical(self, officer: OfficerOfTheWatch) -> None:
        """Should block non-critical alerts in quiet mode."""
        alert = Alert(
            alert_type=AlertType.MEETING_REMINDER,
            priority=AlertPriority.INFO,
            message="Test alert",
            entity_uuid="event-123",
        )

        officer._quiet_mode = True
        should_notify = officer._should_notify(alert)

        assert should_notify is False

    def test_quiet_mode_allows_critical(self, officer: OfficerOfTheWatch) -> None:
        """Should allow CRITICAL alerts in quiet mode."""
        alert = Alert(
            alert_type=AlertType.ANOMALY,
            priority=AlertPriority.CRITICAL,
            message="Critical alert",
            entity_uuid=None,
        )

        officer._quiet_mode = True
        should_notify = officer._should_notify(alert)

        assert should_notify is True

    def test_debouncing_blocks_recent_alert(self, officer: OfficerOfTheWatch) -> None:
        """Should block alert if same alert was recently sent."""
        alert = Alert(
            alert_type=AlertType.DEADLINE_WARNING,
            priority=AlertPriority.WARNING,
            message="Test alert",
            entity_uuid="task-123",
        )

        # Mark as recently sent
        officer._mark_alert_sent(alert)

        should_notify = officer._should_notify(alert)
        assert should_notify is False

    def test_debouncing_allows_different_entity(self, officer: OfficerOfTheWatch) -> None:
        """Should allow alert for different entity."""
        alert1 = Alert(
            alert_type=AlertType.DEADLINE_WARNING,
            priority=AlertPriority.WARNING,
            message="Alert 1",
            entity_uuid="task-123",
        )
        alert2 = Alert(
            alert_type=AlertType.DEADLINE_WARNING,
            priority=AlertPriority.WARNING,
            message="Alert 2",
            entity_uuid="task-456",
        )

        officer._mark_alert_sent(alert1)

        should_notify = officer._should_notify(alert2)
        assert should_notify is True

    def test_clear_recent_alerts(self, officer: OfficerOfTheWatch) -> None:
        """Should clear recent alerts cache."""
        alert = Alert(
            alert_type=AlertType.DEADLINE_WARNING,
            priority=AlertPriority.WARNING,
            message="Test",
            entity_uuid="task-123",
        )

        officer._mark_alert_sent(alert)
        assert len(officer._recent_alerts) > 0

        officer.clear_recent_alerts()
        assert len(officer._recent_alerts) == 0


# =============================================================================
# Check Conditions Integration Tests
# =============================================================================


class TestCheckConditions:
    """Integration tests for check_conditions."""

    @pytest.mark.asyncio
    async def test_check_conditions_empty(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should return empty result when no alerts."""
        mock_neo4j.execute_query.return_value = []

        result = await officer.check_conditions()

        assert isinstance(result, AlertCheckResult)
        assert result.alerts_found == 0
        assert result.alerts_sent == 0
        assert result.quiet_mode is False

    @pytest.mark.asyncio
    async def test_check_conditions_with_alerts(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should aggregate alerts from all checks."""
        # Setup different responses for different queries
        call_count = 0

        async def mock_execute(query: str, params: dict, **kwargs: Any) -> list:
            nonlocal call_count
            call_count += 1

            # Deep work check
            if "e.title =~" in query:
                return []

            # Deadline check
            if "t.due_date" in query and "t.due_date > timestamp()" in query:
                return [
                    {
                        "uuid": "task-1",
                        "action": "Task 1",
                        "due_date": now_ms + (10 * 60 * 60 * 1000),
                        "priority": "high",
                        "status": "todo",
                        "project_name": None,
                    }
                ]

            # Meeting check
            if "e.start_time" in query:
                return [
                    {
                        "uuid": "event-1",
                        "title": "Meeting 1",
                        "start_time": now_ms + (10 * 60 * 1000),
                        "end_time": now_ms + (70 * 60 * 1000),
                        "location": "Room A",
                        "description": None,
                    }
                ]

            # Overdue check
            if "t.due_date < timestamp()" in query:
                return []

            return []

        mock_neo4j.execute_query.side_effect = mock_execute

        result = await officer.check_conditions()

        assert result.alerts_found == 2  # 1 deadline + 1 meeting
        assert result.alerts_sent == 2
        assert len(result.alerts) == 2


# =============================================================================
# Process Message Tests
# =============================================================================


class TestProcessMessage:
    """Tests for process_message interface."""

    @pytest.mark.asyncio
    async def test_process_check_conditions(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should process check_conditions operation."""
        mock_neo4j.execute_query.return_value = []

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="officer_of_the_watch",
            intent="maintenance",
            payload={"operation": "check_conditions"},
            trace_id="test-trace",
        )

        response = await officer.process_message(msg)

        assert response is not None
        assert response.source_agent == "officer_of_the_watch"
        assert response.target_agent == "orchestrator"
        assert "alerts_found" in response.payload

    @pytest.mark.asyncio
    async def test_process_check_deadlines(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should process check_deadlines operation."""
        mock_neo4j.execute_query.return_value = []

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="officer_of_the_watch",
            intent="maintenance",
            payload={"operation": "check_deadlines"},
            trace_id="test-trace",
        )

        response = await officer.process_message(msg)

        assert response is not None
        assert "alerts" in response.payload
        assert "count" in response.payload

    @pytest.mark.asyncio
    async def test_process_check_meetings(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should process check_meetings operation."""
        mock_neo4j.execute_query.return_value = []

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="officer_of_the_watch",
            intent="maintenance",
            payload={"operation": "check_meetings"},
            trace_id="test-trace",
        )

        response = await officer.process_message(msg)

        assert response is not None
        assert "alerts" in response.payload

    @pytest.mark.asyncio
    async def test_process_is_deep_work(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should process is_deep_work operation."""
        mock_neo4j.execute_query.return_value = []

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="officer_of_the_watch",
            intent="query",
            payload={"operation": "is_deep_work"},
            trace_id="test-trace",
        )

        response = await officer.process_message(msg)

        assert response is not None
        assert "is_deep_work" in response.payload

    @pytest.mark.asyncio
    async def test_process_unknown_operation(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should return error for unknown operation."""
        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="officer_of_the_watch",
            intent="unknown",
            payload={"operation": "unknown_op"},
            trace_id="test-trace",
        )

        response = await officer.process_message(msg)

        assert response is not None
        assert "error" in response.payload


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Tests for alert statistics."""

    @pytest.mark.asyncio
    async def test_get_alert_statistics(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should return alert statistics."""
        mock_neo4j.execute_query.side_effect = [
            # Task stats
            [
                {
                    "total_tasks": 10,
                    "overdue_count": 2,
                    "due_24h_count": 3,
                    "due_week_count": 5,
                }
            ],
            # Event stats
            [{"events_24h": 4}],
        ]

        stats = await officer.get_alert_statistics()

        assert stats["total_active_tasks"] == 10
        assert stats["overdue_tasks"] == 2
        assert stats["tasks_due_24h"] == 3
        assert stats["tasks_due_week"] == 5
        assert stats["events_24h"] == 4

    @pytest.mark.asyncio
    async def test_get_alert_statistics_empty(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should handle empty statistics gracefully."""
        mock_neo4j.execute_query.return_value = []

        stats = await officer.get_alert_statistics()

        assert stats["total_active_tasks"] == 0
        assert stats["overdue_tasks"] == 0


# =============================================================================
# Data Classes Tests
# =============================================================================


class TestDataClasses:
    """Tests for Alert and AlertCheckResult data classes."""

    def test_alert_to_dict(self) -> None:
        """Alert should serialize to dict."""
        alert = Alert(
            alert_type=AlertType.DEADLINE_WARNING,
            priority=AlertPriority.WARNING,
            message="Test alert",
            entity_uuid="task-123",
            entity_type="Task",
            due_at=1234567890000,
            metadata={"key": "value"},
        )

        result = alert.to_dict()

        assert result["alert_type"] == "deadline_warning"
        assert result["priority"] == "WARNING"
        assert result["message"] == "Test alert"
        assert result["entity_uuid"] == "task-123"
        assert result["metadata"]["key"] == "value"

    def test_alert_check_result_to_dict(self) -> None:
        """AlertCheckResult should serialize to dict."""
        alert = Alert(
            alert_type=AlertType.MEETING_REMINDER,
            priority=AlertPriority.INFO,
            message="Meeting soon",
        )

        result = AlertCheckResult(
            alerts_found=5,
            alerts_sent=3,
            quiet_mode=False,
            deep_work_event=None,
            duration_ms=123.456,
            alerts=[alert],
        )

        data = result.to_dict()

        assert data["alerts_found"] == 5
        assert data["alerts_sent"] == 3
        assert data["quiet_mode"] is False
        assert data["duration_ms"] == 123.46
        assert len(data["alerts"]) == 1

    def test_calendar_event_summary_to_dict(self) -> None:
        """CalendarEventSummary should serialize to dict."""
        event = CalendarEventSummary(
            uuid="event-123",
            title="Team Meeting",
            start_time=1234567890000,
            end_time=1234571490000,
            location="Room A",
            description="Weekly sync",
        )

        result = event.to_dict()

        assert result["uuid"] == "event-123"
        assert result["title"] == "Team Meeting"
        assert result["start_time"] == 1234567890000
        assert result["location"] == "Room A"

    def test_task_summary_to_dict(self) -> None:
        """TaskSummary should serialize to dict."""
        task = TaskSummary(
            uuid="task-123",
            action="Review PR",
            priority="high",
            status="in_progress",
            due_date=1234567890000,
            project_name="Backend",
        )

        result = task.to_dict()

        assert result["uuid"] == "task-123"
        assert result["action"] == "Review PR"
        assert result["priority"] == "high"
        assert result["project_name"] == "Backend"

    def test_morning_briefing_to_dict(self) -> None:
        """MorningBriefing should serialize to dict."""
        from datetime import datetime

        event = CalendarEventSummary(
            uuid="event-1",
            title="Meeting",
            start_time=1234567890000,
            end_time=1234571490000,
        )
        task = TaskSummary(
            uuid="task-1",
            action="Task",
            priority="high",
            status="todo",
        )
        alert = Alert(
            alert_type=AlertType.DEADLINE_WARNING,
            priority=AlertPriority.WARNING,
            message="Alert",
        )

        briefing = MorningBriefing(
            generated_at=datetime(2026, 1, 22, 7, 0, 0),
            greeting="Good morning, Captain",
            events_today=[event],
            high_priority_tasks=[task],
            overdue_tasks=[],
            overnight_alerts=[alert],
            summary_text="Test summary",
            duration_ms=50.5,
        )

        result = briefing.to_dict()

        assert result["greeting"] == "Good morning, Captain"
        assert len(result["events_today"]) == 1
        assert len(result["high_priority_tasks"]) == 1
        assert len(result["overdue_tasks"]) == 0
        assert len(result["overnight_alerts"]) == 1
        assert result["summary_text"] == "Test summary"


# =============================================================================
# Morning Briefing Tests (#4)
# =============================================================================


class TestMorningBriefing:
    """Tests for morning briefing generation."""

    @pytest.mark.asyncio
    async def test_generate_morning_briefing_empty(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should generate briefing with no events/tasks."""
        mock_neo4j.execute_query.return_value = []

        briefing = await officer.generate_morning_briefing()

        assert isinstance(briefing, MorningBriefing)
        assert briefing.events_today == []
        assert briefing.high_priority_tasks == []
        assert briefing.overdue_tasks == []
        assert "Captain" in briefing.greeting
        assert "Clear skies" in briefing.greeting or "No events" in briefing.summary_text

    @pytest.mark.asyncio
    async def test_generate_morning_briefing_with_events(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should include today's events in briefing."""
        call_count = 0

        async def mock_execute(query: str, params: dict, **kwargs: Any) -> list:
            nonlocal call_count
            call_count += 1

            # Events query (first call)
            if "e:Event" in query and "e.start_time >=" in query:
                return [
                    {
                        "uuid": "event-1",
                        "title": "Morning Standup",
                        "start_time": now_ms + (2 * 60 * 60 * 1000),  # 2 hours from now
                        "end_time": now_ms + (3 * 60 * 60 * 1000),
                        "location": "Zoom",
                        "description": "Daily sync",
                    }
                ]

            return []

        mock_neo4j.execute_query.side_effect = mock_execute

        briefing = await officer.generate_morning_briefing()

        assert len(briefing.events_today) == 1
        assert briefing.events_today[0].title == "Morning Standup"
        assert "Schedule" in briefing.summary_text
        assert "Morning Standup" in briefing.summary_text

    @pytest.mark.asyncio
    async def test_generate_morning_briefing_with_high_priority_tasks(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should include high priority tasks in briefing."""
        call_count = 0

        async def mock_execute(query: str, params: dict, **kwargs: Any) -> list:
            nonlocal call_count
            call_count += 1

            # High priority tasks query
            if "t.priority IN ['urgent', 'high']" in query:
                return [
                    {
                        "uuid": "task-1",
                        "action": "Deploy hotfix",
                        "priority": "urgent",
                        "status": "todo",
                        "due_date": now_ms + (4 * 60 * 60 * 1000),
                        "project_name": "Backend",
                    }
                ]

            return []

        mock_neo4j.execute_query.side_effect = mock_execute

        briefing = await officer.generate_morning_briefing()

        assert len(briefing.high_priority_tasks) == 1
        assert briefing.high_priority_tasks[0].action == "Deploy hotfix"
        assert "High Priority" in briefing.summary_text
        assert "Deploy hotfix" in briefing.summary_text

    @pytest.mark.asyncio
    async def test_generate_morning_briefing_with_overdue_tasks(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should include overdue tasks in briefing."""
        call_count = 0

        async def mock_execute(query: str, params: dict, **kwargs: Any) -> list:
            nonlocal call_count
            call_count += 1

            # Overdue tasks query (for briefing)
            if "t.due_date < timestamp()" in query and "t.priority IN" not in query:
                return [
                    {
                        "uuid": "task-2",
                        "action": "Complete report",
                        "priority": "medium",
                        "status": "in_progress",
                        "due_date": now_ms - (24 * 60 * 60 * 1000),  # 1 day ago
                        "project_name": None,
                    }
                ]

            return []

        mock_neo4j.execute_query.side_effect = mock_execute

        briefing = await officer.generate_morning_briefing()

        assert len(briefing.overdue_tasks) == 1
        assert briefing.overdue_tasks[0].action == "Complete report"
        assert "Overdue" in briefing.summary_text

    @pytest.mark.asyncio
    async def test_generate_morning_briefing_greeting_with_overdue(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should mention overdue items in greeting when present."""

        async def mock_execute(query: str, params: dict, **kwargs: Any) -> list:
            # Overdue tasks
            if "t.due_date < timestamp()" in query and "t.priority IN" not in query:
                return [
                    {
                        "uuid": "task-1",
                        "action": "Overdue task",
                        "priority": "medium",
                        "status": "todo",
                        "due_date": now_ms - (1 * 60 * 60 * 1000),
                        "project_name": None,
                    }
                ]
            return []

        mock_neo4j.execute_query.side_effect = mock_execute

        briefing = await officer.generate_morning_briefing()

        assert "overdue" in briefing.greeting.lower()

    @pytest.mark.asyncio
    async def test_process_message_morning_briefing(
        self, officer: OfficerOfTheWatch, mock_neo4j: MagicMock
    ) -> None:
        """Should handle morning_briefing operation via process_message."""
        mock_neo4j.execute_query.return_value = []

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="officer_of_the_watch",
            intent="briefing",
            payload={"operation": "morning_briefing"},
            trace_id="test-trace",
        )

        response = await officer.process_message(msg)

        assert response is not None
        assert "greeting" in response.payload
        assert "events_today" in response.payload
        assert "high_priority_tasks" in response.payload
        assert "summary_text" in response.payload


class TestBriefingTimeConfig:
    """Tests for briefing time configuration."""

    def test_default_briefing_time(self, mock_neo4j: MagicMock) -> None:
        """Default briefing time should be 7:00."""
        officer = OfficerOfTheWatch(neo4j_client=mock_neo4j)

        assert officer.officer_config.briefing_hour == 7
        assert officer.officer_config.briefing_minute == 0

    def test_custom_briefing_time(self, mock_neo4j: MagicMock) -> None:
        """Should accept custom briefing time."""
        config = OfficerConfig(briefing_hour=8, briefing_minute=30)
        officer = OfficerOfTheWatch(neo4j_client=mock_neo4j, config=config)

        assert officer.officer_config.briefing_hour == 8
        assert officer.officer_config.briefing_minute == 30

    def test_is_briefing_time_at_configured_time(self, mock_neo4j: MagicMock) -> None:
        """is_briefing_time should return True at configured time."""
        from datetime import datetime
        from unittest.mock import patch

        config = OfficerConfig(briefing_hour=7, briefing_minute=0)
        officer = OfficerOfTheWatch(neo4j_client=mock_neo4j, config=config)

        # Mock datetime.now() to return 7:00
        mock_now = datetime(2026, 1, 22, 7, 0, 0)
        with patch("klabautermann.agents.officer.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now

            assert officer.is_briefing_time() is True

    def test_is_briefing_time_not_at_configured_time(self, mock_neo4j: MagicMock) -> None:
        """is_briefing_time should return False at other times."""
        from datetime import datetime
        from unittest.mock import patch

        config = OfficerConfig(briefing_hour=7, briefing_minute=0)
        officer = OfficerOfTheWatch(neo4j_client=mock_neo4j, config=config)

        # Mock datetime.now() to return 9:30
        mock_now = datetime(2026, 1, 22, 9, 30, 0)
        with patch("klabautermann.agents.officer.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now

            assert officer.is_briefing_time() is False


class TestGreetingGeneration:
    """Tests for greeting generation."""

    def test_greeting_clear_skies(self, officer: OfficerOfTheWatch) -> None:
        """Should generate 'clear skies' greeting with no items."""
        greeting = officer._generate_greeting(event_count=0, task_count=0, overdue_count=0)

        assert "Captain" in greeting
        assert "Clear skies" in greeting

    def test_greeting_calm_seas(self, officer: OfficerOfTheWatch) -> None:
        """Should generate 'calm seas' greeting with few items."""
        greeting = officer._generate_greeting(event_count=1, task_count=1, overdue_count=0)

        assert "calm" in greeting.lower() or "manageable" in greeting.lower()

    def test_greeting_moderate_winds(self, officer: OfficerOfTheWatch) -> None:
        """Should generate 'moderate winds' greeting with moderate load."""
        greeting = officer._generate_greeting(event_count=3, task_count=2, overdue_count=0)

        assert "Moderate" in greeting or "full" in greeting.lower()

    def test_greeting_choppy_waters(self, officer: OfficerOfTheWatch) -> None:
        """Should generate 'choppy waters' greeting with heavy load."""
        greeting = officer._generate_greeting(event_count=5, task_count=5, overdue_count=0)

        assert "Choppy" in greeting or "busy" in greeting.lower()

    def test_greeting_overdue_warning(self, officer: OfficerOfTheWatch) -> None:
        """Should mention overdue items when present."""
        greeting = officer._generate_greeting(event_count=1, task_count=1, overdue_count=2)

        assert "overdue" in greeting.lower()
