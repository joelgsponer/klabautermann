# Supporting Pydantic Models

## Metadata
- **ID**: T066
- **Priority**: P0
- **Category**: core
- **Effort**: S
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.2
- Related: [models.py](../../src/klabautermann/core/models.py)

## Dependencies
- None (foundational, can parallel with T051)

## Context
Ensure all supporting Pydantic models referenced by EnrichedContext exist. Some may already exist, others need to be created or extended.

## Requirements
- [x] Verify/create `ThreadSummary` model for archived thread summaries
- [x] Verify/create `TaskNode` model for pending tasks
- [x] Verify/create `EntityReference` model for recent entities
- [x] Ensure all models have proper serialization
- [x] Add any missing fields needed by context queries

## Acceptance Criteria
- [x] `ThreadSummary` has: uuid, title, summary, topics, channel, participants
- [x] `TaskNode` has: uuid, action, status, priority, assignee
- [x] `EntityReference` has: uuid, type, name, created_at
- [x] All models importable from `klabautermann.core.models`
- [x] Models match Cypher query return shapes

## Implementation Notes
Check existing models in `src/klabautermann/core/models.py`:

```python
# ThreadSummary - for Note nodes from archived threads
class ThreadSummary(BaseModel):
    uuid: str
    title: str
    summary: str
    topics: list[str] = Field(default_factory=list)
    channel: str
    participants: list[str] = Field(default_factory=list)
    created_at: float | None = None

# TaskNode - for pending Task nodes
class TaskNode(BaseModel):
    uuid: str
    action: str
    status: str  # "todo", "in_progress", "done"
    priority: str | None = None  # "high", "medium", "low"
    assignee: str | None = None
    due_date: float | None = None

# EntityReference - for recently created entities
class EntityReference(BaseModel):
    uuid: str
    entity_type: str  # "Person", "Organization", "Project", etc.
    name: str
    created_at: float
    summary: str | None = None  # Brief description if available
```

If these already exist, verify they have all needed fields. If not, create them.

---

## Development Notes

### Completed: 2026-01-16

All three models have been verified and updated to support the v2 workflow requirements:

#### ThreadSummary (lines 565-593)
- **Modified**: Extended existing model to support dual purposes
  - V2 Context: Added `uuid`, `title`, `channel`, `created_at` fields (all optional)
  - Archivist: Kept existing `action_items`, `new_facts`, `conflicts`, `sentiment` fields
- **Rationale**: Single model serves both lightweight context queries (from Note nodes) and full Archivist summarization output
- **Verified**: Matches Cypher query shape from MAINAGENT.md Section 4.2 (lines 258-274)

#### TaskNode (lines 135-143)
- **Modified**: Added `assignee: str | None = None` field (line 141)
- **Already had**: `uuid`, `action`, `status`, `priority`, `due_date`, `completed_at`
- **Inherits from**: `BaseNode` which provides `uuid`, `created_at`, `updated_at`
- **Verified**: All acceptance criteria fields present

#### EntityReference (lines 605-620)
- **Status**: Already complete, no changes needed
- **Has**: `uuid`, `name`, `entity_type`, `created_at`
- **Used in**: EnrichedContext for lightweight entity references from Graphiti
- **Verified**: Matches spec requirements

### Test Results
- All 52 tests in `tests/unit/test_v2_models.py` pass
- All 57 related unit tests pass (ingestor, intent, delegation)
- Models correctly serialize/deserialize to/from JSON
- Models validate against Cypher query return shapes

### Export Status
All three models verified in `__all__` export list (lines 770-843).
