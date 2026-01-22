"""
Unit tests for Google Workspace Bridge.

Tests the bridge interface using direct Google API calls.
Uses mocking for Google API services to test parsing and error handling logic.
"""

import base64
from datetime import datetime, timedelta
from pathlib import Path
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
# Email Reply Tests
# ===========================================================================


class TestEmailReply:
    """Test Gmail email reply-to-thread (#207)."""

    @pytest.mark.asyncio
    async def test_reply_to_email_success(self, bridge, mock_gmail_service):
        """Test successful email reply."""
        # Mock getting original message
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "orig_msg123",
            "threadId": "thread123",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Original Subject"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "me@example.com"},
                    {"name": "Message-ID", "value": "<original123@mail.com>"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
            },
        }
        # Mock sending reply
        mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "reply_msg456",
            "threadId": "thread123",
        }

        result = await bridge.reply_to_email(
            message_id="orig_msg123",
            body="This is my reply",
        )

        assert result.success is True
        assert result.message_id == "reply_msg456"
        assert result.is_draft is False
        assert result.error is None

    @pytest.mark.asyncio
    async def test_reply_to_email_draft_mode(self, bridge, mock_gmail_service):
        """Test email reply as draft."""
        # Mock getting original message
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "orig_msg123",
            "threadId": "thread123",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Original Subject"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Message-ID", "value": "<original123@mail.com>"},
                ],
            },
        }
        # Mock creating draft
        mock_gmail_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
            "id": "draft789",
        }

        result = await bridge.reply_to_email(
            message_id="orig_msg123",
            body="Draft reply",
            draft_only=True,
        )

        assert result.success is True
        assert result.is_draft is True

    @pytest.mark.asyncio
    async def test_reply_to_email_adds_re_prefix(self, bridge, mock_gmail_service):
        """Test that reply adds Re: prefix to subject."""
        # Mock getting original message (subject without Re:)
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "orig_msg123",
            "threadId": "thread123",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Meeting Tomorrow"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Message-ID", "value": "<original123@mail.com>"},
                ],
            },
        }
        mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "reply_msg456",
            "threadId": "thread123",
        }

        result = await bridge.reply_to_email(
            message_id="orig_msg123",
            body="Sure!",
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_reply_to_email_preserves_re_prefix(self, bridge, mock_gmail_service):
        """Test that reply doesn't double Re: prefix."""
        # Mock getting original message (subject already has Re:)
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "orig_msg123",
            "threadId": "thread123",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Re: Meeting Tomorrow"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Message-ID", "value": "<original123@mail.com>"},
                ],
            },
        }
        mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "reply_msg456",
            "threadId": "thread123",
        }

        result = await bridge.reply_to_email(
            message_id="orig_msg123",
            body="Looking forward to it",
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_reply_to_email_error(self, bridge, mock_gmail_service):
        """Test email reply handles errors gracefully."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = 404
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.side_effect = HttpError(
            mock_response, b"Message not found"
        )

        result = await bridge.reply_to_email(
            message_id="nonexistent123",
            body="Reply to missing message",
        )

        assert result.success is False
        assert result.error is not None


# ===========================================================================
# Email Pagination Tests
# ===========================================================================


class TestEmailPagination:
    """Test Gmail email pagination (#216)."""

    @pytest.mark.asyncio
    async def test_search_emails_paginated_returns_result(self, bridge, mock_gmail_service):
        """Test paginated search returns EmailSearchResult."""
        from klabautermann.mcp.google_workspace import EmailSearchResult

        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}],
            "nextPageToken": "token123",
            "resultSizeEstimate": 100,
        }
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Test email snippet",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test Subject"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
            },
        }

        result = await bridge.search_emails_paginated("test")

        assert isinstance(result, EmailSearchResult)
        assert len(result.emails) == 1
        assert result.emails[0].subject == "Test Subject"
        assert result.next_page_token == "token123"
        assert result.result_size_estimate == 100
        assert result.has_more is True

    @pytest.mark.asyncio
    async def test_search_emails_with_page_token(self, bridge, mock_gmail_service):
        """Test search with page token for continuation."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg2"}],
        }
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg2",
            "threadId": "thread2",
            "snippet": "Page 2 email",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Page 2"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
            },
        }

        result = await bridge.search_emails_paginated("test", page_token="token123")

        # Verify pageToken was passed
        call_args = mock_gmail_service.users.return_value.messages.return_value.list.call_args
        assert call_args[1].get("pageToken") == "token123"
        assert len(result.emails) == 1
        assert result.emails[0].subject == "Page 2"

    @pytest.mark.asyncio
    async def test_pagination_last_page_no_token(self, bridge, mock_gmail_service):
        """Test that pagination stops when nextPageToken is absent."""
        from klabautermann.mcp.google_workspace import EmailSearchResult

        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}],
            # NO nextPageToken field = last page
        }
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Last page",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Final Email"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
            },
        }

        result = await bridge.search_emails_paginated("test")

        assert isinstance(result, EmailSearchResult)
        assert result.next_page_token is None
        assert result.has_more is False
        assert len(result.emails) == 1

    @pytest.mark.asyncio
    async def test_pagination_empty_results(self, bridge, mock_gmail_service):
        """Test pagination with no matching messages."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [],
            # Empty result set
        }

        result = await bridge.search_emails_paginated("from:nonexistent@example.com")

        assert len(result.emails) == 0
        assert result.next_page_token is None
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_pagination_max_results_enforced(self, bridge, mock_gmail_service):
        """Test that max_results is enforced (max 500)."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [],
        }

        await bridge.search_emails_paginated("test", max_results=1000)

        # Verify maxResults was capped at 500
        call_args = mock_gmail_service.users.return_value.messages.return_value.list.call_args
        assert call_args[1].get("maxResults") == 500


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

    @pytest.mark.asyncio
    async def test_list_calendars_owned_only(self, bridge, mock_calendar_service):
        """Test listing only owned calendars."""
        mock_calendar_service.calendarList.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "primary", "summary": "Main Calendar", "accessRole": "owner"},
                {"id": "work@example.com", "summary": "Work", "accessRole": "owner"},
                {"id": "holidays@google.com", "summary": "Holidays", "accessRole": "reader"},
            ]
        }

        calendars = await bridge.list_calendars(owned_only=True)

        assert len(calendars) == 2
        assert calendars[0]["id"] == "primary"
        assert calendars[1]["id"] == "work@example.com"

    @pytest.mark.asyncio
    async def test_list_calendars_all(self, bridge, mock_calendar_service):
        """Test listing all calendars including shared."""
        mock_calendar_service.calendarList.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "primary", "summary": "Main Calendar", "accessRole": "owner"},
                {"id": "shared@example.com", "summary": "Shared", "accessRole": "reader"},
            ]
        }

        calendars = await bridge.list_calendars(owned_only=False)

        assert len(calendars) == 2

    @pytest.mark.asyncio
    async def test_list_events_with_calendar_id(self, bridge, mock_calendar_service):
        """Test listing events from a specific calendar."""
        start_time = datetime(2024, 1, 15, 10, 0)
        end_time = datetime(2024, 1, 15, 11, 0)

        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "event1",
                    "summary": "Work Meeting",
                    "start": {"dateTime": start_time.isoformat() + "Z"},
                    "end": {"dateTime": end_time.isoformat() + "Z"},
                    "eventType": "default",
                    "transparency": "opaque",
                }
            ]
        }

        events = await bridge.list_events(
            start=datetime(2024, 1, 15),
            end=datetime(2024, 1, 16),
            calendar_id="work@example.com",
            calendar_name="Work Calendar",
        )

        assert len(events) == 1
        assert events[0].calendar_id == "work@example.com"
        assert events[0].calendar_name == "Work Calendar"
        assert events[0].event_type == "default"
        assert events[0].transparency == "opaque"

    @pytest.mark.asyncio
    async def test_list_events_from_all_calendars(self, bridge, mock_calendar_service):
        """Test listing events from all owned calendars."""
        # Mock calendarList response
        mock_calendar_service.calendarList.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "primary", "summary": "Main Calendar", "accessRole": "owner"},
                {"id": "work@example.com", "summary": "Work", "accessRole": "owner"},
            ]
        }

        # Mock events for each calendar
        primary_events = {
            "items": [
                {
                    "id": "event1",
                    "summary": "Personal Event",
                    "start": {"dateTime": "2024-01-15T09:00:00Z"},
                    "end": {"dateTime": "2024-01-15T10:00:00Z"},
                }
            ]
        }
        work_events = {
            "items": [
                {
                    "id": "event2",
                    "summary": "Work Event",
                    "start": {"dateTime": "2024-01-15T11:00:00Z"},
                    "end": {"dateTime": "2024-01-15T12:00:00Z"},
                }
            ]
        }

        def list_events_side_effect(calendarId, **kwargs):
            mock_result = MagicMock()
            if calendarId == "primary":
                mock_result.execute.return_value = primary_events
            else:
                mock_result.execute.return_value = work_events
            return mock_result

        mock_calendar_service.events.return_value.list.side_effect = list_events_side_effect

        events = await bridge.list_events_from_all_calendars(
            start=datetime(2024, 1, 15),
            end=datetime(2024, 1, 16),
            owned_only=True,
        )

        # Should have events from both calendars, sorted by start time
        assert len(events) == 2
        assert events[0].title == "Personal Event"
        assert events[0].calendar_id == "primary"
        assert events[0].calendar_name == "Main Calendar"
        assert events[1].title == "Work Event"
        assert events[1].calendar_id == "work@example.com"
        assert events[1].calendar_name == "Work"


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


# ===========================================================================
# Recurring Events Tests
# ===========================================================================


class TestRecurrenceBuilder:
    """Test RecurrenceBuilder for generating RFC 5545 RRULE strings."""

    def test_daily_basic(self):
        """Test daily recurrence rule."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        rule = RecurrenceBuilder.daily()
        assert rule == "RRULE:FREQ=DAILY"

    def test_daily_with_count(self):
        """Test daily recurrence with occurrence count."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        rule = RecurrenceBuilder.daily(count=10)
        assert rule == "RRULE:FREQ=DAILY;COUNT=10"

    def test_daily_with_until(self):
        """Test daily recurrence with end date."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        until = datetime(2026, 12, 31, 23, 59, 59)
        rule = RecurrenceBuilder.daily(until=until)
        assert rule == "RRULE:FREQ=DAILY;UNTIL=20261231T235959Z"

    def test_weekly_basic(self):
        """Test weekly recurrence rule."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        rule = RecurrenceBuilder.weekly()
        assert rule == "RRULE:FREQ=WEEKLY"

    def test_weekly_with_days(self):
        """Test weekly recurrence on specific days."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        rule = RecurrenceBuilder.weekly(days=["MO", "WE", "FR"])
        assert rule == "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"

    def test_weekly_with_days_and_count(self):
        """Test weekly recurrence on specific days with count."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        rule = RecurrenceBuilder.weekly(days=["TU", "TH"], count=8)
        assert rule == "RRULE:FREQ=WEEKLY;BYDAY=TU,TH;COUNT=8"

    def test_monthly_basic(self):
        """Test monthly recurrence rule."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        rule = RecurrenceBuilder.monthly()
        assert rule == "RRULE:FREQ=MONTHLY"

    def test_monthly_with_day(self):
        """Test monthly recurrence on specific day of month."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        rule = RecurrenceBuilder.monthly(day_of_month=15)
        assert rule == "RRULE:FREQ=MONTHLY;BYMONTHDAY=15"

    def test_yearly_basic(self):
        """Test yearly recurrence rule."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        rule = RecurrenceBuilder.yearly()
        assert rule == "RRULE:FREQ=YEARLY"

    def test_yearly_with_count(self):
        """Test yearly recurrence with count."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        rule = RecurrenceBuilder.yearly(count=5)
        assert rule == "RRULE:FREQ=YEARLY;COUNT=5"

    def test_weekdays(self):
        """Test weekdays (Mon-Fri) recurrence."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        rule = RecurrenceBuilder.weekdays()
        assert rule == "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"


class TestRecurringCalendarEvents:
    """Test calendar operations with recurrence."""

    @pytest.mark.asyncio
    async def test_create_recurring_event(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test creating a recurring event."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        mock_calendar_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "recurring-event-123",
            "htmlLink": "https://calendar.google.com/event/123",
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"],
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        result = await bridge.create_event(
            title="Weekly Standup",
            start=datetime(2026, 1, 20, 9, 0),
            end=datetime(2026, 1, 20, 9, 30),
            recurrence_rule=RecurrenceBuilder.weekly(["MO", "WE", "FR"]),
        )

        assert result.success is True
        assert result.event_id == "recurring-event-123"

        # Verify the API was called with recurrence
        call_args = mock_calendar_service.events.return_value.insert.call_args
        body = call_args[1]["body"]
        assert "recurrence" in body
        assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"]

    @pytest.mark.asyncio
    async def test_parse_recurring_event(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test parsing a recurring event from API response."""
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "recurring-event-456",
                    "summary": "Daily Standup",
                    "start": {"dateTime": "2026-01-20T09:00:00Z"},
                    "end": {"dateTime": "2026-01-20T09:30:00Z"},
                    "recurrence": ["RRULE:FREQ=DAILY"],
                },
                {
                    "id": "instance-789",
                    "summary": "Daily Standup",
                    "start": {"dateTime": "2026-01-21T09:00:00Z"},
                    "end": {"dateTime": "2026-01-21T09:30:00Z"},
                    "recurringEventId": "recurring-event-456",
                },
            ]
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        events = await bridge.list_events(
            start=datetime(2026, 1, 20),
            end=datetime(2026, 1, 22),
        )

        assert len(events) == 2
        # First event is the recurring event definition
        assert events[0].recurrence_rule == "RRULE:FREQ=DAILY"
        assert events[0].recurring_event_id is None
        # Second event is an instance of the recurring event
        assert events[1].recurrence_rule is None
        assert events[1].recurring_event_id == "recurring-event-456"

    @pytest.mark.asyncio
    async def test_update_recurring_event(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test updating a recurring event's recurrence pattern."""
        from klabautermann.mcp.google_workspace import RecurrenceBuilder

        mock_calendar_service.events.return_value.patch.return_value.execute.return_value = {
            "id": "recurring-event-123",
            "htmlLink": "https://calendar.google.com/event/123",
            "recurrence": ["RRULE:FREQ=DAILY"],
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        result = await bridge.update_event(
            event_id="recurring-event-123",
            recurrence_rule=RecurrenceBuilder.daily(),
        )

        assert result.success is True

        # Verify the API was called with recurrence
        call_args = mock_calendar_service.events.return_value.patch.call_args
        body = call_args[1]["body"]
        assert "recurrence" in body
        assert body["recurrence"] == ["RRULE:FREQ=DAILY"]


# ===========================================================================
# Email Attachment Tests
# ===========================================================================


class TestEmailAttachments:
    """Test email attachment parsing and handling."""

    @pytest.mark.asyncio
    async def test_parse_email_with_attachments(self, bridge, mock_gmail_service):
        """Test parsing email with attachments."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}]
        }

        # Email with multipart payload including attachment
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Email with attachment",
            "labelIds": [],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Document attached"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": base64.urlsafe_b64encode(b"See attached").decode()},
                    },
                    {
                        "mimeType": "application/pdf",
                        "filename": "report.pdf",
                        "body": {"attachmentId": "attach-123", "size": 12345},
                    },
                ],
            },
        }

        emails = await bridge.search_emails("test")

        assert len(emails) == 1
        assert emails[0].has_attachments is True
        assert len(emails[0].attachments) == 1
        assert emails[0].attachments[0].filename == "report.pdf"
        assert emails[0].attachments[0].mime_type == "application/pdf"
        assert emails[0].attachments[0].attachment_id == "attach-123"
        assert emails[0].attachments[0].size == 12345
        assert emails[0].body == "See attached"

    @pytest.mark.asyncio
    async def test_parse_email_multiple_attachments(self, bridge, mock_gmail_service):
        """Test parsing email with multiple attachments."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}]
        }

        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Multiple attachments",
            "labelIds": [],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Files"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": base64.urlsafe_b64encode(b"Body text").decode()},
                    },
                    {
                        "mimeType": "image/png",
                        "filename": "screenshot.png",
                        "body": {"attachmentId": "attach-1", "size": 50000},
                    },
                    {
                        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "filename": "data.xlsx",
                        "body": {"attachmentId": "attach-2", "size": 25000},
                    },
                ],
            },
        }

        emails = await bridge.search_emails("test")

        assert len(emails) == 1
        assert len(emails[0].attachments) == 2
        assert emails[0].attachments[0].filename == "screenshot.png"
        assert emails[0].attachments[1].filename == "data.xlsx"

    @pytest.mark.asyncio
    async def test_parse_email_nested_multipart(self, bridge, mock_gmail_service):
        """Test parsing email with nested multipart structure."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}]
        }

        # Nested multipart structure (common with HTML emails)
        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Nested structure",
            "labelIds": [],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Nested email"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {
                                    "data": base64.urlsafe_b64encode(b"Plain text body").decode()
                                },
                            },
                            {
                                "mimeType": "text/html",
                                "body": {
                                    "data": base64.urlsafe_b64encode(
                                        b"<html><body>HTML body</body></html>"
                                    ).decode()
                                },
                            },
                        ],
                    },
                    {
                        "mimeType": "application/pdf",
                        "filename": "doc.pdf",
                        "body": {"attachmentId": "attach-nested", "size": 5000},
                    },
                ],
            },
        }

        emails = await bridge.search_emails("test")

        assert len(emails) == 1
        assert emails[0].body == "Plain text body"
        assert len(emails[0].attachments) == 1
        assert emails[0].attachments[0].filename == "doc.pdf"

    @pytest.mark.asyncio
    async def test_parse_email_no_attachments(self, bridge, mock_gmail_service):
        """Test parsing email without attachments."""
        mock_gmail_service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "msg1"}]
        }

        mock_gmail_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Plain email",
            "labelIds": [],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "No attachment"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                ],
                "body": {"data": base64.urlsafe_b64encode(b"Just text").decode()},
            },
        }

        emails = await bridge.search_emails("test")

        assert len(emails) == 1
        assert emails[0].has_attachments is False
        assert len(emails[0].attachments) == 0

    @pytest.mark.asyncio
    async def test_download_attachment(self, bridge, mock_gmail_service):
        """Test downloading attachment data."""
        attachment_data = b"PDF binary content here"
        mock_gmail_service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
            "data": base64.urlsafe_b64encode(attachment_data).decode()
        }

        result = await bridge.download_attachment("msg1", "attach-123")

        assert result == attachment_data
        mock_gmail_service.users.return_value.messages.return_value.attachments.return_value.get.assert_called_once_with(
            userId="me", messageId="msg1", id="attach-123"
        )

    @pytest.mark.asyncio
    async def test_save_attachment(self, bridge, mock_gmail_service, tmp_path):
        """Test saving attachment to filesystem."""
        attachment_data = b"Test file content"
        mock_gmail_service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
            "data": base64.urlsafe_b64encode(attachment_data).decode()
        }

        from klabautermann.mcp.google_workspace import EmailAttachment

        attachment = EmailAttachment(
            attachment_id="attach-123",
            filename="test.txt",
            mime_type="text/plain",
            size=len(attachment_data),
        )

        save_path = str(tmp_path)
        result = await bridge.save_attachment("msg1", attachment, save_path)

        assert result.endswith("test.txt")
        assert Path(result).read_bytes() == attachment_data

    @pytest.mark.asyncio
    async def test_save_attachment_duplicate_filename(self, bridge, mock_gmail_service, tmp_path):
        """Test saving attachment with duplicate filename creates unique name."""
        attachment_data = b"Test file content"
        mock_gmail_service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
            "data": base64.urlsafe_b64encode(attachment_data).decode()
        }

        from klabautermann.mcp.google_workspace import EmailAttachment

        # Create existing file
        existing_file = tmp_path / "test.txt"
        existing_file.write_bytes(b"existing content")

        attachment = EmailAttachment(
            attachment_id="attach-123",
            filename="test.txt",
            mime_type="text/plain",
            size=len(attachment_data),
        )

        save_path = str(tmp_path)
        result = await bridge.save_attachment("msg1", attachment, save_path)

        # Should create test_1.txt since test.txt exists
        assert "test_1.txt" in result

    def test_attachment_size_human_bytes(self):
        """Test human-readable size formatting for bytes."""
        from klabautermann.mcp.google_workspace import EmailAttachment

        attachment = EmailAttachment(
            attachment_id="test", filename="small.txt", mime_type="text/plain", size=500
        )
        assert attachment.size_human == "500 B"

    def test_attachment_size_human_kilobytes(self):
        """Test human-readable size formatting for kilobytes."""
        from klabautermann.mcp.google_workspace import EmailAttachment

        attachment = EmailAttachment(
            attachment_id="test", filename="medium.txt", mime_type="text/plain", size=2048
        )
        assert attachment.size_human == "2.0 KB"

    def test_attachment_size_human_megabytes(self):
        """Test human-readable size formatting for megabytes."""
        from klabautermann.mcp.google_workspace import EmailAttachment

        attachment = EmailAttachment(
            attachment_id="test", filename="large.pdf", mime_type="application/pdf", size=5242880
        )
        assert attachment.size_human == "5.0 MB"


# ===========================================================================
# Calendar Search Tests
# ===========================================================================


class TestCalendarSearch:
    """Test calendar event search functionality."""

    @pytest.mark.asyncio
    async def test_search_events_by_title(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test searching events by title."""
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "event-1",
                    "summary": "Team Standup",
                    "start": {"dateTime": "2026-01-22T09:00:00Z"},
                    "end": {"dateTime": "2026-01-22T09:30:00Z"},
                },
                {
                    "id": "event-2",
                    "summary": "Standup Review",
                    "start": {"dateTime": "2026-01-22T10:00:00Z"},
                    "end": {"dateTime": "2026-01-22T10:30:00Z"},
                },
            ]
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        events = await bridge.search_events("standup")

        assert len(events) == 2
        assert events[0].title == "Team Standup"
        assert events[1].title == "Standup Review"

        # Verify query parameter was passed
        call_args = mock_calendar_service.events.return_value.list.call_args
        assert call_args[1]["q"] == "standup"

    @pytest.mark.asyncio
    async def test_search_events_with_date_range(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test searching events within a date range."""
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        start = datetime(2026, 1, 22, 0, 0, 0)
        end = datetime(2026, 1, 29, 23, 59, 59)

        await bridge.search_events("meeting", start=start, end=end)

        # Verify time range was passed
        call_args = mock_calendar_service.events.return_value.list.call_args
        assert "timeMin" in call_args[1]
        assert "timeMax" in call_args[1]
        assert "2026-01-22" in call_args[1]["timeMin"]
        assert "2026-01-29" in call_args[1]["timeMax"]

    @pytest.mark.asyncio
    async def test_search_events_no_results(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test search returning no results."""
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        events = await bridge.search_events("nonexistent-event-xyz")

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_search_events_default_date_range(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test search uses 30 day default range when not specified."""
        mock_calendar_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        await bridge.search_events("test")

        # Should use 30 day range by default
        call_args = mock_calendar_service.events.return_value.list.call_args
        assert call_args[1]["maxResults"] == 25  # Default max results


# ===========================================================================
# Calendar Free Slot Tests
# ===========================================================================


class TestCalendarFreeSlots:
    """Test calendar free slot finder functionality."""

    @pytest.mark.asyncio
    async def test_find_free_slots_basic(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test finding free slots with no busy periods."""
        mock_calendar_service.freebusy.return_value.query.return_value.execute.return_value = {
            "calendars": {
                "primary": {
                    "busy": []  # No busy periods
                }
            }
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        # Search for 30-minute slots on a Monday
        start = datetime(2026, 1, 26, 9, 0)  # Monday
        end = datetime(2026, 1, 26, 17, 0)

        slots = await bridge.find_free_slots(
            duration_minutes=30,
            start=start,
            end=end,
            working_hours_start=9,
            working_hours_end=17,
        )

        # Should find 1 slot covering the entire day (9am-5pm)
        assert len(slots) == 1
        assert slots[0].start == datetime(2026, 1, 26, 9, 0)
        assert slots[0].end == datetime(2026, 1, 26, 17, 0)

    @pytest.mark.asyncio
    async def test_find_free_slots_with_busy_periods(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test finding free slots around busy periods."""
        mock_calendar_service.freebusy.return_value.query.return_value.execute.return_value = {
            "calendars": {
                "primary": {
                    "busy": [
                        {"start": "2026-01-26T10:00:00Z", "end": "2026-01-26T11:00:00Z"},
                        {"start": "2026-01-26T14:00:00Z", "end": "2026-01-26T15:00:00Z"},
                    ]
                }
            }
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        start = datetime(2026, 1, 26, 9, 0)  # Monday
        end = datetime(2026, 1, 26, 17, 0)

        slots = await bridge.find_free_slots(
            duration_minutes=30,
            start=start,
            end=end,
            working_hours_start=9,
            working_hours_end=17,
        )

        # Should find 3 slots:
        # 9am-10am, 11am-2pm, 3pm-5pm
        assert len(slots) == 3
        assert slots[0].start.hour == 9
        assert slots[0].end.hour == 10
        assert slots[1].start.hour == 11
        assert slots[1].end.hour == 14
        assert slots[2].start.hour == 15
        assert slots[2].end.hour == 17

    @pytest.mark.asyncio
    async def test_find_free_slots_skips_weekends(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test that free slots finder skips weekends."""
        mock_calendar_service.freebusy.return_value.query.return_value.execute.return_value = {
            "calendars": {"primary": {"busy": []}}
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        # Saturday and Sunday
        start = datetime(2026, 1, 24, 9, 0)  # Saturday
        end = datetime(2026, 1, 25, 17, 0)  # Sunday

        slots = await bridge.find_free_slots(
            duration_minutes=30,
            start=start,
            end=end,
        )

        # Should find no slots on weekends
        assert len(slots) == 0

    @pytest.mark.asyncio
    async def test_find_free_slots_minimum_duration(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test that slots shorter than duration are excluded."""
        mock_calendar_service.freebusy.return_value.query.return_value.execute.return_value = {
            "calendars": {
                "primary": {
                    "busy": [
                        # 20-minute gap at 10am
                        {"start": "2026-01-26T09:00:00Z", "end": "2026-01-26T10:00:00Z"},
                        {"start": "2026-01-26T10:20:00Z", "end": "2026-01-26T17:00:00Z"},
                    ]
                }
            }
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        start = datetime(2026, 1, 26, 9, 0)
        end = datetime(2026, 1, 26, 17, 0)

        # Looking for 30-minute slots
        slots = await bridge.find_free_slots(
            duration_minutes=30,
            start=start,
            end=end,
        )

        # 20-minute gap should be excluded
        assert len(slots) == 0

    @pytest.mark.asyncio
    async def test_find_free_slots_multiple_calendars(
        self, mock_env, mock_credentials, mock_build, mock_calendar_service
    ):
        """Test finding free slots across multiple calendars."""
        mock_calendar_service.freebusy.return_value.query.return_value.execute.return_value = {
            "calendars": {
                "primary": {
                    "busy": [
                        {"start": "2026-01-26T09:00:00Z", "end": "2026-01-26T10:00:00Z"},
                    ]
                },
                "work@example.com": {
                    "busy": [
                        {"start": "2026-01-26T11:00:00Z", "end": "2026-01-26T12:00:00Z"},
                    ]
                },
            }
        }

        bridge = GoogleWorkspaceBridge()
        await bridge.start()

        start = datetime(2026, 1, 26, 9, 0)
        end = datetime(2026, 1, 26, 17, 0)

        slots = await bridge.find_free_slots(
            duration_minutes=30,
            start=start,
            end=end,
            calendar_ids=["primary", "work@example.com"],
        )

        # Should account for busy times from both calendars
        # Free: 10-11, 12-17
        assert len(slots) == 2


# ===========================================================================
# FreeSlot Model Tests
# ===========================================================================


class TestFreeSlotModel:
    """Test FreeSlot model functionality."""

    def test_duration_minutes(self):
        """Test duration calculation in minutes."""
        from klabautermann.mcp.google_workspace import FreeSlot

        slot = FreeSlot(
            start=datetime(2026, 1, 26, 9, 0),
            end=datetime(2026, 1, 26, 10, 30),
        )
        assert slot.duration_minutes == 90

    def test_duration_human_minutes_only(self):
        """Test human-readable duration for minutes only."""
        from klabautermann.mcp.google_workspace import FreeSlot

        slot = FreeSlot(
            start=datetime(2026, 1, 26, 9, 0),
            end=datetime(2026, 1, 26, 9, 45),
        )
        assert slot.duration_human == "45 min"

    def test_duration_human_hours_only(self):
        """Test human-readable duration for whole hours."""
        from klabautermann.mcp.google_workspace import FreeSlot

        slot = FreeSlot(
            start=datetime(2026, 1, 26, 9, 0),
            end=datetime(2026, 1, 26, 11, 0),
        )
        assert slot.duration_human == "2 hr"

    def test_duration_human_hours_and_minutes(self):
        """Test human-readable duration for hours and minutes."""
        from klabautermann.mcp.google_workspace import FreeSlot

        slot = FreeSlot(
            start=datetime(2026, 1, 26, 9, 0),
            end=datetime(2026, 1, 26, 10, 30),
        )
        assert slot.duration_human == "1 hr 30 min"

    def test_format_display(self):
        """Test display formatting of slot."""
        from klabautermann.mcp.google_workspace import FreeSlot

        slot = FreeSlot(
            start=datetime(2026, 1, 26, 9, 0),
            end=datetime(2026, 1, 26, 10, 0),
        )
        display = slot.format_display()
        assert "Mon Jan 26" in display
        assert "09:00 AM" in display
        assert "10:00 AM" in display
        assert "1 hr" in display


# ===========================================================================
# Draft Management Tests (Issue #219)
# ===========================================================================


class TestDraftManagement:
    """Test Gmail draft management operations."""

    @pytest.mark.asyncio
    async def test_list_drafts(self, bridge, mock_gmail_service):
        """Test listing drafts."""
        # Setup mock response for list
        mock_gmail_service.users().drafts().list().execute.return_value = {
            "drafts": [
                {"id": "draft1"},
                {"id": "draft2"},
            ]
        }

        # Setup mock response for individual draft details
        def get_draft_details(*args, **kwargs):
            draft_id = kwargs.get("id", "draft1")
            return {
                "id": draft_id,
                "message": {
                    "id": f"msg_{draft_id}",
                    "threadId": f"thread_{draft_id}",
                    "snippet": "Test snippet",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": f"Subject {draft_id}"},
                            {"name": "To", "value": "test@example.com"},
                        ],
                        "body": {"data": base64.urlsafe_b64encode(b"Test body").decode()},
                    },
                },
            }

        mock_gmail_service.users().drafts().get().execute.side_effect = get_draft_details

        drafts = await bridge.list_drafts(max_results=10)

        assert len(drafts) == 2
        mock_gmail_service.users().drafts().list.assert_called()

    @pytest.mark.asyncio
    async def test_get_draft(self, bridge, mock_gmail_service):
        """Test getting a specific draft."""
        mock_gmail_service.users().drafts().get().execute.return_value = {
            "id": "draft123",
            "message": {
                "id": "msg123",
                "threadId": "thread123",
                "snippet": "Test snippet",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Test Subject"},
                        {"name": "To", "value": "recipient@example.com"},
                        {"name": "Cc", "value": "cc@example.com"},
                    ],
                    "body": {"data": base64.urlsafe_b64encode(b"Draft body content").decode()},
                },
            },
        }

        draft = await bridge.get_draft("draft123")

        assert draft is not None
        assert draft.id == "draft123"
        assert draft.message_id == "msg123"
        assert draft.thread_id == "thread123"
        assert draft.subject == "Test Subject"
        assert draft.to == "recipient@example.com"
        assert draft.cc == "cc@example.com"
        assert draft.body == "Draft body content"

    @pytest.mark.asyncio
    async def test_get_draft_not_found(self, bridge, mock_gmail_service):
        """Test getting a non-existent draft."""
        from googleapiclient.errors import HttpError

        error_resp = MagicMock()
        error_resp.status = 404
        mock_gmail_service.users().drafts().get().execute.side_effect = HttpError(
            error_resp, b"Draft not found"
        )

        draft = await bridge.get_draft("nonexistent")

        assert draft is None

    @pytest.mark.asyncio
    async def test_update_draft(self, bridge, mock_gmail_service):
        """Test updating a draft."""
        # Mock get_draft for existing draft
        mock_gmail_service.users().drafts().get().execute.return_value = {
            "id": "draft123",
            "message": {
                "id": "msg123",
                "threadId": "thread123",
                "snippet": "Old snippet",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Old Subject"},
                        {"name": "To", "value": "old@example.com"},
                    ],
                    "body": {"data": base64.urlsafe_b64encode(b"Old body").decode()},
                },
            },
        }

        # Mock update
        mock_gmail_service.users().drafts().update().execute.return_value = {
            "id": "draft123",
            "message": {"id": "msg123_updated"},
        }

        result = await bridge.update_draft(
            draft_id="draft123",
            subject="New Subject",
            body="New body content",
        )

        assert result.success is True
        assert result.draft_id == "draft123"
        assert result.operation == "update"
        mock_gmail_service.users().drafts().update.assert_called()

    @pytest.mark.asyncio
    async def test_update_draft_not_found(self, bridge, mock_gmail_service):
        """Test updating a non-existent draft."""
        from googleapiclient.errors import HttpError

        error_resp = MagicMock()
        error_resp.status = 404
        mock_gmail_service.users().drafts().get().execute.side_effect = HttpError(
            error_resp, b"Draft not found"
        )

        result = await bridge.update_draft(
            draft_id="nonexistent",
            subject="New Subject",
        )

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_send_draft(self, bridge, mock_gmail_service):
        """Test sending a draft."""
        mock_gmail_service.users().drafts().send().execute.return_value = {
            "id": "sent_msg_id",
            "threadId": "thread123",
        }

        result = await bridge.send_draft("draft123")

        assert result.success is True
        assert result.draft_id == "draft123"
        assert result.message_id == "sent_msg_id"
        assert result.operation == "send"
        mock_gmail_service.users().drafts().send.assert_called()

    @pytest.mark.asyncio
    async def test_send_draft_error(self, bridge, mock_gmail_service):
        """Test sending a draft that fails."""
        from googleapiclient.errors import HttpError

        error_resp = MagicMock()
        error_resp.status = 400
        mock_gmail_service.users().drafts().send().execute.side_effect = HttpError(
            error_resp, b"Send failed"
        )

        result = await bridge.send_draft("draft123")

        assert result.success is False
        assert result.operation == "send"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_delete_draft(self, bridge, mock_gmail_service):
        """Test deleting a draft."""
        mock_gmail_service.users().drafts().delete().execute.return_value = None

        result = await bridge.delete_draft("draft123")

        assert result.success is True
        assert result.draft_id == "draft123"
        assert result.operation == "delete"
        mock_gmail_service.users().drafts().delete.assert_called()

    @pytest.mark.asyncio
    async def test_delete_draft_error(self, bridge, mock_gmail_service):
        """Test deleting a draft that fails."""
        from googleapiclient.errors import HttpError

        error_resp = MagicMock()
        error_resp.status = 404
        mock_gmail_service.users().drafts().delete().execute.side_effect = HttpError(
            error_resp, b"Draft not found"
        )

        result = await bridge.delete_draft("nonexistent")

        assert result.success is False
        assert result.operation == "delete"


class TestDraftModel:
    """Test EmailDraft Pydantic model."""

    def test_draft_model_creation(self):
        """Test creating an EmailDraft model."""
        from klabautermann.mcp.google_workspace import EmailDraft

        draft = EmailDraft(
            id="draft123",
            message_id="msg123",
            thread_id="thread123",
            subject="Test Subject",
            to="recipient@example.com",
            cc="cc@example.com",
            body="Test body",
            snippet="Test snippet",
        )

        assert draft.id == "draft123"
        assert draft.message_id == "msg123"
        assert draft.thread_id == "thread123"
        assert draft.subject == "Test Subject"
        assert draft.to == "recipient@example.com"
        assert draft.cc == "cc@example.com"
        assert draft.body == "Test body"
        assert draft.snippet == "Test snippet"

    def test_draft_model_optional_fields(self):
        """Test EmailDraft with optional fields."""
        from klabautermann.mcp.google_workspace import EmailDraft

        draft = EmailDraft(
            id="draft123",
            message_id="msg123",
            subject="Test Subject",
        )

        assert draft.id == "draft123"
        assert draft.thread_id is None
        assert draft.to is None
        assert draft.cc is None
        assert draft.body is None
        assert draft.snippet == ""


class TestDraftOperationResult:
    """Test DraftOperationResult Pydantic model."""

    def test_draft_operation_success(self):
        """Test successful draft operation result."""
        from klabautermann.mcp.google_workspace import DraftOperationResult

        result = DraftOperationResult(
            success=True,
            draft_id="draft123",
            message_id="msg123",
            operation="send",
        )

        assert result.success is True
        assert result.draft_id == "draft123"
        assert result.message_id == "msg123"
        assert result.operation == "send"
        assert result.error is None

    def test_draft_operation_failure(self):
        """Test failed draft operation result."""
        from klabautermann.mcp.google_workspace import DraftOperationResult

        result = DraftOperationResult(
            success=False,
            draft_id="draft123",
            operation="update",
            error="Draft not found",
        )

        assert result.success is False
        assert result.error == "Draft not found"


# ===========================================================================
# Label Management Tests (Issue #217)
# ===========================================================================


class TestLabelManagement:
    """Test Gmail label management operations."""

    @pytest.mark.asyncio
    async def test_create_label(self, bridge, mock_gmail_service):
        """Test creating a custom label."""
        mock_gmail_service.users().labels().create().execute.return_value = {
            "id": "Label_123",
            "name": "Projects/Work",
            "type": "user",
        }

        label = await bridge.create_label("Projects/Work")

        assert label.id == "Label_123"
        assert label.name == "Projects/Work"
        assert label.type == "user"
        mock_gmail_service.users().labels().create.assert_called()

    @pytest.mark.asyncio
    async def test_create_label_with_visibility(self, bridge, mock_gmail_service):
        """Test creating a label with custom visibility settings."""
        mock_gmail_service.users().labels().create().execute.return_value = {
            "id": "Label_456",
            "name": "Archive",
            "type": "user",
        }

        label = await bridge.create_label(
            name="Archive",
            label_list_visibility="labelHide",
            message_list_visibility="hide",
        )

        assert label.id == "Label_456"
        assert label.name == "Archive"
        # Verify the call was made with correct visibility settings
        call_args = mock_gmail_service.users().labels().create.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_create_label_already_exists(self, bridge, mock_gmail_service):
        """Test creating a label that already exists."""
        from googleapiclient.errors import HttpError

        error_resp = MagicMock()
        error_resp.status = 409
        mock_gmail_service.users().labels().create().execute.side_effect = HttpError(
            error_resp, b"Label already exists"
        )

        with pytest.raises(ExternalServiceError) as exc_info:
            await bridge.create_label("Existing Label")

        assert "Create label failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_label(self, bridge, mock_gmail_service):
        """Test deleting a custom label."""
        mock_gmail_service.users().labels().delete().execute.return_value = None

        result = await bridge.delete_label("Label_123")

        assert result is True
        mock_gmail_service.users().labels().delete.assert_called()

    @pytest.mark.asyncio
    async def test_delete_label_not_found(self, bridge, mock_gmail_service):
        """Test deleting a non-existent label."""
        from googleapiclient.errors import HttpError

        error_resp = MagicMock()
        error_resp.status = 404
        mock_gmail_service.users().labels().delete().execute.side_effect = HttpError(
            error_resp, b"Label not found"
        )

        with pytest.raises(ExternalServiceError) as exc_info:
            await bridge.delete_label("nonexistent")

        assert "Delete label failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_label_name(self, bridge, mock_gmail_service):
        """Test updating a label name."""
        mock_gmail_service.users().labels().patch().execute.return_value = {
            "id": "Label_123",
            "name": "New Name",
            "type": "user",
        }

        label = await bridge.update_label("Label_123", name="New Name")

        assert label.id == "Label_123"
        assert label.name == "New Name"
        mock_gmail_service.users().labels().patch.assert_called()

    @pytest.mark.asyncio
    async def test_update_label_visibility(self, bridge, mock_gmail_service):
        """Test updating label visibility settings."""
        mock_gmail_service.users().labels().patch().execute.return_value = {
            "id": "Label_123",
            "name": "Projects",
            "type": "user",
        }

        label = await bridge.update_label(
            "Label_123",
            label_list_visibility="labelHide",
            message_list_visibility="hide",
        )

        assert label.id == "Label_123"
        mock_gmail_service.users().labels().patch.assert_called()

    @pytest.mark.asyncio
    async def test_update_label_error(self, bridge, mock_gmail_service):
        """Test updating a label that fails."""
        from googleapiclient.errors import HttpError

        error_resp = MagicMock()
        error_resp.status = 400
        mock_gmail_service.users().labels().patch().execute.side_effect = HttpError(
            error_resp, b"Update failed"
        )

        with pytest.raises(ExternalServiceError) as exc_info:
            await bridge.update_label("Label_123", name="New Name")

        assert "Update label failed" in str(exc_info.value)
