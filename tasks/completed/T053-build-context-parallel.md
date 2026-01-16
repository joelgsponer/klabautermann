# Parallel Context Building

## Metadata
- **ID**: T053
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.2
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md)

## Dependencies
- [x] T051 - Orchestrator v2 Pydantic Models
- [x] T052 - Context Retrieval Cypher Queries

## Context
Implement the `_build_context()` method that gathers context from all memory layers in parallel using `asyncio.gather()`. This is the entry point for context injection into the orchestrator.

## Requirements
- [ ] Implement `async def _build_context(thread_uuid, trace_id) -> EnrichedContext`
- [ ] Use `asyncio.gather()` to run all context queries in parallel
- [ ] Include ThreadManager context window (existing)
- [ ] Include recent summaries from T052
- [ ] Include pending tasks from T052
- [ ] Include recent entities from T052
- [ ] Include relevant islands from T052
- [ ] Handle partial failures gracefully (one failing query shouldn't block others)

## Acceptance Criteria
- [ ] Returns `EnrichedContext` with all fields populated
- [ ] All context queries run in parallel (verify with timing)
- [ ] Partial failures logged but don't crash the method
- [ ] Works with existing ThreadManager integration
- [ ] trace_id propagated to all sub-queries

## Implementation Notes
```python
async def _build_context(self, thread_uuid: str, trace_id: str) -> EnrichedContext:
    messages, summaries, tasks, entities, islands = await asyncio.gather(
        self.thread_manager.get_context_window(thread_uuid, limit=20),
        self._get_recent_summaries(hours=12),
        self._get_pending_tasks(),
        self._get_recent_entities(hours=24),
        self._get_relevant_islands(),
        return_exceptions=True,  # Don't fail if one query fails
    )
    # Handle exceptions, build EnrichedContext
```
