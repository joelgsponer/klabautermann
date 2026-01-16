# Context Retrieval Cypher Queries

## Metadata
- **ID**: T052
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.2
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md) Sections 3, 9

## Dependencies
- [x] T051 - Orchestrator v2 Pydantic Models

## Context
Implement the Cypher queries that retrieve context from all memory layers. These queries feed the EnrichedContext that the orchestrator uses for task planning.

## Requirements
- [x] Implement `_get_recent_summaries(hours: int)` - Query Note nodes from archived threads
- [x] Implement `_get_relevant_islands()` - Query Community nodes with pending task counts
- [x] Implement `_get_pending_tasks()` - Query Task nodes with status=pending
- [x] Implement `_get_recent_entities(hours: int)` - Query recently created entities from Graphiti
- [x] All queries use parameterized Cypher (no f-strings)
- [x] All queries return typed Pydantic models

## Acceptance Criteria
- [x] `_get_recent_summaries()` returns `list[ThreadSummary]` from Note nodes
- [x] `_get_relevant_islands()` returns `list[CommunityContext]` from Community nodes
- [x] `_get_pending_tasks()` returns `list[TaskNode]` with pending status
- [x] `_get_recent_entities()` returns `list[EntityReference]` from Graphiti
- [x] All queries handle empty results gracefully (return empty lists)
- [x] Queries are logged with trace_id

## Implementation Notes
Add to `src/klabautermann/agents/orchestrator.py` or create new `src/klabautermann/memory/context_queries.py`.

Key Cypher patterns from spec:
```cypher
-- Recent summaries
MATCH (n:Note)-[:SUMMARY_OF]->(t:Thread)
WHERE n.created_at >= $cutoff
RETURN n.uuid, n.title, n.content_summarized, n.topics, t.channel_type

-- Knowledge Islands
MATCH (c:Community)
WHERE EXISTS((c)<-[:PART_OF_ISLAND]-())
OPTIONAL MATCH (c)<-[:PART_OF_ISLAND]-(t:Task {status: 'todo'})
RETURN c.name, c.theme, c.summary, count(t) as pending_tasks
```

## Development Notes

### Implementation

**Files Created:**
- `src/klabautermann/memory/context_queries.py` - All four context retrieval functions
- `tests/unit/test_context_queries.py` - Comprehensive unit tests with 16 test cases

**Functions Implemented:**
1. `get_recent_summaries(hours, limit)` - Retrieves Note nodes from archived threads with cross-thread awareness
2. `get_relevant_islands(limit)` - Queries Community nodes for Knowledge Island summaries with pending task counts
3. `get_pending_tasks(limit)` - Retrieves pending/todo/in_progress Task nodes ordered by priority and due date
4. `get_recent_entities(hours, limit)` - Queries recently created entities (Person, Organization, Project, Task, Event)

### Decisions Made

1. **Separate module**: Created `context_queries.py` rather than adding to orchestrator.py for better separation of concerns
2. **Function naming**: Removed underscore prefix from spec - these are public functions that will be imported by orchestrator
3. **TaskStatus enum handling**: Added proper type conversion from string to TaskStatus enum with ValueError fallback to maintain type safety
4. **Default values**: Used sensible defaults for missing optional fields (empty lists, empty strings, 0 for counts)
5. **DateTime handling**: Used `datetime.UTC` alias (Python 3.12+) instead of deprecated `timezone.utc`

### Patterns Established

1. **All queries are parametrized** - No f-strings with user input, only enum values in query strings
2. **Consistent error handling** - All functions return empty lists for no results, never None
3. **Nautical logging** - All queries log with [WHISPER] prefix and trace_id
4. **Pydantic validation** - All return values are typed Pydantic models (ThreadSummary, CommunityContext, TaskNode, EntityReference)
5. **Timestamp handling** - Consistent UTC datetime to Unix timestamp conversion using timedelta

### Testing

**Test Coverage:**
- 16 unit tests covering all four functions
- Tests for normal operation, empty results, missing fields
- Tests for timestamp cutoff calculation
- Tests verifying parametrized queries (injection safety)
- Tests verifying trace_id logging

**Quality Checks:**
- All tests passing (16/16)
- Ruff linter: All checks passed
- mypy type checker: Success, no issues

### Issues Encountered

1. **Virtual environment**: Initial test runs failed because package wasn't installed in venv - resolved by activating `.venv`
2. **Type safety**: mypy flagged `status` as `Any | str` when TaskStatus enum expected - fixed by adding explicit enum conversion
3. **Linting**: Initial ruff errors for unused import (Any), unsorted `__all__`, and deprecated `timezone.utc` - all fixed

### Next Steps

This module is ready for integration into Orchestrator v2. The next task should be:
- **T053**: Implement `build_enriched_context()` in Orchestrator that calls these queries
- Or similar task that integrates context retrieval into the Think phase
