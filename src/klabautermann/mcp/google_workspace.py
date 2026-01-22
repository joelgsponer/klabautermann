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
import random
from datetime import UTC, datetime, timedelta
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar


if TYPE_CHECKING:
    from collections.abc import Callable

import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field

from klabautermann.channels.rate_limiter import RateLimitConfig, RateLimiter
from klabautermann.core.exceptions import ExternalServiceError, RateLimitError
from klabautermann.core.logger import logger


T = TypeVar("T")


# ===========================================================================
# Response Models
# ===========================================================================


class EmailAttachment(BaseModel):
    """Email attachment metadata from Gmail."""

    attachment_id: str  # Gmail's internal attachment ID for downloading
    filename: str
    mime_type: str
    size: int  # Size in bytes

    @property
    def size_human(self) -> str:
        """Human-readable file size."""
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        else:
            return f"{self.size / (1024 * 1024):.1f} MB"


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
    attachments: list[EmailAttachment] = Field(default_factory=list)

    @property
    def has_attachments(self) -> bool:
        """Check if email has attachments."""
        return len(self.attachments) > 0


class CalendarEvent(BaseModel):
    """Parsed calendar event from Google Calendar."""

    id: str
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    description: str | None = None
    attendees: list[str] = Field(default_factory=list)
    calendar_id: str = "primary"  # Which calendar this event belongs to
    calendar_name: str | None = None  # Human-readable calendar name
    event_type: str | None = None  # "default", "outOfOffice", "focusTime", "workingLocation"
    transparency: str | None = None  # "opaque" (busy) or "transparent" (free)
    recurrence_rule: str | None = None  # RFC 5545 RRULE string (e.g., "RRULE:FREQ=DAILY")
    recurring_event_id: str | None = None  # ID of parent recurring event (for instances)


class FreeSlot(BaseModel):
    """A free time slot in the calendar."""

    start: datetime
    end: datetime

    @property
    def duration_minutes(self) -> int:
        """Duration of the slot in minutes."""
        return int((self.end - self.start).total_seconds() / 60)

    @property
    def duration_human(self) -> str:
        """Human-readable duration."""
        minutes = self.duration_minutes
        if minutes < 60:
            return f"{minutes} min"
        hours = minutes // 60
        mins = minutes % 60
        if mins == 0:
            return f"{hours} hr"
        return f"{hours} hr {mins} min"

    def format_display(self) -> str:
        """Format slot for display."""
        start_str = self.start.strftime("%a %b %d, %I:%M %p")
        end_str = self.end.strftime("%I:%M %p")
        return f"{start_str} - {end_str} ({self.duration_human})"


class RecurrenceBuilder:
    """
    Build RFC 5545 RRULE strings for common recurrence patterns.

    Examples:
        RecurrenceBuilder.daily()  # "RRULE:FREQ=DAILY"
        RecurrenceBuilder.weekly(["MO", "WE", "FR"])  # "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR"
        RecurrenceBuilder.monthly(15)  # "RRULE:FREQ=MONTHLY;BYMONTHDAY=15"
        RecurrenceBuilder.yearly()  # "RRULE:FREQ=YEARLY"
    """

    @staticmethod
    def daily(count: int | None = None, until: datetime | None = None) -> str:
        """Create a daily recurrence rule."""
        rule = "RRULE:FREQ=DAILY"
        if count:
            rule += f";COUNT={count}"
        elif until:
            rule += f";UNTIL={until.strftime('%Y%m%dT%H%M%SZ')}"
        return rule

    @staticmethod
    def weekly(
        days: list[str] | None = None,
        count: int | None = None,
        until: datetime | None = None,
    ) -> str:
        """
        Create a weekly recurrence rule.

        Args:
            days: List of day abbreviations (MO, TU, WE, TH, FR, SA, SU).
                  If None, recurs on the same day as the event.
            count: Number of occurrences (mutually exclusive with until)
            until: End date for recurrence (mutually exclusive with count)
        """
        rule = "RRULE:FREQ=WEEKLY"
        if days:
            rule += f";BYDAY={','.join(days)}"
        if count:
            rule += f";COUNT={count}"
        elif until:
            rule += f";UNTIL={until.strftime('%Y%m%dT%H%M%SZ')}"
        return rule

    @staticmethod
    def monthly(
        day_of_month: int | None = None,
        count: int | None = None,
        until: datetime | None = None,
    ) -> str:
        """
        Create a monthly recurrence rule.

        Args:
            day_of_month: Day of month (1-31). If None, uses event's day.
            count: Number of occurrences
            until: End date for recurrence
        """
        rule = "RRULE:FREQ=MONTHLY"
        if day_of_month:
            rule += f";BYMONTHDAY={day_of_month}"
        if count:
            rule += f";COUNT={count}"
        elif until:
            rule += f";UNTIL={until.strftime('%Y%m%dT%H%M%SZ')}"
        return rule

    @staticmethod
    def yearly(count: int | None = None, until: datetime | None = None) -> str:
        """Create a yearly recurrence rule."""
        rule = "RRULE:FREQ=YEARLY"
        if count:
            rule += f";COUNT={count}"
        elif until:
            rule += f";UNTIL={until.strftime('%Y%m%dT%H%M%SZ')}"
        return rule

    @staticmethod
    def weekdays(count: int | None = None, until: datetime | None = None) -> str:
        """Create a weekday (Mon-Fri) recurrence rule."""
        return RecurrenceBuilder.weekly(["MO", "TU", "WE", "TH", "FR"], count, until)


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


class UpdateEventResult(BaseModel):
    """Result of updating a calendar event."""

    success: bool
    event_id: str | None = None
    event_link: str | None = None
    error: str | None = None


class DeleteEventResult(BaseModel):
    """Result of deleting a calendar event."""

    success: bool
    event_id: str | None = None
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


class EmailDraft(BaseModel):
    """Email draft from Gmail."""

    id: str  # Draft ID (different from message ID)
    message_id: str  # Associated message ID
    thread_id: str | None = None
    subject: str
    to: str | None = None
    cc: str | None = None
    body: str | None = None
    snippet: str = ""


class DraftOperationResult(BaseModel):
    """Result of draft operations (update, send, delete)."""

    success: bool
    draft_id: str | None = None
    message_id: str | None = None
    operation: str = ""  # "update", "send", "delete"
    error: str | None = None


class EmailSearchResult(BaseModel):
    """Email search results with pagination metadata."""

    emails: list[EmailMessage]
    next_page_token: str | None = None
    result_size_estimate: int | None = None

    @property
    def has_more(self) -> bool:
        """Whether more results are available."""
        return self.next_page_token is not None


class EmailThread(BaseModel):
    """A complete email thread with all messages."""

    id: str  # Thread ID
    subject: str
    messages: list[EmailMessage]
    participant_count: int = 0
    message_count: int = 0

    @property
    def participants(self) -> list[str]:
        """Get unique participants in the thread."""
        senders = {msg.sender for msg in self.messages}
        recipients = {msg.recipient for msg in self.messages if msg.recipient}
        return list(senders | recipients)

    @property
    def date_range(self) -> str:
        """Human-readable date range of the thread."""
        if not self.messages:
            return "No messages"
        dates = sorted(msg.date for msg in self.messages)
        start = dates[0].strftime("%b %d")
        end = dates[-1].strftime("%b %d, %Y")
        if start == end.split(",")[0]:
            return end
        return f"{start} - {end}"


class EmailThreadSummary(BaseModel):
    """Summary of an email thread."""

    thread_id: str
    subject: str
    summary: str  # 2-3 sentence summary of the conversation
    key_points: list[str] = Field(default_factory=list)  # Main takeaways
    action_items: list[str] = Field(default_factory=list)  # Action items mentioned
    participants: list[str] = Field(default_factory=list)  # People in the thread
    message_count: int = 0
    date_range: str = ""
    sentiment: str = "neutral"  # Overall tone: positive, negative, neutral


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

    # Default rate limit configuration
    DEFAULT_REQUESTS_PER_MINUTE: ClassVar[int] = 60
    DEFAULT_MAX_CONCURRENT: ClassVar[int] = 10

    def __init__(
        self,
        gmail_requests_per_minute: int | None = None,
        calendar_requests_per_minute: int | None = None,
        max_concurrent_requests: int | None = None,
        rate_limiting_enabled: bool = True,
    ) -> None:
        """
        Initialize the Google Workspace bridge.

        Args:
            gmail_requests_per_minute: Rate limit for Gmail API (default: 60)
            calendar_requests_per_minute: Rate limit for Calendar API (default: 60)
            max_concurrent_requests: Max concurrent API calls (default: 10)
            rate_limiting_enabled: Whether to enable rate limiting (default: True)
        """
        self._credentials: Credentials | None = None
        self._gmail_service: Any = None
        self._calendar_service: Any = None
        self._started = False

        # OAuth refresh handling
        self._refresh_lock = asyncio.Lock()
        self._last_refresh: datetime | None = None

        # Rate limiting configuration
        self._rate_limiting_enabled = rate_limiting_enabled
        gmail_rpm = gmail_requests_per_minute or self.DEFAULT_REQUESTS_PER_MINUTE
        calendar_rpm = calendar_requests_per_minute or self.DEFAULT_REQUESTS_PER_MINUTE
        max_concurrent = max_concurrent_requests or self.DEFAULT_MAX_CONCURRENT

        # Create per-service rate limiters
        self._gmail_limiter = RateLimiter(
            RateLimitConfig(
                max_requests=gmail_rpm,
                window_seconds=60,
                burst_allowance=10,
                enabled=rate_limiting_enabled,
            )
        )
        self._calendar_limiter = RateLimiter(
            RateLimitConfig(
                max_requests=calendar_rpm,
                window_seconds=60,
                burst_allowance=10,
                enabled=rate_limiting_enabled,
            )
        )

        # Semaphore for limiting concurrent requests
        self._semaphore = asyncio.Semaphore(max_concurrent)

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
        self._last_refresh = None
        logger.info("[CHART] Google Workspace API services stopped")

    # ===========================================================================
    # OAuth Refresh Handling
    # ===========================================================================

    async def _refresh_if_expired(self) -> None:
        """
        Refresh token if expired or about to expire.

        Uses asyncio.Lock to serialize concurrent refresh attempts.
        On invalid_grant error (revoked token), raises ExternalServiceError
        with instructions to re-run bootstrap_auth.py.
        """
        if self._credentials is None:
            raise ExternalServiceError("google", "Credentials not initialized. Call start() first.")

        async with self._refresh_lock:
            try:
                # Run refresh in executor to avoid blocking
                loop = asyncio.get_event_loop()
                credentials = self._credentials  # Capture for type narrowing
                await loop.run_in_executor(None, lambda: credentials.refresh(Request()))
                self._last_refresh = datetime.now(UTC)
                logger.info("[CHART] Token refreshed successfully")
            except google.auth.exceptions.RefreshError as e:
                if "invalid_grant" in str(e).lower():
                    raise ExternalServiceError(
                        "google",
                        "Refresh token revoked or expired. Please run bootstrap_auth.py to re-authenticate.",
                    ) from e
                raise ExternalServiceError("google", f"Token refresh failed: {e}") from e

    # ===========================================================================
    # Rate Limiting
    # ===========================================================================

    async def _rate_limited_call(
        self,
        service: str,
        operation: Callable[[], T],
    ) -> T:
        """
        Execute API call with rate limiting, OAuth refresh, concurrency control, and 429 handling.

        Combines rate limiting check, OAuth 401 refresh, and Google 429 backoff
        into a single unified wrapper for all API calls.

        Args:
            service: Service name ("gmail" or "calendar") for rate limit tracking
            operation: Callable that performs the API call

        Returns:
            Result of the operation

        Raises:
            RateLimitError: If rate limit exceeded and cannot wait
            ExternalServiceError: If operation fails
        """
        # Select the appropriate rate limiter
        limiter = self._gmail_limiter if service == "gmail" else self._calendar_limiter

        # Check rate limit
        result = limiter.check(service)
        if not result.allowed:
            if result.reset_after > 0:
                logger.warning(
                    f"[SWELL] {service} rate limited, waiting {result.reset_after:.1f}s",
                    extra={"service": service, "reset_after": result.reset_after},
                )
                await asyncio.sleep(result.reset_after)
            else:
                raise RateLimitError(service, result.reset_after)
        elif result.is_warning:
            logger.debug(
                f"[WHISPER] {service} in rate limit burst zone",
                extra={"service": service, "remaining": result.remaining},
            )

        # Execute with semaphore for concurrency control
        async with self._semaphore:
            loop = asyncio.get_event_loop()
            try:
                return await loop.run_in_executor(None, operation)
            except HttpError as e:
                if e.resp.status == 401:
                    # OAuth token expired, refresh and retry
                    logger.info(f"[CHART] {service} token expired, refreshing...")
                    await self._refresh_if_expired()
                    return await loop.run_in_executor(None, operation)
                elif e.resp.status == 429:
                    # Handle Google's rate limit response
                    retry_after = self._parse_retry_after(e)
                    logger.warning(
                        f"[STORM] {service} API rate limited (429), waiting {retry_after}s",
                        extra={"service": service, "retry_after": retry_after},
                    )
                    await asyncio.sleep(retry_after)
                    # Retry once
                    return await loop.run_in_executor(None, operation)
                raise

    def _parse_retry_after(self, error: HttpError) -> float:
        """
        Parse Retry-After header from Google API 429 response.

        Returns seconds to wait, with exponential backoff jitter.
        """
        try:
            # Try to get Retry-After header
            retry_after = error.resp.get("Retry-After")
            if retry_after:
                return float(retry_after)
        except (ValueError, AttributeError):
            pass

        # Default: 60s + random jitter (0-10s)
        return 60.0 + random.uniform(0, 10)

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

        def do_search() -> list[dict[str, Any]]:
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

        try:
            raw_messages = await self._rate_limited_call("gmail", do_search)
            return self._parse_gmail_messages(raw_messages)
        except HttpError as e:
            logger.error(f"[STORM] Gmail search failed: {e}", extra={"query": query})
            raise ExternalServiceError("gmail", f"Search failed: {e}") from e
        except Exception as e:
            logger.error(f"[STORM] Gmail search failed: {e}", extra={"query": query})
            raise

    async def search_emails_paginated(
        self,
        query: str,
        max_results: int = 100,
        page_token: str | None = None,
        context: Any = None,  # noqa: ARG002  # Kept for interface compatibility
    ) -> EmailSearchResult:
        """
        Search Gmail messages with pagination support.

        Supports retrieving large result sets efficiently by returning
        a page token for subsequent requests. Each page requires N+1 API calls
        where N is the number of messages (1 list + N individual fetches).

        Args:
            query: Gmail search query (e.g., "from:sarah@acme.com" or "is:unread")
            max_results: Maximum messages per page (1-500, default: 100)
            page_token: Token from previous response to continue pagination
            context: Ignored (kept for interface compatibility)

        Returns:
            EmailSearchResult with emails, next_page_token, and result_size_estimate

        Raises:
            ExternalServiceError: If search fails

        Example:
            result = await bridge.search_emails_paginated("is:unread")
            for email in result.emails:
                process_email(email)

            if result.has_more:
                next_result = await bridge.search_emails_paginated(
                    "is:unread",
                    page_token=result.next_page_token
                )
        """
        await self.start()

        # Enforce Gmail API limits (max 500 per page)
        max_results = min(max_results, 500)

        def do_search() -> tuple[list[dict[str, Any]], str | None, int | None]:
            # Build list request with optional page token
            list_request = (
                self._gmail_service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=max_results,
                )
            )
            if page_token:
                list_request = (
                    self._gmail_service.users()
                    .messages()
                    .list(
                        userId="me",
                        q=query,
                        maxResults=max_results,
                        pageToken=page_token,
                    )
                )

            results = list_request.execute()

            messages = results.get("messages", [])
            next_token = results.get("nextPageToken")
            size_estimate = results.get("resultSizeEstimate")

            if not messages:
                return [], next_token, size_estimate

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

            return full_messages, next_token, size_estimate

        try:
            raw_messages, next_token, size_estimate = await self._rate_limited_call(
                "gmail", do_search
            )
            emails = self._parse_gmail_messages(raw_messages)

            logger.info(
                f"[CHART] Email search returned {len(emails)} results",
                extra={
                    "query": query,
                    "has_more": next_token is not None,
                    "estimate": size_estimate,
                },
            )

            return EmailSearchResult(
                emails=emails,
                next_page_token=next_token,
                result_size_estimate=size_estimate,
            )
        except HttpError as e:
            logger.error(
                f"[STORM] Gmail paginated search failed: {e}",
                extra={"query": query, "page_token": page_token},
            )
            raise ExternalServiceError("gmail", f"Paginated search failed: {e}") from e
        except Exception as e:
            logger.error(
                f"[STORM] Gmail paginated search failed: {e}",
                extra={"query": query, "page_token": page_token},
            )
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

        def do_send() -> dict[str, Any]:
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

        try:
            result = await self._rate_limited_call("gmail", do_send)
            return SendEmailResult(
                success=True,
                message_id=result["id"],
                is_draft=result.get("is_draft", False),
            )
        except (HttpError, ExternalServiceError) as e:
            logger.error(
                f"[STORM] Email {'draft' if draft_only else 'send'} failed: {e}",
                extra={"to": to, "subject": subject},
            )
            return SendEmailResult(success=False, error=str(e), is_draft=draft_only)
        except Exception as e:
            logger.error(
                f"[STORM] Email {'draft' if draft_only else 'send'} failed: {e}",
                extra={"to": to, "subject": subject},
            )
            return SendEmailResult(success=False, error=str(e), is_draft=draft_only)

    async def reply_to_email(
        self,
        message_id: str,
        body: str,
        reply_all: bool = False,
        draft_only: bool = False,
        context: Any = None,  # noqa: ARG002
    ) -> SendEmailResult:
        """
        Reply to an existing email thread.

        Automatically sets In-Reply-To and References headers to maintain
        thread context in Gmail. Extracts the original sender (and CC recipients
        if reply_all) from the original message.

        Args:
            message_id: Gmail message ID to reply to
            body: Reply body (plain text)
            reply_all: If True, include all original recipients in reply
            draft_only: If True, save as draft instead of sending
            context: Ignored (kept for interface compatibility)

        Returns:
            Result containing message ID or error details

        Reference: Issue #207 (MCP-001)
        """
        await self.start()

        def get_original_message() -> dict[str, Any]:
            """Fetch the original message to extract headers."""
            result: dict[str, Any] = (
                self._gmail_service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            return result

        def do_reply(original: dict[str, Any]) -> dict[str, Any]:
            """Build and send/draft the reply message."""
            # Extract headers from original message
            headers = {
                h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])
            }

            thread_id = original.get("threadId")
            original_message_id = headers.get("Message-ID", headers.get("Message-Id", ""))
            original_references = headers.get("References", "")
            original_subject = headers.get("Subject", "")
            original_sender = headers.get("From", "")
            original_to = headers.get("To", "")
            original_cc = headers.get("Cc", "")

            # Build References header: existing references + original message ID
            references = original_references
            if original_message_id:
                if references:
                    references = f"{references} {original_message_id}"
                else:
                    references = original_message_id

            # Determine recipients
            # For reply: reply to the original sender
            # For reply-all: include original sender + all original recipients
            reply_to = original_sender

            cc_recipients = None
            if reply_all and (original_to or original_cc):
                # Combine original To and Cc, excluding our own address
                all_recipients = []
                if original_to:
                    all_recipients.extend([r.strip() for r in original_to.split(",") if r.strip()])
                if original_cc:
                    all_recipients.extend([r.strip() for r in original_cc.split(",") if r.strip()])
                # Filter out the original sender (they're in To:)
                cc_recipients = ", ".join(r for r in all_recipients if r != original_sender)

            # Build subject with Re: prefix if not already present
            subject = original_subject
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            # Create MIME message with threading headers
            message = MIMEText(body)
            message["to"] = reply_to
            message["subject"] = subject
            if cc_recipients:
                message["cc"] = cc_recipients
            if original_message_id:
                message["In-Reply-To"] = original_message_id
            if references:
                message["References"] = references

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

            if draft_only:
                # Create draft in the same thread
                draft = (
                    self._gmail_service.users()
                    .drafts()
                    .create(
                        userId="me",
                        body={"message": {"raw": raw, "threadId": thread_id}},
                    )
                    .execute()
                )
                return {"id": draft["id"], "is_draft": True, "thread_id": thread_id}
            else:
                # Send message in the same thread
                sent = (
                    self._gmail_service.users()
                    .messages()
                    .send(userId="me", body={"raw": raw, "threadId": thread_id})
                    .execute()
                )
                return {"id": sent["id"], "is_draft": False, "thread_id": thread_id}

        try:
            # First fetch the original message
            original = await self._rate_limited_call("gmail", get_original_message)
            # Then send the reply
            result = await self._rate_limited_call("gmail", lambda: do_reply(original))

            logger.info(
                f"[BEACON] Email reply {'drafted' if draft_only else 'sent'} in thread",
                extra={
                    "original_id": message_id,
                    "reply_id": result["id"],
                    "thread_id": result.get("thread_id"),
                    "reply_all": reply_all,
                },
            )

            return SendEmailResult(
                success=True,
                message_id=result["id"],
                is_draft=result.get("is_draft", False),
            )
        except HttpError as e:
            logger.error(
                f"[STORM] Email reply failed: {e}",
                extra={"message_id": message_id, "reply_all": reply_all},
            )
            return SendEmailResult(success=False, error=str(e), is_draft=draft_only)
        except Exception as e:
            logger.error(
                f"[STORM] Email reply failed: {e}",
                extra={"message_id": message_id, "reply_all": reply_all},
            )
            return SendEmailResult(success=False, error=str(e), is_draft=draft_only)

    # ===========================================================================
    # Draft Management Operations
    # ===========================================================================

    async def list_drafts(
        self,
        max_results: int = 20,
        context: Any = None,  # noqa: ARG002
    ) -> list[EmailDraft]:
        """
        List email drafts.

        Args:
            max_results: Maximum number of drafts to return (default: 20)
            context: Ignored (kept for interface compatibility)

        Returns:
            List of EmailDraft objects

        Reference: Issue #219 (MCP-013)
        """
        await self.start()

        def do_list_drafts() -> list[dict[str, Any]]:
            results = (
                self._gmail_service.users()
                .drafts()
                .list(userId="me", maxResults=max_results)
                .execute()
            )
            drafts_list: list[dict[str, Any]] = results.get("drafts", [])
            return drafts_list

        def get_draft_details(draft_id: str) -> dict[str, Any]:
            result: dict[str, Any] = (
                self._gmail_service.users()
                .drafts()
                .get(userId="me", id=draft_id, format="full")
                .execute()
            )
            return result

        try:
            raw_drafts = await self._rate_limited_call("gmail", do_list_drafts)
            drafts: list[EmailDraft] = []

            for raw_draft in raw_drafts:
                draft_id = raw_draft.get("id", "")
                # Get full draft details
                full_draft = await self._rate_limited_call(
                    "gmail",
                    lambda d=draft_id: get_draft_details(d),  # type: ignore[misc]
                )
                message = full_draft.get("message", {})
                headers = {
                    h["name"]: h["value"] for h in message.get("payload", {}).get("headers", [])
                }

                # Extract body
                body = None
                payload = message.get("payload", {})
                if "body" in payload and payload["body"].get("data"):
                    body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
                elif "parts" in payload:
                    for part in payload["parts"]:
                        if part.get("mimeType") == "text/plain" and part.get("body", {}).get(
                            "data"
                        ):
                            body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                            break

                drafts.append(
                    EmailDraft(
                        id=draft_id,
                        message_id=message.get("id", ""),
                        thread_id=message.get("threadId"),
                        subject=headers.get("Subject", "(no subject)"),
                        to=headers.get("To"),
                        cc=headers.get("Cc"),
                        body=body,
                        snippet=message.get("snippet", ""),
                    )
                )

            logger.info(
                f"[BEACON] Listed {len(drafts)} drafts",
                extra={"count": len(drafts)},
            )
            return drafts
        except HttpError as e:
            logger.error(f"[STORM] List drafts failed: {e}")
            raise ExternalServiceError("gmail", f"List drafts failed: {e}") from e

    async def get_draft(
        self,
        draft_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> EmailDraft | None:
        """
        Get a specific draft by ID.

        Args:
            draft_id: Gmail draft ID
            context: Ignored (kept for interface compatibility)

        Returns:
            EmailDraft if found, None otherwise

        Reference: Issue #219 (MCP-013)
        """
        await self.start()

        def do_get_draft() -> dict[str, Any]:
            result: dict[str, Any] = (
                self._gmail_service.users()
                .drafts()
                .get(userId="me", id=draft_id, format="full")
                .execute()
            )
            return result

        try:
            full_draft = await self._rate_limited_call("gmail", do_get_draft)
            message = full_draft.get("message", {})
            headers = {h["name"]: h["value"] for h in message.get("payload", {}).get("headers", [])}

            # Extract body
            body = None
            payload = message.get("payload", {})
            if "body" in payload and payload["body"].get("data"):
                body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
            elif "parts" in payload:
                for part in payload["parts"]:
                    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                        break

            return EmailDraft(
                id=draft_id,
                message_id=message.get("id", ""),
                thread_id=message.get("threadId"),
                subject=headers.get("Subject", "(no subject)"),
                to=headers.get("To"),
                cc=headers.get("Cc"),
                body=body,
                snippet=message.get("snippet", ""),
            )
        except HttpError as e:
            if e.resp.status == 404:
                return None
            logger.error(f"[STORM] Get draft failed: {e}")
            raise ExternalServiceError("gmail", f"Get draft failed: {e}") from e

    async def update_draft(
        self,
        draft_id: str,
        to: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        cc: str | None = None,
        context: Any = None,  # noqa: ARG002
    ) -> DraftOperationResult:
        """
        Update an existing draft.

        Args:
            draft_id: Gmail draft ID to update
            to: New recipient (optional, keeps existing if None)
            subject: New subject (optional, keeps existing if None)
            body: New body (optional, keeps existing if None)
            cc: New CC recipients (optional, keeps existing if None)
            context: Ignored (kept for interface compatibility)

        Returns:
            DraftOperationResult with success status

        Reference: Issue #219 (MCP-013)
        """
        await self.start()

        # First get the existing draft to preserve fields
        existing = await self.get_draft(draft_id)
        if not existing:
            return DraftOperationResult(
                success=False,
                draft_id=draft_id,
                operation="update",
                error="Draft not found",
            )

        # Use existing values if not provided
        final_to = to if to is not None else existing.to
        final_subject = subject if subject is not None else existing.subject
        final_body = body if body is not None else existing.body or ""
        final_cc = cc if cc is not None else existing.cc

        def do_update() -> dict[str, Any]:
            # Create the updated message
            message = MIMEText(final_body)
            if final_to:
                message["to"] = final_to
            message["subject"] = final_subject
            if final_cc:
                message["cc"] = final_cc

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

            draft_body: dict[str, Any] = {"message": {"raw": raw}}
            # Preserve thread if it exists
            if existing.thread_id:
                draft_body["message"]["threadId"] = existing.thread_id

            result: dict[str, Any] = (
                self._gmail_service.users()
                .drafts()
                .update(userId="me", id=draft_id, body=draft_body)
                .execute()
            )
            return result

        try:
            result = await self._rate_limited_call("gmail", do_update)
            logger.info(
                f"[BEACON] Draft updated: {draft_id[:8]}...",
                extra={"draft_id": draft_id},
            )
            return DraftOperationResult(
                success=True,
                draft_id=result.get("id", draft_id),
                message_id=result.get("message", {}).get("id"),
                operation="update",
            )
        except HttpError as e:
            logger.error(f"[STORM] Update draft failed: {e}")
            return DraftOperationResult(
                success=False,
                draft_id=draft_id,
                operation="update",
                error=str(e),
            )

    async def send_draft(
        self,
        draft_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> DraftOperationResult:
        """
        Send an existing draft.

        Args:
            draft_id: Gmail draft ID to send
            context: Ignored (kept for interface compatibility)

        Returns:
            DraftOperationResult with sent message ID

        Reference: Issue #219 (MCP-013)
        """
        await self.start()

        def do_send() -> dict[str, Any]:
            result: dict[str, Any] = (
                self._gmail_service.users()
                .drafts()
                .send(userId="me", body={"id": draft_id})
                .execute()
            )
            return result

        try:
            result = await self._rate_limited_call("gmail", do_send)
            logger.info(
                f"[BEACON] Draft sent: {draft_id[:8]}... -> message {result.get('id', '')[:8]}...",
                extra={"draft_id": draft_id, "message_id": result.get("id")},
            )
            return DraftOperationResult(
                success=True,
                draft_id=draft_id,
                message_id=result.get("id"),
                operation="send",
            )
        except HttpError as e:
            logger.error(f"[STORM] Send draft failed: {e}")
            return DraftOperationResult(
                success=False,
                draft_id=draft_id,
                operation="send",
                error=str(e),
            )

    async def delete_draft(
        self,
        draft_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> DraftOperationResult:
        """
        Delete a draft.

        Args:
            draft_id: Gmail draft ID to delete
            context: Ignored (kept for interface compatibility)

        Returns:
            DraftOperationResult with success status

        Reference: Issue #219 (MCP-013)
        """
        await self.start()

        def do_delete() -> None:
            self._gmail_service.users().drafts().delete(userId="me", id=draft_id).execute()

        try:
            await self._rate_limited_call("gmail", do_delete)
            logger.info(
                f"[BEACON] Draft deleted: {draft_id[:8]}...",
                extra={"draft_id": draft_id},
            )
            return DraftOperationResult(
                success=True,
                draft_id=draft_id,
                operation="delete",
            )
        except HttpError as e:
            logger.error(f"[STORM] Delete draft failed: {e}")
            return DraftOperationResult(
                success=False,
                draft_id=draft_id,
                operation="delete",
                error=str(e),
            )

    # ===========================================================================
    # Email Thread Operations
    # ===========================================================================

    async def get_thread(
        self,
        thread_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> EmailThread | None:
        """
        Get all messages in an email thread.

        Args:
            thread_id: Gmail thread ID
            context: Ignored (kept for interface compatibility)

        Returns:
            EmailThread with all messages, or None if not found

        Reference: Issue #221 (MCP-015)
        """
        await self.start()

        def do_get_thread() -> dict[str, Any]:
            result: dict[str, Any] = (
                self._gmail_service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
            return result

        try:
            raw_thread = await self._rate_limited_call("gmail", do_get_thread)
            messages = self._parse_gmail_messages(raw_thread.get("messages", []))

            if not messages:
                return None

            # Get subject from first message
            subject = messages[0].subject if messages else "(no subject)"

            thread = EmailThread(
                id=thread_id,
                subject=subject,
                messages=messages,
                participant_count=len(
                    {m.sender for m in messages} | {m.recipient for m in messages if m.recipient}
                ),
                message_count=len(messages),
            )

            logger.info(
                f"[BEACON] Fetched thread with {len(messages)} messages",
                extra={"thread_id": thread_id, "message_count": len(messages)},
            )
            return thread

        except HttpError as e:
            if e.resp.status == 404:
                return None
            logger.error(f"[STORM] Get thread failed: {e}")
            raise ExternalServiceError("gmail", f"Get thread failed: {e}") from e

    async def summarize_email_thread(
        self,
        thread_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> EmailThreadSummary | None:
        """
        Fetch an email thread and generate an AI summary.

        Uses Claude Haiku to analyze the conversation and extract:
        - A concise 2-3 sentence summary
        - Key points and takeaways
        - Action items mentioned
        - Overall sentiment

        Args:
            thread_id: Gmail thread ID to summarize
            context: Ignored (kept for interface compatibility)

        Returns:
            EmailThreadSummary with analysis, or None if thread not found

        Raises:
            ExternalServiceError: If thread fetch or summarization fails

        Reference: Issue #221 (MCP-015)
        """
        import os

        import anthropic

        # First fetch the thread
        thread = await self.get_thread(thread_id)
        if not thread:
            return None

        # Format messages for LLM
        formatted_messages = self._format_thread_for_summary(thread)

        # Call LLM for summarization
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ExternalServiceError(
                "anthropic", "ANTHROPIC_API_KEY environment variable not set"
            )

        client = anthropic.Anthropic(api_key=api_key)

        system_prompt = """You are an email thread analyzer. Your task is to read email conversations and provide concise, actionable summaries.

SUMMARIZATION RULES:
1. Write a 2-3 sentence summary capturing the essence of the conversation
2. Extract 3-5 key points (main topics, decisions, important information)
3. Identify any action items or to-dos mentioned
4. Assess the overall sentiment (positive, negative, or neutral)

Be concise and focus on what matters most. Avoid repetition."""

        user_prompt = f"""Analyze this email thread and provide a structured summary.

THREAD SUBJECT: {thread.subject}
PARTICIPANTS: {", ".join(thread.participants)}
DATE RANGE: {thread.date_range}

MESSAGES:
{formatted_messages}

Please analyze this thread using the extract_email_summary tool."""

        try:
            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1500,
                system=system_prompt,
                tools=[
                    {
                        "name": "extract_email_summary",
                        "description": "Extract structured summary from email thread",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "summary": {
                                    "type": "string",
                                    "description": "2-3 sentence summary of the conversation",
                                },
                                "key_points": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "3-5 main takeaways from the thread",
                                },
                                "action_items": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Action items or to-dos mentioned",
                                },
                                "sentiment": {
                                    "type": "string",
                                    "enum": ["positive", "negative", "neutral"],
                                    "description": "Overall tone of the conversation",
                                },
                            },
                            "required": ["summary", "key_points", "sentiment"],
                        },
                    }
                ],
                tool_choice={"type": "tool", "name": "extract_email_summary"},
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Extract tool use block
            tool_use_block = None
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    tool_use_block = block
                    break

            if not tool_use_block:
                logger.warning(
                    "[SWELL] No tool_use block in LLM response, returning minimal summary"
                )
                return EmailThreadSummary(
                    thread_id=thread_id,
                    subject=thread.subject,
                    summary=f"Email thread with {thread.message_count} messages about: {thread.subject}",
                    participants=thread.participants,
                    message_count=thread.message_count,
                    date_range=thread.date_range,
                )

            # Parse LLM response
            llm_result = tool_use_block.input

            summary = EmailThreadSummary(
                thread_id=thread_id,
                subject=thread.subject,
                summary=llm_result.get("summary", ""),
                key_points=llm_result.get("key_points", []),
                action_items=llm_result.get("action_items", []),
                participants=thread.participants,
                message_count=thread.message_count,
                date_range=thread.date_range,
                sentiment=llm_result.get("sentiment", "neutral"),
            )

            logger.info(
                f"[BEACON] Summarized email thread: {len(summary.key_points)} key points, "
                f"{len(summary.action_items)} action items",
                extra={
                    "thread_id": thread_id,
                    "key_points": len(summary.key_points),
                    "action_items": len(summary.action_items),
                },
            )

            return summary

        except anthropic.APIError as e:
            logger.error(f"[STORM] Anthropic API error during summarization: {e}")
            raise ExternalServiceError("anthropic", f"Summarization failed: {e}") from e

    def _format_thread_for_summary(self, thread: EmailThread) -> str:
        """
        Format email thread messages for LLM consumption.

        Args:
            thread: EmailThread with messages

        Returns:
            Formatted string suitable for summarization
        """
        formatted_lines = []

        for i, msg in enumerate(thread.messages, 1):
            date_str = msg.date.strftime("%b %d, %Y %I:%M %p")
            sender = msg.sender

            # Truncate long bodies
            body = msg.body or msg.snippet
            if body and len(body) > 1500:
                body = body[:1500] + "..."

            formatted_lines.append(f"--- Message {i} ---")
            formatted_lines.append(f"From: {sender}")
            formatted_lines.append(f"Date: {date_str}")
            if msg.recipient:
                formatted_lines.append(f"To: {msg.recipient}")
            formatted_lines.append(f"\n{body}\n")

        return "\n".join(formatted_lines)

    async def get_recent_emails(
        self,
        hours: int = 24,
        context: Any = None,  # noqa: ARG002
    ) -> list[EmailMessage]:
        """Get emails from the last N hours."""
        query = f"newer_than:{hours}h"
        return await self.search_emails(query, max_results=50)

    async def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> bytes:
        """
        Download an email attachment's raw bytes.

        Args:
            message_id: Gmail message ID containing the attachment
            attachment_id: Attachment ID from EmailAttachment.attachment_id
            context: Ignored (kept for interface compatibility)

        Returns:
            Raw attachment bytes

        Raises:
            ExternalServiceError: If download fails
        """
        await self.start()

        def do_download() -> bytes:
            attachment = (
                self._gmail_service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )
            data = attachment.get("data", "")
            return base64.urlsafe_b64decode(data)

        try:
            return await self._rate_limited_call("gmail", do_download)
        except HttpError as e:
            logger.error(
                f"[STORM] Attachment download failed: {e}",
                extra={"message_id": message_id, "attachment_id": attachment_id},
            )
            raise ExternalServiceError("gmail", f"Attachment download failed: {e}") from e

    async def save_attachment(
        self,
        message_id: str,
        attachment: EmailAttachment,
        save_path: str,
        context: Any = None,  # noqa: ARG002
    ) -> str:
        """
        Download and save an attachment to the local filesystem.

        Args:
            message_id: Gmail message ID containing the attachment
            attachment: EmailAttachment object with attachment metadata
            save_path: Directory path where the attachment should be saved
            context: Ignored (kept for interface compatibility)

        Returns:
            Full path to the saved file

        Raises:
            ExternalServiceError: If download or save fails
        """
        from pathlib import Path as FilePath

        # Download attachment bytes
        data = await self.download_attachment(message_id, attachment.attachment_id)

        # Ensure save directory exists
        save_dir = FilePath(save_path)
        save_dir.mkdir(parents=True, exist_ok=True)

        # Build full file path
        file_path = save_dir / attachment.filename

        # Handle duplicate filenames
        if file_path.exists():
            base = FilePath(attachment.filename).stem
            ext = FilePath(attachment.filename).suffix
            counter = 1
            while file_path.exists():
                file_path = save_dir / f"{base}_{counter}{ext}"
                counter += 1

        # Save to filesystem
        try:
            file_path.write_bytes(data)

            logger.info(
                f"[BEACON] Attachment saved: {file_path}",
                extra={
                    "message_id": message_id,
                    "attachment_filename": attachment.filename,
                    "attachment_size": len(data),
                },
            )
            return str(file_path)
        except OSError as e:
            logger.error(
                f"[STORM] Failed to save attachment: {e}",
                extra={"file_path": str(file_path)},
            )
            raise ExternalServiceError("filesystem", f"Failed to save attachment: {e}") from e

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

        def do_trash() -> str:
            self._gmail_service.users().messages().trash(userId="me", id=message_id).execute()
            return message_id

        try:
            result_id = await self._rate_limited_call("gmail", do_trash)
            logger.info(
                f"[BEACON] Email trashed: {result_id[:8]}...",
                extra={"message_id": message_id},
            )
            return EmailOperationResult(success=True, message_id=result_id, operation="trash")
        except (HttpError, ExternalServiceError) as e:
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

        def do_delete() -> str:
            self._gmail_service.users().messages().delete(userId="me", id=message_id).execute()
            return message_id

        try:
            result_id = await self._rate_limited_call("gmail", do_delete)
            logger.info(
                f"[BEACON] Email permanently deleted: {result_id[:8]}...",
                extra={"message_id": message_id},
            )
            return EmailOperationResult(success=True, message_id=result_id, operation="delete")
        except (HttpError, ExternalServiceError) as e:
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

        def do_archive() -> str:
            # Archive = remove INBOX label
            self._gmail_service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["INBOX"]},
            ).execute()
            return message_id

        try:
            result_id = await self._rate_limited_call("gmail", do_archive)
            logger.info(
                f"[BEACON] Email archived: {result_id[:8]}...",
                extra={"message_id": message_id},
            )
            return EmailOperationResult(success=True, message_id=result_id, operation="archive")
        except (HttpError, ExternalServiceError) as e:
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

        def do_add_label() -> str:
            self._gmail_service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": label_ids},
            ).execute()
            return message_id

        try:
            result_id = await self._rate_limited_call("gmail", do_add_label)
            logger.info(
                f"[BEACON] Labels added to email: {result_id[:8]}...",
                extra={"message_id": message_id, "labels": label_ids},
            )
            return EmailOperationResult(success=True, message_id=result_id, operation="label")
        except (HttpError, ExternalServiceError) as e:
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

        def do_remove_label() -> str:
            self._gmail_service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": label_ids},
            ).execute()
            return message_id

        try:
            result_id = await self._rate_limited_call("gmail", do_remove_label)
            logger.info(
                f"[BEACON] Labels removed from email: {result_id[:8]}...",
                extra={"message_id": message_id, "labels": label_ids},
            )
            return EmailOperationResult(success=True, message_id=result_id, operation="unlabel")
        except (HttpError, ExternalServiceError) as e:
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

        def do_list_labels() -> list[dict[str, Any]]:
            results = self._gmail_service.users().labels().list(userId="me").execute()
            labels: list[dict[str, Any]] = results.get("labels", [])
            return labels

        try:
            raw_labels = await self._rate_limited_call("gmail", do_list_labels)
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
        except HttpError as e:
            logger.error(f"[STORM] List labels failed: {e}")
            raise ExternalServiceError("gmail", f"List labels failed: {e}") from e
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

    async def create_label(
        self,
        name: str,
        label_list_visibility: str = "labelShow",
        message_list_visibility: str = "show",
        context: Any = None,  # noqa: ARG002
    ) -> GmailLabel:
        """
        Create a custom Gmail label.

        Args:
            name: Label name (can include "/" for nested labels, e.g., "Projects/Work")
            label_list_visibility: Visibility in label list
                - "labelShow": Show in label list
                - "labelShowIfUnread": Show only if there are unread messages
                - "labelHide": Hide from label list
            message_list_visibility: Visibility when viewing message list
                - "show": Show label in message list
                - "hide": Hide label from message list
            context: Ignored (kept for interface compatibility)

        Returns:
            Created GmailLabel object

        Raises:
            ExternalServiceError: If label creation fails (e.g., label already exists)

        Reference: Issue #217 (MCP-011)
        """
        await self.start()

        def do_create_label() -> dict[str, Any]:
            label_body = {
                "name": name,
                "labelListVisibility": label_list_visibility,
                "messageListVisibility": message_list_visibility,
            }
            result: dict[str, Any] = (
                self._gmail_service.users().labels().create(userId="me", body=label_body).execute()
            )
            return result

        try:
            result = await self._rate_limited_call("gmail", do_create_label)
            logger.info(
                f"[BEACON] Label created: {name}",
                extra={"label_id": result.get("id"), "label_name": name},
            )
            return GmailLabel(
                id=result.get("id", ""),
                name=result.get("name", name),
                type="user",
            )
        except HttpError as e:
            logger.error(f"[STORM] Create label failed: {e}")
            raise ExternalServiceError("gmail", f"Create label failed: {e}") from e

    async def delete_label(
        self,
        label_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> bool:
        """
        Delete a custom Gmail label.

        Note: System labels (INBOX, SENT, etc.) cannot be deleted.

        Args:
            label_id: Gmail label ID to delete
            context: Ignored (kept for interface compatibility)

        Returns:
            True if deletion succeeded, False otherwise

        Raises:
            ExternalServiceError: If deletion fails

        Reference: Issue #217 (MCP-011)
        """
        await self.start()

        def do_delete_label() -> None:
            self._gmail_service.users().labels().delete(userId="me", id=label_id).execute()

        try:
            await self._rate_limited_call("gmail", do_delete_label)
            logger.info(
                f"[BEACON] Label deleted: {label_id}",
                extra={"label_id": label_id},
            )
            return True
        except HttpError as e:
            logger.error(f"[STORM] Delete label failed: {e}")
            raise ExternalServiceError("gmail", f"Delete label failed: {e}") from e

    async def update_label(
        self,
        label_id: str,
        name: str | None = None,
        label_list_visibility: str | None = None,
        message_list_visibility: str | None = None,
        context: Any = None,  # noqa: ARG002
    ) -> GmailLabel:
        """
        Update a custom Gmail label.

        Args:
            label_id: Gmail label ID to update
            name: New label name (optional)
            label_list_visibility: New visibility in label list (optional)
            message_list_visibility: New visibility in message list (optional)
            context: Ignored (kept for interface compatibility)

        Returns:
            Updated GmailLabel object

        Raises:
            ExternalServiceError: If update fails

        Reference: Issue #217 (MCP-011)
        """
        await self.start()

        def do_update_label() -> dict[str, Any]:
            label_body: dict[str, Any] = {}
            if name is not None:
                label_body["name"] = name
            if label_list_visibility is not None:
                label_body["labelListVisibility"] = label_list_visibility
            if message_list_visibility is not None:
                label_body["messageListVisibility"] = message_list_visibility

            result: dict[str, Any] = (
                self._gmail_service.users()
                .labels()
                .patch(userId="me", id=label_id, body=label_body)
                .execute()
            )
            return result

        try:
            result = await self._rate_limited_call("gmail", do_update_label)
            logger.info(
                f"[BEACON] Label updated: {label_id}",
                extra={"label_id": label_id, "label_name": result.get("name")},
            )
            return GmailLabel(
                id=result.get("id", label_id),
                name=result.get("name", ""),
                type=result.get("type", "user").lower(),
            )
        except HttpError as e:
            logger.error(f"[STORM] Update label failed: {e}")
            raise ExternalServiceError("gmail", f"Update label failed: {e}") from e

    # ===========================================================================
    # Calendar Operations
    # ===========================================================================

    async def list_calendars(
        self,
        owned_only: bool = True,
    ) -> list[dict[str, Any]]:
        """
        List all calendars accessible to the user.

        Args:
            owned_only: If True, only return calendars where user is owner

        Returns:
            List of calendar metadata dicts with id, summary, accessRole, etc.

        Raises:
            ExternalServiceError: If listing fails
        """
        await self.start()

        loop = asyncio.get_event_loop()

        def do_list() -> list[dict[str, Any]]:
            try:
                calendars: list[dict[str, Any]] = []
                page_token = None

                while True:
                    results = (
                        self._calendar_service.calendarList().list(pageToken=page_token).execute()
                    )
                    calendars.extend(results.get("items", []))
                    page_token = results.get("nextPageToken")
                    if not page_token:
                        break

                if owned_only:
                    calendars = [c for c in calendars if c.get("accessRole") == "owner"]

                return calendars
            except HttpError as e:
                raise ExternalServiceError("calendar", f"List calendars failed: {e}") from e

        try:
            return await loop.run_in_executor(None, do_list)
        except Exception as e:
            logger.error(f"[STORM] Calendar list failed: {e}")
            raise

    async def list_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        max_results: int = 10,
        calendar_id: str = "primary",
        calendar_name: str | None = None,
        context: Any = None,  # noqa: ARG002
    ) -> list[CalendarEvent]:
        """
        List calendar events in a time range from a specific calendar.

        Args:
            start: Start of time range (default: now)
            end: End of time range (default: 7 days from start)
            max_results: Maximum number of events to return (default: 10)
            calendar_id: Calendar ID to fetch from (default: "primary")
            calendar_name: Human-readable calendar name for display
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

        # Capture for closure
        start_time = start
        end_time = end

        def do_list() -> list[dict[str, Any]]:
            # Format as RFC3339 for Google Calendar API
            # Strip timezone info and use Z suffix for UTC
            time_min = start_time.replace(tzinfo=None).isoformat() + "Z"
            time_max = end_time.replace(tzinfo=None).isoformat() + "Z"
            results = (
                self._calendar_service.events()
                .list(
                    calendarId=calendar_id,
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

        try:
            raw_events = await self._rate_limited_call("calendar", do_list)
            return self._parse_calendar_events(raw_events, calendar_id, calendar_name)
        except HttpError as e:
            logger.error(
                f"[STORM] Calendar list failed: {e}",
                extra={"start": start.isoformat(), "end": end.isoformat()},
            )
            raise ExternalServiceError("calendar", f"List failed: {e}") from e
        except Exception as e:
            logger.error(
                f"[STORM] Calendar list failed: {e}",
                extra={"start": start.isoformat(), "end": end.isoformat()},
            )
            raise

    async def list_events_from_all_calendars(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        max_results_per_calendar: int = 50,
        owned_only: bool = True,
    ) -> list[CalendarEvent]:
        """
        List events from all owned calendars.

        Args:
            start: Start of time range (default: now)
            end: End of time range (default: 7 days from start)
            max_results_per_calendar: Max events per calendar (default: 50)
            owned_only: Only fetch from calendars where user is owner

        Returns:
            Combined list of events from all calendars, sorted by start time
        """
        calendars = await self.list_calendars(owned_only=owned_only)

        all_events: list[CalendarEvent] = []
        for cal in calendars:
            cal_id = cal.get("id", "primary")
            cal_name = cal.get("summary", "Unknown Calendar")
            try:
                events = await self.list_events(
                    start=start,
                    end=end,
                    max_results=max_results_per_calendar,
                    calendar_id=cal_id,
                    calendar_name=cal_name,
                )
                all_events.extend(events)
            except Exception as e:
                logger.warning(f"[SWELL] Failed to fetch events from calendar {cal_name}: {e}")
                continue

        # Sort by start time
        all_events.sort(key=lambda e: e.start)
        return all_events

    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        recurrence_rule: str | None = None,
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
            recurrence_rule: Optional RFC 5545 RRULE string for recurring events.
                Use RecurrenceBuilder for common patterns:
                - RecurrenceBuilder.daily() -> "RRULE:FREQ=DAILY"
                - RecurrenceBuilder.weekly(["MO", "WE", "FR"])
                - RecurrenceBuilder.monthly(15)
                - RecurrenceBuilder.yearly()
            context: Ignored (kept for interface compatibility)

        Returns:
            Result containing event ID and link, or error details
        """
        await self.start()

        def do_create() -> dict[str, Any]:
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
            if recurrence_rule:
                event_body["recurrence"] = [recurrence_rule]

            event: dict[str, Any] = (
                self._calendar_service.events()
                .insert(calendarId="primary", body=event_body)
                .execute()
            )
            return event

        try:
            result = await self._rate_limited_call("calendar", do_create)
            return CreateEventResult(
                success=True,
                event_id=result.get("id"),
                event_link=result.get("htmlLink"),
            )
        except (HttpError, ExternalServiceError) as e:
            logger.error(
                f"[STORM] Calendar event creation failed: {e}",
                extra={"title": title, "start": start.isoformat()},
            )
            return CreateEventResult(success=False, error=str(e))

    async def update_event(
        self,
        event_id: str,
        title: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        recurrence_rule: str | None = None,
        context: Any = None,  # noqa: ARG002
    ) -> UpdateEventResult:
        """
        Update an existing calendar event.

        Uses PATCH to allow partial updates - only specified fields are changed.

        Args:
            event_id: The ID of the event to update
            title: New event title/summary (optional)
            start: New start time (optional)
            end: New end time (optional)
            description: New event description (optional)
            location: New event location (optional)
            attendees: New list of attendee email addresses (optional)
            recurrence_rule: New RFC 5545 RRULE string (optional).
                Use RecurrenceBuilder for common patterns.
            context: Ignored (kept for interface compatibility)

        Returns:
            Result containing updated event ID and link, or error details
        """
        await self.start()

        def do_update() -> dict[str, Any]:
            event_body: dict[str, Any] = {}

            if title is not None:
                event_body["summary"] = title
            if start is not None:
                event_body["start"] = {"dateTime": start.isoformat(), "timeZone": "UTC"}
            if end is not None:
                event_body["end"] = {"dateTime": end.isoformat(), "timeZone": "UTC"}
            if description is not None:
                event_body["description"] = description
            if location is not None:
                event_body["location"] = location
            if attendees is not None:
                event_body["attendees"] = [{"email": email} for email in attendees]
            if recurrence_rule is not None:
                event_body["recurrence"] = [recurrence_rule]

            event: dict[str, Any] = (
                self._calendar_service.events()
                .patch(calendarId="primary", eventId=event_id, body=event_body)
                .execute()
            )
            return event

        try:
            result = await self._rate_limited_call("calendar", do_update)
            logger.info(
                f"[BEACON] Calendar event updated: {event_id}",
                extra={"event_id": event_id, "title": title},
            )
            return UpdateEventResult(
                success=True,
                event_id=result.get("id"),
                event_link=result.get("htmlLink"),
            )
        except (HttpError, ExternalServiceError) as e:
            logger.error(
                f"[STORM] Calendar event update failed: {e}",
                extra={"event_id": event_id},
            )
            return UpdateEventResult(success=False, event_id=event_id, error=str(e))

    async def delete_event(
        self,
        event_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> DeleteEventResult:
        """
        Delete a calendar event.

        Args:
            event_id: The ID of the event to delete
            context: Ignored (kept for interface compatibility)

        Returns:
            Result indicating success or error details
        """
        await self.start()

        def do_delete() -> None:
            self._calendar_service.events().delete(calendarId="primary", eventId=event_id).execute()

        try:
            await self._rate_limited_call("calendar", do_delete)
            logger.info(
                f"[BEACON] Calendar event deleted: {event_id}",
                extra={"event_id": event_id},
            )
            return DeleteEventResult(success=True, event_id=event_id)
        except (HttpError, ExternalServiceError) as e:
            logger.error(
                f"[STORM] Calendar event deletion failed: {e}",
                extra={"event_id": event_id},
            )
            return DeleteEventResult(success=False, event_id=event_id, error=str(e))

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

    async def search_events(
        self,
        query: str,
        start: datetime | None = None,
        end: datetime | None = None,
        max_results: int = 25,
        calendar_id: str = "primary",
        context: Any = None,  # noqa: ARG002
    ) -> list[CalendarEvent]:
        """
        Search calendar events by title/description.

        Args:
            query: Search query to match against event title/description
            start: Start of time range (default: now)
            end: End of time range (default: 30 days from start)
            max_results: Maximum number of events to return (default: 25)
            calendar_id: Calendar ID to search in (default: "primary")
            context: Ignored (kept for interface compatibility)

        Returns:
            List of matching calendar events sorted by start time

        Raises:
            ExternalServiceError: If search fails
        """
        await self.start()

        if start is None:
            start = datetime.now()
        if end is None:
            end = start + timedelta(days=30)

        # Capture for closure
        search_query = query
        start_time = start
        end_time = end

        def do_search() -> list[dict[str, Any]]:
            # Format as RFC3339 for Google Calendar API
            time_min = start_time.replace(tzinfo=None).isoformat() + "Z"
            time_max = end_time.replace(tzinfo=None).isoformat() + "Z"
            results = (
                self._calendar_service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                    q=search_query,  # Google Calendar's query parameter
                )
                .execute()
            )
            items: list[dict[str, Any]] = results.get("items", [])
            return items

        try:
            raw_events = await self._rate_limited_call("calendar", do_search)
            events = self._parse_calendar_events(raw_events, calendar_id, None)
            logger.info(
                f"[BEACON] Calendar search found {len(events)} events",
                extra={"query": query, "results": len(events)},
            )
            return events
        except HttpError as e:
            logger.error(
                f"[STORM] Calendar search failed: {e}",
                extra={"query": query},
            )
            raise ExternalServiceError("calendar", f"Search failed: {e}") from e

    async def find_free_slots(
        self,
        duration_minutes: int,
        start: datetime | None = None,
        end: datetime | None = None,
        working_hours_start: int = 9,
        working_hours_end: int = 17,
        calendar_ids: list[str] | None = None,
        context: Any = None,  # noqa: ARG002
    ) -> list[FreeSlot]:
        """
        Find free time slots in the calendar.

        Queries the FreeBusy API to find available meeting times within
        working hours.

        Args:
            duration_minutes: Required meeting duration in minutes
            start: Start of search range (default: now)
            end: End of search range (default: 7 days from start)
            working_hours_start: Start of working hours, 0-23 (default: 9)
            working_hours_end: End of working hours, 0-23 (default: 17)
            calendar_ids: List of calendar IDs to check (default: ["primary"])
            context: Ignored (kept for interface compatibility)

        Returns:
            List of FreeSlot objects representing available time slots

        Raises:
            ExternalServiceError: If FreeBusy query fails
        """
        await self.start()

        if start is None:
            start = datetime.now()
        if end is None:
            end = start + timedelta(days=7)
        if calendar_ids is None:
            calendar_ids = ["primary"]

        # Capture for closure
        search_start = start
        search_end = end
        cal_ids = calendar_ids

        def do_freebusy() -> dict[str, Any]:
            time_min = search_start.replace(tzinfo=None).isoformat() + "Z"
            time_max = search_end.replace(tzinfo=None).isoformat() + "Z"
            body = {
                "timeMin": time_min,
                "timeMax": time_max,
                "items": [{"id": cal_id} for cal_id in cal_ids],
            }
            result: dict[str, Any] = self._calendar_service.freebusy().query(body=body).execute()
            return result

        try:
            freebusy_result = await self._rate_limited_call("calendar", do_freebusy)
        except HttpError as e:
            logger.error(f"[STORM] FreeBusy query failed: {e}")
            raise ExternalServiceError("calendar", f"FreeBusy query failed: {e}") from e

        # Collect all busy periods across all calendars
        busy_periods: list[tuple[datetime, datetime]] = []
        calendars = freebusy_result.get("calendars", {})
        for cal_id in calendar_ids:
            cal_data = calendars.get(cal_id, {})
            for busy in cal_data.get("busy", []):
                busy_start = datetime.fromisoformat(busy["start"].replace("Z", "+00:00"))
                busy_end = datetime.fromisoformat(busy["end"].replace("Z", "+00:00"))
                # Convert to naive datetime for comparison
                busy_periods.append(
                    (busy_start.replace(tzinfo=None), busy_end.replace(tzinfo=None))
                )

        # Sort busy periods by start time
        busy_periods.sort(key=lambda x: x[0])

        # Find free slots
        free_slots: list[FreeSlot] = []
        duration = timedelta(minutes=duration_minutes)

        # Iterate through each day in the range
        current_day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while current_day < end:
            # Working hours for this day
            day_start = current_day.replace(hour=working_hours_start, minute=0, second=0)
            day_end = current_day.replace(hour=working_hours_end, minute=0, second=0)

            # Skip if day_start is in the past
            if day_start < start:
                day_start = start
            # Skip weekends (Saturday=5, Sunday=6)
            if current_day.weekday() >= 5:
                current_day += timedelta(days=1)
                continue
            # Skip if day has already ended
            if day_end <= start:
                current_day += timedelta(days=1)
                continue

            # Find free slots within working hours for this day
            slot_start = day_start
            for busy_start, busy_end in busy_periods:
                # Skip busy periods outside this day
                if busy_end <= day_start or busy_start >= day_end:
                    continue

                # If there's a gap before this busy period
                if busy_start > slot_start:
                    gap_end = min(busy_start, day_end)
                    # Check if gap is long enough
                    if gap_end - slot_start >= duration:
                        free_slots.append(FreeSlot(start=slot_start, end=gap_end))

                # Move slot_start past this busy period
                slot_start = max(slot_start, busy_end)

            # Check for free time after the last busy period
            if slot_start < day_end and day_end - slot_start >= duration:
                free_slots.append(FreeSlot(start=slot_start, end=day_end))

            current_day += timedelta(days=1)

        logger.info(
            f"[BEACON] Found {len(free_slots)} free slots",
            extra={
                "duration_minutes": duration_minutes,
                "slots_found": len(free_slots),
            },
        )
        return free_slots

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

                # Extract body and attachments
                body = None
                attachments: list[EmailAttachment] = []
                payload = msg.get("payload", {})

                if "body" in payload and payload["body"].get("data"):
                    body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
                elif "parts" in payload:
                    body, attachments = self._extract_parts(payload["parts"])

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
                    attachments=attachments,
                )
                parsed.append(email)

            except Exception as e:
                logger.warning(
                    f"[SWELL] Failed to parse email message: {e}",
                    extra={"message_id": msg.get("id")},
                )
                continue

        return parsed

    def _extract_parts(
        self, parts: list[dict[str, Any]]
    ) -> tuple[str | None, list[EmailAttachment]]:
        """
        Recursively extract body text and attachments from email parts.

        Args:
            parts: List of MIME parts from Gmail API

        Returns:
            Tuple of (body_text, attachments_list)
        """
        body = None
        attachments: list[EmailAttachment] = []

        for part in parts:
            mime_type = part.get("mimeType", "")
            filename = part.get("filename", "")
            part_body = part.get("body", {})

            # Check for nested multipart
            if "parts" in part:
                nested_body, nested_attachments = self._extract_parts(part["parts"])
                if nested_body and not body:
                    body = nested_body
                attachments.extend(nested_attachments)

            # Check for text body
            elif mime_type == "text/plain" and part_body.get("data") and not filename:
                if not body:  # Only take first text/plain
                    body = base64.urlsafe_b64decode(part_body["data"]).decode("utf-8")

            # Check for attachments (has filename and attachmentId)
            elif filename and part_body.get("attachmentId"):
                attachment = EmailAttachment(
                    attachment_id=part_body["attachmentId"],
                    filename=filename,
                    mime_type=mime_type,
                    size=part_body.get("size", 0),
                )
                attachments.append(attachment)

        return body, attachments

    def _parse_calendar_events(
        self,
        events: list[dict[str, Any]],
        calendar_id: str = "primary",
        calendar_name: str | None = None,
    ) -> list[CalendarEvent]:
        """Parse Calendar API response into CalendarEvent models.

        Args:
            events: Raw event data from Google Calendar API
            calendar_id: The calendar ID these events belong to
            calendar_name: Human-readable calendar name
        """
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

                # Extract recurrence info
                recurrence = evt.get("recurrence", [])
                recurrence_rule = recurrence[0] if recurrence else None

                event = CalendarEvent(
                    id=evt.get("id", ""),
                    title=evt.get("summary", "(no title)"),
                    start=start,
                    end=end,
                    location=evt.get("location"),
                    description=evt.get("description"),
                    attendees=[a.get("email", "") for a in evt.get("attendees", [])],
                    calendar_id=calendar_id,
                    calendar_name=calendar_name,
                    event_type=evt.get("eventType"),  # "default", "outOfOffice", "focusTime", etc.
                    transparency=evt.get("transparency"),  # "opaque" (busy) or "transparent" (free)
                    recurrence_rule=recurrence_rule,
                    recurring_event_id=evt.get("recurringEventId"),
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
    "EmailAttachment",
    "EmailMessage",
    "FreeSlot",
    "GoogleWorkspaceBridge",
    "RecurrenceBuilder",
    "SendEmailResult",
]
