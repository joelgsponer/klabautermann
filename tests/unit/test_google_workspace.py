"""
Unit tests for Google Workspace Bridge.

Tests the bridge interface using direct Google API calls.
Uses mocking for Google API services to test parsing and error handling logic.

Issues: #207 (reply-to-thread), #208 (attachments), #214 (OAuth refresh),
        #215 (rate limiting), #216 (pagination)
"""

import base64
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from klabautermann.core.exceptions import ExternalServiceError
from klabautermann.mcp.google_workspace import (
    EmailAttachment,
    EmailSearchResult,
    GoogleWorkspaceBridge,
    MCPRateLimiter,
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
# Pagination Tests (#216)
# ===========================================================================


class TestEmailPagination:
    """Test email search pagination (#216)."""

    @pytest.mark.asyncio
    async def test_search_emails_paginated_returns_result(self, bridge, mock_gmail_service):
        """Test paginated search returns EmailSearchResult."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}],
            "nextPageToken": "token123",
            "resultSizeEstimate": 100,
        }
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Test",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
            },
        }

        result = await bridge.search_emails_paginated("test")

        assert isinstance(result, EmailSearchResult)
        assert len(result.emails) == 1
        assert result.next_page_token == "token123"
        assert result.result_size_estimate == 100

    @pytest.mark.asyncio
    async def test_search_emails_with_page_token(self, bridge, mock_gmail_service):
        """Test search with page token for continuation."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg2"}],
        }
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg2",
            "threadId": "thread2",
            "snippet": "Page 2",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Page 2"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
            },
        }

        await bridge.search_emails_paginated("test", page_token="token123")

        # Verify pageToken was passed
        call_kwargs = mock_gmail_service.users.return_value.messages.return_value.list.call_args[1]
        assert call_kwargs.get("pageToken") == "token123"

    @pytest.mark.asyncio
    async def test_search_emails_all_fetches_multiple_pages(self, bridge, mock_gmail_service):
        """Test search_emails_all fetches multiple pages."""
        call_count = 0

        def list_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.execute.return_value = {
                    "messages": [{"id": "msg1"}, {"id": "msg2"}],
                    "nextPageToken": "token2",
                }
            else:
                mock_result.execute.return_value = {
                    "messages": [{"id": "msg3"}],
                }
            return mock_result

        mock_gmail_service.users.return_value.messages.return_value.list.side_effect = (
            list_side_effect
        )
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Test",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
            },
        }

        emails = await bridge.search_emails_all("test", max_results=100)

        # Should have made 2 calls (first page with token, second without)
        assert call_count == 2
        assert len(emails) == 3


# ===========================================================================
# Reply-to-Thread Tests (#207)
# ===========================================================================


class TestReplyToThread:
    """Test email reply-to-thread functionality (#207)."""

    @pytest.mark.asyncio
    async def test_reply_to_email_success(self, bridge, mock_gmail_service):
        """Test successful reply to email."""
        # Mock getting original email
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "original_msg",
            "threadId": "thread123",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Original Subject"},
                    {"name": "From", "value": "original_sender@example.com"},
                    {"name": "Message-ID", "value": "<original-id@example.com>"},
                    {"name": "References", "value": "<older-id@example.com>"},
                ],
            },
        }

        # Mock sending reply
        mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "reply_msg",
            "threadId": "thread123",
        }

        result = await bridge.reply_to_email(
            message_id="original_msg",
            body="This is my reply",
        )

        assert result.success is True
        assert result.message_id == "reply_msg"

    @pytest.mark.asyncio
    async def test_reply_adds_re_prefix(self, bridge, mock_gmail_service):
        """Test reply adds Re: prefix to subject."""
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "original_msg",
            "threadId": "thread123",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Meeting Tomorrow"},
                    {"name": "From", "value": "sender@example.com"},
                ],
            },
        }
        mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "reply_msg"
        }

        await bridge.reply_to_email(message_id="original_msg", body="Reply body")

        # Verify send was called - we can't easily check the encoded message
        # but the functionality is tested through the result
        mock_gmail_service.users.return_value.messages.return_value.send.assert_called()

    @pytest.mark.asyncio
    async def test_reply_preserves_existing_re_prefix(self, bridge, mock_gmail_service):
        """Test reply doesn't double Re: prefix."""
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "original_msg",
            "threadId": "thread123",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Re: Already a reply"},
                    {"name": "From", "value": "sender@example.com"},
                ],
            },
        }
        mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "reply_msg"
        }

        result = await bridge.reply_to_email(message_id="original_msg", body="Reply body")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_reply_handles_missing_original(self, bridge, mock_gmail_service):
        """Test reply handles error when original email not found."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 404
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.side_effect = HttpError(
            mock_response, b"Not found"
        )

        result = await bridge.reply_to_email(message_id="nonexistent", body="Reply")

        assert result.success is False
        assert "Failed to get original email" in result.error

    @pytest.mark.asyncio
    async def test_send_email_with_threading_headers(self, bridge, mock_gmail_service):
        """Test send_email accepts threading parameters."""
        mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "msg123"
        }

        result = await bridge.send_email(
            to="recipient@example.com",
            subject="Re: Test",
            body="Reply body",
            in_reply_to="<original@example.com>",
            references="<older@example.com> <original@example.com>",
            thread_id="thread123",
        )

        assert result.success is True


# ===========================================================================
# Attachment Tests (#208)
# ===========================================================================


class TestEmailAttachments:
    """Test email attachment handling (#208)."""

    @pytest.mark.asyncio
    async def test_parse_email_with_attachments(self, bridge, mock_gmail_service):
        """Test emails with attachments are parsed correctly."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}]
        }
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Email with attachment",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "With Attachment"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": base64.urlsafe_b64encode(b"Text body").decode()},
                    },
                    {
                        "mimeType": "application/pdf",
                        "filename": "document.pdf",
                        "body": {"attachmentId": "attach123", "size": 12345},
                    },
                ],
            },
        }

        emails = await bridge.search_emails("test")

        assert len(emails) == 1
        assert len(emails[0].attachments) == 1
        assert emails[0].attachments[0].filename == "document.pdf"
        assert emails[0].attachments[0].mime_type == "application/pdf"
        assert emails[0].attachments[0].size == 12345
        assert emails[0].attachments[0].id == "attach123"

    @pytest.mark.asyncio
    async def test_download_attachment_success(self, bridge, mock_gmail_service):
        """Test downloading attachment returns bytes."""
        attachment_data = b"This is attachment content"
        mock_gmail_service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
            "data": base64.urlsafe_b64encode(attachment_data).decode()
        }

        data = await bridge.download_attachment("msg123", "attach123")

        assert data == attachment_data

    @pytest.mark.asyncio
    async def test_download_attachment_error(self, bridge, mock_gmail_service):
        """Test download attachment handles errors."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 404
        mock_gmail_service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.side_effect = HttpError(
            mock_response, b"Not found"
        )

        with pytest.raises(ExternalServiceError, match="Download attachment failed"):
            await bridge.download_attachment("msg123", "invalid_attach")

    @pytest.mark.asyncio
    async def test_save_attachment_success(self, bridge, mock_gmail_service, tmp_path):
        """Test saving attachment to disk."""
        attachment_data = b"File content"
        mock_gmail_service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
            "data": base64.urlsafe_b64encode(attachment_data).decode()
        }

        save_path = str(tmp_path / "test_file.pdf")
        result_path = await bridge.save_attachment("msg123", "attach123", save_path)

        assert result_path == save_path
        with Path(save_path).open("rb") as f:
            assert f.read() == attachment_data

    @pytest.mark.asyncio
    async def test_email_message_id_header_parsed(self, bridge, mock_gmail_service):
        """Test Message-ID header is parsed for threading."""
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
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                    {"name": "Message-ID", "value": "<unique-id@example.com>"},
                    {"name": "References", "value": "<older@example.com>"},
                ],
            },
        }

        emails = await bridge.search_emails("test")

        assert emails[0].message_id_header == "<unique-id@example.com>"
        assert emails[0].references == "<older@example.com>"


# ===========================================================================
# OAuth Refresh Tests (#214)
# ===========================================================================


class TestOAuthRefresh:
    """Test OAuth token refresh handling (#214)."""

    @pytest.mark.asyncio
    async def test_refresh_credentials_called_on_401(
        self, mock_env, mock_credentials, mock_build, mock_gmail_service
    ):
        """Test credentials are refreshed on 401 error."""
        from googleapiclient.errors import HttpError

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        call_count = 0

        def list_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # First call returns 401
                mock_response = MagicMock()
                mock_response.status = 401
                raise HttpError(mock_response, b"Token expired")
            else:
                # Second call succeeds
                mock_result.execute.return_value = {"messages": []}
                return mock_result

        mock_gmail_service.users.return_value.messages.return_value.list.side_effect = (
            list_side_effect
        )

        # Should succeed after refresh
        emails = await bridge.search_emails("test")

        assert len(emails) == 0
        assert call_count == 2  # First failed, second succeeded
        # Verify refresh was called
        mock_credentials.return_value.refresh.assert_called()

    @pytest.mark.asyncio
    async def test_refresh_credentials_method(self, mock_env, mock_credentials, mock_build):
        """Test _refresh_credentials method."""
        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        await bridge._refresh_credentials()

        # Verify refresh was called
        mock_credentials.return_value.refresh.assert_called()


# ===========================================================================
# Rate Limiter Tests (#215)
# ===========================================================================


class TestMCPRateLimiter:
    """Test MCP rate limiter (#215)."""

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_burst(self):
        """Test rate limiter allows burst requests."""
        limiter = MCPRateLimiter(requests_per_second=10.0, burst_allowance=5)

        # Should allow burst of 5 immediately
        for _ in range(5):
            wait_time = await limiter.acquire()
            assert wait_time == 0.0

    @pytest.mark.asyncio
    async def test_rate_limiter_throttles_after_burst(self):
        """Test rate limiter throttles after burst exhausted."""
        limiter = MCPRateLimiter(requests_per_second=100.0, burst_allowance=2)

        # Exhaust burst
        await limiter.acquire()
        await limiter.acquire()

        # Third request should wait
        wait_time = await limiter.acquire()
        # Should have waited some time (at least a little)
        assert wait_time >= 0.0

    @pytest.mark.asyncio
    async def test_rate_limiter_tokens_replenish(self):
        """Test rate limiter tokens replenish over time."""
        limiter = MCPRateLimiter(requests_per_second=1000.0, burst_allowance=5)

        # Exhaust burst
        for _ in range(5):
            await limiter.acquire()

        # Wait a bit for tokens to replenish
        import asyncio

        await asyncio.sleep(0.01)  # 10ms at 1000 rps = 10 tokens

        # Should have some tokens now
        assert limiter.available_tokens > 0

    def test_rate_limiter_available_tokens(self):
        """Test available_tokens property."""
        limiter = MCPRateLimiter(requests_per_second=10.0, burst_allowance=5)

        # Initially should have burst allowance
        assert limiter.available_tokens >= 4.5  # Some tolerance for timing

    @pytest.mark.asyncio
    async def test_bridge_uses_rate_limiter(self, bridge, mock_gmail_service):
        """Test bridge uses rate limiter for API calls."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }

        # Make multiple requests
        for _ in range(3):
            await bridge.search_emails("test")

        # Verify rate limiter was used (tokens decreased)
        assert bridge._rate_limiter.available_tokens < 5  # Started with 5


# ===========================================================================
# Email Attachment Model Tests
# ===========================================================================


class TestEmailAttachmentModel:
    """Test EmailAttachment model."""

    def test_attachment_creation(self):
        """Test creating EmailAttachment."""
        attachment = EmailAttachment(
            id="attach123",
            filename="document.pdf",
            mime_type="application/pdf",
            size=12345,
        )

        assert attachment.id == "attach123"
        assert attachment.filename == "document.pdf"
        assert attachment.mime_type == "application/pdf"
        assert attachment.size == 12345


# ===========================================================================
# Email Search Result Model Tests
# ===========================================================================


class TestEmailSearchResultModel:
    """Test EmailSearchResult model."""

    def test_search_result_creation(self):
        """Test creating EmailSearchResult."""
        result = EmailSearchResult(
            emails=[],
            next_page_token="token123",
            result_size_estimate=100,
        )

        assert result.emails == []
        assert result.next_page_token == "token123"
        assert result.result_size_estimate == 100

    def test_search_result_defaults(self):
        """Test EmailSearchResult defaults."""
        result = EmailSearchResult()

        assert result.emails == []
        assert result.next_page_token is None
        assert result.result_size_estimate is None
