"""
Unit tests for the Executor agent.

Tests action parsing, validation, execution, and error handling.
Mocks Google Workspace bridge to avoid external dependencies.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from klabautermann.agents.executor import Executor
from klabautermann.core.models import ActionType, AgentMessage
from klabautermann.mcp.google_workspace import (
    CalendarEvent,
    CreateEventResult,
    EmailMessage,
    GoogleWorkspaceBridge,
    SendEmailResult,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_google_bridge():
    """Mock GoogleWorkspaceBridge for testing."""
    bridge = Mock(spec=GoogleWorkspaceBridge)
    bridge.send_email = AsyncMock()
    bridge.get_recent_emails = AsyncMock()
    bridge.create_event = AsyncMock()
    bridge.get_todays_events = AsyncMock()
    return bridge


@pytest.fixture
def executor(mock_google_bridge):
    """Executor agent with mocked Google bridge."""
    config = {"model": "claude-3-5-sonnet-20241022"}
    agent = Executor(name="executor", config=config, google_bridge=mock_google_bridge)
    return agent


@pytest.fixture
def sample_message():
    """Sample AgentMessage for testing with action_type format."""
    return AgentMessage(
        trace_id="test-trace-123",
        source_agent="orchestrator",
        target_agent="executor",
        intent="execute_action",
        payload={
            "action": "Send email to Sarah",
            "action_type": "email_send",  # Structured action type from LLM
            "context": {"email": "sarah@example.com"},
        },
    )


# ===========================================================================
# Test Action Parsing
# ===========================================================================


class TestActionParsing:
    """Test action_type based parsing into ActionRequest.

    Tests verify that action_type from context is used for parsing,
    not keyword detection from action strings.
    """

    @pytest.mark.asyncio
    async def test_parse_email_send(self, executor):
        """Test parsing email_send action_type."""
        context = {"action_type": "email_send"}
        request = await executor._parse_action("legacy action string", context, "trace-123")
        assert request.type == ActionType.EMAIL_SEND
        assert request.draft_only is True  # Default is True for safety

    @pytest.mark.asyncio
    async def test_parse_email_draft(self, executor):
        """Test parsing email_send with draft_only flag."""
        context = {"action_type": "email_send", "draft_only": True}
        request = await executor._parse_action("draft email", context, "trace-123")
        assert request.type == ActionType.EMAIL_SEND
        assert request.draft_only is True

    @pytest.mark.asyncio
    async def test_parse_email_search(self, executor):
        """Test parsing email_search action_type with gmail_query."""
        context = {"action_type": "email_search", "gmail_query": "from:sarah"}
        request = await executor._parse_action("check emails", context, "trace-123")
        assert request.type == ActionType.EMAIL_SEARCH
        assert request.query == "from:sarah"

    @pytest.mark.asyncio
    async def test_parse_email_search_defaults_to_inbox(self, executor):
        """Test email_search defaults to inbox query when gmail_query not provided."""
        context = {"action_type": "email_search"}
        request = await executor._parse_action("any emails?", context, "trace-123")
        assert request.type == ActionType.EMAIL_SEARCH
        assert request.query == "in:inbox"

    @pytest.mark.asyncio
    async def test_parse_calendar_create(self, executor):
        """Test parsing calendar_create action_type."""
        context = {"action_type": "calendar_create"}
        request = await executor._parse_action("schedule meeting", context, "trace-123")
        assert request.type == ActionType.CALENDAR_CREATE

    @pytest.mark.asyncio
    async def test_parse_calendar_list(self, executor):
        """Test parsing calendar_list action_type."""
        context = {"action_type": "calendar_list"}
        request = await executor._parse_action("what's on my calendar", context, "trace-123")
        assert request.type == ActionType.CALENDAR_LIST

    @pytest.mark.asyncio
    async def test_parse_no_action_type_defaults_to_inbox(self, executor):
        """Test that missing action_type defaults to email search with inbox."""
        context = {}  # No action_type
        request = await executor._parse_action("something vague", context, "trace-123")
        assert request.type == ActionType.EMAIL_SEARCH
        assert request.query == "in:inbox"


# ===========================================================================
# Test Email Extraction from Context
# ===========================================================================


class TestEmailExtraction:
    """Test extracting email addresses from context."""

    def test_find_email_direct_field(self, executor):
        """Test finding email in direct field."""
        context = {"email": "sarah@example.com"}
        email = executor._find_email_in_context(context)
        assert email == "sarah@example.com"

    def test_find_email_in_results(self, executor):
        """Test finding email in search results."""
        context = {
            "results": [
                {"name": "Sarah", "email": "sarah@example.com"},
                {"name": "John", "email": "john@example.com"},
            ]
        }
        email = executor._find_email_in_context(context)
        assert email == "sarah@example.com"

    def test_find_email_in_content_string(self, executor):
        """Test finding email via regex in content string."""
        context = {"result": "Sarah's email is sarah.chen@example.com"}
        email = executor._find_email_in_context(context)
        assert email == "sarah.chen@example.com"

    def test_find_email_not_found(self, executor):
        """Test when no email is found."""
        context = {"result": "No email here"}
        email = executor._find_email_in_context(context)
        assert email is None


# ===========================================================================
# Test Request Validation
# ===========================================================================


class TestRequestValidation:
    """Test validation of action requests."""

    @pytest.mark.asyncio
    async def test_validate_email_send_with_recipient(self, executor):
        """Test validation passes when recipient email is in context."""
        from klabautermann.core.models import ActionRequest

        request = ActionRequest(type=ActionType.EMAIL_SEND)
        context = {"email": "sarah@example.com"}

        result = await executor._validate_request(request, context, "trace-123")

        assert result.success is True
        assert request.target == "sarah@example.com"

    @pytest.mark.asyncio
    async def test_validate_email_send_without_recipient(self, executor):
        """Test validation fails when recipient email is missing."""
        from klabautermann.core.models import ActionRequest

        request = ActionRequest(type=ActionType.EMAIL_SEND)
        context = {}

        result = await executor._validate_request(request, context, "trace-123")

        assert result.success is False
        assert "email address" in result.message.lower()

    @pytest.mark.asyncio
    async def test_validate_calendar_create_with_times(self, executor):
        """Test validation passes when event times are provided."""
        from klabautermann.core.models import ActionRequest

        request = ActionRequest(
            type=ActionType.CALENDAR_CREATE,
            start_time="2026-01-15T14:00:00",
            end_time="2026-01-15T15:00:00",
        )
        context = {}

        result = await executor._validate_request(request, context, "trace-123")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_validate_calendar_create_without_times(self, executor):
        """Test validation fails when event times are missing."""
        from klabautermann.core.models import ActionRequest

        request = ActionRequest(type=ActionType.CALENDAR_CREATE)
        context = {}

        result = await executor._validate_request(request, context, "trace-123")

        assert result.success is False
        assert "start and end time" in result.message.lower()

    @pytest.mark.asyncio
    async def test_validate_calendar_create_invalid_time_format(self, executor):
        """Test validation fails with invalid time format."""
        from klabautermann.core.models import ActionRequest

        request = ActionRequest(
            type=ActionType.CALENDAR_CREATE,
            start_time="not-a-valid-time",
            end_time="also-invalid",
        )
        context = {}

        result = await executor._validate_request(request, context, "trace-123")

        assert result.success is False
        assert "invalid" in result.message.lower()


# ===========================================================================
# Test Action Execution - Email
# ===========================================================================


class TestEmailExecution:
    """Test email action execution."""

    @pytest.mark.asyncio
    async def test_send_email_success(self, executor, mock_google_bridge):
        """Test successful email drafting (new behavior: always draft first)."""
        from klabautermann.core.models import ActionRequest

        mock_google_bridge.send_email.return_value = SendEmailResult(
            success=True, message_id="msg-123", is_draft=True
        )

        request = ActionRequest(
            type=ActionType.EMAIL_SEND,
            target="sarah@example.com",
            subject="Test Subject",
            body="Test body",
        )

        result = await executor._execute_action(request, {}, "trace-123")

        assert result.success is True
        # New behavior: always drafts first for safety
        assert "drafted" in result.message.lower()
        assert result.needs_confirmation is True
        assert result.details["draft_id"] == "msg-123"

    @pytest.mark.asyncio
    async def test_draft_email_success(self, executor, mock_google_bridge):
        """Test successful email drafting."""
        from klabautermann.core.models import ActionRequest

        mock_google_bridge.send_email.return_value = SendEmailResult(
            success=True, message_id="draft-123", is_draft=True
        )

        request = ActionRequest(
            type=ActionType.EMAIL_SEND,
            target="john@example.com",
            subject="Draft Subject",
            body="Draft body",
            draft_only=True,
        )

        result = await executor._execute_action(request, {}, "trace-123")

        assert result.success is True
        assert "drafted" in result.message

    @pytest.mark.asyncio
    async def test_send_email_failure(self, executor, mock_google_bridge):
        """Test email sending failure."""
        from klabautermann.core.models import ActionRequest

        mock_google_bridge.send_email.return_value = SendEmailResult(
            success=False, error="API error: Rate limit exceeded"
        )

        request = ActionRequest(
            type=ActionType.EMAIL_SEND,
            target="sarah@example.com",
            subject="Test",
            body="Test",
        )

        result = await executor._execute_action(request, {}, "trace-123")

        assert result.success is False
        assert "Rate limit exceeded" in result.message

    @pytest.mark.asyncio
    async def test_search_emails_found(self, executor, mock_google_bridge):
        """Test email search with results (uses new handlers)."""
        from klabautermann.core.models import ActionRequest

        # New handler uses search_emails instead of get_recent_emails
        mock_google_bridge.search_emails.return_value = [
            EmailMessage(
                id="1",
                thread_id="t1",
                subject="Meeting tomorrow",
                sender="sarah@example.com",
                date=datetime.now(),
                snippet="Let's meet at 2pm",
            ),
            EmailMessage(
                id="2",
                thread_id="t2",
                subject="Budget review",
                sender="john@example.com",
                date=datetime.now(),
                snippet="Please review the Q1 budget",
            ),
        ]

        request = ActionRequest(type=ActionType.EMAIL_SEARCH, query="recent emails")

        result = await executor._execute_action(request, {}, "trace-123")

        assert result.success is True
        assert "Showing 2 email(s)" in result.message
        assert "sarah@example.com" in result.message
        assert "Meeting tomorrow" in result.message

    @pytest.mark.asyncio
    async def test_search_emails_none_found(self, executor, mock_google_bridge):
        """Test email search with no results (uses new handlers)."""
        from klabautermann.core.models import ActionRequest

        # New handler uses search_emails instead of get_recent_emails
        mock_google_bridge.search_emails.return_value = []

        request = ActionRequest(type=ActionType.EMAIL_SEARCH, query="old emails")

        result = await executor._execute_action(request, {}, "trace-123")

        assert result.success is True
        assert "No emails found" in result.message


# ===========================================================================
# Test Action Execution - Calendar
# ===========================================================================


class TestCalendarExecution:
    """Test calendar action execution."""

    @pytest.mark.asyncio
    async def test_create_event_success(self, executor, mock_google_bridge):
        """Test successful event creation."""
        from klabautermann.core.models import ActionRequest

        mock_google_bridge.create_event.return_value = CreateEventResult(
            success=True,
            event_id="event-123",
            event_link="https://calendar.google.com/event/123",
        )

        request = ActionRequest(
            type=ActionType.CALENDAR_CREATE,
            subject="Team Meeting",
            body="Discuss Q1 goals",
            start_time="2026-01-15T14:00:00",
            end_time="2026-01-15T15:00:00",
        )

        result = await executor._execute_action(request, {}, "trace-123")

        assert result.success is True
        assert "Team Meeting" in result.message
        assert result.details["event_id"] == "event-123"
        assert "calendar.google.com" in result.details["link"]

    @pytest.mark.asyncio
    async def test_create_event_failure(self, executor, mock_google_bridge):
        """Test event creation failure."""
        from klabautermann.core.models import ActionRequest

        mock_google_bridge.create_event.return_value = CreateEventResult(
            success=False, error="Calendar not found"
        )

        request = ActionRequest(
            type=ActionType.CALENDAR_CREATE,
            subject="Meeting",
            start_time="2026-01-15T14:00:00",
            end_time="2026-01-15T15:00:00",
        )

        result = await executor._execute_action(request, {}, "trace-123")

        assert result.success is False
        assert "Calendar not found" in result.message

    @pytest.mark.asyncio
    async def test_list_events_found(self, executor, mock_google_bridge):
        """Test listing calendar events."""
        from klabautermann.core.models import ActionRequest

        mock_google_bridge.get_todays_events.return_value = [
            CalendarEvent(
                id="1",
                title="Morning standup",
                start=datetime(2026, 1, 15, 9, 0),
                end=datetime(2026, 1, 15, 9, 30),
            ),
            CalendarEvent(
                id="2",
                title="Team meeting",
                start=datetime(2026, 1, 15, 14, 0),
                end=datetime(2026, 1, 15, 15, 0),
            ),
        ]

        request = ActionRequest(type=ActionType.CALENDAR_LIST)

        result = await executor._execute_action(request, {}, "trace-123")

        assert result.success is True
        assert "schedule" in result.message.lower()
        assert "Morning standup" in result.message
        assert "Team meeting" in result.message

    @pytest.mark.asyncio
    async def test_list_events_none_found(self, executor, mock_google_bridge):
        """Test listing calendar when no events exist."""
        from klabautermann.core.models import ActionRequest

        mock_google_bridge.get_todays_events.return_value = []

        request = ActionRequest(type=ActionType.CALENDAR_LIST)

        result = await executor._execute_action(request, {}, "trace-123")

        assert result.success is True
        assert "No events scheduled" in result.message


# ===========================================================================
# Test End-to-End Message Processing
# ===========================================================================


class TestMessageProcessing:
    """Test complete message processing flow."""

    @pytest.mark.asyncio
    async def test_process_email_send_complete(self, executor, mock_google_bridge, sample_message):
        """Test complete email sending flow (now creates draft first)."""
        mock_google_bridge.send_email.return_value = SendEmailResult(
            success=True, message_id="msg-123", is_draft=True
        )

        response = await executor.process_message(sample_message)

        assert response is not None
        assert response.source_agent == "executor"
        assert response.target_agent == "orchestrator"
        assert response.intent == "action_response"
        assert response.payload["success"] is True
        # New behavior: always drafts first for safety
        assert "drafted" in response.payload["result"].lower()
        assert response.payload.get("needs_confirmation") is True

    @pytest.mark.asyncio
    async def test_process_missing_action(self, executor):
        """Test processing message with missing action."""
        msg = AgentMessage(
            trace_id="test-123",
            source_agent="orchestrator",
            target_agent="executor",
            intent="execute_action",
            payload={"context": {}},  # No action field
        )

        response = await executor.process_message(msg)

        assert response is not None
        assert response.payload["success"] is False
        assert "No action specified" in response.payload["result"]

    @pytest.mark.asyncio
    async def test_process_missing_email_in_context(self, executor):
        """Test processing email action without recipient email."""
        msg = AgentMessage(
            trace_id="test-123",
            source_agent="orchestrator",
            target_agent="executor",
            intent="execute_action",
            payload={
                "action": "Send email to Sarah",
                "action_type": "email_send",  # Need action_type
                "context": {},  # No email in context
            },
        )

        response = await executor.process_message(msg)

        assert response is not None
        assert response.payload["success"] is False
        assert "email address" in response.payload["result"].lower()

    @pytest.mark.asyncio
    async def test_process_exception_handling(self, executor, mock_google_bridge):
        """Test exception handling during execution."""
        mock_google_bridge.send_email.side_effect = Exception("Network error")

        msg = AgentMessage(
            trace_id="test-123",
            source_agent="orchestrator",
            target_agent="executor",
            intent="execute_action",
            payload={
                "action": "Send email to Sarah",
                "action_type": "email_send",  # Need action_type
                "context": {"email": "sarah@example.com"},
            },
        )

        response = await executor.process_message(msg)

        assert response is not None
        assert response.payload["success"] is False
        assert "Network error" in response.payload["result"]


# ===========================================================================
# Test Agent Configuration
# ===========================================================================


class TestAgentConfiguration:
    """Test agent initialization and configuration."""

    def test_default_configuration(self):
        """Test agent initializes with default config."""
        agent = Executor()

        assert agent.name == "executor"
        assert agent.model == "claude-3-5-sonnet-20241022"
        assert isinstance(agent.google, GoogleWorkspaceBridge)

    def test_custom_configuration(self):
        """Test agent initializes with custom config."""
        config = {"model": "claude-3-opus-20240229"}
        agent = Executor(name="custom_executor", config=config)

        assert agent.name == "custom_executor"
        assert agent.model == "claude-3-opus-20240229"

    def test_custom_google_bridge(self, mock_google_bridge):
        """Test agent accepts custom Google bridge."""
        agent = Executor(google_bridge=mock_google_bridge)

        assert agent.google is mock_google_bridge


# ===========================================================================
# Test Security Requirements
# ===========================================================================


class TestSecurityRequirements:
    """Test that security requirements are enforced."""

    @pytest.mark.asyncio
    async def test_never_send_to_unverified_email(self, executor):
        """Test that emails are never sent to unverified addresses."""
        msg = AgentMessage(
            trace_id="test-123",
            source_agent="orchestrator",
            target_agent="executor",
            intent="execute_action",
            payload={
                "action": "Send email to random person",
                "action_type": "email_send",  # Need action_type
                "context": {},  # No email provided
            },
        )

        response = await executor.process_message(msg)

        # Should fail validation, not attempt to send
        assert response.payload["success"] is False
        assert "email address" in response.payload["result"].lower()

    @pytest.mark.asyncio
    async def test_never_hallucinate_missing_info(self, executor):
        """Test that missing information is never hallucinated."""
        msg = AgentMessage(
            trace_id="test-123",
            source_agent="orchestrator",
            target_agent="executor",
            intent="execute_action",
            payload={
                "action": "Schedule a meeting",
                "action_type": "calendar_create",  # Need action_type
                "context": {},  # No time information
            },
        )

        response = await executor.process_message(msg)

        # Should ask for missing information
        assert response.payload["success"] is False
        assert "start and end time" in response.payload["result"].lower()
