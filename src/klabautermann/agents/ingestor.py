"""
Ingestor Agent for Klabautermann.

Cleans user input, performs LLM-based pre-extraction to validate entities
against the ontology, then passes to Graphiti for final extraction.

Pre-extraction (#11, #13):
- Uses Haiku for fast entity/relationship extraction BEFORE Graphiti
- Validates entities against ontology schema (NodeLabel, RelationType)
- Logs validation issues for audit trail
- Falls back gracefully if pre-extraction fails

Runs asynchronously (fire-and-forget) to avoid blocking user responses.

After ingestion, links extracted entities to the source Message node via
MENTIONED_IN relationships (Bug #350 fix).

Reference: specs/architecture/AGENTS.md Section 1.2
Task: T023 - Ingestor Agent
Issues: #11 LLM-based pre-extraction, #13 Ontology validation
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.agents.pre_extraction import (
    PreExtractionConfig,
    PreExtractionEngine,
)
from klabautermann.core.logger import logger
from klabautermann.core.workflow_inspector import log_thinking


if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

    from klabautermann.core.models import AgentMessage
    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.neo4j_client import Neo4jClient


# ===========================================================================
# Batch Ingestion Data Classes (Issue #17)
# ===========================================================================


@dataclass
class BatchEpisode:
    """
    Represents a single episode for batch ingestion.

    Issue: #17
    """

    content: str
    message_uuid: str | None = None
    captain_uuid: str | None = None
    source: str = "conversation"


@dataclass
class EpisodeResult:
    """
    Result of ingesting a single episode in a batch.

    Issue: #17
    """

    index: int
    success: bool
    episode_name: str | None = None
    error: str | None = None
    entities_linked: int = 0


@dataclass
class BatchIngestionResult:
    """
    Summary result of batch episode ingestion.

    Issue: #17
    """

    total: int
    successful: int
    failed: int
    results: list[EpisodeResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total == 0:
            return 100.0
        return (self.successful / self.total) * 100.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total": self.total,
            "successful": self.successful,
            "failed": self.failed,
            "success_rate": round(self.success_rate, 2),
            "results": [
                {
                    "index": r.index,
                    "success": r.success,
                    "episode_name": r.episode_name,
                    "error": r.error,
                    "entities_linked": r.entities_linked,
                }
                for r in self.results
            ],
        }


class Ingestor(BaseAgent):
    """
    The Ingestor Agent: cleans input, pre-extracts entities, and passes to Graphiti.

    Responsibilities:
    - Clean input text (remove role prefixes, roleplay markers, system mentions)
    - Pre-extract entities using Haiku for ontology validation (#11, #13)
    - Log original vs cleaned text for audit trail
    - Pass cleaned text to Graphiti for entity/relationship extraction
    - Never block user responses (fire-and-forget)

    Pre-extraction validates:
    - Entity types match NodeLabel enum
    - Relationship types match RelationType enum
    - Relationship source/target types are compatible
    - Property types and enum values are valid

    Graphiti handles:
    - Final entity extraction and resolution
    - Semantic relationship naming
    - Entity deduplication
    - Temporal handling (valid_at, invalid_at, expired_at)
    """

    # Patterns to clean from input before Graphiti ingestion
    ROLE_PREFIX_PATTERN = re.compile(
        r"^(User|Assistant|Researcher|Ingestor|Executor):\s*", re.MULTILINE
    )
    ITALICIZED_ACTIONS_PATTERN = re.compile(r"\*[^*]+\*")
    BOLD_AGENT_DISPATCH_PATTERN = re.compile(
        r"\*\*(?:Researcher|Ingestor|Executor)\*\*:.*$", re.MULTILINE
    )
    ROLEPLAY_MENTIONS: ClassVar[list[str]] = ["The Locker", "the locker", "my locker"]

    def __init__(
        self,
        name: str = "ingestor",
        config: dict[str, Any] | None = None,
        graphiti_client: GraphitiClient | None = None,
        neo4j_client: Neo4jClient | None = None,
        anthropic_client: AsyncAnthropic | None = None,
        pre_extraction_config: PreExtractionConfig | None = None,
    ) -> None:
        """
        Initialize the Ingestor agent.

        Args:
            name: Agent name (default "ingestor").
            config: Agent configuration dict.
            graphiti_client: GraphitiClient instance for graph storage.
            neo4j_client: Neo4jClient for entity linking (Bug #350).
            anthropic_client: Anthropic client for pre-extraction (#11).
            pre_extraction_config: Configuration for pre-extraction (#13).
        """
        super().__init__(name, config)
        self.graphiti = graphiti_client
        self.neo4j = neo4j_client
        self.anthropic = anthropic_client

        # Initialize pre-extraction engine if client provided
        self.pre_extraction: PreExtractionEngine | None = None
        if anthropic_client:
            self.pre_extraction = PreExtractionEngine(
                anthropic_client=anthropic_client,
                config=pre_extraction_config or PreExtractionConfig(),
            )

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process ingestion request by cleaning input and passing to Graphiti.

        This is a fire-and-forget agent - it never returns a response.
        Ingestion failures are logged but don't crash the agent.

        After ingestion, links extracted entities to the source message
        via MENTIONED_IN relationships (Bug #350 fix).

        Args:
            msg: AgentMessage with payload containing:
                - text: Text to ingest
                - captain_uuid: User UUID (optional, used for group_id)
                - message_uuid: UUID of source Message for entity linking (Bug #350)

        Returns:
            None (fire-and-forget pattern)
        """
        text = msg.payload.get("text", "")
        captain_uuid = msg.payload.get("captain_uuid")
        message_uuid = msg.payload.get("message_uuid")

        if not text:
            logger.warning(
                "[SWELL] Ingestor received empty text",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
            )
            return None

        # Clean input before sending to Graphiti
        cleaned = self.clean_input(text)

        # Log THINKING phase: text cleaning decision
        log_thinking(
            trace_id=msg.trace_id,
            agent_name=self.name,
            data={
                "step": "text_cleaning",
                "original_length": len(text),
                "cleaned_length": len(cleaned),
                "removed_chars": len(text) - len(cleaned),
                "text_preview": text[:100] + "..." if len(text) > 100 else text,
                "cleaned_preview": cleaned[:100] + "..." if len(cleaned) > 100 else cleaned,
            },
        )

        if not cleaned:
            logger.debug(
                "[WHISPER] Text cleaned to empty - skipping ingestion",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
            )
            return None

        # Log for audit trail
        logger.info(
            f"[BEACON] Ingesting: {len(text)} chars -> {len(cleaned)} chars cleaned",
            extra={
                "trace_id": msg.trace_id,
                "agent_name": self.name,
                "original_length": len(text),
                "cleaned_length": len(cleaned),
            },
        )

        try:
            # Pre-extract entities for validation (#11, #13)
            pre_extraction_result = None
            validation_result = None
            if self.pre_extraction:
                log_thinking(
                    trace_id=msg.trace_id,
                    agent_name=self.name,
                    data={
                        "step": "pre_extraction",
                        "decision": "running LLM pre-extraction for ontology validation",
                        "content_length": len(cleaned),
                    },
                )

                pre_extraction_result, validation_result = await self.pre_extraction.extract(
                    text=cleaned,
                    trace_id=msg.trace_id,
                )

                # Log pre-extraction results
                if pre_extraction_result:
                    log_thinking(
                        trace_id=msg.trace_id,
                        agent_name=self.name,
                        data={
                            "step": "pre_extraction_complete",
                            "entities_found": len(pre_extraction_result.entities),
                            "relationships_found": len(pre_extraction_result.relationships),
                            "validation_valid": validation_result.is_valid
                            if validation_result
                            else None,
                            "validation_errors": validation_result.error_count
                            if validation_result
                            else 0,
                            "validation_warnings": validation_result.warning_count
                            if validation_result
                            else 0,
                        },
                    )

                    # Log entity details at debug level
                    for entity in pre_extraction_result.entities:
                        logger.debug(
                            f"[WHISPER] Pre-extracted: {entity.entity_type} '{entity.name}' "
                            f"(confidence: {entity.confidence:.0%})",
                            extra={"trace_id": msg.trace_id, "agent_name": self.name},
                        )

            # Log THINKING phase: Graphiti ingestion decision
            log_thinking(
                trace_id=msg.trace_id,
                agent_name=self.name,
                data={
                    "step": "graphiti_ingestion",
                    "decision": "sending to Graphiti for entity extraction",
                    "content_length": len(cleaned),
                    "captain_uuid": captain_uuid,
                    "will_link_entities": bool(message_uuid and self.neo4j and self.graphiti),
                    "pre_extracted_entities": len(pre_extraction_result.entities)
                    if pre_extraction_result
                    else 0,
                },
            )

            # Pass cleaned text directly to Graphiti
            # Graphiti's internal LLM handles entity/relationship extraction
            episode_name = await self._ingest_to_graphiti(
                content=cleaned,
                captain_uuid=captain_uuid,
                trace_id=msg.trace_id,
            )

            # Link extracted entities to source message (Bug #350 fix)
            if episode_name and message_uuid and self.neo4j and self.graphiti:
                # Log THINKING phase: entity linking
                log_thinking(
                    trace_id=msg.trace_id,
                    agent_name=self.name,
                    data={
                        "step": "entity_linking",
                        "decision": "linking entities to source message",
                        "episode_name": episode_name,
                        "message_uuid": message_uuid[:8] if message_uuid else None,
                    },
                )
                await self._link_entities_to_message(
                    episode_name=episode_name,
                    message_uuid=message_uuid,
                    trace_id=msg.trace_id,
                )

        except Exception as e:
            # Log but don't crash - ingestion is best-effort
            logger.error(
                f"[STORM] Ingestion failed: {e}",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
                exc_info=True,
            )

        # Ingestor doesn't return responses (fire-and-forget)
        return None

    @classmethod
    def clean_input(cls, text: str) -> str:
        """
        Clean input text before sending to Graphiti.

        Removes:
        - Role prefixes (User:, Assistant:, Researcher:, etc.)
        - Italicized action markers (*does something*)
        - Bold agent dispatch markers (**Researcher**: ...)
        - Roleplay/system mentions (The Locker, etc.)

        This is a classmethod so it can be called from other components
        (like the Orchestrator) without instantiating an Ingestor.

        Args:
            text: Raw input text.

        Returns:
            Cleaned text suitable for Graphiti extraction.
        """
        # Remove role prefixes
        cleaned = cls.ROLE_PREFIX_PATTERN.sub("", text)

        # Remove italicized actions (*doing something*)
        cleaned = cls.ITALICIZED_ACTIONS_PATTERN.sub("", cleaned)

        # Remove bold agent dispatch lines (**Researcher**: Please search...)
        cleaned = cls.BOLD_AGENT_DISPATCH_PATTERN.sub("", cleaned)

        # Remove roleplay/system mentions
        for mention in cls.ROLEPLAY_MENTIONS:
            cleaned = cleaned.replace(mention, "")

        # Clean up whitespace
        # Remove multiple consecutive newlines
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        # Remove leading/trailing whitespace from each line
        cleaned = "\n".join(line.strip() for line in cleaned.split("\n"))
        # Remove empty lines at start/end
        cleaned = cleaned.strip()

        return cleaned

    async def _ingest_to_graphiti(
        self,
        content: str,
        captain_uuid: str | None,
        trace_id: str,
    ) -> str | None:
        """
        Send cleaned content to Graphiti for extraction.

        Graphiti handles:
        - Entity extraction using its internal LLM
        - Semantic relationship naming
        - Entity resolution and deduplication
        - Temporal metadata (valid_at, invalid_at)

        Args:
            content: Cleaned text to ingest.
            captain_uuid: User UUID for grouping related episodes.
            trace_id: Trace ID for logging.

        Returns:
            Episode name for entity linking, or None if ingestion skipped.

        Raises:
            Exception: If Graphiti ingestion fails.
        """
        if not self.graphiti:
            logger.warning(
                "[SWELL] No Graphiti client configured - skipping ingestion",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return None

        if not self.graphiti.is_connected:
            logger.warning(
                "[SWELL] Graphiti not connected - skipping ingestion",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return None

        logger.debug(
            f"[WHISPER] Sending to Graphiti: {len(content)} chars",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        episode_name = await self.graphiti.add_episode(
            content=content,
            source="conversation",
            reference_time=None,  # Use current time
            group_id=captain_uuid or "default",
            trace_id=trace_id,
        )

        return episode_name

    async def _link_entities_to_message(
        self,
        episode_name: str,
        message_uuid: str,
        trace_id: str,
    ) -> None:
        """
        Link entities extracted by Graphiti to the source message.

        After Graphiti ingestion, queries for entities created by that episode
        and creates MENTIONED_IN relationships to the Message node.

        Bug #350 fix: Enables queries like "What did I talk about with John?"
        to find the specific message where John was mentioned.

        Args:
            episode_name: Name of the Graphiti episode (from add_episode).
            message_uuid: UUID of the Message node to link entities to.
            trace_id: Trace ID for logging.
        """
        if not self.graphiti or not self.neo4j:
            return

        try:
            # Import here to avoid circular imports
            from klabautermann.agents.researcher_models import EntityReference
            from klabautermann.memory.message_linking import link_entities_to_message

            # Get entities extracted by this episode
            entities = await self.graphiti.get_entities_from_episode(
                episode_name=episode_name,
                trace_id=trace_id,
            )

            if not entities:
                logger.debug(
                    "[WHISPER] No entities found from episode to link",
                    extra={
                        "trace_id": trace_id,
                        "agent_name": self.name,
                        "episode_name": episode_name,
                    },
                )
                return

            # Convert to EntityReference objects
            entity_refs = [
                EntityReference(
                    uuid=e["uuid"],
                    name=e.get("name", "Unknown"),
                    entity_type=e.get("labels", ["Entity"])[0] if e.get("labels") else "Entity",
                    confidence=1.0,  # High confidence since Graphiti extracted them
                    source_technique="graphiti_ingestion",
                )
                for e in entities
            ]

            # Create MENTIONED_IN relationships
            link_count = await link_entities_to_message(
                neo4j=self.neo4j,
                message_uuid=message_uuid,
                entity_refs=entity_refs,
                trace_id=trace_id,
            )

            logger.info(
                f"[BEACON] Linked {link_count} ingested entities to message",
                extra={
                    "trace_id": trace_id,
                    "agent_name": self.name,
                    "episode_name": episode_name,
                    "message_uuid": message_uuid[:8],
                    "entity_count": len(entities),
                    "link_count": link_count,
                },
            )

        except Exception as e:
            # Non-blocking: log but don't fail
            logger.warning(
                f"[SWELL] Entity linking failed (non-blocking): {e}",
                extra={
                    "trace_id": trace_id,
                    "agent_name": self.name,
                    "episode_name": episode_name,
                },
            )

    # ===========================================================================
    # Batch Ingestion (Issue #17)
    # ===========================================================================

    async def batch_ingest(
        self,
        episodes: list[BatchEpisode],
        max_concurrent: int = 5,
        trace_id: str | None = None,
    ) -> BatchIngestionResult:
        """
        Ingest multiple episodes in parallel.

        Processes episodes concurrently using asyncio.gather with a semaphore
        to limit concurrent operations. Each episode is processed independently,
        so failures in one don't affect others.

        Args:
            episodes: List of BatchEpisode objects to ingest.
            max_concurrent: Maximum number of concurrent ingestion operations.
            trace_id: Optional trace ID for logging.

        Returns:
            BatchIngestionResult with summary and per-episode results.

        Issue: #17
        """
        if not episodes:
            return BatchIngestionResult(total=0, successful=0, failed=0)

        trace_id = trace_id or "batch"

        logger.info(
            f"[CHART] Starting batch ingestion of {len(episodes)} episodes",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "episode_count": len(episodes),
                "max_concurrent": max_concurrent,
            },
        )

        # Use semaphore to limit concurrent operations
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_episode(index: int, episode: BatchEpisode) -> EpisodeResult:
            """Process a single episode with semaphore control."""
            async with semaphore:
                return await self._ingest_single_episode(index, episode, trace_id)

        # Process all episodes concurrently
        tasks = [process_episode(i, ep) for i, ep in enumerate(episodes)]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # Aggregate results
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful

        batch_result = BatchIngestionResult(
            total=len(episodes),
            successful=successful,
            failed=failed,
            results=list(results),
        )

        logger.info(
            f"[BEACON] Batch ingestion complete: {successful}/{len(episodes)} successful",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "total": len(episodes),
                "successful": successful,
                "failed": failed,
                "success_rate": batch_result.success_rate,
            },
        )

        return batch_result

    async def _ingest_single_episode(
        self,
        index: int,
        episode: BatchEpisode,
        trace_id: str,
    ) -> EpisodeResult:
        """
        Ingest a single episode and return the result.

        Args:
            index: Index of episode in batch (for result tracking).
            episode: BatchEpisode to ingest.
            trace_id: Trace ID for logging.

        Returns:
            EpisodeResult with success/failure information.

        Issue: #17
        """
        episode_trace = f"{trace_id}-{index}"

        try:
            # Clean and ingest the episode
            cleaned = self.clean_input(episode.content)

            if not cleaned.strip():
                return EpisodeResult(
                    index=index,
                    success=False,
                    error="Empty content after cleaning",
                )

            # Perform pre-extraction if available
            if hasattr(self, "pre_extraction_engine") and self.pre_extraction_engine:
                extraction_result, validation = await self.pre_extraction_engine.extract(
                    cleaned, episode_trace
                )
                if validation and not validation.is_valid:
                    logger.debug(
                        f"[WHISPER] Batch episode {index} has validation issues",
                        extra={
                            "trace_id": episode_trace,
                            "agent_name": self.name,
                            "issues": len(validation.issues),
                        },
                    )

            # Ingest to Graphiti
            episode_name = await self._ingest_to_graphiti(
                content=cleaned,
                captain_uuid=episode.captain_uuid,
                trace_id=episode_trace,
            )

            if not episode_name:
                return EpisodeResult(
                    index=index,
                    success=False,
                    error="Graphiti ingestion returned no episode name",
                )

            # Link entities to message if message_uuid provided
            entities_linked = 0
            if episode.message_uuid:
                await self._link_entities_to_message(
                    episode_name=episode_name,
                    message_uuid=episode.message_uuid,
                    trace_id=episode_trace,
                )
                # Note: We don't track exact count here, just mark as attempted

            return EpisodeResult(
                index=index,
                success=True,
                episode_name=episode_name,
                entities_linked=entities_linked,
            )

        except Exception as e:
            logger.warning(
                f"[SWELL] Batch episode {index} failed: {e}",
                extra={
                    "trace_id": episode_trace,
                    "agent_name": self.name,
                    "error": str(e),
                },
            )
            return EpisodeResult(
                index=index,
                success=False,
                error=str(e),
            )


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["BatchEpisode", "BatchIngestionResult", "EpisodeResult", "Ingestor"]
