"""
Archivist Agent for Klabautermann.

The Archivist is the Janitor that maintains the knowledge graph. It scans for
inactive threads, summarizes them, and prunes original messages. This agent
orchestrates the archival pipeline, ensuring long-term memory is preserved
efficiently while keeping the graph clean.

Responsibilities:
1. Scan for inactive threads (60+ minutes cooldown by default)
2. Summarize threads into Note nodes
3. Prune original messages after archival
4. Detect and flag entity duplicates (future enhancement)

Reference: specs/architecture/AGENTS.md Section 1.5 (The Archivist)
Task: T040 - Archivist Agent Skeleton
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.agents.summarization import summarize_thread
from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage, ThreadSummary
from klabautermann.memory.note_queries import create_note_with_links


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient
    from klabautermann.memory.thread_manager import ThreadManager


class Archivist(BaseAgent):
    """
    The Archivist - keeper of The Locker's long-term memory.

    Responsibilities:
    1. Scan for inactive threads (60+ minutes cooldown)
    2. Summarize threads into Note nodes
    3. Prune original messages after archival
    4. Detect and flag entity duplicates
    """

    def __init__(
        self,
        name: str = "archivist",
        config: dict[str, Any] | None = None,
        thread_manager: ThreadManager | None = None,
        neo4j_client: Neo4jClient | None = None,
    ) -> None:
        """
        Initialize the Archivist agent.

        Args:
            name: Agent name (default: "archivist")
            config: Agent configuration (loaded from config/agents/archivist.yaml)
            thread_manager: ThreadManager instance for thread operations
            neo4j_client: Neo4jClient instance for graph operations
        """
        super().__init__(name=name, config=config or {})
        self.thread_manager = thread_manager
        self.neo4j = neo4j_client

        # Extract configuration values with defaults
        self.cooldown_minutes = self.config.get("cooldown_minutes", 60)
        self.max_threads_per_scan = self.config.get("max_threads_per_scan", 10)

    async def scan_for_inactive_threads(
        self,
        trace_id: str | None = None,
    ) -> list[str]:
        """
        Scan for threads that are ready for archival.

        Finds threads that have been inactive for longer than the configured
        cooldown period and are in 'active' status.

        Args:
            trace_id: Trace ID for logging

        Returns:
            List of thread UUIDs ready for archival
        """
        if not self.thread_manager:
            logger.warning(
                "[SWELL] Cannot scan for inactive threads: ThreadManager not configured",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return []

        trace_id = trace_id or str(uuid.uuid4())

        logger.info(
            f"[CHART] Scanning for inactive threads (cooldown: {self.cooldown_minutes}m)",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        thread_uuids = await self.thread_manager.get_inactive_threads(
            cooldown_minutes=self.cooldown_minutes,
            limit=self.max_threads_per_scan,
            trace_id=trace_id,
        )

        logger.info(
            f"[BEACON] Found {len(thread_uuids)} inactive threads ready for archival",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "thread_count": len(thread_uuids),
            },
        )

        return thread_uuids

    async def archive_thread(
        self,
        thread_uuid: str,
        trace_id: str | None = None,
    ) -> str | None:
        """
        Archive a single thread.

        This method orchestrates the complete archival pipeline:
        1. Mark thread as archiving (atomic lock)
        2. Fetch all messages
        3. Summarize thread content
        4. Create Note node from summary
        5. Mark thread as archived with summary link
        6. Prune original messages

        If any step fails, the thread is reactivated to prevent data loss.

        Args:
            thread_uuid: UUID of thread to archive
            trace_id: Trace ID for logging

        Returns:
            Note UUID on success, None on failure
        """
        if not self.thread_manager:
            logger.warning(
                "[SWELL] Cannot archive thread: ThreadManager not configured",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return None

        trace_id = trace_id or str(uuid.uuid4())

        logger.info(
            f"[CHART] Archiving thread {thread_uuid[:8]}...",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Step 1: Mark as archiving (atomic lock)
        if not await self.thread_manager.mark_archiving(thread_uuid, trace_id):
            logger.info(
                f"[CHART] Thread {thread_uuid[:8]}... not available for archival",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return None

        try:
            # Step 2: Fetch all messages
            # Use high limit to get full thread history for summarization
            context = await self.thread_manager.get_context_window(
                thread_uuid=thread_uuid,
                limit=1000,  # High limit for complete thread history
                trace_id=trace_id,
            )

            if not context.messages:
                logger.warning(
                    f"[SWELL] Thread {thread_uuid[:8]}... has no messages",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                await self.thread_manager.reactivate_thread(thread_uuid, trace_id)
                return None

            # Step 3: Summarize thread
            logger.debug(
                f"[WHISPER] Summarizing thread with {len(context.messages)} messages",
                extra={
                    "trace_id": trace_id,
                    "agent_name": self.name,
                    "message_count": len(context.messages),
                },
            )
            summary = await summarize_thread(
                messages=context.messages,
                context={"thread_uuid": thread_uuid},
                trace_id=trace_id,
            )

            # Step 4: Create Note node (stub for now - T041 will implement)
            note_uuid = await self._create_summary_note(
                thread_uuid=thread_uuid,
                summary=summary,
                trace_id=trace_id,
            )

            # Step 5: Mark archived and link summary
            success = await self.thread_manager.mark_archived(
                thread_uuid=thread_uuid,
                summary_uuid=note_uuid,
                trace_id=trace_id,
            )

            if not success:
                logger.error(
                    f"[STORM] Failed to mark thread {thread_uuid[:8]}... as archived",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                await self.thread_manager.reactivate_thread(thread_uuid, trace_id)
                return None

            # Step 6: Prune messages (stub for now - T043 will implement)
            await self._prune_messages(thread_uuid=thread_uuid, trace_id=trace_id)

            logger.info(
                f"[BEACON] Archived thread {thread_uuid[:8]}... -> Note {note_uuid[:8]}...",
                extra={
                    "trace_id": trace_id,
                    "agent_name": self.name,
                    "thread_uuid": thread_uuid,
                    "note_uuid": note_uuid,
                },
            )

            return note_uuid

        except Exception as e:
            logger.error(
                f"[STORM] Archival failed for {thread_uuid[:8]}...: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            # Reactivate thread on failure
            await self.thread_manager.reactivate_thread(thread_uuid, trace_id)
            return None

    async def process_archival_queue(
        self,
        trace_id: str | None = None,
    ) -> int:
        """
        Process the archival queue by archiving all inactive threads.

        This method is the main entry point for batch archival operations.
        It scans for inactive threads and archives them sequentially.

        Args:
            trace_id: Trace ID for logging

        Returns:
            Number of successfully archived threads
        """
        trace_id = trace_id or str(uuid.uuid4())

        logger.info(
            "[CHART] Processing archival queue",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        # Get inactive threads
        thread_uuids = await self.scan_for_inactive_threads(trace_id)

        if not thread_uuids:
            logger.debug(
                "[WHISPER] No inactive threads to archive",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return 0

        # Archive each thread sequentially
        archived_count = 0
        for thread_uuid in thread_uuids:
            note_uuid = await self.archive_thread(thread_uuid, trace_id)
            if note_uuid:
                archived_count += 1

        logger.info(
            f"[BEACON] Archival queue complete: {archived_count}/{len(thread_uuids)} threads archived",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "archived_count": archived_count,
                "total_threads": len(thread_uuids),
            },
        )

        return archived_count

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process incoming agent messages.

        Handles ARCHIVE_THREAD intent from orchestrator or other agents.

        Args:
            msg: Incoming agent message

        Returns:
            Response message with archival result, or None if no response needed
        """
        trace_id = msg.trace_id

        logger.debug(
            f"[WHISPER] Processing message with intent: {msg.intent}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        if msg.intent == "ARCHIVE_THREAD":
            thread_uuid = msg.payload.get("thread_uuid")
            if not thread_uuid:
                logger.warning(
                    "[SWELL] ARCHIVE_THREAD message missing thread_uuid",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                return None

            note_uuid = await self.archive_thread(thread_uuid, trace_id)

            # Return result to source agent
            return AgentMessage(
                trace_id=trace_id,
                source_agent=self.name,
                target_agent=msg.source_agent,
                intent="ARCHIVE_RESULT",
                payload={
                    "thread_uuid": thread_uuid,
                    "note_uuid": note_uuid,
                    "success": note_uuid is not None,
                },
            )

        logger.warning(
            f"[SWELL] Unknown intent: {msg.intent}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )
        return None

    # ========================================================================
    # Stub Methods (to be implemented in future tasks)
    # ========================================================================

    async def _create_summary_note(
        self,
        thread_uuid: str,
        summary: ThreadSummary,
        trace_id: str,
    ) -> str:
        """
        Create a Note node from the thread summary.

        Creates the Note node in Neo4j, links it to the Thread via [:SUMMARY_OF],
        and links any mentioned entities via [:MENTIONED_IN].

        Args:
            thread_uuid: UUID of the thread being archived
            summary: ThreadSummary extracted from the thread
            trace_id: Trace ID for logging

        Returns:
            UUID of the created Note node
        """
        if not self.neo4j:
            # Fallback to stub behavior if no neo4j client
            note_uuid = str(uuid.uuid4())
            logger.warning(
                f"[SWELL] Cannot create Note: Neo4j client not configured, returning stub UUID {note_uuid[:8]}...",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return note_uuid

        result = await create_note_with_links(
            neo4j=self.neo4j,
            thread_uuid=thread_uuid,
            summary=summary,
            trace_id=trace_id,
        )

        logger.debug(
            f"[WHISPER] Created summary note {result['note_uuid'][:8]}... for thread {thread_uuid[:8]}...",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "note_uuid": result["note_uuid"],
                "thread_uuid": thread_uuid,
                "entity_link_count": result.get("entity_link_count", 0),
            },
        )

        return str(result["note_uuid"])

    async def _prune_messages(
        self,
        thread_uuid: str,
        trace_id: str,
    ) -> None:
        """
        Prune original messages from an archived thread.

        Deletes all Message nodes linked to the thread after verifying the thread
        has been safely archived with a summary Note.

        Args:
            thread_uuid: UUID of the thread to prune
            trace_id: Trace ID for logging
        """
        if not self.thread_manager:
            logger.warning(
                "[SWELL] Cannot prune messages: ThreadManager not configured",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return

        count = await self.thread_manager.prune_thread_messages(
            thread_uuid=thread_uuid,
            trace_id=trace_id,
        )

        logger.debug(
            f"[WHISPER] Pruned {count} messages from thread {thread_uuid[:8]}...",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "thread_uuid": thread_uuid,
                "message_count": count,
            },
        )


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Archivist"]
