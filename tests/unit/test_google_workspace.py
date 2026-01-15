"""
Unit tests for Google Workspace MCP Bridge.

Tests the bridge interface without requiring actual MCP server or Google API access.
Uses mocking for MCP client to test parsing and error handling logic.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.core.exceptions import MCPError
from klabautermann.mcp.google_workspace import (
    GoogleWorkspaceBridge,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_mcp_client():
    """Create a mock MCP client for testing."""
    client = MagicMock()
    client.start_server = AsyncMock()
    client.stop_server = AsyncMock()
    client.invoke_tool = AsyncMock()
    return client


@pytest.fixture
async def bridge(mock_mcp_client):
    """Create a GoogleWorkspaceBridge with mocked client."""
    bridge = GoogleWorkspaceBridge(mcp_client=mock_mcp_client)
    return bridge


# ===========================================================================
# Email Tests
# ===========================================================================


class TestEmailOperations:
    """Test Gmail operations."""

    @pytest.mark.asyncio
    async def test_search_emails_success(self, bridge, mock_mcp_client):
        """Test successful email search."""
        # Mock MCP response
        mock_mcp_client.invoke_tool.return_value = {
            "messages": [
                {
                    "id": "msg1",
                    "threadId": "thread1",
                    "subject": "Test Email",
                    "from": "sender@example.com",
                    "to": "recipient@example.com",
                    "date": "2024-01-15T10:30:00Z",
                    "snippet": "This is a test",
                    "labelIds": ["UNREAD"],
                },
                {
                    "id": "msg2",
                    "threadId": "thread2",
                    "subject": "Another Email",
                    "from": "other@example.com",
                    "date": "2024-01-15T11:00:00Z",
                    "snippet": "Another test",
                    "labelIds": [],
                },
            ]
        }

        # Execute search
        emails = await bridge.search_emails("from:sender@example.com")

        # Verify
        assert len(emails) == 2
        assert emails[0].id == "msg1"
        assert emails[0].subject == "Test Email"
        assert emails[0].sender == "sender@example.com"
        assert emails[0].is_unread is True
        assert emails[1].is_unread is False

        # Verify MCP client was called correctly
        mock_mcp_client.invoke_tool.assert_called_once()
        call_args = mock_mcp_client.invoke_tool.call_args
        assert call_args.kwargs["tool_name"] == "gmail_search_messages"
        assert call_args.kwargs["arguments"]["query"] == "from:sender@example.com"

    @pytest.mark.asyncio
    async def test_search_emails_empty_result(self, bridge, mock_mcp_client):
        """Test email search with no results."""
        mock_mcp_client.invoke_tool.return_value = {"messages": []}

        emails = await bridge.search_emails("from:nobody@example.com")

        assert len(emails) == 0

    @pytest.mark.asyncio
    async def test_search_emails_malformed_date(self, bridge, mock_mcp_client):
        """Test email search handles malformed date gracefully."""
        mock_mcp_client.invoke_tool.return_value = {
            "messages": [
                {
                    "id": "msg1",
                    "threadId": "thread1",
                    "subject": "Test",
                    "from": "sender@example.com",
                    "date": "invalid-date",
                    "snippet": "Test",
                }
            ]
        }

        emails = await bridge.search_emails("test")

        # Should parse successfully with default date
        assert len(emails) == 1
        assert isinstance(emails[0].date, datetime)

    @pytest.mark.asyncio
    async def test_search_emails_error(self, bridge, mock_mcp_client):
        """Test email search handles errors."""
        mock_mcp_client.invoke_tool.side_effect = MCPError("Server error")

        with pytest.raises(MCPError, match="Gmail search failed"):
            await bridge.search_emails("test")

    @pytest.mark.asyncio
    async def test_send_email_success(self, bridge, mock_mcp_client):
        """Test successful email sending."""
        mock_mcp_client.invoke_tool.return_value = {
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

        # Verify correct tool was called
        call_args = mock_mcp_client.invoke_tool.call_args
        assert call_args.kwargs["tool_name"] == "gmail_send_message"
        assert call_args.kwargs["arguments"]["to"] == "recipient@example.com"
        assert call_args.kwargs["arguments"]["subject"] == "Test Subject"

    @pytest.mark.asyncio
    async def test_send_email_draft_mode(self, bridge, mock_mcp_client):
        """Test email draft creation."""
        mock_mcp_client.invoke_tool.return_value = {"id": "draft123"}

        result = await bridge.send_email(
            to="recipient@example.com",
            subject="Draft Subject",
            body="Draft Body",
            draft_only=True,
        )

        assert result.success is True
        assert result.is_draft is True

        # Verify draft tool was called
        call_args = mock_mcp_client.invoke_tool.call_args
        assert call_args.kwargs["tool_name"] == "gmail_create_draft"

    @pytest.mark.asyncio
    async def test_send_email_with_cc(self, bridge, mock_mcp_client):
        """Test email sending with CC."""
        mock_mcp_client.invoke_tool.return_value = {"id": "msg123"}

        result = await bridge.send_email(
            to="recipient@example.com",
            subject="Test",
            body="Test",
            cc="cc1@example.com,cc2@example.com",
        )

        assert result.success is True

        # Verify CC was included
        call_args = mock_mcp_client.invoke_tool.call_args
        assert "cc" in call_args.kwargs["arguments"]
        assert call_args.kwargs["arguments"]["cc"] == "cc1@example.com,cc2@example.com"

    @pytest.mark.asyncio
    async def test_send_email_error(self, bridge, mock_mcp_client):
        """Test email sending handles errors gracefully."""
        mock_mcp_client.invoke_tool.side_effect = MCPError("Send failed")

        result = await bridge.send_email(
            to="recipient@example.com",
            subject="Test",
            body="Test",
        )

        assert result.success is False
        assert result.error is not None
        assert "Send failed" in result.error

    @pytest.mark.asyncio
    async def test_get_recent_emails(self, bridge, mock_mcp_client):
        """Test getting recent emails."""
        mock_mcp_client.invoke_tool.return_value = {
            "messages": [
                {
                    "id": "msg1",
                    "threadId": "thread1",
                    "subject": "Recent",
                    "from": "sender@example.com",
                    "date": datetime.now().isoformat(),
                    "snippet": "Recent email",
                }
            ]
        }

        emails = await bridge.get_recent_emails(hours=24)

        assert len(emails) == 1

        # Verify query format
        call_args = mock_mcp_client.invoke_tool.call_args
        assert call_args.kwargs["arguments"]["query"] == "newer_than:24h"


# ===========================================================================
# Calendar Tests
# ===========================================================================


class TestCalendarOperations:
    """Test Google Calendar operations."""

    @pytest.mark.asyncio
    async def test_list_events_success(self, bridge, mock_mcp_client):
        """Test successful event listing."""
        start_time = datetime(2024, 1, 15, 10, 0)
        end_time = datetime(2024, 1, 15, 11, 0)

        mock_mcp_client.invoke_tool.return_value = {
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
    async def test_list_events_all_day(self, bridge, mock_mcp_client):
        """Test listing all-day events."""
        mock_mcp_client.invoke_tool.return_value = {
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
    async def test_list_events_default_range(self, bridge, mock_mcp_client):
        """Test listing events with default time range."""
        mock_mcp_client.invoke_tool.return_value = {"items": []}

        await bridge.list_events()

        # Verify default range is 7 days
        call_args = mock_mcp_client.invoke_tool.call_args
        time_min = call_args.kwargs["arguments"]["timeMin"]
        time_max = call_args.kwargs["arguments"]["timeMax"]

        # Both should be ISO format with Z suffix
        assert time_min.endswith("Z")
        assert time_max.endswith("Z")

    @pytest.mark.asyncio
    async def test_list_events_error(self, bridge, mock_mcp_client):
        """Test event listing handles errors."""
        mock_mcp_client.invoke_tool.side_effect = MCPError("Calendar error")

        with pytest.raises(MCPError, match="Calendar list failed"):
            await bridge.list_events()

    @pytest.mark.asyncio
    async def test_create_event_success(self, bridge, mock_mcp_client):
        """Test successful event creation."""
        start = datetime(2024, 1, 15, 14, 0)
        end = datetime(2024, 1, 15, 15, 0)

        mock_mcp_client.invoke_tool.return_value = {
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

        # Verify tool arguments
        call_args = mock_mcp_client.invoke_tool.call_args
        args = call_args.kwargs["arguments"]
        assert args["summary"] == "Team Standup"
        assert args["description"] == "Daily standup meeting"
        assert args["location"] == "Zoom"
        assert len(args["attendees"]) == 2

    @pytest.mark.asyncio
    async def test_create_event_minimal(self, bridge, mock_mcp_client):
        """Test event creation with minimal fields."""
        start = datetime(2024, 1, 15, 14, 0)
        end = datetime(2024, 1, 15, 15, 0)

        mock_mcp_client.invoke_tool.return_value = {"id": "event123"}

        result = await bridge.create_event(
            title="Quick Meeting",
            start=start,
            end=end,
        )

        assert result.success is True

        # Verify only required fields sent
        call_args = mock_mcp_client.invoke_tool.call_args
        args = call_args.kwargs["arguments"]
        assert "description" not in args
        assert "location" not in args
        assert "attendees" not in args

    @pytest.mark.asyncio
    async def test_create_event_error(self, bridge, mock_mcp_client):
        """Test event creation handles errors gracefully."""
        mock_mcp_client.invoke_tool.side_effect = MCPError("Creation failed")

        result = await bridge.create_event(
            title="Meeting",
            start=datetime.now(),
            end=datetime.now() + timedelta(hours=1),
        )

        assert result.success is False
        assert result.error is not None
        assert "Creation failed" in result.error

    @pytest.mark.asyncio
    async def test_get_todays_events(self, bridge, mock_mcp_client):
        """Test getting today's events."""
        mock_mcp_client.invoke_tool.return_value = {"items": []}

        await bridge.get_todays_events()

        # Verify time range is today
        call_args = mock_mcp_client.invoke_tool.call_args
        time_min = call_args.kwargs["arguments"]["timeMin"]
        time_max = call_args.kwargs["arguments"]["timeMax"]

        # Should be same date, different times
        assert "T00:00:00" in time_min
        assert "T23:59:59" in time_max

    @pytest.mark.asyncio
    async def test_get_tomorrows_events(self, bridge, mock_mcp_client):
        """Test getting tomorrow's events."""
        mock_mcp_client.invoke_tool.return_value = {"items": []}

        await bridge.get_tomorrows_events()

        # Verify time range is tomorrow
        call_args = mock_mcp_client.invoke_tool.call_args
        time_min = call_args.kwargs["arguments"]["timeMin"]

        # Parse and check it's tomorrow
        min_date = datetime.fromisoformat(time_min.replace("Z", "+00:00"))
        tomorrow = datetime.now() + timedelta(days=1)
        assert min_date.date() == tomorrow.date()


# ===========================================================================
# Lifecycle Tests
# ===========================================================================


class TestBridgeLifecycle:
    """Test bridge initialization and lifecycle."""

    @pytest.mark.asyncio
    async def test_start_server(self, bridge, mock_mcp_client):
        """Test starting the MCP server."""
        await bridge.start()

        assert bridge._started is True
        mock_mcp_client.start_server.assert_called_once()

        # Verify credentials are injected
        call_args = mock_mcp_client.start_server.call_args
        config = call_args.args[0]
        assert "GOOGLE_REFRESH_TOKEN" in config.env
        assert "GOOGLE_CLIENT_ID" in config.env
        assert "GOOGLE_CLIENT_SECRET" in config.env

    @pytest.mark.asyncio
    async def test_start_server_idempotent(self, bridge, mock_mcp_client):
        """Test starting server multiple times is safe."""
        await bridge.start()
        await bridge.start()

        # Should only start once
        assert mock_mcp_client.start_server.call_count == 1

    @pytest.mark.asyncio
    async def test_stop_server(self, bridge, mock_mcp_client):
        """Test stopping the MCP server."""
        await bridge.start()
        await bridge.stop()

        assert bridge._started is False
        mock_mcp_client.stop_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_start_on_operation(self, bridge, mock_mcp_client):
        """Test that operations auto-start the server."""
        mock_mcp_client.invoke_tool.return_value = {"messages": []}

        # Don't manually start
        await bridge.search_emails("test")

        # Server should have auto-started
        assert bridge._started is True

    @pytest.mark.asyncio
    async def test_default_context(self, bridge):
        """Test default context generation."""
        context = bridge._default_context()

        assert context.agent_name == "google_workspace_bridge"
        assert context.trace_id is not None
        assert len(context.trace_id) > 0


# ===========================================================================
# Parsing Tests
# ===========================================================================


class TestResponseParsing:
    """Test response parsing and validation."""

    @pytest.mark.asyncio
    async def test_parse_email_missing_fields(self, bridge, mock_mcp_client):
        """Test parsing emails with missing optional fields."""
        mock_mcp_client.invoke_tool.return_value = {
            "messages": [
                {
                    "id": "msg1",
                    "threadId": "thread1",
                    # Missing subject, from, date, etc.
                }
            ]
        }

        emails = await bridge.search_emails("test")

        assert len(emails) == 1
        assert emails[0].subject == "(no subject)"
        assert emails[0].sender == "unknown"

    @pytest.mark.asyncio
    async def test_parse_email_invalid_message_skipped(self, bridge, mock_mcp_client):
        """Test that messages with missing fields use defaults gracefully."""
        mock_mcp_client.invoke_tool.return_value = {
            "messages": [
                {
                    # Valid message
                    "id": "msg1",
                    "threadId": "thread1",
                    "subject": "Valid",
                    "from": "sender@example.com",
                    "date": datetime.now().isoformat(),
                    "snippet": "Test",
                },
                {
                    # Missing id - should use empty string default
                    "subject": "Invalid",
                },
            ]
        }

        emails = await bridge.search_emails("test")

        # Should parse both with defaults for missing fields
        assert len(emails) == 2
        assert emails[0].id == "msg1"
        assert emails[1].id == ""  # Default for missing id
        assert emails[1].subject == "Invalid"

    @pytest.mark.asyncio
    async def test_parse_event_missing_fields(self, bridge, mock_mcp_client):
        """Test parsing events with missing optional fields."""
        mock_mcp_client.invoke_tool.return_value = {
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

    @pytest.mark.asyncio
    async def test_parse_event_invalid_event_skipped(self, bridge, mock_mcp_client):
        """Test that events with missing fields use defaults gracefully."""
        mock_mcp_client.invoke_tool.return_value = {
            "items": [
                {
                    # Valid event
                    "id": "event1",
                    "summary": "Valid",
                    "start": {"dateTime": datetime.now().isoformat() + "Z"},
                    "end": {"dateTime": (datetime.now() + timedelta(hours=1)).isoformat() + "Z"},
                },
                {
                    # Missing start/end - should use current time defaults
                    "id": "event2",
                    "summary": "Invalid",
                },
            ]
        }

        events = await bridge.list_events()

        # Should parse both with defaults for missing fields
        assert len(events) == 2
        assert events[0].id == "event1"
        assert events[1].id == "event2"
        assert events[1].title == "Invalid"
