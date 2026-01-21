"""
Ingestor Agent for Klabautermann.

Cleans user input and passes it to Graphiti for entity/relationship extraction.
Graphiti handles the actual extraction using its internal LLM - this agent
only preprocesses input to remove role prefixes, roleplay, and system mentions.

Runs asynchronously (fire-and-forget) to avoid blocking user responses.

After ingestion, links extracted entities to the source Message node via
MENTIONED_IN relationships (Bug #350 fix).

Reference: specs/architecture/AGENTS.md Section 1.2
Task: T023 - Ingestor Agent
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.core.models import AgentMessage
    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.neo4j_client import Neo4jClient


class Ingestor(BaseAgent):
    """
    The Ingestor Agent: cleans input and passes to Graphiti for extraction.

    Responsibilities:
    - Clean input text (remove role prefixes, roleplay markers, system mentions)
    - Log original vs cleaned text for audit trail
    - Pass cleaned text to Graphiti for entity/relationship extraction
    - Never block user responses (fire-and-forget)

    Graphiti handles:
    - Entity extraction (Person, Organization, Project, etc.)
    - Relationship extraction with semantic naming
    - Entity resolution and deduplication
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
    ) -> None:
        """
        Initialize the Ingestor agent.

        Args:
            name: Agent name (default "ingestor").
            config: Agent configuration dict.
            graphiti_client: GraphitiClient instance for graph storage.
            neo4j_client: Neo4jClient for entity linking (Bug #350).
        """
        super().__init__(name, config)
        self.graphiti = graphiti_client
        self.neo4j = neo4j_client

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
            # Pass cleaned text directly to Graphiti
            # Graphiti's internal LLM handles entity/relationship extraction
            episode_name = await self._ingest_to_graphiti(
                content=cleaned,
                captain_uuid=captain_uuid,
                trace_id=msg.trace_id,
            )

            # Link extracted entities to source message (Bug #350 fix)
            if episode_name and message_uuid and self.neo4j and self.graphiti:
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
# Export
# ===========================================================================

__all__ = ["Ingestor"]
