"""
Scribe Agent for Klabautermann.

The Scribe is the Historian that generates daily reflections. It runs at midnight
(or on-demand), gathers the day's statistics, and creates a JournalEntry node
linked to the Day node. The journal serves as a high-level summary of activity,
written in Klabautermann's distinctive voice.

Responsibilities:
1. Generate daily reflection journals (typically at midnight)
2. Gather analytics for the specified day
3. Create JournalEntry nodes with full content and metadata
4. Link journal entries to Day nodes via [:OCCURRED_ON]
5. Ensure idempotency (no duplicate journals for same day)

Reference: specs/architecture/AGENTS.md Section 1.6 (The Scribe)
Task: T046 - Scribe Agent Implementation
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.agents.journal_generation import generate_journal
from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage, DailyAnalytics, JournalEntry
from klabautermann.memory.analytics import get_daily_analytics


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


class Scribe(BaseAgent):
    """
    The Scribe - chronicler of the daily voyage.

    Responsibilities:
    1. Run at midnight (scheduled via APScheduler or called directly)
    2. Query the day's activity statistics
    3. Generate journal entry with Klabautermann personality
    4. Create JournalEntry node linked to Day
    """

    def __init__(
        self,
        name: str = "scribe",
        config: dict[str, Any] | None = None,
        neo4j_client: Neo4jClient | None = None,
    ) -> None:
        """
        Initialize the Scribe agent.

        Args:
            name: Agent name (default: "scribe")
            config: Agent configuration (loaded from config/agents/scribe.yaml)
            neo4j_client: Neo4jClient instance for graph operations
        """
        super().__init__(name=name, config=config or {})
        self.neo4j = neo4j_client

        # Extract configuration values with defaults
        self.min_interactions = self.config.get("min_interactions", 1)
        self.include_highlights = self.config.get("journal", {}).get("include_highlights", True)
        self.max_content_length = self.config.get("journal", {}).get("max_content_length", 2000)

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process incoming messages for the Scribe agent.

        Supports the following intents:
        - generate_journal: Generate a journal entry for a specific date

        Args:
            msg: Incoming agent message

        Returns:
            Response message with journal UUID or error, or None
        """
        trace_id = msg.trace_id

        if msg.intent == "generate_journal":
            date = msg.payload.get("date")
            journal_uuid = await self.generate_daily_reflection(date=date, trace_id=trace_id)

            return AgentMessage(
                trace_id=trace_id,
                source_agent=self.name,
                target_agent=msg.source_agent,
                intent="journal_generated",
                payload={
                    "journal_uuid": journal_uuid,
                    "date": date,
                    "success": journal_uuid is not None,
                },
            )

        logger.warning(
            f"[SWELL] Unknown intent: {msg.intent}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )
        return None

    async def generate_daily_reflection(
        self,
        date: str | None = None,
        trace_id: str | None = None,
    ) -> str | None:
        """
        Generate daily reflection journal entry.

        Workflow:
        1. Default to yesterday's date (for midnight runs)
        2. Check if journal already exists (idempotent)
        3. Gather analytics using get_daily_analytics()
        4. Check minimum activity threshold
        5. Call journal generation pipeline
        6. Create JournalEntry node and link to Day
        7. Return JournalEntry UUID

        Args:
            date: Date in YYYY-MM-DD format. Defaults to yesterday.
            trace_id: Trace ID for logging

        Returns:
            JournalEntry UUID if created, None if skipped or already exists
        """
        if not self.neo4j:
            logger.error(
                "[STORM] Cannot generate journal: Neo4jClient not configured",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return None

        trace_id = trace_id or str(uuid.uuid4())

        # Default to yesterday for midnight runs
        if date is None:
            yesterday = datetime.now(UTC) - timedelta(days=1)
            date = yesterday.strftime("%Y-%m-%d")

        logger.info(
            f"[CHART] Generating daily reflection for {date}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Check if journal already exists (idempotent)
        if await self._journal_exists(date, trace_id):
            logger.info(
                f"[WHISPER] Journal already exists for {date}, skipping",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return None

        # Gather analytics
        try:
            analytics = await get_daily_analytics(self.neo4j, date, trace_id)
        except Exception as e:
            logger.error(
                f"[STORM] Failed to gather analytics for {date}: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return None

        # Check minimum activity threshold
        if analytics.interaction_count < self.min_interactions:
            logger.info(
                f"[WHISPER] Skipping {date}: insufficient activity "
                f"({analytics.interaction_count} < {self.min_interactions})",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return None

        # Generate journal using the pipeline
        try:
            journal = await generate_journal(analytics)
        except Exception as e:
            logger.error(
                f"[STORM] Failed to generate journal for {date}: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return None

        # Create node and link to Day
        try:
            journal_uuid = await self._create_journal_node(date, journal, analytics, trace_id)
        except Exception as e:
            logger.error(
                f"[STORM] Failed to create journal node for {date}: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return None

        logger.info(
            f"[BEACON] Created journal {journal_uuid} for {date}",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "date": date,
                "mood": journal.mood,
            },
        )

        return journal_uuid

    async def get_recent_journals(
        self,
        days: int = 7,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve recent journal entries for context/continuity.

        Used to provide historical context when generating new journals
        or for user-facing journal browsing features.

        Args:
            days: Number of recent days to retrieve (default: 7)
            trace_id: Trace ID for logging

        Returns:
            List of journal entry dictionaries with uuid, date, summary, mood
        """
        if not self.neo4j:
            logger.warning(
                "[SWELL] Cannot retrieve journals: Neo4jClient not configured",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return []

        trace_id = trace_id or str(uuid.uuid4())

        logger.debug(
            f"[WHISPER] Retrieving {days} recent journals",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        query = """
        MATCH (j:JournalEntry)-[:OCCURRED_ON]->(d:Day)
        RETURN j.uuid as uuid,
               d.date as date,
               j.summary as summary,
               j.mood as mood,
               j.interaction_count as interaction_count,
               j.tasks_completed as tasks_completed,
               j.generated_at as generated_at
        ORDER BY d.date DESC
        LIMIT $days
        """

        try:
            records = await self.neo4j.execute_read(
                query,
                {"days": days},
                trace_id=trace_id,
            )

            logger.debug(
                f"[WHISPER] Retrieved {len(records)} recent journals",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

            return records

        except Exception as e:
            logger.error(
                f"[STORM] Failed to retrieve recent journals: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return []

    async def _journal_exists(self, date: str, trace_id: str | None = None) -> bool:
        """
        Check if journal already exists for the given date.

        Args:
            date: Date in YYYY-MM-DD format
            trace_id: Trace ID for logging

        Returns:
            True if journal exists, False otherwise
        """
        if not self.neo4j:
            return False

        query = """
        MATCH (j:JournalEntry)-[:OCCURRED_ON]->(d:Day {date: $date})
        RETURN j.uuid
        LIMIT 1
        """

        try:
            result = await self.neo4j.execute_read(
                query,
                {"date": date},
                trace_id=trace_id,
            )
            return len(result) > 0

        except Exception as e:
            logger.error(
                f"[STORM] Failed to check journal existence for {date}: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return False

    async def _create_journal_node(
        self,
        date: str,
        journal: JournalEntry,
        analytics: DailyAnalytics,
        trace_id: str | None = None,
    ) -> str:
        """
        Create JournalEntry node and link to Day.

        Uses MERGE for Day node to ensure idempotency.
        Creates new JournalEntry with UUID and links via [:OCCURRED_ON].

        Args:
            date: Date in YYYY-MM-DD format
            journal: JournalEntry model with content and metadata
            analytics: DailyAnalytics snapshot for reference
            trace_id: Trace ID for logging

        Returns:
            UUID of created JournalEntry node

        Raises:
            Exception: If node creation fails
        """
        if not self.neo4j:
            raise ValueError("Neo4jClient not configured")

        journal_uuid = str(uuid.uuid4())

        logger.debug(
            f"[WHISPER] Creating journal node {journal_uuid} for {date}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Convert highlights list to array for Neo4j
        highlights_array = journal.highlights if self.include_highlights else []

        query = """
        MERGE (d:Day {date: $date})
        CREATE (j:JournalEntry {
            uuid: $uuid,
            content: $content,
            summary: $summary,
            mood: $mood,
            forward_look: $forward_look,
            highlights: $highlights,
            interaction_count: $interaction_count,
            tasks_completed: $tasks_completed,
            new_entities_count: $new_entities_count,
            generated_at: timestamp()
        })
        CREATE (j)-[:OCCURRED_ON]->(d)
        RETURN j.uuid
        """

        params = {
            "date": date,
            "uuid": journal_uuid,
            "content": journal.content[: self.max_content_length],  # Respect max length
            "summary": journal.summary,
            "mood": journal.mood,
            "forward_look": journal.forward_look,
            "highlights": highlights_array,
            "interaction_count": analytics.interaction_count,
            "tasks_completed": analytics.tasks_completed,
            "new_entities_count": sum(analytics.new_entities.values()),
        }

        result = await self.neo4j.execute_write(
            query,
            params,
            trace_id=trace_id,
        )

        if not result:
            raise ValueError(f"Failed to create journal node for {date}")

        logger.debug(
            f"[WHISPER] Journal node created successfully: {journal_uuid}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return journal_uuid


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Scribe"]
