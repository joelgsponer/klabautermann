# Implement Ingestor Agent

## Metadata
- **ID**: T023
- **Priority**: P0
- **Category**: subagent
- **Effort**: L
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.2
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md)
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md)

## Dependencies
- [ ] T021 - Agent delegation pattern
- [x] T009 - Graphiti client
- [x] T016 - Base Agent class

## Context
The Ingestor is the "Data Scientist" that extracts structured entities from unstructured conversation and updates the knowledge graph. It uses Claude Haiku for cost-effective extraction and runs asynchronously (fire-and-forget) so it never blocks user responses.

## Requirements
- [ ] Create `src/klabautermann/agents/ingestor.py`:

### Entity Extraction
- [ ] Extract entity types from conversation:
  - Person (name, email, bio, title)
  - Organization (name, industry, website)
  - Project (name, status, deadline)
  - Goal (description, timeframe)
  - Task (action, status, priority)
  - Event (title, timestamp)
  - Location (name, address)
- [ ] Use structured Pydantic output parsing

### Relationship Extraction
- [ ] Extract relationships between entities:
  - WORKS_AT (Person -> Organization)
  - PART_OF (Task -> Project, Project -> Goal)
  - ATTENDED (Person -> Event)
  - DISCUSSED (Event -> Topic)
  - MENTIONED_IN (Entity -> Note)
- [ ] Map relationships to ontology types

### Temporal Awareness
- [ ] Default: relationships are current (`expired_at: null`)
- [ ] Detect past tense: "used to work at", "was previously"
- [ ] Flag historical relationships for expiration

### Graphiti Integration
- [ ] Call `graphiti_client.add_episode()` with extracted data
- [ ] Handle extraction failures gracefully (log, don't crash)

### System Prompt
- [ ] Implement extraction-focused system prompt
- [ ] Include ontology constraints
- [ ] Include output format specification

## Acceptance Criteria
- [ ] "I met Sarah from Acme" extracts Person + Organization + WORKS_AT
- [ ] "Sarah (sarah@acme.com) is a PM" captures email and title
- [ ] "I used to work at Google" flags for expiration
- [ ] Extracted entities appear in Neo4j within 5 seconds
- [ ] Extraction errors logged but don't crash agent

## Implementation Notes

```python
from typing import Optional, List
from pydantic import BaseModel, Field
import json

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.models import AgentMessage
from klabautermann.core.ontology import NodeLabel, RelationType
from klabautermann.core.logger import logger


class ExtractedEntity(BaseModel):
    """Extracted entity from conversation."""
    type: str  # NodeLabel value
    name: str
    properties: dict = Field(default_factory=dict)


class ExtractedRelationship(BaseModel):
    """Extracted relationship between entities."""
    source: str  # Entity name
    type: str  # RelationType value
    target: str  # Entity name
    properties: dict = Field(default_factory=dict)
    is_historical: bool = False  # If true, should expire existing


class ExtractionResult(BaseModel):
    """Complete extraction result."""
    entities: List[ExtractedEntity] = Field(default_factory=list)
    relationships: List[ExtractedRelationship] = Field(default_factory=list)
    facts: List[str] = Field(default_factory=list)


class Ingestor(BaseAgent):
    """
    The Ingestor: extracts entities and relationships from conversation.

    Uses Claude Haiku for cost-effective extraction.
    Runs asynchronously - never blocks user responses.
    """

    EXTRACTION_PROMPT = '''You are the Klabautermann Ingestor. Extract entities and relationships from the conversation.

ENTITY TYPES (use exactly these):
- Person: name, email, bio, title
- Organization: name, industry, website
- Project: name, status, deadline
- Goal: description, timeframe
- Task: action, status, priority
- Event: title, timestamp
- Location: name, address

RELATIONSHIP TYPES (use exactly these):
- WORKS_AT: Person -> Organization
- PART_OF: Task -> Project, Project -> Goal
- CONTRIBUTES_TO: Person -> Project
- ATTENDED: Person -> Event
- HELD_AT: Event -> Location
- BLOCKS: Task -> Task
- MENTIONED_IN: Entity -> Note

TEMPORAL RULES:
- Default: relationships are current
- "used to", "previously", "was", "former" -> mark is_historical: true

OUTPUT FORMAT (JSON only):
{
  "entities": [{"type": "Person", "name": "Sarah", "properties": {"email": "sarah@acme.com", "title": "PM"}}],
  "relationships": [{"source": "Sarah", "type": "WORKS_AT", "target": "Acme Corp", "properties": {}, "is_historical": false}],
  "facts": ["Sarah is a PM at Acme Corp"]
}

If no entities found, return: {"entities": [], "relationships": [], "facts": []}

Conversation to analyze:
'''

    def __init__(
        self,
        name: str = "ingestor",
        config: Optional[dict] = None,
        graphiti_client = None,
        llm_client = None,
    ):
        super().__init__(name, config)
        self.graphiti = graphiti_client
        self.llm = llm_client
        self.model = config.get("model", "claude-3-haiku-20240307") if config else "claude-3-haiku-20240307"

    async def process_message(self, msg: AgentMessage) -> Optional[AgentMessage]:
        """Process extraction request."""
        text = msg.payload.get("text", "")
        thread_id = msg.payload.get("thread_id")

        if not text:
            logger.warning(
                f"[SWELL] Ingestor received empty text",
                extra={"trace_id": msg.trace_id}
            )
            return None

        try:
            # Extract entities
            extraction = await self._extract(text, msg.trace_id)

            if extraction.entities or extraction.relationships:
                # Write to graph via Graphiti
                await self._write_to_graph(extraction, thread_id, msg.trace_id)

                logger.info(
                    f"[BEACON] Extracted {len(extraction.entities)} entities, "
                    f"{len(extraction.relationships)} relationships",
                    extra={"trace_id": msg.trace_id}
                )
            else:
                logger.debug(
                    f"[WHISPER] No entities extracted",
                    extra={"trace_id": msg.trace_id}
                )

        except Exception as e:
            # Log but don't crash - extraction is best-effort
            logger.error(
                f"[STORM] Extraction failed: {e}",
                extra={"trace_id": msg.trace_id},
                exc_info=True,
            )

        # Ingestor doesn't return responses (fire-and-forget)
        return None

    async def _extract(self, text: str, trace_id: str) -> ExtractionResult:
        """Extract entities and relationships using LLM."""
        prompt = self.EXTRACTION_PROMPT + text

        response = await self.llm.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse JSON from response
        content = response.content[0].text.strip()

        # Handle potential markdown code blocks
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        try:
            data = json.loads(content)
            return ExtractionResult(**data)
        except json.JSONDecodeError as e:
            logger.warning(
                f"[SWELL] Failed to parse extraction JSON: {e}",
                extra={"trace_id": trace_id, "content": content[:200]}
            )
            return ExtractionResult()

    async def _write_to_graph(
        self, extraction: ExtractionResult, thread_id: str, trace_id: str
    ) -> None:
        """Write extracted data to graph via Graphiti."""
        # Format as episode for Graphiti
        episode_content = f"Extracted from conversation: {', '.join(extraction.facts)}"

        await self.graphiti.add_episode(
            name=f"extraction-{trace_id[:8]}",
            episode_body=episode_content,
            source_description="conversation",
            reference_time=None,  # Use current time
        )
```

Note: The actual Graphiti integration may need adjustment based on the Graphiti client implementation from T009. The extraction format should match what Graphiti expects.
