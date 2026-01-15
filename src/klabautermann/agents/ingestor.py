"""
Ingestor Agent for Klabautermann.

Extracts structured entities and relationships from unstructured conversation text
and updates the temporal knowledge graph via Graphiti. Runs asynchronously
(fire-and-forget) to avoid blocking user responses.

Uses Claude Haiku for cost-effective extraction.

Reference: specs/architecture/AGENTS.md Section 1.2
Task: T023 - Ingestor Agent
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.logger import logger
from klabautermann.core.models import (
    AgentMessage,
    EntityExtraction,
    EntityLabel,
    ExtractionResult,
    RelationshipExtraction,
)
from klabautermann.utils.retry import retry_on_llm_errors


if TYPE_CHECKING:
    from anthropic import Anthropic

    from klabautermann.memory.graphiti_client import GraphitiClient


class Ingestor(BaseAgent):
    """
    The Ingestor Agent: extracts entities and relationships from conversation.

    Responsibilities:
    - Extract entities (Person, Organization, Project, Goal, Task, Event, Location)
    - Extract relationships (WORKS_AT, PART_OF, ATTENDED, etc.)
    - Handle temporal awareness (current vs historical relationships)
    - Write to knowledge graph via Graphiti
    - Never block user responses (fire-and-forget)

    Uses Claude Haiku for cost-effective extraction.
    """

    # Extraction prompt with ontology constraints
    EXTRACTION_PROMPT = """You are the Klabautermann Ingestor. Extract entities and relationships from the conversation.

ENTITY TYPES (use exactly these):
- Person: name, email, phone, bio, title
- Organization: name, industry, website, domain
- Project: name, description, status, deadline, priority
- Goal: description, timeframe, status, category
- Task: action, status, priority, due_date
- Event: title, description, start_time, location_context
- Location: name, address, type

RELATIONSHIP TYPES (use exactly these):
- WORKS_AT: Person -> Organization (with properties: title, department)
- REPORTS_TO: Person -> Person
- AFFILIATED_WITH: Person -> Organization (with properties: role)
- CONTRIBUTES_TO: Project -> Goal (with properties: weight)
- PART_OF: Task -> Project OR Project -> Project
- SUBTASK_OF: Task -> Task
- BLOCKS: Task -> Task (with properties: reason)
- DEPENDS_ON: Task -> Task (with properties: reason)
- ASSIGNED_TO: Task -> Person
- HELD_AT: Event -> Location
- LOCATED_IN: Person -> Location (with properties: type)
- ATTENDED: Person -> Event (with properties: role)
- DISCUSSED: Event -> Project/Task/Goal
- MENTIONED_IN: Person/Organization -> Note/Event
- KNOWS: Person -> Person (with properties: context, strength)
- INTRODUCED_BY: Person -> Person
- FAMILY_OF: Person -> Person (with properties: role)
- SPOUSE_OF: Person -> Person (with properties: married_at)
- PARENT_OF: Person -> Person
- CHILD_OF: Person -> Person
- SIBLING_OF: Person -> Person
- FRIEND_OF: Person -> Person (with properties: since, how_met, strength)

TEMPORAL RULES:
- Default: relationships are current (do not set expired_at)
- "used to", "previously", "was", "former", "no longer" -> this is HISTORICAL context
- Historical context means the relationship ENDED - you should note this in properties

EXTRACTION RULES:
1. Extract ALL entities mentioned, even if they're already in the graph
2. For Person entities, always extract email if mentioned in format "name (email)" or "name <email>"
3. For employment relationships, capture job title in properties
4. Be precise with entity names - use full names when available
5. If dates/times mentioned, convert to Unix timestamps (seconds since epoch)
6. For Task entities, the "action" field should be imperative (verb + object)

OUTPUT FORMAT (JSON only, no markdown):
{
  "entities": [
    {"name": "Sarah Johnson", "label": "Person", "properties": {"email": "sarah@acme.com", "title": "PM"}, "confidence": 1.0},
    {"name": "Acme Corp", "label": "Organization", "properties": {"domain": "acme.com"}, "confidence": 1.0}
  ],
  "relationships": [
    {"source_name": "Sarah Johnson", "source_label": "Person", "relationship_type": "WORKS_AT", "target_name": "Acme Corp", "target_label": "Organization", "properties": {"title": "PM"}, "confidence": 1.0}
  ]
}

If no entities found, return: {"entities": [], "relationships": []}

IMPORTANT: Return ONLY valid JSON. No markdown code blocks, no explanations, just the JSON object.

Conversation to analyze:
"""

    def __init__(
        self,
        name: str = "ingestor",
        config: dict[str, Any] | None = None,
        graphiti_client: GraphitiClient | None = None,
        llm_client: Anthropic | None = None,
    ) -> None:
        """
        Initialize the Ingestor agent.

        Args:
            name: Agent name (default "ingestor").
            config: Agent configuration dict.
            graphiti_client: GraphitiClient instance for graph storage.
            llm_client: Anthropic client for LLM calls.
        """
        super().__init__(name, config)
        self.graphiti = graphiti_client
        self.llm = llm_client
        model_config = self.config.get("model", {})
        if isinstance(model_config, dict):
            self.model = model_config.get("primary", "claude-3-haiku-20240307")
        else:
            self.model = model_config or "claude-3-haiku-20240307"
        self.max_tokens = self.config.get("max_tokens", 2048)
        self.temperature = self.config.get("temperature", 0.3)

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process extraction request.

        This is a fire-and-forget agent - it never returns a response.
        Extraction failures are logged but don't crash the agent.

        Args:
            msg: AgentMessage with payload containing:
                - text: Text to extract from
                - thread_id: Thread UUID for context
                - captain_uuid: User UUID (optional)

        Returns:
            None (fire-and-forget pattern)
        """
        text = msg.payload.get("text", "")
        thread_id = msg.payload.get("thread_id")
        captain_uuid = msg.payload.get("captain_uuid")

        if not text:
            logger.warning(
                "[SWELL] Ingestor received empty text",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
            )
            return None

        try:
            # Extract entities and relationships
            extraction = await self._extract(text, msg.trace_id)

            if extraction.entities or extraction.relationships:
                # Write to graph via Graphiti
                await self._write_to_graph(
                    extraction=extraction,
                    thread_id=thread_id,
                    captain_uuid=captain_uuid,
                    trace_id=msg.trace_id,
                )

                logger.info(
                    f"[BEACON] Extracted {len(extraction.entities)} entities, "
                    f"{len(extraction.relationships)} relationships",
                    extra={"trace_id": msg.trace_id, "agent_name": self.name},
                )
            else:
                logger.debug(
                    "[WHISPER] No entities extracted from text",
                    extra={"trace_id": msg.trace_id, "agent_name": self.name},
                )

        except Exception as e:
            # Log but don't crash - extraction is best-effort
            logger.error(
                f"[STORM] Extraction failed: {e}",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
                exc_info=True,
            )

        # Ingestor doesn't return responses (fire-and-forget)
        return None

    @retry_on_llm_errors(max_retries=2)
    async def _extract(self, text: str, trace_id: str) -> ExtractionResult:
        """
        Extract entities and relationships using LLM.

        Args:
            text: Text to extract from.
            trace_id: Trace ID for logging.

        Returns:
            ExtractionResult with entities and relationships.

        Raises:
            Exception: If LLM call fails after retries.
        """
        if not self.llm:
            logger.warning(
                "[SWELL] No LLM client configured - skipping extraction",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return ExtractionResult(trace_id=trace_id, entities=[], relationships=[])

        prompt = self.EXTRACTION_PROMPT + text

        logger.debug(
            f"[WHISPER] Calling LLM for extraction (model: {self.model})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        response = await self.llm.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse JSON from response
        content = response.content[0].text.strip()

        # Handle potential markdown code blocks
        if content.startswith("```"):
            # Extract JSON from code block
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1]
                # Remove language identifier (e.g., "json")
                if content.startswith("json") or content.startswith("JSON"):
                    content = content[4:]
            content = content.strip()

        try:
            data = json.loads(content)

            # Parse entities
            entities: list[EntityExtraction] = []
            for entity_data in data.get("entities", []):
                try:
                    # Validate label against EntityLabel enum
                    label = EntityLabel(entity_data.get("label"))
                    entities.append(
                        EntityExtraction(
                            name=entity_data.get("name", ""),
                            label=label,
                            properties=entity_data.get("properties", {}),
                            confidence=entity_data.get("confidence", 1.0),
                        )
                    )
                except (ValueError, KeyError) as e:
                    logger.warning(
                        f"[SWELL] Invalid entity in extraction: {e}",
                        extra={
                            "trace_id": trace_id,
                            "agent_name": self.name,
                            "entity": entity_data,
                        },
                    )

            # Parse relationships
            relationships: list[RelationshipExtraction] = []
            for rel_data in data.get("relationships", []):
                try:
                    # Validate source and target labels
                    source_label = EntityLabel(rel_data.get("source_label"))
                    target_label = EntityLabel(rel_data.get("target_label"))

                    relationships.append(
                        RelationshipExtraction(
                            source_name=rel_data.get("source_name", ""),
                            source_label=source_label,
                            relationship_type=rel_data.get("relationship_type", ""),
                            target_name=rel_data.get("target_name", ""),
                            target_label=target_label,
                            properties=rel_data.get("properties", {}),
                            confidence=rel_data.get("confidence", 1.0),
                        )
                    )
                except (ValueError, KeyError) as e:
                    logger.warning(
                        f"[SWELL] Invalid relationship in extraction: {e}",
                        extra={
                            "trace_id": trace_id,
                            "agent_name": self.name,
                            "relationship": rel_data,
                        },
                    )

            return ExtractionResult(
                trace_id=trace_id,
                entities=entities,
                relationships=relationships,
                raw_text=text,
            )

        except json.JSONDecodeError as e:
            logger.warning(
                f"[SWELL] Failed to parse extraction JSON: {e}",
                extra={
                    "trace_id": trace_id,
                    "agent_name": self.name,
                    "content_preview": content[:200],
                },
            )
            return ExtractionResult(trace_id=trace_id, entities=[], relationships=[], raw_text=text)

    async def _write_to_graph(
        self,
        extraction: ExtractionResult,
        thread_id: str | None,  # noqa: ARG002
        captain_uuid: str | None,  # noqa: ARG002
        trace_id: str,
    ) -> None:
        """
        Write extracted data to graph via Graphiti.

        Args:
            extraction: ExtractionResult with entities and relationships.
            thread_id: Thread UUID for context.
            captain_uuid: User UUID for context.
            trace_id: Trace ID for logging.

        Raises:
            Exception: If Graphiti write fails.
        """
        if not self.graphiti:
            logger.warning(
                "[SWELL] No Graphiti client configured - skipping graph write",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return

        if not self.graphiti.is_connected:
            logger.warning(
                "[SWELL] Graphiti not connected - skipping graph write",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return

        # Format extraction as episode content for Graphiti
        # Graphiti will handle entity creation and relationship management
        facts: list[str] = []

        # Add entity facts
        for entity in extraction.entities:
            props_str = ", ".join(f"{k}={v}" for k, v in entity.properties.items() if v)
            if props_str:
                facts.append(f"{entity.label.value}: {entity.name} ({props_str})")
            else:
                facts.append(f"{entity.label.value}: {entity.name}")

        # Add relationship facts
        for rel in extraction.relationships:
            props_str = ""
            if rel.properties:
                props_str = (
                    " (" + ", ".join(f"{k}={v}" for k, v in rel.properties.items() if v) + ")"
                )
            facts.append(f"{rel.source_name} {rel.relationship_type} {rel.target_name}{props_str}")

        episode_content = "Extracted from conversation:\n" + "\n".join(
            f"- {fact}" for fact in facts
        )

        logger.debug(
            f"[WHISPER] Writing to Graphiti: {len(facts)} facts",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        await self.graphiti.add_episode(
            content=episode_content,
            source="conversation",
            reference_time=None,  # Use current time
            group_id=captain_uuid or "default",
            trace_id=trace_id,
        )


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Ingestor"]
