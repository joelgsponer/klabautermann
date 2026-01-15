"""
Ingestor Agent for Klabautermann.

Cleans user input and passes it to Graphiti for entity/relationship extraction.
Graphiti handles the actual extraction using its internal LLM - this agent
only preprocesses input to remove role prefixes, roleplay, and system mentions.

Runs asynchronously (fire-and-forget) to avoid blocking user responses.

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
    ) -> None:
        """
        Initialize the Ingestor agent.

        Args:
            name: Agent name (default "ingestor").
            config: Agent configuration dict.
            graphiti_client: GraphitiClient instance for graph storage.
        """
        super().__init__(name, config)
        self.graphiti = graphiti_client

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process ingestion request by cleaning input and passing to Graphiti.

        This is a fire-and-forget agent - it never returns a response.
        Ingestion failures are logged but don't crash the agent.

        Args:
            msg: AgentMessage with payload containing:
                - text: Text to ingest
                - captain_uuid: User UUID (optional, used for group_id)

        Returns:
            None (fire-and-forget pattern)
        """
        text = msg.payload.get("text", "")
        captain_uuid = msg.payload.get("captain_uuid")

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
            await self._ingest_to_graphiti(
                content=cleaned,
                captain_uuid=captain_uuid,
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
    ) -> None:
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

        Raises:
            Exception: If Graphiti ingestion fails.
        """
        if not self.graphiti:
            logger.warning(
                "[SWELL] No Graphiti client configured - skipping ingestion",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return

        if not self.graphiti.is_connected:
            logger.warning(
                "[SWELL] Graphiti not connected - skipping ingestion",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return

        logger.debug(
            f"[WHISPER] Sending to Graphiti: {len(content)} chars",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        await self.graphiti.add_episode(
            content=content,
            source="conversation",
            reference_time=None,  # Use current time
            group_id=captain_uuid or "default",
            trace_id=trace_id,
        )


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Ingestor"]
