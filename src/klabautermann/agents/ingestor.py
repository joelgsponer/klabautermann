"""
Ingestor Agent for Klabautermann.

Cleans user input, performs LLM-based pre-extraction to validate entities
against the ontology, then either:
1. Uses LLM-powered extraction with merge decisions (default)
2. Falls back to Graphiti for final extraction

Pre-extraction (#11, #13):
- Uses Haiku for fast entity/relationship extraction BEFORE Graphiti
- Validates entities against ontology schema (NodeLabel, RelationType)
- Logs validation issues for audit trail
- Falls back gracefully if pre-extraction fails

LLM-powered extraction (agent-based):
- Queries Researcher agent to find existing entities
- Uses Haiku to decide merge vs create for each entity
- Executes decisions via direct Cypher (bypasses Graphiti extraction)

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
from klabautermann.agents.merge_decision import MergeDecisionConfig, MergeDecisionEngine
from klabautermann.agents.pre_extraction import (
    PreExtractionConfig,
    PreExtractionEngine,
)
from klabautermann.core.logger import logger
from klabautermann.core.workflow_inspector import log_thinking
from klabautermann.memory.entity_operations import (
    create_entity,
    create_mentioned_in_relationship,
    create_relationship,
    update_entity,
)


if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

    from klabautermann.agents.researcher_models import EntityReference
    from klabautermann.core.models import AgentMessage
    from klabautermann.core.validation import ExtractedEntity, ExtractedRelationship
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
class IngestorConfig:
    """
    Configuration for the Ingestor agent.

    Controls LLM-powered extraction vs Graphiti fallback.
    """

    use_llm_extraction: bool = True  # Feature flag for LLM-powered path
    fallback_to_graphiti: bool = True  # Use Graphiti if LLM path fails
    researcher_timeout: float = 10.0  # Timeout for Researcher queries (seconds)
    max_candidates: int = 5  # Max entities to consider for merge


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
        ingestor_config: IngestorConfig | None = None,
        merge_decision_config: MergeDecisionConfig | None = None,
        agent_registry: dict[str, Any] | None = None,
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
            ingestor_config: Configuration for LLM extraction path.
            merge_decision_config: Configuration for merge decisions.
            agent_registry: Registry for accessing other agents (Researcher).
        """
        super().__init__(name, config)
        self.graphiti = graphiti_client
        self.neo4j = neo4j_client
        self.anthropic = anthropic_client
        self.ingestor_config = ingestor_config or IngestorConfig()
        self._agent_registry = agent_registry or {}

        # Initialize pre-extraction engine if client provided
        self.pre_extraction: PreExtractionEngine | None = None
        if anthropic_client:
            self.pre_extraction = PreExtractionEngine(
                anthropic_client=anthropic_client,
                config=pre_extraction_config or PreExtractionConfig(),
            )

        # Initialize merge decision engine for LLM-powered extraction
        self.merge_engine: MergeDecisionEngine | None = None
        if anthropic_client and self.ingestor_config.use_llm_extraction:
            self.merge_engine = MergeDecisionEngine(
                anthropic_client=anthropic_client,
                config=merge_decision_config or MergeDecisionConfig(),
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

            # Decide extraction path: LLM-powered or Graphiti fallback
            use_llm_path = (
                self.ingestor_config.use_llm_extraction
                and self.merge_engine
                and self.neo4j
                and pre_extraction_result
                and pre_extraction_result.entities
            )

            if use_llm_path and pre_extraction_result is not None:
                # LLM-powered extraction path
                log_thinking(
                    trace_id=msg.trace_id,
                    agent_name=self.name,
                    data={
                        "step": "llm_extraction",
                        "decision": "using LLM-powered entity extraction with merge decisions",
                        "entity_count": len(pre_extraction_result.entities),
                        "relationship_count": len(pre_extraction_result.relationships),
                    },
                )

                try:
                    await self._process_with_llm(
                        entities=pre_extraction_result.entities,
                        relationships=pre_extraction_result.relationships,
                        message_uuid=message_uuid,
                        trace_id=msg.trace_id,
                    )
                    # LLM path succeeded, skip Graphiti
                    return None
                except Exception as llm_error:
                    if self.ingestor_config.fallback_to_graphiti:
                        logger.warning(
                            f"[SWELL] LLM extraction failed, falling back to Graphiti: {llm_error}",
                            extra={"trace_id": msg.trace_id, "agent_name": self.name},
                        )
                        # Fall through to Graphiti path
                    else:
                        raise

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

            # Log entity creation details for The Bridge visibility
            log_thinking(
                trace_id=trace_id,
                agent_name=self.name,
                data={
                    "event": "entities_created",
                    "episode_name": episode_name,
                    "message_uuid": message_uuid[:8],
                    "entity_count": len(entity_refs),
                    "entities": [
                        {
                            "name": ref.name,
                            "type": ref.entity_type,
                            "uuid": ref.uuid[:8],
                        }
                        for ref in entity_refs[:10]  # Limit to first 10 for readability
                    ],
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
    # LLM-Powered Extraction (Agent-Based)
    # ===========================================================================

    async def _process_with_llm(
        self,
        entities: list[ExtractedEntity],
        relationships: list[ExtractedRelationship],
        message_uuid: str | None,
        trace_id: str | None,
    ) -> None:
        """
        Process extracted entities using LLM-powered merge decisions.

        Uses Graphiti's add_triplet() API to ensure proper embeddings are generated
        for semantic search. Only entities participating in relationships are created
        (standalone entities are deferred until a relationship is found).

        For merge decisions:
        1. Query Researcher for existing candidates
        2. Ask LLM to decide merge or create
        3. For "merge" -> use entity_operations.update_entity()
        4. For "create" -> use graphiti.add_triplet() for embeddings

        Args:
            entities: Pre-extracted entities to process.
            relationships: Pre-extracted relationships to create.
            message_uuid: UUID of source Message for MENTIONED_IN linking.
            trace_id: Trace ID for logging.
        """
        if not self.merge_engine or not self.neo4j:
            raise RuntimeError("LLM extraction requires merge_engine and neo4j")

        # Build entity lookup by name
        entity_by_name: dict[str, ExtractedEntity] = {e.name: e for e in entities}

        # Track which entities participate in relationships
        entities_in_relationships: set[str] = set()
        for rel in relationships:
            entities_in_relationships.add(rel.source_name)
            entities_in_relationships.add(rel.target_name)

        # Log standalone entities (those not in any relationship)
        standalone_entities = [e for e in entities if e.name not in entities_in_relationships]
        if standalone_entities:
            logger.info(
                f"[CHART] Deferring {len(standalone_entities)} standalone entities "
                "(no relationships found)",
                extra={
                    "trace_id": trace_id,
                    "agent_name": self.name,
                    "standalone": [e.name for e in standalone_entities[:5]],
                },
            )

        created_uuids: dict[str, str] = {}  # name -> uuid mapping
        merge_decisions: dict[str, str] = {}  # name -> merged_uuid (for entities being merged)

        # Phase 1: Make merge decisions for all entities in relationships
        for entity_name in entities_in_relationships:
            entity = entity_by_name.get(entity_name)
            if not entity:
                logger.debug(
                    f"[WHISPER] Entity '{entity_name}' referenced in relationship but not extracted",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                continue

            try:
                # Query Researcher for existing candidates
                candidates = await self._query_researcher_for_entity(entity, trace_id)

                # LLM decides merge or create
                decision = await self.merge_engine.decide(entity, candidates, trace_id)

                if decision.action == "merge" and decision.target_uuid:
                    # Update existing entity with new properties
                    if decision.properties_to_update:
                        await update_entity(
                            self.neo4j,
                            entity.entity_type,
                            decision.target_uuid,
                            decision.properties_to_update,
                            trace_id,
                        )
                    merge_decisions[entity.name] = decision.target_uuid
                    created_uuids[entity.name] = decision.target_uuid
                    logger.info(
                        f"[CHART] Merged entity '{entity.name}' into {decision.target_uuid[:8]}...",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )
                # For "create" decisions, we'll create via add_triplet in Phase 2

            except Exception as entity_error:
                logger.warning(
                    f"[SWELL] Failed to process entity '{entity.name}': {entity_error}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )

        # Phase 2: Create relationships using Graphiti add_triplet (with embeddings)
        triplets_created = 0
        for rel in relationships:
            source_entity = entity_by_name.get(rel.source_name)
            target_entity = entity_by_name.get(rel.target_name)

            if not source_entity or not target_entity:
                logger.debug(
                    "[WHISPER] Skipping relationship: missing entity definition",
                    extra={
                        "trace_id": trace_id,
                        "agent_name": self.name,
                        "source_name": rel.source_name,
                        "target_name": rel.target_name,
                    },
                )
                continue

            # Check if both entities were merged to existing nodes
            source_merged = rel.source_name in merge_decisions
            target_merged = rel.target_name in merge_decisions

            try:
                if source_merged and target_merged:
                    # Both entities already exist - just create the relationship
                    source_uuid = merge_decisions[rel.source_name]
                    target_uuid = merge_decisions[rel.target_name]
                    await create_relationship(
                        self.neo4j,
                        rel.source_type,
                        source_uuid,
                        rel.relationship_type,
                        rel.target_type,
                        target_uuid,
                        rel.properties,
                        trace_id,
                    )
                    logger.debug(
                        f"[WHISPER] Created relationship between merged entities: "
                        f"{rel.source_name} -[{rel.relationship_type}]-> {rel.target_name}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )
                elif self.graphiti and self.graphiti.is_connected:
                    # At least one entity needs creation - use add_triplet for embeddings
                    group_id = message_uuid or "default"
                    result = await self.graphiti.add_triplet_from_extraction(
                        source_entity=source_entity,
                        target_entity=target_entity,
                        relationship=rel,
                        group_id=group_id,
                        trace_id=trace_id,
                    )
                    # Update UUID mappings from triplet result
                    if rel.source_name not in created_uuids:
                        created_uuids[rel.source_name] = result.source_uuid
                    if rel.target_name not in created_uuids:
                        created_uuids[rel.target_name] = result.target_uuid
                    triplets_created += 1
                else:
                    # Fallback to direct Cypher if Graphiti not available
                    logger.warning(
                        "[SWELL] Graphiti not available for embeddings, using direct Cypher",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )
                    # Create entities without embeddings
                    for entity in [source_entity, target_entity]:
                        if entity.name not in created_uuids:
                            entity_props = {"name": entity.name, **entity.properties}
                            entity_uuid = await create_entity(
                                self.neo4j,
                                entity.entity_type,
                                entity_props,
                                trace_id,
                            )
                            created_uuids[entity.name] = entity_uuid

                    # Create relationship
                    await create_relationship(
                        self.neo4j,
                        rel.source_type,
                        created_uuids[rel.source_name],
                        rel.relationship_type,
                        rel.target_type,
                        created_uuids[rel.target_name],
                        rel.properties,
                        trace_id,
                    )

            except Exception as rel_error:
                logger.warning(
                    f"[SWELL] Failed to create relationship: {rel_error}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )

        # Phase 3: Link entities to source message
        if message_uuid:
            for entity_name, entity_uuid in created_uuids.items():
                entity = entity_by_name.get(entity_name)
                if entity:
                    try:
                        await create_mentioned_in_relationship(
                            self.neo4j,
                            entity_uuid,
                            entity.entity_type,
                            message_uuid,
                            trace_id,
                        )
                    except Exception as link_error:
                        logger.debug(
                            f"[WHISPER] Failed to link entity to message: {link_error}",
                            extra={"trace_id": trace_id, "agent_name": self.name},
                        )

        logger.info(
            f"[BEACON] LLM extraction complete: {len(created_uuids)} entities, "
            f"{len(relationships)} relationships, {triplets_created} with embeddings",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "entity_count": len(created_uuids),
                "relationship_count": len(relationships),
                "triplets_with_embeddings": triplets_created,
                "standalone_deferred": len(standalone_entities),
            },
        )

        # Log entity creation details for The Bridge visibility
        log_thinking(
            trace_id=trace_id or "",
            agent_name=self.name,
            data={
                "event": "entities_created",
                "extraction_method": "llm_with_embeddings",
                "message_uuid": message_uuid[:8] if message_uuid else None,
                "entity_count": len(created_uuids),
                "relationship_count": len(relationships),
                "triplets_with_embeddings": triplets_created,
                "standalone_deferred": len(standalone_entities),
                "entities": [
                    {
                        "name": entity.name,
                        "type": entity.entity_type,
                        "uuid": created_uuids.get(entity.name, "")[:8],
                        "has_embedding": entity.name not in merge_decisions,
                    }
                    for entity in entities[:10]
                    if entity.name in entities_in_relationships
                ],
                "relationships": [
                    {
                        "source": rel.source_name,
                        "type": rel.relationship_type,
                        "target": rel.target_name,
                    }
                    for rel in relationships[:10]
                ],
            },
        )

    async def _query_researcher_for_entity(
        self,
        entity: ExtractedEntity,
        trace_id: str | None,
    ) -> list[EntityReference]:
        """
        Query Researcher agent for existing entities that might match.

        Args:
            entity: The extracted entity to find matches for.
            trace_id: Trace ID for logging.

        Returns:
            List of EntityReference candidates (may be empty).
        """
        from klabautermann.agents.researcher_models import EntityReference
        from klabautermann.core.models import AgentMessage

        # Get Researcher from registry
        researcher = self._agent_registry.get("researcher")
        if not researcher:
            logger.debug(
                "[WHISPER] No Researcher agent in registry, skipping candidate lookup",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return []

        # Create response queue for this request
        response_queue: asyncio.Queue[AgentMessage] = asyncio.Queue()

        # Build search message
        msg = AgentMessage(
            trace_id=trace_id or "",
            source_agent=self.name,
            target_agent="researcher",
            intent="entity_lookup",
            payload={
                "query": f"Find {entity.entity_type} named {entity.name}",
                "max_results": self.ingestor_config.max_candidates,
            },
            response_queue=response_queue,
        )

        # Send to Researcher
        try:
            await researcher.inbox.put(msg)

            # Wait for response with timeout
            response = await asyncio.wait_for(
                response_queue.get(),
                timeout=self.ingestor_config.researcher_timeout,
            )

            # Extract entity references from response
            report = response.payload.get("report", {})
            refs_data = report.get("key_entity_refs", [])

            # Convert to EntityReference objects
            import contextlib

            candidates = []
            for ref in refs_data:
                if isinstance(ref, EntityReference):
                    candidates.append(ref)
                elif isinstance(ref, dict):
                    with contextlib.suppress(Exception):
                        candidates.append(EntityReference(**ref))

            logger.debug(
                f"[WHISPER] Found {len(candidates)} candidates for '{entity.name}'",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return candidates

        except TimeoutError:
            logger.warning(
                f"[SWELL] Researcher timeout for '{entity.name}'",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return []
        except Exception as e:
            logger.warning(
                f"[SWELL] Researcher query failed for '{entity.name}': {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return []

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
                _extraction_result, validation = await self.pre_extraction_engine.extract(
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

__all__ = ["BatchEpisode", "BatchIngestionResult", "EpisodeResult", "Ingestor", "IngestorConfig"]
