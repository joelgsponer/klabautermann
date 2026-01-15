"""
Google Workspace MCP Bridge - Clean interface to Gmail and Calendar via MCP.

Wraps the Google Workspace MCP server and provides Pydantic-validated responses
for Gmail and Calendar operations. Designed for easy fallback to direct API calls
if MCP proves unreliable.

Reference: specs/architecture/AGENTS.md Section 1.4
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from klabautermann.core.exceptions import MCPError
from klabautermann.core.logger import logger
from klabautermann.mcp.client import MCPClient, MCPServerConfig, ToolInvocationContext


# ===========================================================================
# Response Models
# ===========================================================================


class EmailMessage(BaseModel):
    """Parsed email message from Gmail."""

    id: str
    thread_id: str
    subject: str
    sender: str
    recipient: str | None = None
    date: datetime
    snippet: str
    body: str | None = None
    is_unread: bool = False


class CalendarEvent(BaseModel):
    """Parsed calendar event from Google Calendar."""

    id: str
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    description: str | None = None
    attendees: list[str] = Field(default_factory=list)


class SendEmailResult(BaseModel):
    """Result of sending or drafting an email."""

    success: bool
    message_id: str | None = None
    is_draft: bool = False
    error: str | None = None


class CreateEventResult(BaseModel):
    """Result of creating a calendar event."""

    success: bool
    event_id: str | None = None
    event_link: str | None = None
    error: str | None = None


# ===========================================================================
# Google Workspace Bridge
# ===========================================================================


class GoogleWorkspaceBridge:
    """
    Bridge to Google Workspace services via MCP.

    Wraps the Google Workspace MCP server and provides a clean interface
    for Gmail and Calendar operations with Pydantic-validated responses.

    Example:
        bridge = GoogleWorkspaceBridge()
        await bridge.start()
        emails = await bridge.search_emails("from:sarah@acme.com")
        events = await bridge.get_todays_events()
        await bridge.stop()

    Note:
        If MCP proves unreliable, this class can be refactored to use direct
        Google API calls while maintaining the same interface.
    """

    SERVER_CONFIG = MCPServerConfig(
        name="google-workspace",
        command=["npx", "-y", "@anthropic/mcp-google-workspace"],
        env={},  # Populated with credentials during start()
        timeout=30.0,
    )

    def __init__(self, mcp_client: MCPClient | None = None) -> None:
        """
        Initialize the Google Workspace bridge.

        Args:
            mcp_client: Optional shared MCP client. If not provided,
                       creates a dedicated client for this bridge.
        """
        self._client = mcp_client or MCPClient()
        self._started = False

    async def start(self) -> None:
        """
        Start the Google Workspace MCP server.

        Injects OAuth credentials from environment variables and initializes
        the MCP connection.

        Raises:
            MCPConnectionError: If server fails to start.
        """
        if self._started:
            logger.debug("[WHISPER] Google Workspace MCP server already running")
            return

        # Inject credentials from environment
        config = MCPServerConfig(
            name=self.SERVER_CONFIG.name,
            command=self.SERVER_CONFIG.command,
            env={
                "GOOGLE_REFRESH_TOKEN": os.getenv("GOOGLE_REFRESH_TOKEN", ""),
                "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID", ""),
                "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET", ""),
            },
            timeout=self.SERVER_CONFIG.timeout,
        )

        await self._client.start_server(config)
        self._started = True
        logger.info("[CHART] Google Workspace MCP server started")

    async def stop(self) -> None:
        """Stop the Google Workspace MCP server."""
        if self._started:
            await self._client.stop_server(self.SERVER_CONFIG.name)
            self._started = False
            logger.info("[CHART] Google Workspace MCP server stopped")

    # ===========================================================================
    # Gmail Operations
    # ===========================================================================

    async def search_emails(
        self,
        query: str,
        max_results: int = 10,
        context: ToolInvocationContext | None = None,
    ) -> list[EmailMessage]:
        """
        Search Gmail messages with a query.

        Args:
            query: Gmail search query (e.g., "from:sarah@acme.com" or "is:unread")
            max_results: Maximum number of messages to return (default: 10)
            context: Optional invocation context for tracing

        Returns:
            List of matching email messages

        Raises:
            MCPError: If search fails
        """
        await self.start()

        try:
            result = await self._client.invoke_tool(
                server_name=self.SERVER_CONFIG.name,
                tool_name="gmail_search_messages",
                arguments={
                    "query": query,
                    "maxResults": max_results,
                },
                context=context or self._default_context(),
            )

            return self._parse_email_list(result)

        except Exception as e:
            logger.error(
                f"[STORM] Gmail search failed: {e}",
                extra={"query": query},
            )
            raise MCPError(f"Gmail search failed: {e}", tool_name="gmail_search_messages") from e

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        draft_only: bool = False,
        context: ToolInvocationContext | None = None,
    ) -> SendEmailResult:
        """
        Send or draft an email via Gmail.

        Args:
            to: Recipient email address
            subject: Email subject line
            body: Email body (plain text)
            cc: Optional CC recipients (comma-separated)
            draft_only: If True, save as draft instead of sending
            context: Optional invocation context for tracing

        Returns:
            Result containing message ID or error details
        """
        await self.start()

        tool_name = "gmail_create_draft" if draft_only else "gmail_send_message"

        try:
            arguments: dict[str, Any] = {
                "to": to,
                "subject": subject,
                "body": body,
            }
            if cc:
                arguments["cc"] = cc

            result = await self._client.invoke_tool(
                server_name=self.SERVER_CONFIG.name,
                tool_name=tool_name,
                arguments=arguments,
                context=context or self._default_context(),
            )

            return SendEmailResult(
                success=True,
                message_id=result.get("id"),
                is_draft=draft_only,
            )

        except Exception as e:
            logger.error(
                f"[STORM] Email {'draft' if draft_only else 'send'} failed: {e}",
                extra={"to": to, "subject": subject},
            )
            return SendEmailResult(
                success=False,
                error=str(e),
                is_draft=draft_only,
            )

    async def get_recent_emails(
        self,
        hours: int = 24,
        context: ToolInvocationContext | None = None,
    ) -> list[EmailMessage]:
        """
        Get emails from the last N hours.

        Args:
            hours: Number of hours to look back (default: 24)
            context: Optional invocation context for tracing

        Returns:
            List of recent email messages
        """
        query = f"newer_than:{hours}h"
        return await self.search_emails(query, max_results=50, context=context)

    # ===========================================================================
    # Calendar Operations
    # ===========================================================================

    async def list_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        max_results: int = 10,
        context: ToolInvocationContext | None = None,
    ) -> list[CalendarEvent]:
        """
        List calendar events in a time range.

        Args:
            start: Start of time range (default: now)
            end: End of time range (default: 7 days from start)
            max_results: Maximum number of events to return (default: 10)
            context: Optional invocation context for tracing

        Returns:
            List of calendar events in the specified range

        Raises:
            MCPError: If listing fails
        """
        await self.start()

        if start is None:
            start = datetime.now()
        if end is None:
            end = start + timedelta(days=7)

        try:
            result = await self._client.invoke_tool(
                server_name=self.SERVER_CONFIG.name,
                tool_name="calendar_list_events",
                arguments={
                    "timeMin": start.isoformat() + "Z",
                    "timeMax": end.isoformat() + "Z",
                    "maxResults": max_results,
                },
                context=context or self._default_context(),
            )

            return self._parse_event_list(result)

        except Exception as e:
            logger.error(
                f"[STORM] Calendar list failed: {e}",
                extra={"start": start.isoformat(), "end": end.isoformat()},
            )
            raise MCPError(f"Calendar list failed: {e}", tool_name="calendar_list_events") from e

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        context: ToolInvocationContext | None = None,
    ) -> CreateEventResult:
        """
        Create a new calendar event.

        Args:
            title: Event title/summary
            start: Event start time
            end: Event end time
            description: Optional event description
            location: Optional event location
            attendees: Optional list of attendee email addresses
            context: Optional invocation context for tracing

        Returns:
            Result containing event ID and link, or error details
        """
        await self.start()

        try:
            arguments: dict[str, Any] = {
                "summary": title,
                "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
            }

            if description:
                arguments["description"] = description
            if location:
                arguments["location"] = location
            if attendees:
                arguments["attendees"] = [{"email": email} for email in attendees]

            result = await self._client.invoke_tool(
                server_name=self.SERVER_CONFIG.name,
                tool_name="calendar_create_event",
                arguments=arguments,
                context=context or self._default_context(),
            )

            return CreateEventResult(
                success=True,
                event_id=result.get("id"),
                event_link=result.get("htmlLink"),
            )

        except Exception as e:
            logger.error(
                f"[STORM] Calendar event creation failed: {e}",
                extra={"title": title, "start": start.isoformat()},
            )
            return CreateEventResult(
                success=False,
                error=str(e),
            )

    async def get_todays_events(
        self,
        context: ToolInvocationContext | None = None,
    ) -> list[CalendarEvent]:
        """
        Get all events for today.

        Args:
            context: Optional invocation context for tracing

        Returns:
            List of today's calendar events
        """
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        return await self.list_events(start, end, max_results=50, context=context)

    async def get_tomorrows_events(
        self,
        context: ToolInvocationContext | None = None,
    ) -> list[CalendarEvent]:
        """
        Get all events for tomorrow.

        Args:
            context: Optional invocation context for tracing

        Returns:
            List of tomorrow's calendar events
        """
        tomorrow = datetime.now() + timedelta(days=1)
        start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
        return await self.list_events(start, end, max_results=50, context=context)

    # ===========================================================================
    # Helper Methods
    # ===========================================================================

    def _default_context(self) -> ToolInvocationContext:
        """Create a default invocation context with generated trace ID."""
        return ToolInvocationContext(
            trace_id=str(uuid.uuid4()),
            agent_name="google_workspace_bridge",
        )

    def _parse_email_list(self, result: dict[str, Any]) -> list[EmailMessage]:
        """
        Parse MCP response into list of EmailMessage models.

        Args:
            result: Raw MCP tool result

        Returns:
            List of validated EmailMessage instances
        """
        messages = result.get("messages", [])
        parsed: list[EmailMessage] = []

        for msg in messages:
            try:
                # Parse date, handling various formats
                date_str = msg.get("date", datetime.now().isoformat())
                try:
                    # Try ISO format first
                    date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    # Fall back to now if parsing fails
                    date = datetime.now()

                email = EmailMessage(
                    id=msg.get("id", ""),
                    thread_id=msg.get("threadId", ""),
                    subject=msg.get("subject", "(no subject)"),
                    sender=msg.get("from", "unknown"),
                    recipient=msg.get("to"),
                    date=date,
                    snippet=msg.get("snippet", ""),
                    body=msg.get("body"),
                    is_unread="UNREAD" in msg.get("labelIds", []),
                )
                parsed.append(email)

            except Exception as e:
                logger.warning(
                    f"[SWELL] Failed to parse email message: {e}",
                    extra={"message_id": msg.get("id")},
                )
                continue

        return parsed

    def _parse_event_list(self, result: dict[str, Any]) -> list[CalendarEvent]:
        """
        Parse MCP response into list of CalendarEvent models.

        Args:
            result: Raw MCP tool result

        Returns:
            List of validated CalendarEvent instances
        """
        events = result.get("items", [])
        parsed: list[CalendarEvent] = []

        for evt in events:
            try:
                # Parse start/end times
                start_data = evt.get("start", {})
                end_data = evt.get("end", {})

                # Handle dateTime vs date (all-day events)
                start_str = start_data.get("dateTime") or start_data.get(
                    "date", datetime.now().isoformat()
                )
                end_str = end_data.get("dateTime") or end_data.get(
                    "date", datetime.now().isoformat()
                )

                # Remove Z suffix and parse
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

                event = CalendarEvent(
                    id=evt.get("id", ""),
                    title=evt.get("summary", "(no title)"),
                    start=start,
                    end=end,
                    location=evt.get("location"),
                    description=evt.get("description"),
                    attendees=[a.get("email", "") for a in evt.get("attendees", [])],
                )
                parsed.append(event)

            except Exception as e:
                logger.warning(
                    f"[SWELL] Failed to parse calendar event: {e}",
                    extra={"event_id": evt.get("id")},
                )
                continue

        return parsed


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "CalendarEvent",
    "CreateEventResult",
    "EmailMessage",
    "GoogleWorkspaceBridge",
    "SendEmailResult",
]
