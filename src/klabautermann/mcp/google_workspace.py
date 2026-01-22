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
    calendar_id: str = "primary"  # Which calendar this event belongs to
    calendar_name: str | None = None  # Human-readable calendar name
    event_type: str | None = None  # "default", "outOfOffice", "focusTime", "workingLocation"
    transparency: str | None = None  # "opaque" (busy) or "transparent" (free)


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


class EmailSearchResult(BaseModel):
    """Email search results with pagination metadata."""

    emails: list[EmailMessage]
    next_page_token: str | None = None
    result_size_estimate: int | None = None

    @property
    def has_more(self) -> bool:
        """Whether more results are available."""
        return self.next_page_token is not None


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
