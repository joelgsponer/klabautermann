"""
Google Workspace Bridge - Direct API integration for Gmail and Calendar.

Uses Google APIs directly with OAuth2 refresh tokens, avoiding MCP subprocess
complexity. Provides Pydantic-validated responses for Gmail and Calendar operations.

Reference: specs/architecture/AGENTS.md Section 1.4
"""

from __future__ import annotations

import asyncio
import base64
import os
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import Any, ClassVar

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field

from klabautermann.core.exceptions import ExternalServiceError
from klabautermann.core.logger import logger


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


class EmailOperationResult(BaseModel):
    """Result of email management operations (delete, archive, label)."""

    success: bool
    message_id: str | None = None
    operation: str = ""  # "trash", "delete", "archive", "label", "unlabel"
    error: str | None = None


class GmailLabel(BaseModel):
    """Gmail label information."""

    id: str
    name: str
    type: str = "user"  # "system" or "user"
    message_count: int | None = None
    unread_count: int | None = None


# ===========================================================================
# Google Workspace Bridge
# ===========================================================================


class GoogleWorkspaceBridge:
    """
    Bridge to Google Workspace services via direct API calls.

    Uses OAuth2 refresh tokens from environment variables to authenticate
    with Gmail and Calendar APIs directly.

    Example:
        bridge = GoogleWorkspaceBridge()
        await bridge.start()
        emails = await bridge.search_emails("from:sarah@acme.com")
        events = await bridge.get_todays_events()

    Environment Variables Required:
        GOOGLE_CLIENT_ID: OAuth2 client ID
        GOOGLE_CLIENT_SECRET: OAuth2 client secret
        GOOGLE_REFRESH_TOKEN: OAuth2 refresh token with gmail and calendar scopes
    """

    # Gmail API scopes
    GMAIL_SCOPES: ClassVar[list[str]] = ["https://www.googleapis.com/auth/gmail.modify"]
    CALENDAR_SCOPES: ClassVar[list[str]] = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self) -> None:
        """Initialize the Google Workspace bridge."""
        self._credentials: Credentials | None = None
        self._gmail_service: Any = None
        self._calendar_service: Any = None
        self._started = False

    async def start(self) -> None:
        """
        Initialize Google API services.

        Creates OAuth2 credentials from environment variables and builds
        Gmail and Calendar service objects.

        Raises:
            ExternalServiceError: If credentials are missing or invalid.
        """
        if self._started:
            return

        # Get credentials from environment
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")

        if not all([client_id, client_secret, refresh_token]):
            missing = []
            if not client_id:
                missing.append("GOOGLE_CLIENT_ID")
            if not client_secret:
                missing.append("GOOGLE_CLIENT_SECRET")
            if not refresh_token:
                missing.append("GOOGLE_REFRESH_TOKEN")
            raise ExternalServiceError(
                "google",
                f"Missing required environment variables: {', '.join(missing)}",
            )

        # Create credentials from refresh token
        self._credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=self.GMAIL_SCOPES + self.CALENDAR_SCOPES,
        )

        # Refresh to get access token
        try:
            self._credentials.refresh(Request())
        except Exception as e:
            raise ExternalServiceError("google", f"Failed to refresh credentials: {e}") from e

        # Build services (run in executor to avoid blocking)
        loop = asyncio.get_event_loop()

        def build_services() -> tuple[Any, Any]:
            gmail = build("gmail", "v1", credentials=self._credentials)
            calendar = build("calendar", "v3", credentials=self._credentials)
            return gmail, calendar

        self._gmail_service, self._calendar_service = await loop.run_in_executor(
            None, build_services
        )

        self._started = True
        logger.info("[CHART] Google Workspace API services initialized")

    async def stop(self) -> None:
        """Clean up resources (no-op for direct API)."""
        self._started = False
        self._gmail_service = None
        self._calendar_service = None
        logger.info("[CHART] Google Workspace API services stopped")

    # ===========================================================================
    # Gmail Operations
    # ===========================================================================

    async def search_emails(
        self,
        query: str,
        max_results: int = 10,
        context: Any = None,  # noqa: ARG002  # Kept for interface compatibility
    ) -> list[EmailMessage]:
        """
        Search Gmail messages with a query.

        Args:
            query: Gmail search query (e.g., "from:sarah@acme.com" or "is:unread")
            max_results: Maximum number of messages to return (default: 10)
            context: Ignored (kept for interface compatibility)

        Returns:
            List of matching email messages

        Raises:
            ExternalServiceError: If search fails
        """
        await self.start()

        loop = asyncio.get_event_loop()

        def do_search() -> list[dict[str, Any]]:
            try:
                # List message IDs matching query
                results = (
                    self._gmail_service.users()
                    .messages()
                    .list(userId="me", q=query, maxResults=max_results)
                    .execute()
                )

                messages = results.get("messages", [])
                if not messages:
                    return []

                # Fetch full message details
                full_messages = []
                for msg in messages:
                    full = (
                        self._gmail_service.users()
                        .messages()
                        .get(userId="me", id=msg["id"], format="full")
                        .execute()
                    )
                    full_messages.append(full)

                return full_messages

            except HttpError as e:
                raise ExternalServiceError("gmail", f"Search failed: {e}") from e

        try:
            raw_messages = await loop.run_in_executor(None, do_search)
            return self._parse_gmail_messages(raw_messages)
        except Exception as e:
            logger.error(f"[STORM] Gmail search failed: {e}", extra={"query": query})
            raise

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        draft_only: bool = False,
        context: Any = None,  # noqa: ARG002
    ) -> SendEmailResult:
        """
        Send or draft an email via Gmail.

        Args:
            to: Recipient email address
            subject: Email subject line
            body: Email body (plain text)
            cc: Optional CC recipients (comma-separated)
            draft_only: If True, save as draft instead of sending
            context: Ignored (kept for interface compatibility)

        Returns:
            Result containing message ID or error details
        """
        await self.start()

        loop = asyncio.get_event_loop()

        def do_send() -> dict[str, Any]:
            try:
                # Create message
                message = MIMEText(body)
                message["to"] = to
                message["subject"] = subject
                if cc:
                    message["cc"] = cc

                raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

                if draft_only:
                    # Create draft
                    draft = (
                        self._gmail_service.users()
                        .drafts()
                        .create(userId="me", body={"message": {"raw": raw}})
                        .execute()
                    )
                    return {"id": draft["id"], "is_draft": True}
                else:
                    # Send message
                    sent = (
                        self._gmail_service.users()
                        .messages()
                        .send(userId="me", body={"raw": raw})
                        .execute()
                    )
                    return {"id": sent["id"], "is_draft": False}

            except HttpError as e:
                raise ExternalServiceError("gmail", f"Send failed: {e}") from e

        try:
            result = await loop.run_in_executor(None, do_send)
            return SendEmailResult(
                success=True,
                message_id=result["id"],
                is_draft=result.get("is_draft", False),
            )
        except Exception as e:
            logger.error(
                f"[STORM] Email {'draft' if draft_only else 'send'} failed: {e}",
                extra={"to": to, "subject": subject},
            )
            return SendEmailResult(success=False, error=str(e), is_draft=draft_only)

    async def get_recent_emails(
        self,
        hours: int = 24,
        context: Any = None,  # noqa: ARG002
    ) -> list[EmailMessage]:
        """Get emails from the last N hours."""
        query = f"newer_than:{hours}h"
        return await self.search_emails(query, max_results=50)

    # ===========================================================================
    # Email Management Operations
    # ===========================================================================

    async def trash_email(
        self,
        message_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> EmailOperationResult:
        """
        Move an email to trash.

        Args:
            message_id: Gmail message ID to trash
            context: Ignored (kept for interface compatibility)

        Returns:
            Result indicating success or failure
        """
        await self.start()
        loop = asyncio.get_event_loop()

        def do_trash() -> str:
            try:
                self._gmail_service.users().messages().trash(userId="me", id=message_id).execute()
                return message_id
            except HttpError as e:
                raise ExternalServiceError("gmail", f"Trash failed: {e}") from e

        try:
            result_id = await loop.run_in_executor(None, do_trash)
            logger.info(
                f"[BEACON] Email trashed: {result_id[:8]}...",
                extra={"message_id": message_id},
            )
            return EmailOperationResult(success=True, message_id=result_id, operation="trash")
        except Exception as e:
            logger.error(
                f"[STORM] Email trash failed: {e}",
                extra={"message_id": message_id},
            )
            return EmailOperationResult(
                success=False, message_id=message_id, operation="trash", error=str(e)
            )

    async def delete_email(
        self,
        message_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> EmailOperationResult:
        """
        Permanently delete an email (use with caution).

        Args:
            message_id: Gmail message ID to delete permanently
            context: Ignored (kept for interface compatibility)

        Returns:
            Result indicating success or failure
        """
        await self.start()
        loop = asyncio.get_event_loop()

        def do_delete() -> str:
            try:
                self._gmail_service.users().messages().delete(userId="me", id=message_id).execute()
                return message_id
            except HttpError as e:
                raise ExternalServiceError("gmail", f"Delete failed: {e}") from e

        try:
            result_id = await loop.run_in_executor(None, do_delete)
            logger.info(
                f"[BEACON] Email permanently deleted: {result_id[:8]}...",
                extra={"message_id": message_id},
            )
            return EmailOperationResult(success=True, message_id=result_id, operation="delete")
        except Exception as e:
            logger.error(
                f"[STORM] Email delete failed: {e}",
                extra={"message_id": message_id},
            )
            return EmailOperationResult(
                success=False, message_id=message_id, operation="delete", error=str(e)
            )

    async def archive_email(
        self,
        message_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> EmailOperationResult:
        """
        Archive an email (remove from inbox but keep in All Mail).

        Args:
            message_id: Gmail message ID to archive
            context: Ignored (kept for interface compatibility)

        Returns:
            Result indicating success or failure
        """
        await self.start()
        loop = asyncio.get_event_loop()

        def do_archive() -> str:
            try:
                # Archive = remove INBOX label
                self._gmail_service.users().messages().modify(
                    userId="me",
                    id=message_id,
                    body={"removeLabelIds": ["INBOX"]},
                ).execute()
                return message_id
            except HttpError as e:
                raise ExternalServiceError("gmail", f"Archive failed: {e}") from e

        try:
            result_id = await loop.run_in_executor(None, do_archive)
            logger.info(
                f"[BEACON] Email archived: {result_id[:8]}...",
                extra={"message_id": message_id},
            )
            return EmailOperationResult(success=True, message_id=result_id, operation="archive")
        except Exception as e:
            logger.error(
                f"[STORM] Email archive failed: {e}",
                extra={"message_id": message_id},
            )
            return EmailOperationResult(
                success=False, message_id=message_id, operation="archive", error=str(e)
            )

    async def add_label(
        self,
        message_id: str,
        label_ids: list[str],
        context: Any = None,  # noqa: ARG002
    ) -> EmailOperationResult:
        """
        Add labels to an email.

        Args:
            message_id: Gmail message ID
            label_ids: List of label IDs to add
            context: Ignored (kept for interface compatibility)

        Returns:
            Result indicating success or failure
        """
        await self.start()
        loop = asyncio.get_event_loop()

        def do_add_label() -> str:
            try:
                self._gmail_service.users().messages().modify(
                    userId="me",
                    id=message_id,
                    body={"addLabelIds": label_ids},
                ).execute()
                return message_id
            except HttpError as e:
                raise ExternalServiceError("gmail", f"Add label failed: {e}") from e

        try:
            result_id = await loop.run_in_executor(None, do_add_label)
            logger.info(
                f"[BEACON] Labels added to email: {result_id[:8]}...",
                extra={"message_id": message_id, "labels": label_ids},
            )
            return EmailOperationResult(success=True, message_id=result_id, operation="label")
        except Exception as e:
            logger.error(
                f"[STORM] Add label failed: {e}",
                extra={"message_id": message_id, "labels": label_ids},
            )
            return EmailOperationResult(
                success=False, message_id=message_id, operation="label", error=str(e)
            )

    async def remove_label(
        self,
        message_id: str,
        label_ids: list[str],
        context: Any = None,  # noqa: ARG002
    ) -> EmailOperationResult:
        """
        Remove labels from an email.

        Args:
            message_id: Gmail message ID
            label_ids: List of label IDs to remove
            context: Ignored (kept for interface compatibility)

        Returns:
            Result indicating success or failure
        """
        await self.start()
        loop = asyncio.get_event_loop()

        def do_remove_label() -> str:
            try:
                self._gmail_service.users().messages().modify(
                    userId="me",
                    id=message_id,
                    body={"removeLabelIds": label_ids},
                ).execute()
                return message_id
            except HttpError as e:
                raise ExternalServiceError("gmail", f"Remove label failed: {e}") from e

        try:
            result_id = await loop.run_in_executor(None, do_remove_label)
            logger.info(
                f"[BEACON] Labels removed from email: {result_id[:8]}...",
                extra={"message_id": message_id, "labels": label_ids},
            )
            return EmailOperationResult(success=True, message_id=result_id, operation="unlabel")
        except Exception as e:
            logger.error(
                f"[STORM] Remove label failed: {e}",
                extra={"message_id": message_id, "labels": label_ids},
            )
            return EmailOperationResult(
                success=False, message_id=message_id, operation="unlabel", error=str(e)
            )

    async def list_labels(
        self,
        context: Any = None,  # noqa: ARG002
    ) -> list[GmailLabel]:
        """
        List all Gmail labels (system and user-created).

        Args:
            context: Ignored (kept for interface compatibility)

        Returns:
            List of Gmail labels with their IDs and names
        """
        await self.start()
        loop = asyncio.get_event_loop()

        def do_list_labels() -> list[dict[str, Any]]:
            try:
                results = self._gmail_service.users().labels().list(userId="me").execute()
                labels: list[dict[str, Any]] = results.get("labels", [])
                return labels
            except HttpError as e:
                raise ExternalServiceError("gmail", f"List labels failed: {e}") from e

        try:
            raw_labels = await loop.run_in_executor(None, do_list_labels)
            labels = []
            for label in raw_labels:
                labels.append(
                    GmailLabel(
                        id=label.get("id", ""),
                        name=label.get("name", ""),
                        type=label.get("type", "user").lower(),
                        message_count=label.get("messagesTotal"),
                        unread_count=label.get("messagesUnread"),
                    )
                )
            logger.info(
                f"[BEACON] Listed {len(labels)} Gmail labels",
            )
            return labels
        except Exception as e:
            logger.error(f"[STORM] List labels failed: {e}")
            raise

    async def get_label_by_name(
        self,
        name: str,
        context: Any = None,
    ) -> GmailLabel | None:
        """
        Find a label by its name (case-insensitive).

        Args:
            name: Label name to search for
            context: Ignored (kept for interface compatibility)

        Returns:
            GmailLabel if found, None otherwise
        """
        labels = await self.list_labels(context)
        name_lower = name.lower()
        for label in labels:
            if label.name.lower() == name_lower:
                return label
        return None

    # ===========================================================================
    # Calendar Operations
    # ===========================================================================

    async def list_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        max_results: int = 10,
        context: Any = None,  # noqa: ARG002
    ) -> list[CalendarEvent]:
        """
        List calendar events in a time range.

        Args:
            start: Start of time range (default: now)
            end: End of time range (default: 7 days from start)
            max_results: Maximum number of events to return (default: 10)
            context: Ignored (kept for interface compatibility)

        Returns:
            List of calendar events in the specified range

        Raises:
            ExternalServiceError: If listing fails
        """
        await self.start()

        if start is None:
            start = datetime.now()
        if end is None:
            end = start + timedelta(days=7)

        loop = asyncio.get_event_loop()

        def do_list() -> list[dict[str, Any]]:
            try:
                # Format as RFC3339 for Google Calendar API
                # Strip timezone info and use Z suffix for UTC
                time_min = start.replace(tzinfo=None).isoformat() + "Z"
                time_max = end.replace(tzinfo=None).isoformat() + "Z"
                results = (
                    self._calendar_service.events()
                    .list(
                        calendarId="primary",
                        timeMin=time_min,
                        timeMax=time_max,
                        maxResults=max_results,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )
                items: list[dict[str, Any]] = results.get("items", [])
                return items
            except HttpError as e:
                raise ExternalServiceError("calendar", f"List failed: {e}") from e

        try:
            raw_events = await loop.run_in_executor(None, do_list)
            return self._parse_calendar_events(raw_events)
        except Exception as e:
            logger.error(
                f"[STORM] Calendar list failed: {e}",
                extra={"start": start.isoformat(), "end": end.isoformat()},
            )
            raise

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        context: Any = None,  # noqa: ARG002
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
            context: Ignored (kept for interface compatibility)

        Returns:
            Result containing event ID and link, or error details
        """
        await self.start()

        loop = asyncio.get_event_loop()

        def do_create() -> dict[str, Any]:
            try:
                event_body: dict[str, Any] = {
                    "summary": title,
                    "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
                    "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
                }

                if description:
                    event_body["description"] = description
                if location:
                    event_body["location"] = location
                if attendees:
                    event_body["attendees"] = [{"email": email} for email in attendees]

                event: dict[str, Any] = (
                    self._calendar_service.events()
                    .insert(calendarId="primary", body=event_body)
                    .execute()
                )
                return event

            except HttpError as e:
                raise ExternalServiceError("calendar", f"Create failed: {e}") from e

        try:
            result = await loop.run_in_executor(None, do_create)
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
            return CreateEventResult(success=False, error=str(e))

    async def get_todays_events(
        self,
        context: Any = None,  # noqa: ARG002
    ) -> list[CalendarEvent]:
        """Get all events for today."""
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        return await self.list_events(start, end, max_results=50)

    async def get_tomorrows_events(
        self,
        context: Any = None,  # noqa: ARG002
    ) -> list[CalendarEvent]:
        """Get all events for tomorrow."""
        tomorrow = datetime.now() + timedelta(days=1)
        start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
        return await self.list_events(start, end, max_results=50)

    # ===========================================================================
    # Helper Methods
    # ===========================================================================

    def _parse_gmail_messages(self, messages: list[dict[str, Any]]) -> list[EmailMessage]:
        """Parse Gmail API response into EmailMessage models."""
        parsed: list[EmailMessage] = []

        for msg in messages:
            try:
                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

                # Parse date
                date_str = headers.get("Date", "")
                try:
                    # Try parsing common date formats
                    from email.utils import parsedate_to_datetime

                    date = parsedate_to_datetime(date_str)
                except Exception:
                    date = datetime.now()

                # Extract body
                body = None
                payload = msg.get("payload", {})
                if "body" in payload and payload["body"].get("data"):
                    body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
                elif "parts" in payload:
                    for part in payload["parts"]:
                        if part.get("mimeType") == "text/plain" and part.get("body", {}).get(
                            "data"
                        ):
                            body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                            break

                email = EmailMessage(
                    id=msg.get("id", ""),
                    thread_id=msg.get("threadId", ""),
                    subject=headers.get("Subject", "(no subject)"),
                    sender=headers.get("From", "unknown"),
                    recipient=headers.get("To"),
                    date=date,
                    snippet=msg.get("snippet", ""),
                    body=body,
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

    def _parse_calendar_events(self, events: list[dict[str, Any]]) -> list[CalendarEvent]:
        """Parse Calendar API response into CalendarEvent models."""
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

                # Parse ISO format
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
