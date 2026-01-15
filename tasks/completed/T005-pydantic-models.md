# Create Pydantic Core Models

## Metadata
- **ID**: T005
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) Section 6
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md) Section 2

## Dependencies
- [ ] T003 - Project directory structure

## Context
Pydantic models are the foundation of type safety in Klabautermann. Every data structure must be validated through Pydantic before use. These models define the contract between agents, the graph database, and external systems.

## Requirements
- [ ] Create `src/klabautermann/core/models.py` with:

### Graph Node Models
- [ ] `PersonNode` - Human contacts
- [ ] `OrganizationNode` - Companies, groups
- [ ] `ProjectNode` - Goal-oriented endeavors
- [ ] `GoalNode` - High-level objectives
- [ ] `TaskNode` - Atomic action items
- [ ] `EventNode` - Meetings, occurrences
- [ ] `LocationNode` - Physical places
- [ ] `NoteNode` - Knowledge artifacts
- [ ] `ResourceNode` - External links, files
- [ ] `ThreadNode` - Conversation containers
- [ ] `MessageNode` - Individual messages
- [ ] `DayNode` - Temporal spine

### Agent Communication Models
- [ ] `AgentMessage` - Inter-agent message format
- [ ] `ThreadContext` - Rolling context window
- [ ] `SearchResult` - Search response format
- [ ] `EntityExtraction` - LLM extraction output

### Relationship Models
- [ ] `WorksAtRelation` - Employment with temporal properties
- [ ] `BaseRelation` - Base for all temporal relationships

## Acceptance Criteria
- [ ] All models use strict type hints
- [ ] All models have proper validation (Field constraints)
- [ ] Models match ONTOLOGY.md specifications exactly
- [ ] `from klabautermann.core.models import PersonNode` works
- [ ] Validation rejects invalid data (test with malformed input)

## Implementation Notes

Follow the pattern from ONTOLOGY.md Section 6:

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum

class PersonNode(BaseModel):
    """Human contact node in the knowledge graph."""
    uuid: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    bio: Optional[str] = None
    linkedin_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    avatar_url: Optional[str] = None
    vector_embedding: Optional[List[float]] = None
    created_at: float
    updated_at: float

class AgentMessage(BaseModel):
    """Message format for inter-agent communication."""
    trace_id: str
    source_agent: str
    target_agent: str
    intent: str
    payload: Dict[str, Any]
    timestamp: float
    priority: str = "normal"

class EntityExtraction(BaseModel):
    """Validated output from LLM entity extraction."""
    name: str
    label: str = Field(pattern="^(Person|Organization|Location|Project|Event|Task)$")
    properties: Dict[str, Any] = {}
```

Key patterns:
- All timestamps are Unix epoch (float)
- UUIDs are strings (UUID v4 format)
- Optional fields have defaults
- Use Field() for validation constraints
