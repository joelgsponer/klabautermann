"""
LLM-based entity pre-extraction for Klabautermann Ingestor.

Uses Claude Haiku to extract entities and relationships from text BEFORE
passing to Graphiti. Validates extractions against the ontology schema.

This provides:
1. Early validation - catch schema violations before Graphiti
2. Transparency - see what entities were detected
3. Quality control - filter low-confidence extractions

Reference: specs/architecture/AGENTS.md Section 2.1
Issues: #11, #13
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from klabautermann.core.logger import logger
from klabautermann.core.validation import (
    VALID_ENTITY_TYPES,
    VALID_RELATIONSHIP_TYPES,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    OntologyValidator,
    ValidationResult,
)
from klabautermann.core.workflow_inspector import log_thinking


if TYPE_CHECKING:
    from anthropic import AsyncAnthropic


# ===========================================================================
# Pre-Extraction Configuration
# ===========================================================================


@dataclass
class PreExtractionConfig:
    """Configuration for LLM-based pre-extraction."""

    enabled: bool = True
    model: str = "claude-3-5-haiku-latest"  # Fast model for extraction
    min_confidence: float = 0.5  # Minimum confidence to include entity
    max_tokens: int = 2048
    temperature: float = 0.0  # Deterministic extraction
    validate_ontology: bool = True  # Validate against ontology before return
    strict_validation: bool = False  # Treat warnings as errors


# ===========================================================================
# Extraction Response Model
# ===========================================================================


class LLMExtractionResponse(BaseModel):
    """Schema for LLM extraction response."""

    entities: list[dict[str, Any]] = Field(default_factory=list, description="Extracted entities")
    relationships: list[dict[str, Any]] = Field(
        default_factory=list, description="Extracted relationships"
    )


# ===========================================================================
# Pre-Extraction Prompt
# ===========================================================================

EXTRACTION_SYSTEM_PROMPT = """You are an entity extraction specialist for a personal knowledge management system.
Your task is to extract entities and relationships from user text according to a strict ontology.

VALID ENTITY TYPES (use exact casing):
{entity_types}

VALID RELATIONSHIP TYPES (use exact casing):
{relationship_types}

EXTRACTION RULES:
1. Only extract entities that are explicitly mentioned
2. Assign confidence scores (0.0-1.0) based on how clearly the entity is identified
3. For relationships, both source and target entities must be extracted
4. Use WORKS_AT for employment (not "employed_by")
5. Use REPORTS_TO for management hierarchy
6. Use KNOWS for general interpersonal connections
7. Family relationships use specific types: SPOUSE_OF, PARENT_OF, CHILD_OF, SIBLING_OF, FRIEND_OF
8. Names should be title-cased ("John Smith" not "john smith")
9. Email addresses should be lowercase

PROPERTY GUIDELINES:
- Person: Extract email, title (job title), phone if mentioned
- Organization: Extract industry, domain (website) if mentioned
- Task: Extract status (todo/in_progress/done), priority (high/medium/low), due_date
- Project: Extract status (active/on_hold/completed), deadline
- Event: Extract start_time, location if mentioned

OUTPUT FORMAT:
Return a JSON object with "entities" and "relationships" arrays:
{{
  "entities": [
    {{"name": "John Smith", "entity_type": "Person", "properties": {{"email": "john@acme.com", "title": "PM"}}, "confidence": 0.95}}
  ],
  "relationships": [
    {{"source_name": "John Smith", "source_type": "Person", "relationship_type": "WORKS_AT", "target_name": "Acme Corp", "target_type": "Organization", "properties": {{}}, "confidence": 0.9}}
  ]
}}

IMPORTANT:
- Only return the JSON object, no markdown or explanation
- If no entities found, return {{"entities": [], "relationships": []}}
- Do not invent entities not mentioned in the text"""

EXTRACTION_USER_PROMPT = """Extract entities and relationships from this text:

{text}

Return ONLY a valid JSON object."""


def _build_system_prompt() -> str:
    """Build the system prompt with valid entity/relationship types."""
    entity_types = ", ".join(sorted(VALID_ENTITY_TYPES))
    relationship_types = ", ".join(sorted(VALID_RELATIONSHIP_TYPES)[:30]) + "..."

    return EXTRACTION_SYSTEM_PROMPT.format(
        entity_types=entity_types,
        relationship_types=relationship_types,
    )


# ===========================================================================
# Pre-Extraction Engine
# ===========================================================================


class PreExtractionEngine:
    """
    LLM-based entity pre-extraction engine.

    Uses Claude Haiku to extract entities and relationships from text,
    validates against the ontology, and returns structured results.
    """

    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        config: PreExtractionConfig | None = None,
    ) -> None:
        """
        Initialize the pre-extraction engine.

        Args:
            anthropic_client: Anthropic API client for LLM calls.
            config: Pre-extraction configuration.
        """
        self.client = anthropic_client
        self.config = config or PreExtractionConfig()
        self.validator = OntologyValidator(strict=self.config.strict_validation)

    async def extract(
        self,
        text: str,
        trace_id: str | None = None,
    ) -> tuple[ExtractionResult, ValidationResult | None]:
        """
        Extract entities and relationships from text using LLM.

        Args:
            text: The text to extract from.
            trace_id: Optional trace ID for logging.

        Returns:
            Tuple of (ExtractionResult, ValidationResult or None).
            ValidationResult is None if validation is disabled.
        """
        if not self.config.enabled:
            return ExtractionResult(source_text=text), None

        if not text or len(text.strip()) < 10:
            logger.debug(
                "[WHISPER] Text too short for pre-extraction",
                extra={"trace_id": trace_id, "text_length": len(text)},
            )
            return ExtractionResult(source_text=text), None

        # Log thinking phase
        if trace_id:
            log_thinking(
                trace_id=trace_id,
                agent_name="pre_extraction",
                data={
                    "step": "llm_extraction_start",
                    "text_length": len(text),
                    "model": self.config.model,
                },
            )

        try:
            # Call LLM for extraction
            extraction = await self._call_llm(text, trace_id)

            # Filter by confidence
            extraction = self._filter_by_confidence(extraction)

            # Validate against ontology
            validation_result = None
            if self.config.validate_ontology:
                validation_result = self.validator.validate_extraction(
                    extraction, trace_id=trace_id
                )

                # Log validation result
                if trace_id:
                    log_thinking(
                        trace_id=trace_id,
                        agent_name="pre_extraction",
                        data={
                            "step": "ontology_validation",
                            "is_valid": validation_result.is_valid,
                            "error_count": validation_result.error_count,
                            "warning_count": validation_result.warning_count,
                        },
                    )

            logger.info(
                f"[BEACON] Pre-extraction complete: {len(extraction.entities)} entities, "
                f"{len(extraction.relationships)} relationships",
                extra={
                    "trace_id": trace_id,
                    "entity_count": len(extraction.entities),
                    "relationship_count": len(extraction.relationships),
                    "validation_valid": validation_result.is_valid if validation_result else None,
                },
            )

            return extraction, validation_result

        except Exception as e:
            logger.error(
                f"[STORM] Pre-extraction failed: {e}",
                extra={"trace_id": trace_id},
                exc_info=True,
            )
            # Return empty result on failure - don't block ingestion
            return ExtractionResult(source_text=text), None

    async def _call_llm(
        self,
        text: str,
        trace_id: str | None = None,
    ) -> ExtractionResult:
        """Call the LLM to extract entities and relationships."""
        system_prompt = _build_system_prompt()
        user_prompt = EXTRACTION_USER_PROMPT.format(text=text)

        response = await self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # Extract text content from response
        content = response.content[0].text if response.content else "{}"

        # Parse JSON response
        try:
            data = json.loads(content)
        except json.JSONDecodeError as parse_error:
            logger.warning(
                f"[SWELL] Failed to parse LLM extraction response: {parse_error}",
                extra={"trace_id": trace_id, "response_preview": content[:200]},
            )
            return ExtractionResult(source_text=text)

        # Convert to structured result
        entities = []
        for entity_data in data.get("entities", []):
            try:
                entities.append(
                    ExtractedEntity(
                        name=entity_data.get("name", ""),
                        entity_type=entity_data.get("entity_type", ""),
                        properties=entity_data.get("properties", {}),
                        confidence=float(entity_data.get("confidence", 1.0)),
                    )
                )
            except Exception as ex:
                logger.debug(
                    f"[WHISPER] Skipping malformed entity: {ex}",
                    extra={"trace_id": trace_id},
                )

        relationships = []
        for r in data.get("relationships", []):
            try:
                relationships.append(
                    ExtractedRelationship(
                        source_name=r.get("source_name", ""),
                        source_type=r.get("source_type", ""),
                        relationship_type=r.get("relationship_type", ""),
                        target_name=r.get("target_name", ""),
                        target_type=r.get("target_type", ""),
                        properties=r.get("properties", {}),
                        confidence=float(r.get("confidence", 1.0)),
                    )
                )
            except Exception as ex:
                logger.debug(
                    f"[WHISPER] Skipping malformed relationship: {ex}",
                    extra={"trace_id": trace_id},
                )

        return ExtractionResult(
            entities=entities,
            relationships=relationships,
            source_text=text,
        )

    def _filter_by_confidence(
        self,
        extraction: ExtractionResult,
    ) -> ExtractionResult:
        """Filter out low-confidence extractions."""
        min_conf = self.config.min_confidence

        filtered_entities = [e for e in extraction.entities if e.confidence >= min_conf]
        filtered_relationships = [r for r in extraction.relationships if r.confidence >= min_conf]

        return ExtractionResult(
            entities=filtered_entities,
            relationships=filtered_relationships,
            source_text=extraction.source_text,
        )


# ===========================================================================
# Convenience Function
# ===========================================================================


async def pre_extract_entities(
    text: str,
    anthropic_client: AsyncAnthropic,
    config: PreExtractionConfig | None = None,
    trace_id: str | None = None,
) -> tuple[ExtractionResult, ValidationResult | None]:
    """
    Convenience function to extract entities from text.

    Args:
        text: Text to extract from.
        anthropic_client: Anthropic API client.
        config: Optional configuration.
        trace_id: Optional trace ID.

    Returns:
        Tuple of (ExtractionResult, ValidationResult or None).
    """
    engine = PreExtractionEngine(anthropic_client, config)
    return await engine.extract(text, trace_id)


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "PreExtractionConfig",
    "PreExtractionEngine",
    "pre_extract_entities",
]
