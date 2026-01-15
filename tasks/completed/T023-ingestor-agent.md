# Implement Ingestor Agent

## Metadata
- **ID**: T023
- **Priority**: P0
- **Category**: subagent
- **Effort**: L
- **Status**: completed
- **Assignee**: carpenter

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

## Development Notes

### Implementation

**Files Created:**
- `/home/klabautermann/klabautermann3/src/klabautermann/agents/ingestor.py` - Full Ingestor agent implementation
- `/home/klabautermann/klabautermann3/tests/unit/test_ingestor.py` - Comprehensive unit tests (15 tests, all passing)

**Key Components:**
1. **Ingestor class** - Inherits from BaseAgent, implements fire-and-forget pattern
2. **EXTRACTION_PROMPT** - Comprehensive prompt with full ontology constraints (20+ relationship types)
3. **_extract()** - LLM-based entity/relationship extraction with retry decorator
4. **_write_to_graph()** - Graphiti integration for episode ingestion
5. **process_message()** - Main entry point, never returns response (fire-and-forget)

### Decisions Made

1. **Used existing Pydantic models** - Leveraged `EntityExtraction`, `RelationshipExtraction`, and `ExtractionResult` from `core.models` instead of creating new ones. This maintains consistency with the codebase.

2. **Comprehensive EXTRACTION_PROMPT** - Included all relationship types from ONTOLOGY.md (WORKS_AT, REPORTS_TO, FAMILY_OF, FRIEND_OF, PRACTICES, etc.) to enable rich entity extraction from day one.

3. **retry_on_llm_errors decorator** - Applied to `_extract()` method for resilience against transient LLM failures (rate limits, timeouts).

4. **Graceful error handling** - All extraction failures are logged but never crash the agent. Empty text returns None immediately without calling LLM.

5. **Markdown code block parsing** - LLM sometimes returns JSON wrapped in ```json blocks. Parser handles both raw JSON and markdown-wrapped JSON.

6. **Entity label validation** - Invalid entity labels are skipped with warning rather than crashing. Maintains robustness against LLM hallucinations.

7. **Episode formatting** - Extraction results are formatted as human-readable bullet lists for Graphiti episodes, making them easy to query and understand.

8. **Fire-and-forget confirmation** - `process_message()` always returns None, confirming this agent never blocks the orchestrator's response to the user.

### Patterns Established

1. **LLM retry pattern** - Use `@retry_on_llm_errors()` decorator for all LLM calls in agents
2. **JSON parsing pattern** - Always handle markdown code blocks and invalid JSON gracefully
3. **Entity validation pattern** - Use Pydantic enum validation (EntityLabel) with try/except to skip invalid entries
4. **Fire-and-forget pattern** - Background agents return None and never block caller
5. **Episode content format** - Structure as "Extracted from conversation:\n- fact1\n- fact2" for readability

### Testing

**15 unit tests, all passing:**
- Entity extraction (Person, Organization, Task, Event, Location)
- Relationship extraction (WORKS_AT, HELD_AT, REPORTS_TO)
- Temporal awareness (historical relationship detection)
- Error handling (empty text, invalid JSON, invalid labels, LLM failures)
- Graphiti integration (episode formatting, disconnected client)
- Fire-and-forget pattern validation
- Complex multi-entity conversation extraction

**Test coverage includes:**
- All entity types from ontology
- Multiple relationship types
- JSON parsing edge cases
- Graceful degradation scenarios
- Integration test with realistic conversation

### Issues Encountered

**None.** Implementation went smoothly. All tests pass on first run.

### Next Steps

1. **T024 - Researcher Agent** - Search counterpart to Ingestor
2. **T029 - Executor Agent** - Action execution with MCP tools
3. **Integration testing** - Wire Ingestor into Orchestrator for full flow testing
