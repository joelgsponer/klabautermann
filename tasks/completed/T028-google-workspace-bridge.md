# Create Google Workspace MCP Bridge

## Metadata
- **ID**: T028
- **Priority**: P0
- **Category**: core
- **Effort**: L
- **Status**: completed
- **Assignee**: purser

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.4
- Related: [PRD.md](../../specs/PRD.md) Section 6

## Dependencies
- [x] T026 - MCP client wrapper
- [x] T027 - Google OAuth bootstrap

## Context
The Executor agent needs to interact with Gmail and Calendar through MCP. This task creates the Google Workspace bridge that wraps the Google Workspace MCP server and provides a clean interface for the Executor. If MCP proves unreliable, this module can be swapped for direct API calls.

## Requirements
- [x] Create `src/klabautermann/mcp/google_workspace.py`:

### Gmail Operations
- [x] `search_emails` - Search inbox with query
- [x] `send_email` - Send or draft email
- [x] `get_recent_emails` - Get emails from last N hours

### Calendar Operations
- [x] `list_events` - List events in time range
- [x] `create_event` - Create new event
- [x] `get_todays_events` - Get today's events
- [x] `get_tomorrows_events` - Get tomorrow's events

### Response Formatting
- [x] Parse MCP responses into Pydantic models
- [x] Handle errors gracefully
- [x] Format results for agent consumption

### Configuration
- [x] Server command configuration
- [x] Credential injection from environment
- [x] Timeout configuration

### Fallback Support
- [x] Interface that can be backed by MCP or direct API
- [x] Easy swap if MCP proves unreliable

## Acceptance Criteria
- [x] Gmail search returns recent messages
- [x] Gmail send creates draft or sends message
- [x] Calendar list returns upcoming events
- [x] Calendar create adds event
- [x] Errors return informative messages

## Implementation Notes

```python
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
import os

from klabautermann.mcp.client import MCPClient, MCPServerConfig, ToolInvocationContext
from klabautermann.core.logger import logger


# ====================
# RESPONSE MODELS
# ====================

class EmailMessage(BaseModel):
    """Parsed email message."""
    id: str
    thread_id: str
    subject: str
    sender: str
    recipient: Optional[str] = None
    date: datetime
    snippet: str
    body: Optional[str] = None
    is_unread: bool = False


class CalendarEvent(BaseModel):
    """Parsed calendar event."""
    id: str
    title: str
    start: datetime
    end: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    attendees: List[str] = Field(default_factory=list)


class SendEmailResult(BaseModel):
    """Result of sending email."""
    success: bool
    message_id: Optional[str] = None
    is_draft: bool = False
    error: Optional[str] = None


class CreateEventResult(BaseModel):
    """Result of creating event."""
    success: bool
    event_id: Optional[str] = None
    event_link: Optional[str] = None
    error: Optional[str] = None


# ====================
# GOOGLE WORKSPACE BRIDGE
# ====================

class GoogleWorkspaceBridge:
    """
    Bridge to Google Workspace services via MCP.

    Wraps the Google Workspace MCP server and provides
    a clean interface for Gmail and Calendar operations.
    """

    SERVER_CONFIG = MCPServerConfig(
        name="google-workspace",
        command=["npx", "-y", "@anthropic/mcp-google-workspace"],
        env={},  # Will be populated with credentials
        timeout=30.0,
    )

    def __init__(self, mcp_client: Optional[MCPClient] = None):
        """
        Initialize the bridge.

        Args:
            mcp_client: Optional shared MCP client. If not provided,
                        creates a dedicated client.
        """
        self._client = mcp_client or MCPClient()
        self._started = False

    async def start(self) -> None:
        """Start the Google Workspace MCP server."""
        if self._started:
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
        """Stop the MCP server."""
        if self._started:
            await self._client.stop_server(self.SERVER_CONFIG.name)
            self._started = False

    # ====================
    # GMAIL OPERATIONS
    # ====================

    async def search_emails(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[ToolInvocationContext] = None,
    ) -> List[EmailMessage]:
        """
        Search Gmail messages.

        Args:
            query: Gmail search query (e.g., "from:sarah@acme.com")
            max_results: Maximum messages to return.
            context: Invocation context for logging.

        Returns:
            List of matching email messages.
        """
        await self.start()

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

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        draft_only: bool = False,
        context: Optional[ToolInvocationContext] = None,
    ) -> SendEmailResult:
        """
        Send or draft an email.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body: Email body (plain text).
            cc: Optional CC recipients.
            draft_only: If True, save as draft instead of sending.
            context: Invocation context.

        Returns:
            Result with message ID or error.
        """
        await self.start()

        tool_name = "gmail_create_draft" if draft_only else "gmail_send_message"

        try:
            result = await self._client.invoke_tool(
                server_name=self.SERVER_CONFIG.name,
                tool_name=tool_name,
                arguments={
                    "to": to,
                    "subject": subject,
                    "body": body,
                    "cc": cc,
                },
                context=context or self._default_context(),
            )

            return SendEmailResult(
                success=True,
                message_id=result.get("id"),
                is_draft=draft_only,
            )

        except Exception as e:
            return SendEmailResult(success=False, error=str(e))

    async def get_recent_emails(
        self,
        hours: int = 24,
        context: Optional[ToolInvocationContext] = None,
    ) -> List[EmailMessage]:
        """Get emails from the last N hours."""
        query = f"newer_than:{hours}h"
        return await self.search_emails(query, context=context)

    # ====================
    # CALENDAR OPERATIONS
    # ====================

    async def list_events(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        max_results: int = 10,
        context: Optional[ToolInvocationContext] = None,
    ) -> List[CalendarEvent]:
        """
        List calendar events in time range.

        Args:
            start: Start of time range (default: now).
            end: End of time range (default: 7 days from now).
            max_results: Maximum events to return.
            context: Invocation context.

        Returns:
            List of calendar events.
        """
        await self.start()

        if start is None:
            start = datetime.now()
        if end is None:
            end = start + timedelta(days=7)

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

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        context: Optional[ToolInvocationContext] = None,
    ) -> CreateEventResult:
        """
        Create a calendar event.

        Args:
            title: Event title.
            start: Start time.
            end: End time.
            description: Optional description.
            location: Optional location.
            attendees: Optional list of attendee emails.
            context: Invocation context.

        Returns:
            Result with event ID or error.
        """
        await self.start()

        try:
            result = await self._client.invoke_tool(
                server_name=self.SERVER_CONFIG.name,
                tool_name="calendar_create_event",
                arguments={
                    "summary": title,
                    "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
                    "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
                    "description": description,
                    "location": location,
                    "attendees": [{"email": a} for a in (attendees or [])],
                },
                context=context or self._default_context(),
            )

            return CreateEventResult(
                success=True,
                event_id=result.get("id"),
                event_link=result.get("htmlLink"),
            )

        except Exception as e:
            return CreateEventResult(success=False, error=str(e))

    async def get_todays_events(
        self,
        context: Optional[ToolInvocationContext] = None,
    ) -> List[CalendarEvent]:
        """Get events for today."""
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        return await self.list_events(start, end, context=context)

    async def get_tomorrows_events(
        self,
        context: Optional[ToolInvocationContext] = None,
    ) -> List[CalendarEvent]:
        """Get events for tomorrow."""
        tomorrow = datetime.now() + timedelta(days=1)
        start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
        return await self.list_events(start, end, context=context)

    # ====================
    # HELPERS
    # ====================

    def _default_context(self) -> ToolInvocationContext:
        """Create default context for tool invocations."""
        import uuid
        return ToolInvocationContext(
            trace_id=str(uuid.uuid4()),
            agent_name="google_workspace_bridge",
        )

    def _parse_email_list(self, result: Dict) -> List[EmailMessage]:
        """Parse email list from MCP response."""
        messages = result.get("messages", [])
        return [
            EmailMessage(
                id=m.get("id", ""),
                thread_id=m.get("threadId", ""),
                subject=m.get("subject", "(no subject)"),
                sender=m.get("from", "unknown"),
                recipient=m.get("to"),
                date=datetime.fromisoformat(m.get("date", datetime.now().isoformat())),
                snippet=m.get("snippet", ""),
                is_unread="UNREAD" in m.get("labelIds", []),
            )
            for m in messages
        ]

    def _parse_event_list(self, result: Dict) -> List[CalendarEvent]:
        """Parse event list from MCP response."""
        events = result.get("items", [])
        return [
            CalendarEvent(
                id=e.get("id", ""),
                title=e.get("summary", "(no title)"),
                start=datetime.fromisoformat(
                    e.get("start", {}).get("dateTime", datetime.now().isoformat()).replace("Z", "")
                ),
                end=datetime.fromisoformat(
                    e.get("end", {}).get("dateTime", datetime.now().isoformat()).replace("Z", "")
                ),
                location=e.get("location"),
                description=e.get("description"),
                attendees=[a.get("email", "") for a in e.get("attendees", [])],
            )
            for e in events
        ]
```

**Fallback Note**: If MCP proves unreliable, this class can be refactored to use direct Google API calls while keeping the same interface. The Executor agent should depend on this interface, not the MCP implementation directly.

---

## Development Notes

**Date**: 2026-01-15

### Implementation

**Files Created**:
- `src/klabautermann/mcp/google_workspace.py` (492 lines) - Main bridge implementation
- `tests/unit/test_google_workspace.py` (598 lines) - Comprehensive unit tests

**Files Modified**:
- `src/klabautermann/mcp/__init__.py` - Added exports for GoogleWorkspaceBridge and response models

### Decisions Made

1. **Resilient Parsing**: Implemented forgiving parsing that fills in default values for missing fields rather than skipping invalid entries. This ensures maximum data availability even with malformed MCP responses.

2. **Auto-Start Behavior**: The bridge automatically starts the MCP server on first operation, removing the need for explicit lifecycle management by the caller.

3. **Convenience Methods**: Added `get_recent_emails()`, `get_todays_events()`, and `get_tomorrows_events()` as convenient wrappers around the core search/list methods.

4. **Result Models**: Email and calendar operations return structured result objects (`SendEmailResult`, `CreateEventResult`) that include success/error state, enabling graceful error handling at the agent level.

5. **Error Handling Strategy**:
   - Email/calendar operations catch exceptions and return Result objects with error details
   - Search/list operations propagate MCPError for explicit failure handling
   - Parsing errors are logged but don't crash - entries with parsing issues use sensible defaults

6. **OAuth Credential Injection**: Credentials are injected from environment variables (`GOOGLE_REFRESH_TOKEN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) during server start, following the pattern established in T027.

### Patterns Established

1. **Pydantic Response Models**: All MCP responses are parsed into strongly-typed Pydantic models for validation and type safety.

2. **Optional Context Propagation**: All methods accept optional `ToolInvocationContext` for trace ID propagation, falling back to auto-generated context.

3. **Lazy Server Initialization**: MCP server starts on first use, not in `__init__`, enabling bridge instantiation without immediate connection.

4. **Draft Mode Toggle**: Email sending supports `draft_only` parameter to switch between sending and drafting without separate methods.

### Testing

**Coverage**: 27 unit tests, all passing

Test organization:
- `TestEmailOperations` (9 tests) - Gmail search, send, drafts, error handling
- `TestCalendarOperations` (9 tests) - Event listing, creation, time range queries
- `TestBridgeLifecycle` (5 tests) - Server start/stop, idempotency, auto-start
- `TestResponseParsing` (4 tests) - Malformed data, missing fields, graceful degradation

Testing patterns:
- Mock MCP client with AsyncMock for isolated testing
- Fixture-based bridge setup for consistency
- Test both success and error paths for all operations
- Validate datetime parsing for ISO format and all-day events

### Issues Encountered

None. Implementation followed the MCP client patterns from T026 and integrated smoothly with the existing codebase.

### Next Steps

This bridge is ready for use by:
- **T029** - Executor agent (will use this bridge for tool execution)
- **T030** - Gmail tool handlers (higher-level agent operations)
- **T031** - Calendar tool handlers (higher-level agent operations)
