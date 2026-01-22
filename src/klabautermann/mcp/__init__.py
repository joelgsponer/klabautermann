"""
MCP module - Model Context Protocol integration.

Contains:
- client: MCP client wrapper for external tool execution
- google_workspace: Gmail and Calendar integration via direct API
- filesystem: Filesystem operations via MCP server

Supported MCP servers:
- Filesystem: Local file operations with sandboxed access
"""

from klabautermann.mcp.filesystem import (
    FilesystemBridge,
    FilesystemConfig,
)
from klabautermann.mcp.google_workspace import (
    CalendarEvent,
    CreateEventResult,
    EmailAttachment,
    EmailMessage,
    GoogleWorkspaceBridge,
    SendEmailResult,
)


__all__ = [
    "CalendarEvent",
    "CreateEventResult",
    "EmailAttachment",
    "EmailMessage",
    "FilesystemBridge",
    "FilesystemConfig",
    "GoogleWorkspaceBridge",
    "SendEmailResult",
]
