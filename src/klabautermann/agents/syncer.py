"""
Syncer Agent for Klabautermann.

The Syncer is the dock worker that imports external data into the knowledge graph.
It periodically fetches emails and calendar events from Google Workspace and ingests
them via Graphiti for entity extraction, enabling persistent memory of communications
and meetings.

Responsibilities:
1. Sync calendar events from Google Calendar
2. Sync emails from Gmail
3. Create Email nodes with relationships (SENT_BY, SENT_TO)
4. Extract entities from email/event content via Graphiti
5. Track sync state to prevent duplicates

Reference: specs/architecture/AGENTS.md
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage


if TYPE_CHECKING:
    from klabautermann.mcp.google_workspace import (
        CalendarEvent,
        EmailMessage,
        GoogleWorkspaceBridge,
    )
    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.neo4j_client import Neo4jClient


class Syncer(BaseAgent):
    """
    The Syncer Agent - imports external data into the knowledge graph.

    Periodically fetches emails and calendar events from Google Workspace
    and ingests them via Graphiti for entity extraction.
    """

    def __init__(
        self,
        name: str = "syncer",
        config: dict[str, Any] | None = None,
        google_bridge: GoogleWorkspaceBridge | None = None,
        graphiti: GraphitiClient | None = None,
        neo4j: Neo4jClient | None = None,
    ) -> None:
        """
        Initialize the Syncer agent.

        Args:
            name: Agent name (default: "syncer")
            config: Agent configuration (loaded from config/agents/syncer.yaml)
            google_bridge: GoogleWorkspaceBridge for Gmail/Calendar access
            graphiti: GraphitiClient for entity extraction
            neo4j: Neo4jClient for direct graph operations
        """
        super().__init__(name=name, config=config or {})
        self.google_bridge = google_bridge
        self.graphiti = graphiti
        self.neo4j = neo4j

        # Extract configuration with defaults
        calendar_config = self.config.get("calendar", {})
        self.calendar_enabled = calendar_config.get("enabled", True)
        self.calendar_lookback_days = calendar_config.get("lookback_days", 7)
        self.calendar_lookahead_days = calendar_config.get("lookahead_days", 14)

        email_config = self.config.get("email", {})
        self.email_enabled = email_config.get("enabled", True)
        self.email_lookback_hours = email_config.get("lookback_hours", 24)
        self.email_max_per_sync = email_config.get("max_per_sync", 50)
        self.email_query = email_config.get("query", "is:inbox")

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process incoming agent messages.

        Handles SYNC_NOW intent from orchestrator or other agents.

        Args:
            msg: Incoming agent message

        Returns:
            Response message with sync result, or None if no response needed
        """
        trace_id = msg.trace_id

        logger.debug(
            f"[WHISPER] Processing message with intent: {msg.intent}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        if msg.intent == "SYNC_NOW":
            result = await self.process_sync_queue(trace_id=trace_id)

            return AgentMessage(
                trace_id=trace_id,
                source_agent=self.name,
                target_agent=msg.source_agent,
                intent="SYNC_RESULT",
                payload=result,
            )

        logger.warning(
            f"[SWELL] Unknown intent: {msg.intent}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )
        return None

    async def process_sync_queue(self, trace_id: str | None = None) -> dict[str, Any]:
        """
        Main entry point for scheduled sync job.

        Syncs both calendar events and emails from Google Workspace.

        Args:
            trace_id: Trace ID for logging

        Returns:
            Dictionary with sync results (emails_synced, events_synced, errors)
        """
        trace_id = trace_id or str(uuid.uuid4())

        logger.info(
            "[CHART] Processing sync queue",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        result: dict[str, Any] = {
            "emails_synced": 0,
            "events_synced": 0,
            "errors": [],
        }

        if not self.google_bridge:
            logger.warning(
                "[SWELL] Cannot sync: GoogleWorkspaceBridge not configured",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            result["errors"].append("GoogleWorkspaceBridge not configured")
            return result

        # Sync calendar events
        if self.calendar_enabled:
            try:
                events_count = await self.sync_calendar(trace_id)
                result["events_synced"] = events_count
            except Exception as e:
                logger.error(
                    f"[STORM] Calendar sync failed: {e}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                    exc_info=True,
                )
                result["errors"].append(f"Calendar sync failed: {e}")

        # Sync emails
        if self.email_enabled:
            try:
                emails_count = await self.sync_emails(trace_id)
                result["emails_synced"] = emails_count
            except Exception as e:
                logger.error(
                    f"[STORM] Email sync failed: {e}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                    exc_info=True,
                )
                result["errors"].append(f"Email sync failed: {e}")

        # Update sync state
        await self._update_sync_state(trace_id)

        logger.info(
            f"[BEACON] Sync complete: {result['emails_synced']} emails, "
            f"{result['events_synced']} events",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                **result,
            },
        )

        return result

    async def sync_calendar(self, trace_id: str) -> int:
        """
        Sync calendar events from Google Calendar.

        Args:
            trace_id: Trace ID for logging

        Returns:
            Number of events synced
        """
        if not self.google_bridge:
            return 0

        logger.info(
            f"[CHART] Syncing calendar events (lookback: {self.calendar_lookback_days} days, "
            f"lookahead: {self.calendar_lookahead_days} days)",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Calculate time range
        now = datetime.now(tz=UTC)
        start = now - timedelta(days=self.calendar_lookback_days)
        end = now + timedelta(days=self.calendar_lookahead_days)

        # Fetch events
        events = await self.google_bridge.list_events(
            start=start,
            end=end,
            max_results=100,
        )

        synced_count = 0
        for event in events:
            # Check if already synced
            if await self._is_already_synced(event.id, "calendar", trace_id):
                continue

            try:
                await self._ingest_calendar_event(event, trace_id)
                synced_count += 1
            except Exception as e:
                logger.warning(
                    f"[SWELL] Failed to ingest calendar event {event.id}: {e}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )

        logger.info(
            f"[BEACON] Synced {synced_count} calendar events",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return synced_count

    async def sync_emails(self, trace_id: str) -> int:
        """
        Sync emails from Gmail.

        Args:
            trace_id: Trace ID for logging

        Returns:
            Number of emails synced
        """
        if not self.google_bridge:
            return 0

        logger.info(
            f"[CHART] Syncing emails (lookback: {self.email_lookback_hours} hours)",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Build query with time filter
        query = f"{self.email_query} newer_than:{self.email_lookback_hours}h"

        # Fetch emails
        emails = await self.google_bridge.search_emails(
            query=query,
            max_results=self.email_max_per_sync,
        )

        synced_count = 0
        for email in emails:
            # Check if already synced
            if await self._is_already_synced(email.id, "gmail", trace_id):
                continue

            try:
                await self._ingest_email(email, trace_id)
                synced_count += 1
            except Exception as e:
                logger.warning(
                    f"[SWELL] Failed to ingest email {email.id}: {e}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )

        logger.info(
            f"[BEACON] Synced {synced_count} emails",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return synced_count

    # =========================================================================
    # Ingestion Methods
    # =========================================================================

    async def _ingest_calendar_event(
        self,
        event: CalendarEvent,
        trace_id: str,
    ) -> None:
        """
        Create CalendarEvent node and link attendees.

        Args:
            event: Calendar event to ingest
            trace_id: Trace ID for logging
        """
        # 1. Create CalendarEvent node
        event_uuid = str(uuid.uuid4())
        await self._create_calendar_event_node(event, event_uuid, trace_id)

        # 2. Link attendees via ATTENDED_BY
        for attendee in event.attendees:
            await self._link_attendee(event_uuid, attendee, trace_id)

        # 3. Link to Day node
        await self._link_event_to_day(event_uuid, event.start, trace_id)

        # 4. Link to Location if present
        if event.location:
            await self._link_event_to_location(event_uuid, event.location, trace_id)

        # 5. Extract additional entities from event content via Graphiti
        # Call when there's meaningful content: attendees, description, or location
        # Check entities_extracted flag to ensure idempotency
        has_extractable_content = event.description or event.attendees or event.location
        if self.graphiti and has_extractable_content:
            already_extracted = await self._check_entities_extracted(event.id, trace_id)
            if not already_extracted:
                content = self._format_calendar_event(event)
                await self.graphiti.add_episode(
                    content=content,
                    source="calendar",
                    reference_time=event.start,
                    group_id="sync",
                    trace_id=trace_id,
                )
                await self._mark_entities_extracted(event.id, "calendar", trace_id)

        logger.debug(
            f"[WHISPER] Ingested calendar event: {event.title}",
            extra={"trace_id": trace_id, "agent_name": self.name, "event_id": event.id},
        )

    async def _create_calendar_event_node(
        self,
        event: CalendarEvent,
        event_uuid: str,
        trace_id: str,
    ) -> None:
        """
        Create CalendarEvent node in Neo4j.

        Args:
            event: Calendar event data
            event_uuid: UUID for the new CalendarEvent node
            trace_id: Trace ID for logging
        """
        if not self.neo4j:
            return

        query = """
        CREATE (c:CalendarEvent {
            uuid: $uuid,
            title: $title,
            start_time: $start_time,
            end_time: $end_time,
            location: $location,
            description: $description,
            external_id: $external_id,
            source: $source,
            created_at: $created_at
        })
        """
        # Truncate description to prevent oversized nodes
        description = event.description
        if description and len(description) > 2000:
            description = description[:2000] + "..."

        await self.neo4j.execute_write(
            query,
            {
                "uuid": event_uuid,
                "title": event.title,
                "start_time": event.start.timestamp(),
                "end_time": event.end.timestamp(),
                "location": event.location,
                "description": description,
                "external_id": event.id,
                "source": "google_calendar",
                "created_at": datetime.now(tz=UTC).timestamp(),
            },
            trace_id=trace_id,
        )

    async def _link_attendee(
        self,
        event_uuid: str,
        attendee_email: str,
        trace_id: str,
    ) -> None:
        """
        Find or create Person for attendee and link via ATTENDED_BY.

        Args:
            event_uuid: UUID of the CalendarEvent node
            attendee_email: Attendee email address
            trace_id: Trace ID for logging
        """
        if not self.neo4j:
            return

        # Extract name and email
        attendee_name, attendee_addr = self._parse_email_address(attendee_email)

        query = """
        MATCH (c:CalendarEvent {uuid: $event_uuid})
        MERGE (p:Person {email: $attendee_addr})
        ON CREATE SET
            p.uuid = $person_uuid,
            p.name = $attendee_name,
            p.created_at = $now
        CREATE (c)-[:ATTENDED_BY {created_at: $now}]->(p)
        """
        await self.neo4j.execute_write(
            query,
            {
                "event_uuid": event_uuid,
                "attendee_addr": attendee_addr,
                "person_uuid": str(uuid.uuid4()),
                "attendee_name": attendee_name,
                "now": datetime.now(tz=UTC).timestamp(),
            },
            trace_id=trace_id,
        )

    async def _link_event_to_day(
        self,
        event_uuid: str,
        event_date: datetime,
        trace_id: str,
    ) -> None:
        """
        Link CalendarEvent to Day node for temporal spine.

        Args:
            event_uuid: UUID of the CalendarEvent node
            event_date: Date of the event
            trace_id: Trace ID for logging
        """
        if not self.neo4j:
            return

        day_str = event_date.strftime("%Y-%m-%d")
        day_of_week = event_date.strftime("%A")
        is_weekend = event_date.weekday() >= 5

        query = """
        MATCH (c:CalendarEvent {uuid: $event_uuid})
        MERGE (d:Day {date: $day_str})
        ON CREATE SET
            d.day_of_week = $day_of_week,
            d.is_weekend = $is_weekend
        CREATE (c)-[:OCCURRED_ON {created_at: $now}]->(d)
        """
        await self.neo4j.execute_write(
            query,
            {
                "event_uuid": event_uuid,
                "day_str": day_str,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend,
                "now": datetime.now(tz=UTC).timestamp(),
            },
            trace_id=trace_id,
        )

    async def _link_event_to_location(
        self,
        event_uuid: str,
        location_name: str,
        trace_id: str,
    ) -> None:
        """
        Find or create Location and link via HELD_AT_LOCATION.

        Args:
            event_uuid: UUID of the CalendarEvent node
            location_name: Location name/address
            trace_id: Trace ID for logging
        """
        if not self.neo4j:
            return

        query = """
        MATCH (c:CalendarEvent {uuid: $event_uuid})
        MERGE (l:Location {name: $location_name})
        ON CREATE SET
            l.uuid = $location_uuid,
            l.created_at = $now
        CREATE (c)-[:HELD_AT_LOCATION {created_at: $now}]->(l)
        """
        await self.neo4j.execute_write(
            query,
            {
                "event_uuid": event_uuid,
                "location_name": location_name,
                "location_uuid": str(uuid.uuid4()),
                "now": datetime.now(tz=UTC).timestamp(),
            },
            trace_id=trace_id,
        )

    async def _ingest_email(
        self,
        email: EmailMessage,
        trace_id: str,
    ) -> None:
        """
        Create Email node and extract entities from content.

        Args:
            email: Email message to ingest
            trace_id: Trace ID for logging
        """
        # 1. Create Email node
        email_uuid = str(uuid.uuid4())
        await self._create_email_node(email, email_uuid, trace_id)

        # 2. Find/create sender Person and link
        await self._link_sender(email_uuid, email.sender, trace_id)

        # 3. Find/create recipient Person and link
        if email.recipient:
            await self._link_recipient(email_uuid, email.recipient, trace_id)

        # 4. Link to Day node
        await self._link_to_day(email_uuid, email.date, trace_id)

        # 5. Extract additional entities from body via Graphiti
        # Check entities_extracted flag to ensure idempotency
        if self.graphiti and email.body:
            already_extracted = await self._check_entities_extracted(email.id, trace_id)
            if not already_extracted:
                content = self._format_email(email)
                await self.graphiti.add_episode(
                    content=content,
                    source="email",
                    reference_time=email.date,
                    group_id="sync",
                    trace_id=trace_id,
                )
                await self._mark_entities_extracted(email.id, "gmail", trace_id)

        logger.debug(
            f"[WHISPER] Ingested email: {email.subject}",
            extra={"trace_id": trace_id, "agent_name": self.name, "email_id": email.id},
        )

    async def _create_email_node(
        self,
        email: EmailMessage,
        email_uuid: str,
        trace_id: str,
    ) -> None:
        """
        Create Email node in Neo4j.

        Args:
            email: Email message data
            email_uuid: UUID for the new Email node
            trace_id: Trace ID for logging
        """
        if not self.neo4j:
            return

        query = """
        CREATE (e:Email {
            uuid: $uuid,
            subject: $subject,
            sender: $sender,
            recipient: $recipient,
            date: $date,
            snippet: $snippet,
            body: $body,
            thread_id: $thread_id,
            external_id: $external_id,
            is_unread: $is_unread,
            source: $source,
            created_at: $created_at
        })
        """
        # Truncate body to prevent oversized nodes
        body = email.body[:2000] + "..." if email.body and len(email.body) > 2000 else email.body

        await self.neo4j.execute_write(
            query,
            {
                "uuid": email_uuid,
                "subject": email.subject,
                "sender": email.sender,
                "recipient": email.recipient,
                "date": email.date.timestamp(),
                "snippet": email.snippet,
                "body": body,
                "thread_id": email.thread_id,
                "external_id": email.id,
                "is_unread": email.is_unread,
                "source": "gmail",
                "created_at": datetime.now(tz=UTC).timestamp(),
            },
            trace_id=trace_id,
        )

    async def _link_sender(
        self,
        email_uuid: str,
        sender_email: str,
        trace_id: str,
    ) -> None:
        """
        Find or create Person for sender and link via SENT_BY.

        Args:
            email_uuid: UUID of the Email node
            sender_email: Sender email address (may include name)
            trace_id: Trace ID for logging
        """
        if not self.neo4j:
            return

        # Extract name and email from "Name <email>" format
        sender_name, sender_addr = self._parse_email_address(sender_email)

        query = """
        MATCH (e:Email {uuid: $email_uuid})
        MERGE (p:Person {email: $sender_addr})
        ON CREATE SET
            p.uuid = $person_uuid,
            p.name = $sender_name,
            p.created_at = $now
        CREATE (e)-[:SENT_BY {created_at: $now}]->(p)
        """
        await self.neo4j.execute_write(
            query,
            {
                "email_uuid": email_uuid,
                "sender_addr": sender_addr,
                "person_uuid": str(uuid.uuid4()),
                "sender_name": sender_name,
                "now": datetime.now(tz=UTC).timestamp(),
            },
            trace_id=trace_id,
        )

    async def _link_recipient(
        self,
        email_uuid: str,
        recipient_email: str,
        trace_id: str,
    ) -> None:
        """
        Find or create Person for recipient and link via SENT_TO.

        Args:
            email_uuid: UUID of the Email node
            recipient_email: Recipient email address (may include name)
            trace_id: Trace ID for logging
        """
        if not self.neo4j:
            return

        # Extract name and email from "Name <email>" format
        recipient_name, recipient_addr = self._parse_email_address(recipient_email)

        query = """
        MATCH (e:Email {uuid: $email_uuid})
        MERGE (p:Person {email: $recipient_addr})
        ON CREATE SET
            p.uuid = $person_uuid,
            p.name = $recipient_name,
            p.created_at = $now
        CREATE (e)-[:SENT_TO {created_at: $now}]->(p)
        """
        await self.neo4j.execute_write(
            query,
            {
                "email_uuid": email_uuid,
                "recipient_addr": recipient_addr,
                "person_uuid": str(uuid.uuid4()),
                "recipient_name": recipient_name,
                "now": datetime.now(tz=UTC).timestamp(),
            },
            trace_id=trace_id,
        )

    async def _link_to_day(
        self,
        email_uuid: str,
        email_date: datetime,
        trace_id: str,
    ) -> None:
        """
        Link Email to Day node for temporal spine.

        Args:
            email_uuid: UUID of the Email node
            email_date: Date of the email
            trace_id: Trace ID for logging
        """
        if not self.neo4j:
            return

        day_str = email_date.strftime("%Y-%m-%d")
        day_of_week = email_date.strftime("%A")
        is_weekend = email_date.weekday() >= 5

        query = """
        MATCH (e:Email {uuid: $email_uuid})
        MERGE (d:Day {date: $day_str})
        ON CREATE SET
            d.day_of_week = $day_of_week,
            d.is_weekend = $is_weekend
        CREATE (e)-[:OCCURRED_ON {created_at: $now}]->(d)
        """
        await self.neo4j.execute_write(
            query,
            {
                "email_uuid": email_uuid,
                "day_str": day_str,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend,
                "now": datetime.now(tz=UTC).timestamp(),
            },
            trace_id=trace_id,
        )

    # =========================================================================
    # Deduplication Methods
    # =========================================================================

    async def _is_already_synced(
        self,
        external_id: str,
        source: str,
        trace_id: str,
    ) -> bool:
        """
        Check if item was already synced.

        Args:
            external_id: External ID of the item (Gmail message ID or Calendar event ID)
            source: Source system ("gmail" or "calendar")
            trace_id: Trace ID for logging

        Returns:
            True if already synced, False otherwise
        """
        if not self.neo4j:
            return False

        if source == "gmail":
            query = """
            MATCH (e:Email {external_id: $external_id})
            RETURN e.uuid IS NOT NULL as exists
            """
        elif source == "calendar":
            query = """
            MATCH (c:CalendarEvent {external_id: $external_id})
            RETURN c.uuid IS NOT NULL as exists
            """
        else:
            return False

        result = await self.neo4j.execute_read(
            query,
            {"external_id": external_id},
            trace_id=trace_id,
        )

        return bool(result and result[0].get("exists", False))

    async def _mark_synced(
        self,
        external_id: str,
        source: str,
        timestamp: float,
        trace_id: str,
    ) -> None:
        """
        Mark item as synced (for calendar events).

        Note: Emails are marked via the Email node's external_id.
        Calendar events need separate tracking since they go through Graphiti.

        Args:
            external_id: External ID of the item
            source: Source system
            timestamp: Timestamp of the item
            trace_id: Trace ID for logging
        """
        # Calendar events are tracked via SyncState node
        # Email deduplication is handled by the Email node's external_id constraint
        pass

    async def _check_entities_extracted(
        self,
        external_id: str,
        trace_id: str,
    ) -> bool:
        """
        Check if Graphiti entity extraction was already done for this item.

        This provides idempotency for entity extraction, preventing duplicate
        Episodic nodes from being created if the main sync dedup fails.

        Args:
            external_id: External ID of the item (Gmail message ID or Calendar event ID)
            trace_id: Trace ID for logging

        Returns:
            True if entities were already extracted, False otherwise
        """
        if not self.neo4j:
            return False

        query = """
        MATCH (n {external_id: $external_id})
        WHERE n:Email OR n:CalendarEvent
        RETURN n.entities_extracted = true AS extracted
        """
        result = await self.neo4j.execute_read(
            query,
            {"external_id": external_id},
            trace_id=trace_id,
        )

        return bool(result and result[0].get("extracted", False))

    async def _mark_entities_extracted(
        self,
        external_id: str,
        source: str,
        trace_id: str,
    ) -> None:
        """
        Mark node as having had entity extraction done.

        Sets the entities_extracted flag on the Email or CalendarEvent node
        to prevent duplicate Graphiti add_episode() calls.

        Args:
            external_id: External ID of the item
            source: Source system ("gmail" or "calendar")
            trace_id: Trace ID for logging
        """
        if not self.neo4j:
            return

        if source == "gmail":
            query = """
            MATCH (e:Email {external_id: $id})
            SET e.entities_extracted = true
            """
        else:
            query = """
            MATCH (c:CalendarEvent {external_id: $id})
            SET c.entities_extracted = true
            """

        await self.neo4j.execute_write(
            query,
            {"id": external_id},
            trace_id=trace_id,
        )

        logger.debug(
            f"[WHISPER] Marked entities_extracted for {source} {external_id}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

    async def _update_sync_state(self, trace_id: str) -> None:
        """
        Update the SyncState node with current sync timestamp.

        Args:
            trace_id: Trace ID for logging
        """
        if not self.neo4j:
            return

        now = datetime.now(tz=UTC).timestamp()

        # Update Gmail sync state
        if self.email_enabled:
            await self.neo4j.execute_write(
                """
                MERGE (s:SyncState {source: 'gmail'})
                SET s.last_sync_at = $now
                """,
                {"now": now},
                trace_id=trace_id,
            )

        # Update Calendar sync state
        if self.calendar_enabled:
            await self.neo4j.execute_write(
                """
                MERGE (s:SyncState {source: 'google_calendar'})
                SET s.last_sync_at = $now
                """,
                {"now": now},
                trace_id=trace_id,
            )

    # =========================================================================
    # Formatting Methods
    # =========================================================================

    def _format_calendar_event(self, event: CalendarEvent) -> str:
        """
        Format calendar event as natural language for entity extraction.

        Args:
            event: Calendar event to format

        Returns:
            Formatted text for Graphiti ingestion
        """
        start_fmt = event.start.strftime("%B %d, %Y at %I:%M %p")
        end_fmt = event.end.strftime("%I:%M %p")
        parts = [
            f"Calendar Event: {event.title}",
            f"When: {start_fmt} to {end_fmt}",
        ]
        if event.location:
            parts.append(f"Location: {event.location}")
        if event.attendees:
            parts.append(f"Attendees: {', '.join(event.attendees)}")
        if event.description:
            # Truncate long descriptions
            if len(event.description) > 500:
                desc = event.description[:500] + "..."
            else:
                desc = event.description
            parts.append(f"Details: {desc}")
        return "\n".join(parts)

    def _format_email(self, email: EmailMessage) -> str:
        """
        Format email as natural language for entity extraction.

        Args:
            email: Email message to format

        Returns:
            Formatted text for Graphiti ingestion
        """
        parts = [
            f"Email: {email.subject}",
            f"From: {email.sender}",
            f"Date: {email.date.strftime('%B %d, %Y at %I:%M %p')}",
        ]
        if email.recipient:
            parts.append(f"To: {email.recipient}")
        if email.body:
            # Truncate long bodies
            body = email.body[:2000] + "..." if len(email.body) > 2000 else email.body
            parts.append(f"Content: {body}")
        return "\n".join(parts)

    def _parse_email_address(self, email_str: str) -> tuple[str, str]:
        """
        Parse email address from "Name <email>" format.

        Args:
            email_str: Email string like "John Doe <john@example.com>" or "john@example.com"

        Returns:
            Tuple of (name, email_address)
        """
        if "<" in email_str and ">" in email_str:
            # Name-and-address format with angle brackets
            name = email_str.split("<")[0].strip()
            email = email_str.split("<")[1].rstrip(">").strip()
            return (name if name else email, email)
        else:
            # Plain email address
            return (email_str, email_str)


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Syncer"]
