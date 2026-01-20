"""
Unit tests for Google Workspace Bridge.

Tests the bridge interface using direct Google API calls.
Uses mocking for Google API services to test parsing and error handling logic.
"""

import base64
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from klabautermann.core.exceptions import ExternalServiceError
from klabautermann.mcp.google_workspace import (
    GoogleWorkspaceBridge,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_credentials():
    """Create mock Google credentials."""
    with patch("klabautermann.mcp.google_workspace.Credentials") as mock_creds_class:
        mock_creds = MagicMock()
        mock_creds.token = "mock_access_token"
        mock_creds.refresh = MagicMock()
        mock_creds_class.return_value = mock_creds
        yield mock_creds_class


@pytest.fixture
def mock_gmail_service():
    """Create mock Gmail service."""
    service = MagicMock()
    return service


@pytest.fixture
def mock_calendar_service():
    """Create mock Calendar service."""
    service = MagicMock()
    return service


@pytest.fixture
def mock_build(mock_gmail_service, mock_calendar_service):
    """Mock googleapiclient.discovery.build."""
    with patch("klabautermann.mcp.google_workspace.build") as mock_build_fn:

        def build_side_effect(api, version, credentials=None):
            if api == "gmail":
                return mock_gmail_service
            elif api == "calendar":
                return mock_calendar_service
            return MagicMock()

        mock_build_fn.side_effect = build_side_effect
        yield mock_build_fn


@pytest.fixture
def mock_env():
    """Mock environment variables for Google OAuth."""
    env_vars = {
        "GOOGLE_CLIENT_ID": "test_client_id",
        "GOOGLE_CLIENT_SECRET": "test_client_secret",
        "GOOGLE_REFRESH_TOKEN": "test_refresh_token",
    }
    with patch.dict("os.environ", env_vars):
        yield env_vars


@pytest.fixture
async def bridge(mock_env, mock_credentials, mock_build, mock_gmail_service, mock_calendar_service):
    """Create a GoogleWorkspaceBridge with mocked services."""
    bridge = GoogleWorkspaceBridge()
    # Pre-start to inject mocks
    await bridge.start()
    return bridge


# ===========================================================================
# Email Tests
# ===========================================================================


class TestEmailOperations:
    """Test Gmail operations."""

    @pytest.mark.asyncio
    async def test_search_emails_success(self, bridge, mock_gmail_service):
        """Test successful email search."""
        # Setup mock Gmail API responses
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}, {"id": "msg2"}]
        }

        # Mock individual message fetches
        def get_message(userId, id, format):
            messages_data = {
                "msg1": {
                    "id": "msg1",
                    "threadId": "thread1",
                    "snippet": "This is a test",
                    "labelIds": ["UNREAD"],
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Test Email"},
                            {"name": "From", "value": "sender@example.com"},
                            {"name": "To", "value": "recipient@example.com"},
                            {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                        ],
                        "body": {"data": base64.urlsafe_b64encode(b"Test body").decode()},
                    },
                },
                "msg2": {
                    "id": "msg2",
                    "threadId": "thread2",
                    "snippet": "Another test",
                    "labelIds": [],
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Another Email"},
                            {"name": "From", "value": "other@example.com"},
                            {"name": "Date", "value": "Mon, 15 Jan 2024 11:00:00 +0000"},
                        ],
                    },
                },
            }
            mock_result = MagicMock()
            mock_result.execute.return_value = messages_data.get(id, {})
            return mock_result

        mock_gmail_service.users.return_value.messages.return_value.get.side_effect = (
            lambda userId, id, format: get_message(userId, id, format)
        )

        # Execute search
        emails = await bridge.search_emails("from:sender@example.com")

        # Verify
        assert len(emails) == 2
        assert emails[0].id == "msg1"
        assert emails[0].subject == "Test Email"
        assert emails[0].sender == "sender@example.com"
        assert emails[0].is_unread is True
        assert emails[1].is_unread is False

    @pytest.mark.asyncio
    async def test_search_emails_empty_result(self, bridge, mock_gmail_service):
        """Test email search with no results."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }

        emails = await bridge.search_emails("from:nobody@example.com")

        assert len(emails) == 0

    @pytest.mark.asyncio
    async def test_search_emails_malformed_date(self, bridge, mock_gmail_service):
        """Test email search handles malformed date gracefully."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}]
        }
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Test",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "invalid-date"},
                ],
            },
        }

        emails = await bridge.search_emails("test")

        # Should parse successfully with default date
        assert len(emails) == 1
        assert isinstance(emails[0].date, datetime)

    @pytest.mark.asyncio
    async def test_search_emails_error(self, bridge, mock_gmail_service):
        """Test email search handles errors."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 500
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.side_effect = HttpError(
            mock_response, b"Server error"
        )

        with pytest.raises(ExternalServiceError, match="Search failed"):
            await bridge.search_emails("test")

    @pytest.mark.asyncio
    async def test_send_email_success(self, bridge, mock_gmail_service):
        """Test successful email sending."""
        mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "msg123",
            "threadId": "thread123",
        }

        result = await bridge.send_email(
            to="recipient@example.com",
            subject="Test Subject",
            body="Test Body",
        )

        assert result.success is True
        assert result.message_id == "msg123"
        assert result.is_draft is False
        assert result.error is None

    @pytest.mark.asyncio
    async def test_send_email_draft_mode(self, bridge, mock_gmail_service):
        """Test email draft creation."""
        mock_gmail_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
            "id": "draft123"
        }

        result = await bridge.send_email(
            to="recipient@example.com",
            subject="Draft Subject",
            body="Draft Body",
            draft_only=True,
        )

        assert result.success is True
        assert result.is_draft is True

    @pytest.mark.asyncio
    async def test_send_email_with_cc(self, bridge, mock_gmail_service):
        """Test email sending with CC."""
        mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "msg123"
        }

        result = await bridge.send_email(
            to="recipient@example.com",
            subject="Test",
            body="Test",
            cc="cc1@example.com,cc2@example.com",
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_email_error(self, bridge, mock_gmail_service):
        """Test email sending handles errors gracefully."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 500
        mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.side_effect = HttpError(
            mock_response, b"Send failed"
        )

        result = await bridge.send_email(
            to="recipient@example.com",
            subject="Test",
            body="Test",
        )

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_get_recent_emails(self, bridge, mock_gmail_service):
        """Test getting recent emails."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}]
        }
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Recent email",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Recent"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
            },
        }

        emails = await bridge.get_recent_emails(hours=24)

        assert len(emails) == 1


# ===========================================================================
# Calendar Tests
# ===========================================================================


class TestCalendarOperations:
    """Test Google Calendar operations."""

    @pytest.mark.asyncio
    async def test_list_events_success(self, bridge, mock_calendar_service):
        """Test successful event listing."""
        start_time = datetime(2024, 1, 15, 10, 0)
        end_time = datetime(2024, 1, 15, 11, 0)

        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "event1",
                    "summary": "Team Meeting",
                    "start": {"dateTime": start_time.isoformat() + "Z"},
                    "end": {"dateTime": end_time.isoformat() + "Z"},
                    "location": "Conference Room A",
                    "description": "Weekly sync",
                    "attendees": [
                        {"email": "alice@example.com"},
                        {"email": "bob@example.com"},
                    ],
                }
            ]
        }

        events = await bridge.list_events(
            start=datetime(2024, 1, 15),
            end=datetime(2024, 1, 16),
        )

        assert len(events) == 1
        assert events[0].id == "event1"
        assert events[0].title == "Team Meeting"
        assert events[0].location == "Conference Room A"
        assert len(events[0].attendees) == 2
        assert "alice@example.com" in events[0].attendees

    @pytest.mark.asyncio
    async def test_list_events_all_day(self, bridge, mock_calendar_service):
        """Test listing all-day events."""
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "event1",
                    "summary": "Holiday",
                    "start": {"date": "2024-01-15"},
                    "end": {"date": "2024-01-16"},
                }
            ]
        }

        events = await bridge.list_events()

        assert len(events) == 1
        assert events[0].title == "Holiday"
        # Date-only events should parse successfully
        assert isinstance(events[0].start, datetime)

    @pytest.mark.asyncio
    async def test_list_events_default_range(self, bridge, mock_calendar_service):
        """Test listing events with default time range."""
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        await bridge.list_events()

        # Verify list was called
        mock_calendar_service.events.return_value.list.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_events_error(self, bridge, mock_calendar_service):
        """Test event listing handles errors."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 500
        mock_calendar_service.events.return_value.list.return_value.execute.side_effect = HttpError(
            mock_response, b"Calendar error"
        )

        with pytest.raises(ExternalServiceError, match="List failed"):
            await bridge.list_events()

    @pytest.mark.asyncio
    async def test_create_event_success(self, bridge, mock_calendar_service):
        """Test successful event creation."""
        start = datetime(2024, 1, 15, 14, 0)
        end = datetime(2024, 1, 15, 15, 0)

        mock_calendar_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "event123",
            "htmlLink": "https://calendar.google.com/event?eid=event123",
        }

        result = await bridge.create_event(
            title="Team Standup",
            start=start,
            end=end,
            description="Daily standup meeting",
            location="Zoom",
            attendees=["alice@example.com", "bob@example.com"],
        )

        assert result.success is True
        assert result.event_id == "event123"
        assert result.event_link is not None
        assert result.error is None

    @pytest.mark.asyncio
    async def test_create_event_minimal(self, bridge, mock_calendar_service):
        """Test event creation with minimal fields."""
        start = datetime(2024, 1, 15, 14, 0)
        end = datetime(2024, 1, 15, 15, 0)

        mock_calendar_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "event123"
        }

        result = await bridge.create_event(
            title="Quick Meeting",
            start=start,
            end=end,
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_create_event_error(self, bridge, mock_calendar_service):
        """Test event creation handles errors gracefully."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 500
        mock_calendar_service.events.return_value.insert.return_value.execute.side_effect = (
            HttpError(mock_response, b"Creation failed")
        )

        result = await bridge.create_event(
            title="Meeting",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1),
        )

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_get_todays_events(self, bridge, mock_calendar_service):
        """Test getting today's events."""
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        await bridge.get_todays_events()

        # Verify list was called
        mock_calendar_service.events.return_value.list.assert_called()

    @pytest.mark.asyncio
    async def test_get_tomorrows_events(self, bridge, mock_calendar_service):
        """Test getting tomorrow's events."""
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        await bridge.get_tomorrows_events()

        # Verify list was called
        mock_calendar_service.events.return_value.list.assert_called()


# ===========================================================================
# Lifecycle Tests
# ===========================================================================


class TestBridgeLifecycle:
    """Test bridge initialization and lifecycle."""

    @pytest.mark.asyncio
    async def test_start_initializes_services(self, mock_env, mock_credentials, mock_build):
        """Test starting initializes Google API services."""
        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        assert bridge._started is True
        # Verify build was called for both services
        assert mock_build.call_count == 2

    @pytest.mark.asyncio
    async def test_start_idempotent(self, mock_env, mock_credentials, mock_build):
        """Test starting multiple times is safe."""
        bridge = GoogleWorkspaceBridge()
        await bridge.start()
        await bridge.start()

        # Services should only be built once
        assert mock_build.call_count == 2  # gmail + calendar

    @pytest.mark.asyncio
    async def test_stop_clears_state(self, mock_env, mock_credentials, mock_build):
        """Test stopping clears state."""
        bridge = GoogleWorkspaceBridge()
        await bridge.start()
        await bridge.stop()

        assert bridge._started is False
        assert bridge._gmail_service is None
        assert bridge._calendar_service is None

    @pytest.mark.asyncio
    async def test_auto_start_on_operation(
        self, mock_env, mock_credentials, mock_build, mock_gmail_service
    ):
        """Test that operations auto-start the services."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }

        bridge = GoogleWorkspaceBridge()
        # Don't manually start
        await bridge.search_emails("test")

        # Services should have auto-started
        assert bridge._started is True

    @pytest.mark.asyncio
    async def test_missing_credentials_error(self):
        """Test error when credentials are missing."""
        with patch.dict("os.environ", {}, clear=True):
            bridge = GoogleWorkspaceBridge()
            with pytest.raises(ExternalServiceError, match="Missing required environment"):
                await bridge.start()


# ===========================================================================
# Parsing Tests
# ===========================================================================


class TestResponseParsing:
    """Test response parsing and validation."""

    @pytest.mark.asyncio
    async def test_parse_email_missing_fields(self, bridge, mock_gmail_service):
        """Test parsing emails with missing optional fields."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}]
        }
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "payload": {"headers": []},
        }

        emails = await bridge.search_emails("test")

        assert len(emails) == 1
        assert emails[0].subject == "(no subject)"
        assert emails[0].sender == "unknown"

    @pytest.mark.asyncio
    async def test_parse_event_missing_fields(self, bridge, mock_calendar_service):
        """Test parsing events with missing optional fields."""
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "event1",
                    "start": {"dateTime": datetime.now().isoformat() + "Z"},
                    "end": {"dateTime": (datetime.now() + timedelta(hours=1)).isoformat() + "Z"},
                    # Missing summary, location, etc.
                }
            ]
        }

        events = await bridge.list_events()

        assert len(events) == 1
        assert events[0].title == "(no title)"
        assert events[0].location is None
        assert len(events[0].attendees) == 0


# ===========================================================================
# OAuth Refresh Tests
# ===========================================================================


class TestOAuthRefresh:
    """Test OAuth token refresh handling."""

    @pytest.mark.asyncio
    async def test_401_triggers_refresh(
        self, mock_env, mock_credentials, mock_build, mock_gmail_service
    ):
        """Test that 401 error triggers token refresh and retries."""
        from googleapiclient.errors import HttpError

        # First call raises 401, second succeeds
        mock_response = MagicMock()
        mock_response.status = 401
        mock_response.reason = "Unauthorized"

        call_count = [0]

        def side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                raise HttpError(mock_response, b"Token expired")
            return {"messages": []}

        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.side_effect = side_effect

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        # Should succeed after refresh
        result = await bridge.search_emails("test")

        assert result == []
        # Verify refresh was called
        assert mock_credentials.return_value.refresh.call_count >= 1

    @pytest.mark.asyncio
    async def test_refresh_retries_operation(
        self, mock_env, mock_credentials, mock_build, mock_gmail_service
    ):
        """Test that failed operation is retried after token refresh."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 401
        mock_response.reason = "Unauthorized"

        # Succeed on second try
        first_call = True

        def list_side_effect():
            nonlocal first_call
            if first_call:
                first_call = False
                raise HttpError(mock_response, b"Token expired")
            return {"messages": [{"id": "msg1"}]}

        def get_side_effect(userId, id, format):
            return MagicMock(
                execute=MagicMock(
                    return_value={
                        "id": id,
                        "threadId": "thread1",
                        "snippet": "test",
                        "payload": {
                            "headers": [
                                {"name": "Subject", "value": "Test"},
                                {"name": "From", "value": "test@test.com"},
                                {"name": "Date", "value": "Mon, 01 Jan 2024 00:00:00 +0000"},
                            ]
                        },
                    }
                )
            )

        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.side_effect = list_side_effect
        mock_gmail_service.users.return_value.messages.return_value.get.side_effect = (
            get_side_effect
        )

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        emails = await bridge.search_emails("test")

        assert len(emails) == 1
        assert emails[0].id == "msg1"

    @pytest.mark.asyncio
    async def test_invalid_grant_raises_error(self, mock_env, mock_build, mock_gmail_service):
        """Test that invalid_grant error raises ExternalServiceError."""
        import google.auth.exceptions

        with patch("klabautermann.mcp.google_workspace.Credentials") as mock_creds_class:
            mock_creds = MagicMock()
            mock_creds.token = "mock_token"

            def raise_invalid_grant(_):
                raise google.auth.exceptions.RefreshError("invalid_grant: Token has been revoked")

            mock_creds.refresh.side_effect = raise_invalid_grant
            mock_creds_class.return_value = mock_creds

            bridge = GoogleWorkspaceBridge()

            with pytest.raises(ExternalServiceError, match="Failed to refresh credentials"):
                await bridge.start()

    @pytest.mark.asyncio
    async def test_non_401_error_not_retried(
        self, mock_env, mock_credentials, mock_build, mock_gmail_service
    ):
        """Test that non-401 errors are not retried."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.reason = "Internal Server Error"

        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.side_effect = HttpError(
            mock_response, b"Server error"
        )

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        with pytest.raises(ExternalServiceError, match="Search failed"):
            await bridge.search_emails("test")


# ===========================================================================
# Rate Limiting Tests
# ===========================================================================


class TestRateLimiting:
    """Test API rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limiter_initialization(self, mock_env, mock_credentials, mock_build):
        """Test that rate limiters are initialized with correct config."""
        bridge = GoogleWorkspaceBridge(
            gmail_requests_per_minute=30,
            calendar_requests_per_minute=20,
            max_concurrent_requests=5,
        )

        assert bridge._gmail_limiter.config.max_requests == 30
        assert bridge._calendar_limiter.config.max_requests == 20

    @pytest.mark.asyncio
    async def test_rate_limiting_disabled(
        self, mock_env, mock_credentials, mock_build, mock_gmail_service
    ):
        """Test that rate limiting can be disabled."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }

        bridge = GoogleWorkspaceBridge(rate_limiting_enabled=False)
        await bridge.start()

        # Should work without rate limiting
        for _ in range(100):
            await bridge.search_emails("test")

        # Gmail limiter should show full remaining (disabled)
        assert bridge._gmail_limiter.config.enabled is False

    @pytest.mark.asyncio
    async def test_separate_gmail_calendar_limits(
        self, mock_env, mock_credentials, mock_build, mock_gmail_service, mock_calendar_service
    ):
        """Test that Gmail and Calendar have separate rate limits."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        bridge = GoogleWorkspaceBridge(
            gmail_requests_per_minute=5,
            calendar_requests_per_minute=5,
            rate_limiting_enabled=True,
        )
        await bridge.start()

        # Make some Gmail calls
        for _ in range(3):
            await bridge.search_emails("test")

        # Gmail should have 2 remaining, Calendar should have 5
        gmail_remaining = bridge._gmail_limiter.get_remaining("gmail")
        calendar_remaining = bridge._calendar_limiter.get_remaining("calendar")

        assert gmail_remaining == 2
        assert calendar_remaining == 5

    @pytest.mark.asyncio
    async def test_429_response_backoff(
        self, mock_env, mock_credentials, mock_build, mock_gmail_service
    ):
        """Test that 429 responses trigger backoff and retry."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 429
        mock_response.reason = "Too Many Requests"
        mock_response.get.return_value = "1"  # Retry-After: 1 second

        call_count = [0]

        def side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                raise HttpError(mock_response, b"Rate limit exceeded")
            return {"messages": []}

        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.side_effect = side_effect

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        # Should succeed after retry
        result = await bridge.search_emails("test")

        assert result == []
        assert call_count[0] == 2  # Initial + retry

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(
        self, mock_env, mock_credentials, mock_build, mock_gmail_service
    ):
        """Test that semaphore limits concurrent API calls."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute = (
            MagicMock(side_effect=lambda: {"messages": []})
        )

        bridge = GoogleWorkspaceBridge(max_concurrent_requests=2, rate_limiting_enabled=False)
        await bridge.start()

        # Bridge was started, semaphore should be created
        assert bridge._semaphore._value == 2
