"""
MCP module - Model Context Protocol integration.

Contains:
- client: MCP client wrapper for external tool execution
- google_workspace: Gmail and Calendar integration via MCP

Supported MCP servers (Sprint 2+):
- Gmail: Email reading and sending
- Google Calendar: Event management
- Filesystem: Local file operations
"""

from klabautermann.mcp.google_workspace import (
    CalendarEvent,
    CreateEventResult,
    EmailMessage,
    GoogleWorkspaceBridge,
    SendEmailResult,
)


__all__ = [
    "GoogleWorkspaceBridge",
    "EmailMessage",
    "CalendarEvent",
    "SendEmailResult",
    "CreateEventResult",
]
