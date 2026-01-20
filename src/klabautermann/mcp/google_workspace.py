"""
Google Workspace Bridge - Direct API integration for Gmail and Calendar.

Uses Google APIs directly with OAuth2 refresh tokens, avoiding MCP subprocess
complexity. Provides Pydantic-validated responses for Gmail and Calendar operations.

Reference: specs/architecture/AGENTS.md Section 1.4
Issues: #207 (reply-to-thread), #208 (attachments), #214 (OAuth refresh),
        #215 (rate limiting), #216 (pagination)
"""

from __future__ import annotations

import asyncio
import base64
import functools
import os
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field

from klabautermann.core.exceptions import ExternalServiceError
from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from collections.abc import Callable


# ===========================================================================
# Response Models
# ===========================================================================


class EmailAttachment(BaseModel):
    """Email attachment metadata (#208)."""

    id: str
    filename: str
    mime_type: str
    size: int


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
    message_id_header: str | None = None  # For reply-to (#207)
    references: str | None = None  # For reply-to (#207)
    attachments: list[EmailAttachment] = Field(default_factory=list)  # (#208)


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


class EmailSearchResult(BaseModel):
    """Paginated email search result (#216)."""

    emails: list[EmailMessage] = Field(default_factory=list)
    next_page_token: str | None = None
    result_size_estimate: int | None = None


# ===========================================================================
# Rate Limiting (#215)
# ===========================================================================


class MCPRateLimiter:
    """
    Rate limiter for MCP/Google API calls (#215).

    Uses a sliding window algorithm to enforce rate limits
    and prevent API abuse.
    """

    def __init__(
        self,
        requests_per_second: float = 10.0,
        burst_allowance: int = 5,
    ) -> None:
        """
        Initialize rate limiter.

        Args:
            requests_per_second: Maximum sustained request rate
            burst_allowance: Extra requests allowed for short bursts
        """
        self._requests_per_second = requests_per_second
        self._burst_allowance = burst_allowance
        self._tokens = float(burst_allowance)
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """
        Acquire permission to make a request.

        Returns the time waited (0 if no wait was needed).
        Blocks if rate limit exceeded until a token is available.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            self._last_update = now

            # Add tokens based on elapsed time
            self._tokens = min(
                self._burst_allowance,
                self._tokens + elapsed * self._requests_per_second,
            )

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0

            # Calculate wait time
            wait_time = (1.0 - self._tokens) / self._requests_per_second
            await asyncio.sleep(wait_time)

            # Update after sleep
            self._tokens = 0.0
            self._last_update = time.monotonic()
            return wait_time

    @property
    def available_tokens(self) -> float:
        """Get current available tokens (approximate)."""
        now = time.monotonic()
        elapsed = now - self._last_update
        return min(
            self._burst_allowance,
            self._tokens + elapsed * self._requests_per_second,
        )


# ===========================================================================
# OAuth Refresh Decorator (#214)
# ===========================================================================


def with_oauth_retry(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to retry on OAuth 401 errors after refreshing credentials (#214).

    Catches HttpError with 401 status, refreshes the token, and retries once.
    """

    @functools.wraps(func)
    async def wrapper(self: GoogleWorkspaceBridge, *args: Any, **kwargs: Any) -> Any:
        try:
            return await func(self, *args, **kwargs)
        except HttpError as e:
            if e.resp.status == 401:
                logger.info(
                    "[CHART] OAuth token expired, refreshing credentials",
                    extra={"agent_name": "google_workspace"},
                )
                await self._refresh_credentials()
                # Retry once after refresh
                return await func(self, *args, **kwargs)
            raise

    return wrapper


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

    def __init__(
        self,
        rate_limit_rps: float = 10.0,
        rate_limit_burst: int = 5,
    ) -> None:
        """
        Initialize the Google Workspace bridge.

        Args:
            rate_limit_rps: Requests per second limit (#215)
            rate_limit_burst: Burst allowance for rate limiter (#215)
        """
        self._credentials: Credentials | None = None
        self._gmail_service: Any = None
        self._calendar_service: Any = None
        self._started = False
        self._rate_limiter = MCPRateLimiter(rate_limit_rps, rate_limit_burst)
        # Store config for credential refresh
        self._client_id: str | None = None
        self._client_secret: str | None = None
        self._refresh_token: str | None = None

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
        self._client_id = os.getenv("GOOGLE_CLIENT_ID")
        self._client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self._refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")

        if not all([self._client_id, self._client_secret, self._refresh_token]):
            missing = []
            if not self._client_id:
                missing.append("GOOGLE_CLIENT_ID")
            if not self._client_secret:
                missing.append("GOOGLE_CLIENT_SECRET")
            if not self._refresh_token:
                missing.append("GOOGLE_REFRESH_TOKEN")
            raise ExternalServiceError(
                "google",
                f"Missing required environment variables: {', '.join(missing)}",
            )

        # Create credentials from refresh token
        self._credentials = Credentials(
            token=None,
            refresh_token=self._refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._client_id,
            client_secret=self._client_secret,
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

    async def _refresh_credentials(self) -> None:
        """
        Refresh OAuth credentials (#214).

        Called when a 401 error is detected to get a new access token.
        """
        if not self._credentials:
            raise ExternalServiceError("google", "Credentials not initialized")

        loop = asyncio.get_event_loop()

        def do_refresh() -> None:
            self._credentials.refresh(Request())  # type: ignore[union-attr]

        try:
            await loop.run_in_executor(None, do_refresh)
            logger.info(
                "[CHART] OAuth credentials refreshed successfully",
                extra={"agent_name": "google_workspace"},
            )
        except Exception as e:
            raise ExternalServiceError("google", f"Failed to refresh credentials: {e}") from e

    async def stop(self) -> None:
        """Clean up resources (no-op for direct API)."""
        self._started = False
        self._gmail_service = None
        self._calendar_service = None
        logger.info("[CHART] Google Workspace API services stopped")

    # ===========================================================================
    # Gmail Operations
    # ===========================================================================

    @with_oauth_retry
    async def search_emails(
        self,
        query: str,
        max_results: int = 10,
        page_token: str | None = None,
        context: Any = None,  # Kept for interface compatibility
    ) -> list[EmailMessage]:
        """
        Search Gmail messages with a query.

        Args:
            query: Gmail search query (e.g., "from:sarah@acme.com" or "is:unread")
            max_results: Maximum number of messages to return (default: 10)
            page_token: Token for pagination (#216)
            context: Ignored (kept for interface compatibility)

        Returns:
            List of matching email messages

        Raises:
            ExternalServiceError: If search fails
        """
        result = await self.search_emails_paginated(query, max_results, page_token, context)
        return result.emails  # type: ignore[no-any-return]

    @with_oauth_retry
    async def search_emails_paginated(
        self,
        query: str,
        max_results: int = 10,
        page_token: str | None = None,
        context: Any = None,  # noqa: ARG002
    ) -> EmailSearchResult:
        """
        Search Gmail messages with pagination support (#216).

        Args:
            query: Gmail search query (e.g., "from:sarah@acme.com" or "is:unread")
            max_results: Maximum number of messages to return (default: 10)
            page_token: Token for fetching next page
            context: Ignored (kept for interface compatibility)

        Returns:
            EmailSearchResult with emails and pagination info

        Raises:
            ExternalServiceError: If search fails
        """
        await self.start()

        # Rate limiting (#215)
        await self._rate_limiter.acquire()

        loop = asyncio.get_event_loop()

        def do_search() -> tuple[list[dict[str, Any]], str | None, int | None]:
            try:
                # Build request parameters
                params: dict[str, Any] = {
                    "userId": "me",
                    "q": query,
                    "maxResults": max_results,
                }
                if page_token:
                    params["pageToken"] = page_token

                # List message IDs matching query
                results = self._gmail_service.users().messages().list(**params).execute()

                next_token = results.get("nextPageToken")
                result_estimate = results.get("resultSizeEstimate")
                messages = results.get("messages", [])
                if not messages:
                    return [], next_token, result_estimate

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

                return full_messages, next_token, result_estimate

            except HttpError as e:
                raise ExternalServiceError("gmail", f"Search failed: {e}") from e

        try:
            raw_messages, next_token, result_estimate = await loop.run_in_executor(None, do_search)
            emails = self._parse_gmail_messages(raw_messages)
            return EmailSearchResult(
                emails=emails,
                next_page_token=next_token,
                result_size_estimate=result_estimate,
            )
        except Exception as e:
            logger.error(f"[STORM] Gmail search failed: {e}", extra={"query": query})
            raise

    async def search_emails_all(
        self,
        query: str,
        max_results: int = 100,
        context: Any = None,
    ) -> list[EmailMessage]:
        """
        Search Gmail messages and fetch all pages up to max_results (#216).

        Args:
            query: Gmail search query
            max_results: Maximum total messages to return
            context: Ignored (kept for interface compatibility)

        Returns:
            List of all matching email messages up to max_results
        """
        all_emails: list[EmailMessage] = []
        page_token: str | None = None

        while len(all_emails) < max_results:
            # Calculate how many more we need
            remaining = max_results - len(all_emails)
            page_size = min(remaining, 50)  # Gmail API max per page is 500

            result = await self.search_emails_paginated(query, page_size, page_token, context)
            all_emails.extend(result.emails)

            if not result.next_page_token:
                break
            page_token = result.next_page_token

        return all_emails[:max_results]

    @with_oauth_retry
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        draft_only: bool = False,
        in_reply_to: str | None = None,
        references: str | None = None,
        thread_id: str | None = None,
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
            in_reply_to: Message-ID header for reply threading (#207)
            references: References header for reply threading (#207)
            thread_id: Gmail thread ID to add message to (#207)
            context: Ignored (kept for interface compatibility)

        Returns:
            Result containing message ID or error details
        """
        await self.start()

        # Rate limiting (#215)
        await self._rate_limiter.acquire()

        loop = asyncio.get_event_loop()

        def do_send() -> dict[str, Any]:
            try:
                # Create message
                message = MIMEText(body)
                message["to"] = to
                message["subject"] = subject
                if cc:
                    message["cc"] = cc
                # Reply threading headers (#207)
                if in_reply_to:
                    message["In-Reply-To"] = in_reply_to
                if references:
                    message["References"] = references

                raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

                # Build message body with optional thread_id (#207)
                msg_body: dict[str, Any] = {"raw": raw}
                if thread_id:
                    msg_body["threadId"] = thread_id

                if draft_only:
                    # Create draft
                    draft = (
                        self._gmail_service.users()
                        .drafts()
                        .create(userId="me", body={"message": msg_body})
                        .execute()
                    )
                    return {"id": draft["id"], "is_draft": True}
                else:
                    # Send message
                    sent = (
                        self._gmail_service.users()
                        .messages()
                        .send(userId="me", body=msg_body)
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

    @with_oauth_retry
    async def reply_to_email(
        self,
        message_id: str,
        body: str,
        cc: str | None = None,
        draft_only: bool = False,
        context: Any = None,
    ) -> SendEmailResult:
        """
        Reply to an existing email thread (#207).

        Gets the original email's headers and sends a reply that maintains
        proper threading in email clients.

        Args:
            message_id: Gmail message ID to reply to
            body: Reply body (plain text)
            cc: Optional CC recipients (comma-separated)
            draft_only: If True, save as draft instead of sending
            context: Ignored (kept for interface compatibility)

        Returns:
            Result containing message ID or error details
        """
        await self.start()

        # Rate limiting (#215)
        await self._rate_limiter.acquire()

        loop = asyncio.get_event_loop()

        # First, get the original email to extract threading info
        def get_original() -> dict[str, Any]:
            result: dict[str, Any] = (
                self._gmail_service.users()
                .messages()
                .get(userId="me", id=message_id, format="metadata")
                .execute()
            )
            return result

        try:
            original = await loop.run_in_executor(None, get_original)
        except HttpError as e:
            logger.error(
                f"[STORM] Failed to get original email for reply: {e}",
                extra={"message_id": message_id},
            )
            return SendEmailResult(success=False, error=f"Failed to get original email: {e}")

        # Extract headers
        headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}

        original_subject = headers.get("Subject", "")
        original_from = headers.get("From", "")
        original_message_id = headers.get("Message-ID", headers.get("Message-Id", ""))
        original_references = headers.get("References", "")
        thread_id = original.get("threadId", "")

        # Build subject with "Re: " prefix if not present
        subject = original_subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Build References header: original references + original message-id
        references = original_references
        if original_message_id:
            if references:
                references = f"{references} {original_message_id}"
            else:
                references = original_message_id

        logger.info(
            f"[CHART] Replying to email in thread {thread_id[:8]}...",
            extra={"message_id": message_id, "thread_id": thread_id},
        )

        result: SendEmailResult = await self.send_email(
            to=original_from,
            subject=subject,
            body=body,
            cc=cc,
            draft_only=draft_only,
            in_reply_to=original_message_id,
            references=references,
            thread_id=thread_id,
            context=context,
        )
        return result

    async def get_recent_emails(
        self,
        hours: int = 24,
        context: Any = None,  # noqa: ARG002
    ) -> list[EmailMessage]:
        """Get emails from the last N hours."""
        query = f"newer_than:{hours}h"
        emails: list[EmailMessage] = await self.search_emails(query, max_results=50)
        return emails

    @with_oauth_retry
    async def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        context: Any = None,  # noqa: ARG002
    ) -> bytes:
        """
        Download an email attachment (#208).

        Args:
            message_id: Gmail message ID containing the attachment
            attachment_id: Attachment ID from EmailAttachment.id
            context: Ignored (kept for interface compatibility)

        Returns:
            Raw attachment bytes

        Raises:
            ExternalServiceError: If download fails
        """
        await self.start()

        # Rate limiting (#215)
        await self._rate_limiter.acquire()

        loop = asyncio.get_event_loop()

        def do_download() -> bytes:
            try:
                attachment = (
                    self._gmail_service.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=message_id, id=attachment_id)
                    .execute()
                )
                data = attachment.get("data", "")
                return base64.urlsafe_b64decode(data)
            except HttpError as e:
                raise ExternalServiceError("gmail", f"Download attachment failed: {e}") from e

        try:
            data = await loop.run_in_executor(None, do_download)
            logger.info(
                f"[BEACON] Downloaded attachment ({len(data)} bytes)",
                extra={"message_id": message_id, "attachment_id": attachment_id},
            )
            return data
        except Exception as e:
            logger.error(
                f"[STORM] Attachment download failed: {e}",
                extra={"message_id": message_id, "attachment_id": attachment_id},
            )
            raise

    async def save_attachment(
        self,
        message_id: str,
        attachment_id: str,
        save_path: str,
        context: Any = None,
    ) -> str:
        """
        Download and save an email attachment to disk (#208).

        Args:
            message_id: Gmail message ID containing the attachment
            attachment_id: Attachment ID from EmailAttachment.id
            save_path: Path to save the attachment
            context: Ignored (kept for interface compatibility)

        Returns:
            Path where attachment was saved

        Raises:
            ExternalServiceError: If download or save fails
        """
        data = await self.download_attachment(message_id, attachment_id, context)

        loop = asyncio.get_event_loop()

        def do_save() -> str:
            Path(save_path).write_bytes(data)
            return save_path

        try:
            saved_path = await loop.run_in_executor(None, do_save)
            logger.info(
                f"[BEACON] Saved attachment to {saved_path}",
                extra={"message_id": message_id, "attachment_id": attachment_id},
            )
            return saved_path
        except Exception as e:
            logger.error(
                f"[STORM] Failed to save attachment: {e}",
                extra={"save_path": save_path},
            )
            raise ExternalServiceError("gmail", f"Failed to save attachment: {e}") from e

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

                # Extract body and attachments (#208)
                body = None
                attachments: list[EmailAttachment] = []
                payload = msg.get("payload", {})

                def extract_parts(
                    parts: list[dict[str, Any]],
                ) -> tuple[str | None, list[EmailAttachment]]:
                    """Recursively extract body and attachments from message parts."""
                    found_body = None
                    found_attachments: list[EmailAttachment] = []

                    for part in parts:
                        mime_type = part.get("mimeType", "")
                        part_body = part.get("body", {})

                        # Check for attachment (#208)
                        if part_body.get("attachmentId"):
                            filename = part.get("filename", "")
                            if filename:  # Only include if has filename
                                found_attachments.append(
                                    EmailAttachment(
                                        id=part_body["attachmentId"],
                                        filename=filename,
                                        mime_type=mime_type,
                                        size=part_body.get("size", 0),
                                    )
                                )

                        # Extract text body
                        if mime_type == "text/plain" and part_body.get("data") and not found_body:
                            found_body = base64.urlsafe_b64decode(part_body["data"]).decode("utf-8")

                        # Recurse into nested parts (multipart messages)
                        if "parts" in part:
                            nested_body, nested_attachments = extract_parts(part["parts"])
                            if not found_body and nested_body:
                                found_body = nested_body
                            found_attachments.extend(nested_attachments)

                    return found_body, found_attachments

                if "body" in payload and payload["body"].get("data"):
                    body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
                elif "parts" in payload:
                    body, attachments = extract_parts(payload["parts"])

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
                    # Threading headers (#207)
                    message_id_header=headers.get("Message-ID", headers.get("Message-Id")),
                    references=headers.get("References"),
                    # Attachments (#208)
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
    "EmailAttachment",
    "EmailMessage",
    "EmailOperationResult",
    "EmailSearchResult",
    "GmailLabel",
    "GoogleWorkspaceBridge",
    "MCPRateLimiter",
    "SendEmailResult",
]
