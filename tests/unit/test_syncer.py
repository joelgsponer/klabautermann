"""
Unit tests for Syncer Agent.

The Syncer imports emails and calendar events from Google Workspace
into the knowledge graph for persistent memory of communications.

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from klabautermann.agents.syncer import Syncer
from klabautermann.core.models import AgentMessage


class MockCalendarEvent:
    """Mock CalendarEvent for testing."""

    def __init__(
        self,
        id: str = "event-001",
        title: str = "Test Meeting",
        start: datetime | None = None,
        end: datetime | None = None,
        location: str | None = None,
        description: str | None = None,
        attendees: list[str] | None = None,
        calendar_id: str = "primary",
        calendar_name: str | None = None,
        event_type: str | None = None,
        transparency: str | None = None,
    ):
        self.id = id
        self.title = title
        self.start = start or datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
        self.end = end or datetime(2024, 1, 15, 11, 0, tzinfo=UTC)
        self.location = location
        self.description = description
        self.attendees = attendees or []
        self.calendar_id = calendar_id
        self.calendar_name = calendar_name
        self.event_type = event_type
        self.transparency = transparency


class MockEmailMessage:
    """Mock EmailMessage for testing."""

    def __init__(
        self,
        id: str = "email-001",
        thread_id: str = "thread-001",
        subject: str = "Test Subject",
        sender: str = "John Doe <john@example.com>",
        recipient: str | None = "me@example.com",
        date: datetime | None = None,
        snippet: str = "Test snippet...",
        body: str | None = "Test email body content",
        is_unread: bool = False,
    ):
        self.id = id
        self.thread_id = thread_id
        self.subject = subject
        self.sender = sender
        self.recipient = recipient
        self.date = date or datetime(2024, 1, 15, 9, 30, tzinfo=UTC)
        self.snippet = snippet
        self.body = body
        self.is_unread = is_unread


class TestSyncerInit:
    """Test suite for Syncer initialization."""

    def test_default_config(self) -> None:
        """Should use default config values when not specified."""
        syncer = Syncer(name="syncer")

        assert syncer.calendar_enabled is True
        assert syncer.calendar_lookback_days == 7
        assert syncer.calendar_lookahead_days == 14
        assert syncer.calendar_sync_all is True  # Default: sync all owned calendars
        assert syncer.calendar_owned_only is True  # Default: only owned calendars
        assert syncer.email_enabled is True
        assert syncer.email_lookback_hours == 24
        assert syncer.email_max_per_sync == 50
        assert syncer.email_query == "is:inbox"

    def test_custom_config(self) -> None:
        """Should use custom config values when specified."""
        config = {
            "calendar": {
                "enabled": False,
                "lookback_days": 14,
                "lookahead_days": 30,
                "sync_all_calendars": False,
                "owned_only": False,
            },
            "email": {
                "enabled": True,
                "lookback_hours": 48,
                "max_per_sync": 100,
                "query": "is:unread",
            },
        }
        syncer = Syncer(name="syncer", config=config)

        assert syncer.calendar_enabled is False
        assert syncer.calendar_lookback_days == 14
        assert syncer.calendar_lookahead_days == 30
        assert syncer.calendar_sync_all is False
        assert syncer.calendar_owned_only is False
        assert syncer.email_enabled is True
        assert syncer.email_lookback_hours == 48
        assert syncer.email_max_per_sync == 100
        assert syncer.email_query == "is:unread"


class TestProcessSyncQueue:
    """Test suite for the main sync queue processing."""

    @pytest.fixture
    def mock_google_bridge(self) -> Mock:
        """Create a mock GoogleWorkspaceBridge."""
        mock = Mock()
        mock.list_events = AsyncMock(return_value=[])
        mock.search_emails = AsyncMock(return_value=[])
        return mock

    @pytest.fixture
    def mock_graphiti(self) -> Mock:
        """Create a mock GraphitiClient."""
        mock = Mock()
        mock.add_episode = AsyncMock()
        return mock

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_read = AsyncMock(return_value=[])
        mock.execute_write = AsyncMock(return_value=[])
        return mock

    @pytest.fixture
    def syncer(self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock) -> Syncer:
        """Create a Syncer instance with mocked dependencies."""
        return Syncer(
            name="syncer",
            config={
                "calendar": {"enabled": True, "lookback_days": 7},
                "email": {"enabled": True, "lookback_hours": 24},
            },
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

    @pytest.mark.asyncio
    async def test_process_sync_queue_returns_results(self, syncer: Syncer) -> None:
        """Should return sync results with counts."""
        result = await syncer.process_sync_queue(trace_id="test-trace-001")

        assert "emails_synced" in result
        assert "events_synced" in result
        assert "errors" in result
        assert isinstance(result["errors"], list)

    @pytest.mark.asyncio
    async def test_process_sync_queue_no_google_bridge(self) -> None:
        """Should return error when GoogleWorkspaceBridge not configured."""
        syncer = Syncer(name="syncer", google_bridge=None)

        result = await syncer.process_sync_queue(trace_id="test-trace-002")

        assert len(result["errors"]) > 0
        assert "GoogleWorkspaceBridge not configured" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_sync_disabled_calendar(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should skip calendar sync when disabled."""
        syncer = Syncer(
            name="syncer",
            config={"calendar": {"enabled": False}, "email": {"enabled": False}},
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        await syncer.process_sync_queue(trace_id="test-trace-003")

        mock_google_bridge.list_events.assert_not_called()
        mock_google_bridge.search_emails.assert_not_called()


class TestSyncCalendar:
    """Test suite for calendar sync."""

    @pytest.fixture
    def mock_google_bridge(self) -> Mock:
        """Create a mock GoogleWorkspaceBridge."""
        mock = Mock()
        mock.list_events = AsyncMock()
        mock.list_events_from_all_calendars = AsyncMock()
        return mock

    @pytest.fixture
    def mock_graphiti(self) -> Mock:
        """Create a mock GraphitiClient."""
        mock = Mock()
        mock.add_episode = AsyncMock()
        return mock

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_read = AsyncMock(return_value=[])
        mock.execute_write = AsyncMock(return_value=[])
        return mock

    @pytest.mark.asyncio
    async def test_sync_calendar_ingests_events_from_all_calendars(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should ingest calendar events from all calendars via Graphiti (default mode)."""
        event = MockCalendarEvent(
            id="event-001",
            title="Team Standup",
            attendees=["alice@example.com", "bob@example.com"],
            calendar_id="work@example.com",
            calendar_name="Work Calendar",
        )
        mock_google_bridge.list_events_from_all_calendars.return_value = [event]

        syncer = Syncer(
            name="syncer",
            config={"calendar": {"enabled": True, "sync_all_calendars": True}},
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        count = await syncer.sync_calendar(trace_id="test-trace-004")

        assert count == 1
        mock_google_bridge.list_events_from_all_calendars.assert_called_once()
        mock_graphiti.add_episode.assert_called_once()
        call_kwargs = mock_graphiti.add_episode.call_args.kwargs
        assert call_kwargs["source"] == "calendar"
        assert "Team Standup" in call_kwargs["content"]
        assert "Work Calendar" in call_kwargs["content"]

    @pytest.mark.asyncio
    async def test_sync_calendar_primary_only(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should sync only from primary calendar when sync_all_calendars is False."""
        event = MockCalendarEvent(
            id="event-001",
            title="Team Standup",
            attendees=["alice@example.com"],
        )
        mock_google_bridge.list_events.return_value = [event]

        syncer = Syncer(
            name="syncer",
            config={"calendar": {"enabled": True, "sync_all_calendars": False}},
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        count = await syncer.sync_calendar(trace_id="test-trace-primary")

        assert count == 1
        mock_google_bridge.list_events.assert_called_once()
        mock_google_bridge.list_events_from_all_calendars.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_calendar_includes_calendar_id_in_node(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should include calendar_id and calendar_name in created nodes."""
        event = MockCalendarEvent(
            id="event-multi-001",
            title="Multi-Calendar Event",
            calendar_id="personal@example.com",
            calendar_name="Personal",
            attendees=["friend@example.com"],
        )
        mock_google_bridge.list_events_from_all_calendars.return_value = [event]

        syncer = Syncer(
            name="syncer",
            config={"calendar": {"enabled": True, "sync_all_calendars": True}},
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        await syncer.sync_calendar(trace_id="test-trace-multi")

        # Check that execute_write was called with calendar_id and calendar_name
        write_calls = mock_neo4j.execute_write.call_args_list
        # First call should be creating the CalendarEvent node
        create_call = write_calls[0]
        params = create_call.kwargs.get("parameters") or create_call.args[1]
        assert params["calendar_id"] == "personal@example.com"
        assert params["calendar_name"] == "Personal"
        # external_id should be composite: calendar_id:event_id
        assert params["external_id"] == "personal@example.com:event-multi-001"

    @pytest.mark.asyncio
    async def test_sync_calendar_empty_list(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should handle empty event list gracefully."""
        mock_google_bridge.list_events_from_all_calendars.return_value = []

        syncer = Syncer(
            name="syncer",
            config={"calendar": {"enabled": True, "sync_all_calendars": True}},
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        count = await syncer.sync_calendar(trace_id="test-trace-005")

        assert count == 0
        mock_graphiti.add_episode.assert_not_called()


class TestCalendarFiltering:
    """Test suite for calendar event filtering."""

    def test_should_filter_home_office(self) -> None:
        """Should filter out Home Office events."""
        config = {
            "calendar": {
                "filter": {"blocked_title_patterns": ["^Home Office$", "^OOO", "^Focus Time"]}
            }
        }
        syncer = Syncer(name="syncer", config=config)

        assert syncer._should_filter_event("Home Office") is True
        assert syncer._should_filter_event("OOO - Vacation") is True
        assert syncer._should_filter_event("Focus Time") is True
        assert syncer._should_filter_event("Team Meeting") is False
        assert syncer._should_filter_event("My Home Office Setup") is False  # Doesn't match ^$

    def test_should_filter_case_insensitive(self) -> None:
        """Should filter events case-insensitively."""
        config = {"calendar": {"filter": {"blocked_title_patterns": ["^Home Office$", "^OOO"]}}}
        syncer = Syncer(name="syncer", config=config)

        assert syncer._should_filter_event("HOME OFFICE") is True
        assert syncer._should_filter_event("home office") is True
        assert syncer._should_filter_event("OOO") is True
        assert syncer._should_filter_event("ooo - sick") is True

    def test_no_filter_patterns(self) -> None:
        """Should not filter when no patterns configured."""
        syncer = Syncer(name="syncer", config={})

        assert syncer._should_filter_event("Home Office") is False
        assert syncer._should_filter_event("OOO") is False

    @pytest.mark.asyncio
    async def test_sync_calendar_filters_status_events(self) -> None:
        """Should filter out status events during sync."""
        mock_google_bridge = Mock()
        mock_google_bridge.list_events_from_all_calendars = AsyncMock(
            return_value=[
                MockCalendarEvent(
                    id="event-1",
                    title="Team Meeting",
                    attendees=["alice@example.com"],
                ),
                MockCalendarEvent(
                    id="event-2",
                    title="Home Office",
                ),
                MockCalendarEvent(
                    id="event-3",
                    title="OOO - Vacation",
                ),
            ]
        )
        mock_graphiti = Mock()
        mock_graphiti.add_episode = AsyncMock()
        mock_neo4j = Mock()
        mock_neo4j.execute_read = AsyncMock(return_value=[])
        mock_neo4j.execute_write = AsyncMock(return_value=[])

        syncer = Syncer(
            name="syncer",
            config={
                "calendar": {
                    "enabled": True,
                    "sync_all_calendars": True,
                    "sync_deletions": False,
                    "filter": {"blocked_title_patterns": ["^Home Office$", "^OOO"]},
                }
            },
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        count = await syncer.sync_calendar(trace_id="test-filter")

        # Only "Team Meeting" should be synced
        assert count == 1
        # Graphiti should only be called for the Team Meeting
        mock_graphiti.add_episode.assert_called_once()
        call_kwargs = mock_graphiti.add_episode.call_args.kwargs
        assert "Team Meeting" in call_kwargs["content"]


class TestCalendarDeletionSync:
    """Test suite for calendar deletion sync."""

    @pytest.fixture
    def mock_google_bridge(self) -> Mock:
        """Create a mock GoogleWorkspaceBridge."""
        mock = Mock()
        mock.list_events_from_all_calendars = AsyncMock()
        return mock

    @pytest.fixture
    def mock_graphiti(self) -> Mock:
        """Create a mock GraphitiClient."""
        mock = Mock()
        mock.add_episode = AsyncMock()
        return mock

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_read = AsyncMock(return_value=[])
        mock.execute_write = AsyncMock(return_value=[])
        return mock

    @pytest.mark.asyncio
    async def test_deletion_sync_removes_orphaned_events(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should delete CalendarEvent nodes that no longer exist in Google Calendar."""
        # Current events from Google Calendar
        mock_google_bridge.list_events_from_all_calendars.return_value = [
            MockCalendarEvent(
                id="event-1",
                title="Existing Meeting",
                attendees=["alice@example.com"],
            ),
        ]

        # Existing events in the graph (includes one that no longer exists)
        mock_neo4j.execute_read.return_value = [
            {"external_id": "primary:event-1"},
            {"external_id": "primary:event-deleted"},  # This one was deleted from Calendar
        ]

        syncer = Syncer(
            name="syncer",
            config={
                "calendar": {
                    "enabled": True,
                    "sync_all_calendars": True,
                    "sync_deletions": True,
                }
            },
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        await syncer.sync_calendar(trace_id="test-deletion")

        # Should have called execute_write to delete the orphaned event
        write_calls = mock_neo4j.execute_write.call_args_list
        delete_calls = [c for c in write_calls if "DETACH DELETE" in str(c.args[0])]
        assert len(delete_calls) == 1
        assert delete_calls[0].args[1]["external_id"] == "primary:event-deleted"

    @pytest.mark.asyncio
    async def test_deletion_sync_disabled(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should not delete events when sync_deletions is disabled."""
        mock_google_bridge.list_events_from_all_calendars.return_value = []
        mock_neo4j.execute_read.return_value = [
            {"external_id": "primary:event-orphaned"},
        ]

        syncer = Syncer(
            name="syncer",
            config={
                "calendar": {
                    "enabled": True,
                    "sync_all_calendars": True,
                    "sync_deletions": False,
                }
            },
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        await syncer.sync_calendar(trace_id="test-no-deletion")

        # Should not have called execute_write to delete anything
        write_calls = mock_neo4j.execute_write.call_args_list
        delete_calls = [
            c for c in write_calls if "DETACH DELETE" in str(c.args[0] if c.args else "")
        ]
        assert len(delete_calls) == 0


class TestSyncEmails:
    """Test suite for email sync."""

    @pytest.fixture
    def mock_google_bridge(self) -> Mock:
        """Create a mock GoogleWorkspaceBridge."""
        mock = Mock()
        mock.search_emails = AsyncMock()
        return mock

    @pytest.fixture
    def mock_graphiti(self) -> Mock:
        """Create a mock GraphitiClient."""
        mock = Mock()
        mock.add_episode = AsyncMock()
        return mock

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_read = AsyncMock(return_value=[])
        mock.execute_write = AsyncMock(return_value=[])
        return mock

    @pytest.mark.asyncio
    async def test_sync_emails_creates_nodes(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should create Email nodes and link to Person nodes."""
        email = MockEmailMessage(
            id="email-001",
            subject="Project Update",
            sender="Alice Smith <alice@example.com>",
            recipient="bob@example.com",
        )
        mock_google_bridge.search_emails.return_value = [email]

        syncer = Syncer(
            name="syncer",
            config={"email": {"enabled": True}},
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        count = await syncer.sync_emails(trace_id="test-trace-006")

        assert count == 1
        # Should have multiple write calls: create email, link sender, link recipient, link day
        assert mock_neo4j.execute_write.call_count >= 3

    @pytest.mark.asyncio
    async def test_sync_emails_skips_duplicates(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should skip emails that are already synced."""
        email = MockEmailMessage(id="email-dup-001")
        mock_google_bridge.search_emails.return_value = [email]
        # Simulate email already exists
        mock_neo4j.execute_read.return_value = [{"exists": True}]

        syncer = Syncer(
            name="syncer",
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        count = await syncer.sync_emails(trace_id="test-trace-007")

        assert count == 0

    @pytest.mark.asyncio
    async def test_sync_emails_extracts_entities(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should extract entities from email body via Graphiti."""
        email = MockEmailMessage(
            id="email-002",
            subject="Meeting Notes",
            body="Discussed the Q1 roadmap with Sarah from Acme Corp.",
        )
        mock_google_bridge.search_emails.return_value = [email]

        syncer = Syncer(
            name="syncer",
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        await syncer.sync_emails(trace_id="test-trace-008")

        # Graphiti should be called for entity extraction
        mock_graphiti.add_episode.assert_called_once()
        call_kwargs = mock_graphiti.add_episode.call_args.kwargs
        assert call_kwargs["source"] == "email"


class TestFormatMethods:
    """Test suite for formatting methods."""

    def test_format_calendar_event_basic(self) -> None:
        """Should format basic calendar event."""
        syncer = Syncer(name="syncer")
        event = MockCalendarEvent(
            title="Team Meeting",
            start=datetime(2024, 1, 15, 10, 0, tzinfo=UTC),
            end=datetime(2024, 1, 15, 11, 0, tzinfo=UTC),
        )

        result = syncer._format_calendar_event(event)

        assert "Team Meeting" in result
        assert "January 15, 2024" in result

    def test_format_calendar_event_with_attendees(self) -> None:
        """Should include attendees in formatted output."""
        syncer = Syncer(name="syncer")
        event = MockCalendarEvent(
            title="Planning Session",
            attendees=["alice@example.com", "bob@example.com"],
        )

        result = syncer._format_calendar_event(event)

        assert "Attendees:" in result
        assert "alice@example.com" in result
        assert "bob@example.com" in result

    def test_format_calendar_event_with_calendar_name(self) -> None:
        """Should include calendar name in formatted output."""
        syncer = Syncer(name="syncer")
        event = MockCalendarEvent(
            title="Work Meeting",
            calendar_id="work@example.com",
            calendar_name="Work Calendar",
            attendees=["colleague@example.com"],
        )

        result = syncer._format_calendar_event(event)

        assert "Calendar: Work Calendar" in result
        assert "Work Meeting" in result

    def test_format_email_basic(self) -> None:
        """Should format basic email message."""
        syncer = Syncer(name="syncer")
        email = MockEmailMessage(
            subject="Important Update",
            sender="Jane <jane@example.com>",
        )

        result = syncer._format_email(email)

        assert "Important Update" in result
        assert "jane@example.com" in result

    def test_format_email_truncates_long_body(self) -> None:
        """Should truncate body over 2000 characters."""
        syncer = Syncer(name="syncer")
        long_body = "x" * 3000
        email = MockEmailMessage(subject="Long Email", body=long_body)

        result = syncer._format_email(email)

        # Body should be truncated with "..."
        assert len(result) < len(long_body) + 200  # Allow for formatting overhead
        assert "..." in result


class TestParseEmailAddress:
    """Test suite for email address parsing."""

    def test_parse_with_name(self) -> None:
        """Should parse name and email from 'Name <email>' format."""
        syncer = Syncer(name="syncer")

        name, email = syncer._parse_email_address("John Doe <john@example.com>")

        assert name == "John Doe"
        assert email == "john@example.com"

    def test_parse_plain_email(self) -> None:
        """Should handle plain email address."""
        syncer = Syncer(name="syncer")

        name, email = syncer._parse_email_address("john@example.com")

        assert name == "john@example.com"
        assert email == "john@example.com"

    def test_parse_empty_name(self) -> None:
        """Should handle empty name before angle brackets."""
        syncer = Syncer(name="syncer")

        name, email = syncer._parse_email_address("<john@example.com>")

        assert name == "john@example.com"  # Falls back to email
        assert email == "john@example.com"


class TestProcessMessage:
    """Test suite for agent message processing."""

    @pytest.fixture
    def mock_google_bridge(self) -> Mock:
        """Create a mock GoogleWorkspaceBridge."""
        mock = Mock()
        mock.list_events = AsyncMock(return_value=[])
        mock.search_emails = AsyncMock(return_value=[])
        return mock

    @pytest.fixture
    def mock_graphiti(self) -> Mock:
        """Create a mock GraphitiClient."""
        mock = Mock()
        mock.add_episode = AsyncMock()
        return mock

    @pytest.fixture
    def mock_neo4j(self) -> Mock:
        """Create a mock Neo4jClient."""
        mock = Mock()
        mock.execute_read = AsyncMock(return_value=[])
        mock.execute_write = AsyncMock(return_value=[])
        return mock

    @pytest.mark.asyncio
    async def test_process_sync_now_intent(
        self, mock_google_bridge: Mock, mock_graphiti: Mock, mock_neo4j: Mock
    ) -> None:
        """Should handle SYNC_NOW intent."""
        syncer = Syncer(
            name="syncer",
            google_bridge=mock_google_bridge,
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )

        msg = AgentMessage(
            trace_id="test-trace-009",
            source_agent="orchestrator",
            target_agent="syncer",
            intent="SYNC_NOW",
            payload={},
        )

        response = await syncer.process_message(msg)

        assert response is not None
        assert response.intent == "SYNC_RESULT"
        assert response.target_agent == "orchestrator"

    @pytest.mark.asyncio
    async def test_process_unknown_intent(self) -> None:
        """Should return None for unknown intents."""
        syncer = Syncer(name="syncer")

        msg = AgentMessage(
            trace_id="test-trace-010",
            source_agent="orchestrator",
            target_agent="syncer",
            intent="UNKNOWN_INTENT",
            payload={},
        )

        response = await syncer.process_message(msg)

        assert response is None
