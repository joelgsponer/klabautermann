"""
Purser agent for Klabautermann.

State synchronization agent that maintains bidirectional sync between the
knowledge graph and external services (Gmail, Google Calendar). Uses delta-link
pattern to track what has been synced and detect changes.

Includes TheSieve for email filtering - detecting noise and prompt injection.

Reference: specs/architecture/AGENTS_EXTENDED.md Section 2
Issues: #49, #50, #51, #52
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Configuration
# =============================================================================


class RiskLevel(str, Enum):
    """Risk levels for email filtering."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SyncService(str, Enum):
    """External services that can be synced."""

    GMAIL = "gmail"
    CALENDAR = "calendar"


@dataclass
class PurserConfig:
    """Configuration for Purser agent."""

    # Gmail settings
    gmail_enabled: bool = True
    gmail_max_per_sync: int = 50
    gmail_lookback_hours: int = 24

    # Calendar settings
    calendar_enabled: bool = True
    calendar_lookahead_days: int = 30
    calendar_max_per_sync: int = 100

    # Sync scheduling
    sync_interval_minutes: int = 15

    # Sieve settings
    min_email_words: int = 5


@dataclass
class EmailManifest:
    """Result of email filtering by TheSieve."""

    email_id: str
    is_manifest_worthy: bool
    risk_level: RiskLevel
    filter_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "email_id": self.email_id,
            "is_manifest_worthy": self.is_manifest_worthy,
            "risk_level": self.risk_level.value,
            "filter_reason": self.filter_reason,
        }


@dataclass
class SyncResult:
    """Result of a sync operation."""

    service: SyncService
    items_found: int
    items_synced: int
    items_skipped: int
    items_expired: int
    errors: list[str]
    duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "service": self.service.value,
            "items_found": self.items_found,
            "items_synced": self.items_synced,
            "items_skipped": self.items_skipped,
            "items_expired": self.items_expired,
            "errors": self.errors,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class SyncState:
    """Tracks sync state for a service."""

    service: SyncService
    last_sync: datetime | None = None
    last_sync_ms: int = 0
    items_synced_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "service": self.service.value,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "last_sync_ms": self.last_sync_ms,
            "items_synced_total": self.items_synced_total,
        }


@dataclass
class SyncHealthMetrics:
    """
    Health metrics for sync operations.

    Tracks success/failure counts and provides health status calculation.
    Issue: #57
    """

    service: SyncService
    sync_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_error: str | None = None
    total_items_synced: int = 0
    total_items_failed: int = 0
    avg_duration_ms: float = 0.0
    _durations: list[float] | None = None  # Internal, not serialized

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.sync_count == 0:
            return 100.0
        return (self.success_count / self.sync_count) * 100.0

    @property
    def is_healthy(self) -> bool:
        """Determine if sync is healthy (>= 90% success rate)."""
        return self.success_rate >= 90.0

    def record_success(self, items_synced: int, duration_ms: float) -> None:
        """Record a successful sync."""
        self.sync_count += 1
        self.success_count += 1
        self.last_success = datetime.now()
        self.total_items_synced += items_synced
        self._update_avg_duration(duration_ms)

    def record_failure(self, error: str, duration_ms: float) -> None:
        """Record a failed sync."""
        self.sync_count += 1
        self.failure_count += 1
        self.last_failure = datetime.now()
        self.last_error = error
        self._update_avg_duration(duration_ms)

    def _update_avg_duration(self, duration_ms: float) -> None:
        """Update rolling average duration."""
        if self._durations is None:
            self._durations = []
        self._durations.append(duration_ms)
        # Keep last 100 durations for rolling average
        if len(self._durations) > 100:
            self._durations = self._durations[-100:]
        self.avg_duration_ms = sum(self._durations) / len(self._durations)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "service": self.service.value,
            "sync_count": self.sync_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 2),
            "is_healthy": self.is_healthy,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
            "last_error": self.last_error,
            "total_items_synced": self.total_items_synced,
            "total_items_failed": self.total_items_failed,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
        }


# =============================================================================
# TheSieve - Email Filtering
# =============================================================================


class TheSieve:
    """
    Email filtering logic to keep the Locker clean.

    Filters out:
    - Noise: newsletters, promotional emails, no-reply addresses
    - Boarding Parties: prompt injection attempts in email content
    - Insufficient signal: emails with too little content
    """

    # Patterns that indicate noise/transactional emails
    NOISE_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"(?i)unsubscribe"),
        re.compile(r"(?i)no-?reply"),
        re.compile(r"(?i)newsletter"),
        re.compile(r"(?i)promotions?@"),
        re.compile(r"(?i)marketing@"),
        re.compile(r"(?i)noreply@"),
        re.compile(r"(?i)do-not-reply"),
        re.compile(r"(?i)automated message"),
        re.compile(r"(?i)this is an automated"),
    ]

    # Patterns that indicate prompt injection attempts (Boarding Party)
    INJECTION_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"(?i)ignore previous instructions"),
        re.compile(r"(?i)ignore all previous"),
        re.compile(r"(?i)disregard (your|all) (instructions|rules)"),
        re.compile(r"(?i)system prompt"),
        re.compile(r"(?i)you are now"),
        re.compile(r"(?i)new instructions:"),
        re.compile(r"(?i)delete all"),
        re.compile(r"(?i)forget everything"),
        re.compile(r"(?i)act as (a|an) (different|new)"),
        re.compile(r"(?i)override (your|the) (rules|instructions)"),
    ]

    def __init__(self, min_words: int = 5) -> None:
        """
        Initialize TheSieve.

        Args:
            min_words: Minimum word count for an email to be considered.
        """
        self.min_words = min_words

    def filter_email(self, email_data: dict[str, Any]) -> EmailManifest:
        """
        Determine if email is manifest-worthy.

        Checks for:
        1. Prompt injection (HIGH risk - immediate reject)
        2. Noise patterns (LOW risk - skip)
        3. Minimum content (LOW risk - skip)

        Args:
            email_data: Email data with subject, from, body fields.

        Returns:
            EmailManifest with filtering decision.
        """
        email_id = email_data.get("id", "unknown")
        subject = email_data.get("subject", "")
        sender = email_data.get("from", "")
        body = email_data.get("body", "")

        # 1. Security check - Boarding Party detection (prompt injection)
        for pattern in self.INJECTION_PATTERNS:
            if pattern.search(body) or pattern.search(subject):
                logger.warning(
                    f"[SWELL] Boarding Party detected in email {email_id}",
                    extra={"pattern": pattern.pattern},
                )
                return EmailManifest(
                    email_id=email_id,
                    is_manifest_worthy=False,
                    risk_level=RiskLevel.HIGH,
                    filter_reason="Boarding Party (Prompt Injection) detected",
                )

        # 2. Noise check - newsletters, promotions, automated messages
        combined = f"{subject} {sender} {body[:500]}"
        for pattern in self.NOISE_PATTERNS:
            if pattern.search(combined):
                return EmailManifest(
                    email_id=email_id,
                    is_manifest_worthy=False,
                    risk_level=RiskLevel.LOW,
                    filter_reason=f"Noise pattern matched: {pattern.pattern}",
                )

        # 3. Minimum content check
        word_count = len(body.split())
        if word_count < self.min_words:
            return EmailManifest(
                email_id=email_id,
                is_manifest_worthy=False,
                risk_level=RiskLevel.LOW,
                filter_reason=f"Insufficient signal ({word_count} words < {self.min_words})",
            )

        # Email passes all filters
        return EmailManifest(
            email_id=email_id,
            is_manifest_worthy=True,
            risk_level=RiskLevel.LOW,
        )

    def check_injection(self, text: str) -> bool:
        """
        Check if text contains prompt injection patterns.

        Args:
            text: Text to check.

        Returns:
            True if injection detected, False otherwise.
        """
        return any(pattern.search(text) for pattern in self.INJECTION_PATTERNS)

    def check_noise(self, text: str) -> bool:
        """
        Check if text matches noise patterns.

        Args:
            text: Text to check.

        Returns:
            True if noise detected, False otherwise.
        """
        return any(pattern.search(text) for pattern in self.NOISE_PATTERNS)


# =============================================================================
# Purser Agent
# =============================================================================


class Purser(BaseAgent):
    """
    State synchronization agent.

    The Purser maintains bidirectional synchronization between the knowledge
    graph and external services (Gmail, Google Calendar). Uses delta-link
    pattern to track what has been synced and detect changes.
    """

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        config: PurserConfig | None = None,
    ) -> None:
        """
        Initialize Purser.

        Args:
            neo4j_client: Connected Neo4j client for graph operations.
            config: Optional configuration for sync behavior.
        """
        super().__init__(name="purser")
        self.neo4j = neo4j_client
        self.purser_config = config or PurserConfig()
        self.sieve = TheSieve(min_words=self.purser_config.min_email_words)

        # Track sync state in memory (persisted to graph on update)
        self._sync_states: dict[SyncService, SyncState] = {
            SyncService.GMAIL: SyncState(service=SyncService.GMAIL),
            SyncService.CALENDAR: SyncState(service=SyncService.CALENDAR),
        }

        # Health metrics for monitoring (#57)
        self._health_metrics: dict[SyncService, SyncHealthMetrics] = {
            SyncService.GMAIL: SyncHealthMetrics(service=SyncService.GMAIL),
            SyncService.CALENDAR: SyncHealthMetrics(service=SyncService.CALENDAR),
        }

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process an incoming message.

        Purser responds to sync commands.

        Args:
            msg: The incoming agent message.

        Returns:
            Response message with sync results.
        """
        trace_id = msg.trace_id
        payload = msg.payload or {}

        operation = payload.get("operation", "sync_all")

        logger.info(
            f"[CHART] Purser processing {operation}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        if operation == "sync_all":
            results = await self.sync_all(trace_id=trace_id)
            result_payload = {
                "results": [r.to_dict() for r in results],
                "total_synced": sum(r.items_synced for r in results),
            }
        elif operation == "sync_gmail":
            result = await self.sync_gmail(trace_id=trace_id)
            result_payload = result.to_dict()
        elif operation == "sync_calendar":
            result = await self.sync_calendar(trace_id=trace_id)
            result_payload = result.to_dict()
        elif operation == "get_sync_state":
            service_name = payload.get("service")
            if service_name:
                service = SyncService(service_name)
                state = await self.get_sync_state(service, trace_id=trace_id)
                result_payload = state.to_dict() if state else {"error": "Service not found"}
            else:
                states = {s.value: self._sync_states[s].to_dict() for s in SyncService}
                result_payload = {"states": states}
        elif operation == "filter_email":
            email_data = payload.get("email", {})
            manifest = self.sieve.filter_email(email_data)
            result_payload = manifest.to_dict()
        elif operation == "get_health":
            # Health monitoring endpoint (#57)
            service_name = payload.get("service")
            if service_name:
                service = SyncService(service_name)
                metrics = self._health_metrics.get(service)
                if metrics:
                    result_payload = metrics.to_dict()
                else:
                    result_payload = {"error": f"Service not found: {service_name}"}
            else:
                # Return all health metrics
                result_payload = {
                    "health": {s.value: self._health_metrics[s].to_dict() for s in SyncService},
                    "overall_healthy": all(m.is_healthy for m in self._health_metrics.values()),
                }
        else:
            result_payload = {"error": f"Unknown operation: {operation}"}

        return AgentMessage(
            source_agent=self.name,
            target_agent=msg.source_agent,
            intent="purser_result",
            payload=result_payload,
            trace_id=trace_id,
        )

    # =========================================================================
    # Main Sync Operations
    # =========================================================================

    async def sync_all(
        self,
        trace_id: str | None = None,
    ) -> list[SyncResult]:
        """
        Run delta-sync for all enabled services.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            List of SyncResult for each service.
        """
        results: list[SyncResult] = []

        logger.info(
            "[CHART] Purser starting full sync",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        if self.purser_config.gmail_enabled:
            gmail_result = await self.sync_gmail(trace_id=trace_id)
            results.append(gmail_result)

        if self.purser_config.calendar_enabled:
            calendar_result = await self.sync_calendar(trace_id=trace_id)
            results.append(calendar_result)

        total_synced = sum(r.items_synced for r in results)
        total_errors = sum(len(r.errors) for r in results)

        logger.info(
            f"[BEACON] Purser sync complete: {total_synced} items synced, {total_errors} errors",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return results

    # =========================================================================
    # Gmail Delta-Sync (#50)
    # =========================================================================

    async def sync_gmail(
        self,
        trace_id: str | None = None,
    ) -> SyncResult:
        """
        Delta-sync emails from Gmail.

        Fetches emails since last sync, applies TheSieve filtering,
        and ingests worthy emails into the graph.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            SyncResult with operation statistics.
        """
        start_time = time.time()
        errors: list[str] = []

        logger.info(
            "[CHART] Purser syncing Gmail",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Get last sync timestamp
        last_sync = await self._get_last_sync(SyncService.GMAIL, trace_id)

        # Calculate query time range
        if last_sync:
            query_after = last_sync
        else:
            # First sync - look back configured hours
            query_after = datetime.now() - timedelta(hours=self.purser_config.gmail_lookback_hours)

        # Fetch emails (simulated - actual implementation would use MCP)
        emails = await self._fetch_emails_since(query_after, trace_id)

        items_found = len(emails)
        items_synced = 0
        items_skipped = 0

        for email in emails:
            # Apply TheSieve filtering
            manifest = self.sieve.filter_email(email)

            if manifest.risk_level == RiskLevel.HIGH:
                logger.warning(
                    f"[SWELL] Boarding Party detected in email {email.get('id')}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                items_skipped += 1
                continue

            if not manifest.is_manifest_worthy:
                logger.debug(
                    f"[WHISPER] Discarding email: {manifest.filter_reason}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                items_skipped += 1
                continue

            # Check for duplicates via external_id
            email_id = email.get("id", "")
            exists = await self._check_external_id(SyncService.GMAIL, email_id, trace_id)
            if exists:
                items_skipped += 1
                continue

            # Ingest worthy email
            try:
                await self._ingest_email(email, manifest, trace_id)
                items_synced += 1
            except Exception as e:
                error_msg = f"Failed to ingest email {email_id}: {e}"
                logger.error(
                    f"[STORM] {error_msg}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                errors.append(error_msg)

        # Update sync timestamp
        await self._update_sync_timestamp(SyncService.GMAIL, trace_id)

        duration_ms = (time.time() - start_time) * 1000

        result = SyncResult(
            service=SyncService.GMAIL,
            items_found=items_found,
            items_synced=items_synced,
            items_skipped=items_skipped,
            items_expired=0,
            errors=errors,
            duration_ms=duration_ms,
        )

        logger.info(
            f"[BEACON] Gmail sync complete: found {items_found}, "
            f"synced {items_synced}, skipped {items_skipped}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Record health metrics (#57)
        if errors:
            self._health_metrics[SyncService.GMAIL].record_failure(errors[0], duration_ms)
        else:
            self._health_metrics[SyncService.GMAIL].record_success(items_synced, duration_ms)

        return result

    # =========================================================================
    # Calendar Delta-Sync (#51)
    # =========================================================================

    async def sync_calendar(
        self,
        trace_id: str | None = None,
    ) -> SyncResult:
        """
        Delta-sync calendar events.

        Fetches events since last sync, creates/updates event nodes,
        and marks deleted events as expired.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            SyncResult with operation statistics.
        """
        start_time = time.time()
        errors: list[str] = []

        logger.info(
            "[CHART] Purser syncing Calendar",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Get last sync timestamp
        last_sync = await self._get_last_sync(SyncService.CALENDAR, trace_id)

        # Calculate query time range
        time_min = last_sync or datetime.now()
        time_max = datetime.now() + timedelta(days=self.purser_config.calendar_lookahead_days)

        # Fetch events (simulated - actual implementation would use MCP)
        events = await self._fetch_events_in_range(time_min, time_max, trace_id)

        items_found = len(events)
        items_synced = 0
        items_skipped = 0
        items_expired = 0

        # Track fetched event IDs for deletion detection
        fetched_ids: set[str] = set()

        for event in events:
            event_id = event.get("id", "")
            fetched_ids.add(event_id)

            # Check if already synced
            exists = await self._check_external_id(SyncService.CALENDAR, event_id, trace_id)

            if exists:
                # Check for updates
                try:
                    updated = await self._update_event_if_changed(event, trace_id)
                    if updated:
                        items_synced += 1
                    else:
                        items_skipped += 1
                except Exception as e:
                    error_msg = f"Failed to update event {event_id}: {e}"
                    logger.error(
                        f"[STORM] {error_msg}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )
                    errors.append(error_msg)
            else:
                # Create new event node
                try:
                    await self._create_event_node(event, trace_id)
                    items_synced += 1
                except Exception as e:
                    error_msg = f"Failed to create event {event_id}: {e}"
                    logger.error(
                        f"[STORM] {error_msg}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )
                    errors.append(error_msg)

        # Handle deleted events (mark as expired)
        try:
            items_expired = await self._expire_deleted_events(fetched_ids, trace_id)
        except Exception as e:
            error_msg = f"Failed to expire deleted events: {e}"
            logger.error(
                f"[STORM] {error_msg}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            errors.append(error_msg)

        # Update sync timestamp
        await self._update_sync_timestamp(SyncService.CALENDAR, trace_id)

        duration_ms = (time.time() - start_time) * 1000

        result = SyncResult(
            service=SyncService.CALENDAR,
            items_found=items_found,
            items_synced=items_synced,
            items_skipped=items_skipped,
            items_expired=items_expired,
            errors=errors,
            duration_ms=duration_ms,
        )

        logger.info(
            f"[BEACON] Calendar sync complete: found {items_found}, "
            f"synced {items_synced}, expired {items_expired}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Record health metrics (#57)
        if errors:
            self._health_metrics[SyncService.CALENDAR].record_failure(errors[0], duration_ms)
        else:
            self._health_metrics[SyncService.CALENDAR].record_success(items_synced, duration_ms)

        return result

    # =========================================================================
    # Sync State Management
    # =========================================================================

    async def get_sync_state(
        self,
        service: SyncService,
        trace_id: str | None = None,
    ) -> SyncState | None:
        """
        Get sync state for a service.

        Args:
            service: Service to get state for.
            trace_id: Optional trace ID for logging.

        Returns:
            SyncState if found, None otherwise.
        """
        # Try to load from graph if not in memory
        if self._sync_states[service].last_sync is None:
            await self._load_sync_state(service, trace_id)

        return self._sync_states.get(service)

    def get_sync_health(
        self,
        service: SyncService | None = None,
    ) -> dict[str, Any]:
        """
        Get health metrics for sync operations.

        Args:
            service: Optional service to get metrics for. If None, returns all.

        Returns:
            Dictionary with health metrics.

        Issue: #57
        """
        if service:
            metrics = self._health_metrics.get(service)
            if metrics:
                return metrics.to_dict()
            return {"error": f"Service not found: {service.value}"}

        return {
            "health": {s.value: self._health_metrics[s].to_dict() for s in SyncService},
            "overall_healthy": all(m.is_healthy for m in self._health_metrics.values()),
        }

    async def _get_last_sync(
        self,
        service: SyncService,
        trace_id: str | None = None,
    ) -> datetime | None:
        """
        Get last sync timestamp for a service.

        Args:
            service: Service to get timestamp for.
            trace_id: Optional trace ID for logging.

        Returns:
            Last sync datetime if available, None otherwise.
        """
        state = await self.get_sync_state(service, trace_id)
        return state.last_sync if state else None

    async def _update_sync_timestamp(
        self,
        service: SyncService,
        trace_id: str | None = None,
    ) -> None:
        """
        Update sync timestamp for a service.

        Args:
            service: Service to update.
            trace_id: Optional trace ID for logging.
        """
        now = datetime.now()
        now_ms = int(now.timestamp() * 1000)

        self._sync_states[service].last_sync = now
        self._sync_states[service].last_sync_ms = now_ms

        # Persist to graph
        query = """
        MERGE (s:SyncState {service: $service})
        SET s.last_sync_ms = $last_sync_ms,
            s.updated_at = timestamp()
        """

        await self.neo4j.execute_query(
            query,
            {"service": service.value, "last_sync_ms": now_ms},
            trace_id=trace_id,
        )

        logger.debug(
            f"[WHISPER] Updated sync timestamp for {service.value}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

    async def _load_sync_state(
        self,
        service: SyncService,
        trace_id: str | None = None,
    ) -> None:
        """
        Load sync state from graph.

        Args:
            service: Service to load state for.
            trace_id: Optional trace ID for logging.
        """
        query = """
        MATCH (s:SyncState {service: $service})
        RETURN s.last_sync_ms as last_sync_ms
        """

        result = await self.neo4j.execute_query(
            query,
            {"service": service.value},
            trace_id=trace_id,
        )

        if result:
            last_sync_ms = result[0].get("last_sync_ms", 0)
            if last_sync_ms:
                self._sync_states[service].last_sync_ms = last_sync_ms
                self._sync_states[service].last_sync = datetime.fromtimestamp(last_sync_ms / 1000)

    # =========================================================================
    # External ID Tracking
    # =========================================================================

    async def _check_external_id(
        self,
        service: SyncService,
        external_id: str,
        trace_id: str | None = None,
    ) -> bool:
        """
        Check if external ID already exists in graph.

        Args:
            service: External service name.
            external_id: External ID to check.
            trace_id: Optional trace ID for logging.

        Returns:
            True if ID exists, False otherwise.
        """
        query = """
        MATCH (n)
        WHERE n.external_service = $service
          AND n.external_id = $external_id
        RETURN count(n) > 0 as exists
        """

        result = await self.neo4j.execute_query(
            query,
            {"service": service.value, "external_id": external_id},
            trace_id=trace_id,
        )

        exists: bool = result[0].get("exists", False) if result else False
        return exists

    # =========================================================================
    # Email Ingestion
    # =========================================================================

    async def _fetch_emails_since(
        self,
        since: datetime,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch emails since a given timestamp.

        This is a placeholder - actual implementation would use MCP
        to call Gmail API.

        Args:
            since: Fetch emails after this timestamp.
            trace_id: Optional trace ID for logging.

        Returns:
            List of email data dictionaries.
        """
        # Placeholder - would be replaced with MCP call
        logger.debug(
            f"[WHISPER] Would fetch emails since {since.isoformat()}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )
        return []

    async def _ingest_email(
        self,
        email: dict[str, Any],
        manifest: EmailManifest,  # noqa: ARG002 - reserved for future use
        trace_id: str | None = None,
    ) -> None:
        """
        Ingest a worthy email into the graph.

        Creates an Email node with relationships to sender/recipients.

        Args:
            email: Email data.
            manifest: Filtering result from TheSieve.
            trace_id: Optional trace ID for logging.
        """
        email_id = email.get("id", "")
        subject = email.get("subject", "")
        sender = email.get("from", "")
        body = email.get("body", "")
        received_at = email.get("received_at", int(time.time() * 1000))

        query = """
        CREATE (e:Email {
            uuid: randomUUID(),
            external_service: 'gmail',
            external_id: $email_id,
            subject: $subject,
            sender: $sender,
            body_preview: $body_preview,
            received_at: $received_at,
            created_at: timestamp()
        })
        RETURN e.uuid as uuid
        """

        await self.neo4j.execute_query(
            query,
            {
                "email_id": email_id,
                "subject": subject,
                "sender": sender,
                "body_preview": body[:500] if body else "",
                "received_at": received_at,
            },
            trace_id=trace_id,
        )

        logger.debug(
            f"[WHISPER] Ingested email {email_id}: {subject[:50]}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

    # =========================================================================
    # Calendar Event Management
    # =========================================================================

    async def _fetch_events_in_range(
        self,
        time_min: datetime,
        time_max: datetime,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch calendar events in a time range.

        This is a placeholder - actual implementation would use MCP
        to call Calendar API.

        Args:
            time_min: Start of time range.
            time_max: End of time range.
            trace_id: Optional trace ID for logging.

        Returns:
            List of event data dictionaries.
        """
        # Placeholder - would be replaced with MCP call
        logger.debug(
            f"[WHISPER] Would fetch events from {time_min.isoformat()} to {time_max.isoformat()}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )
        return []

    async def _create_event_node(
        self,
        event: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        """
        Create a new Event node in the graph.

        Args:
            event: Event data.
            trace_id: Optional trace ID for logging.
        """
        event_id = event.get("id", "")
        title = event.get("title", "")
        start_time = event.get("start_time", 0)
        end_time = event.get("end_time", 0)
        location = event.get("location", "")
        description = event.get("description", "")

        query = """
        CREATE (e:Event {
            uuid: randomUUID(),
            external_service: 'calendar',
            external_id: $event_id,
            title: $title,
            start_time: $start_time,
            end_time: $end_time,
            location_context: $location,
            description: $description,
            created_at: timestamp()
        })
        RETURN e.uuid as uuid
        """

        await self.neo4j.execute_query(
            query,
            {
                "event_id": event_id,
                "title": title,
                "start_time": start_time,
                "end_time": end_time,
                "location": location,
                "description": description,
            },
            trace_id=trace_id,
        )

        logger.debug(
            f"[WHISPER] Created event {event_id}: {title}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

    async def _update_event_if_changed(
        self,
        event: dict[str, Any],
        trace_id: str | None = None,
    ) -> bool:
        """
        Update an event if it has changed.

        Args:
            event: Event data.
            trace_id: Optional trace ID for logging.

        Returns:
            True if event was updated, False if unchanged.
        """
        event_id = event.get("id", "")
        title = event.get("title", "")
        start_time = event.get("start_time", 0)
        end_time = event.get("end_time", 0)
        location = event.get("location", "")

        # Check if any field changed and update
        query = """
        MATCH (e:Event {external_service: 'calendar', external_id: $event_id})
        WHERE e.title <> $title
           OR e.start_time <> $start_time
           OR e.end_time <> $end_time
           OR coalesce(e.location_context, '') <> $location
        SET e.title = $title,
            e.start_time = $start_time,
            e.end_time = $end_time,
            e.location_context = $location,
            e.updated_at = timestamp()
        RETURN count(e) > 0 as updated
        """

        result = await self.neo4j.execute_query(
            query,
            {
                "event_id": event_id,
                "title": title,
                "start_time": start_time,
                "end_time": end_time,
                "location": location,
            },
            trace_id=trace_id,
        )

        updated: bool = result[0].get("updated", False) if result else False

        if updated:
            logger.debug(
                f"[WHISPER] Updated event {event_id}: {title}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

        return updated

    async def _expire_deleted_events(
        self,
        current_ids: set[str],
        trace_id: str | None = None,
    ) -> int:
        """
        Mark events as expired if they've been deleted externally.

        Args:
            current_ids: Set of current external IDs from API.
            trace_id: Optional trace ID for logging.

        Returns:
            Number of events expired.
        """
        if not current_ids:
            return 0

        # Mark events as expired if not in current fetch
        # Only affect future/recent events to avoid touching historical data
        query = """
        MATCH (e:Event {external_service: 'calendar'})
        WHERE e.external_id IS NOT NULL
          AND NOT e.external_id IN $current_ids
          AND e.expired_at IS NULL
          AND e.start_time > timestamp() - 86400000
        SET e.expired_at = timestamp()
        RETURN count(e) as expired_count
        """

        result = await self.neo4j.execute_query(
            query,
            {"current_ids": list(current_ids)},
            trace_id=trace_id,
        )

        expired_count: int = result[0].get("expired_count", 0) if result else 0

        if expired_count > 0:
            logger.info(
                f"[CHART] Expired {expired_count} deleted calendar events",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

        return expired_count


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "EmailManifest",
    "Purser",
    "PurserConfig",
    "RiskLevel",
    "SyncResult",
    "SyncService",
    "SyncState",
    "TheSieve",
]
