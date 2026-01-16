# Task Deduplication

## Metadata
- **ID**: T072
- **Priority**: P2
- **Category**: core
- **Effort**: S
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 12 (Open Question 4)

## Dependencies
- [x] T054 - Task Planning with Claude Opus

## Context
When the LLM generates multiple similar tasks (e.g., two research queries about the same entity), merge them to avoid redundant work and improve efficiency.

## Requirements
- [x] Implement `_deduplicate_tasks(tasks: list[PlannedTask]) -> list[PlannedTask]`
- [x] Detect similar research queries (same entity, overlapping topics)
- [x] Merge payloads when appropriate
- [x] Preserve unique tasks
- [x] Log when deduplication occurs

## Acceptance Criteria
- [x] Two "search for Sarah" tasks merged into one
- [x] Different search types (semantic vs structural) not merged
- [x] Ingest tasks never merged (each fact is unique)
- [x] Execute tasks merged only if same action type
- [x] Original task count vs deduplicated count logged

## Implementation Notes
```python
def _deduplicate_tasks(self, tasks: list[PlannedTask]) -> list[PlannedTask]:
    """Merge similar tasks to avoid redundant work."""
    if len(tasks) <= 1:
        return tasks

    deduplicated = []
    seen_queries = {}  # query_key -> task index

    for task in tasks:
        if task.task_type == "ingest":
            # Never dedupe ingestion - each fact matters
            deduplicated.append(task)
            continue

        # Generate a key for similarity check
        key = self._task_similarity_key(task)

        if key in seen_queries:
            # Merge with existing task
            existing_idx = seen_queries[key]
            deduplicated[existing_idx] = self._merge_tasks(
                deduplicated[existing_idx], task
            )
        else:
            seen_queries[key] = len(deduplicated)
            deduplicated.append(task)

    if len(deduplicated) < len(tasks):
        logger.info(f"[WHISPER] Deduplicated {len(tasks)} -> {len(deduplicated)} tasks")

    return deduplicated
```

## Development Notes

### Implementation Summary
Implemented task deduplication in the orchestrator's `_parse_task_plan()` method. The deduplication logic runs after parsing the LLM response and before returning the TaskPlan.

### Files Modified
- `/home/klabautermann/klabautermann3/src/klabautermann/agents/orchestrator.py`:
  - Modified `_parse_task_plan()` signature to use `trace_id` instead of `_trace_id`
  - Added call to `_deduplicate_tasks()` before returning task plan
  - Implemented `_deduplicate_tasks()` - main deduplication logic
  - Implemented `_task_similarity_key()` - generates similarity keys for tasks
  - Implemented `_merge_tasks()` - merges two similar tasks into one

- `/home/klabautermann/klabautermann3/tests/unit/test_orchestrator_v2_deduplication.py`:
  - Created comprehensive test suite with 19 tests covering all deduplication scenarios

### Key Design Decisions

1. **Similarity Key Strategy**:
   - Research tasks: Extract entity name by removing common prefixes ("search for", "find", etc.) and using the first word as the key
   - This allows "Sarah" and "Sarah Johnson" to match (both have key "sarah")
   - Execute tasks: Use action verb (first word of action)
   - Ingest tasks: Use object ID (ensures uniqueness - never dedupe)

2. **Merge Strategy**:
   - Keep longer/more detailed description
   - Merge payload fields (prefer non-None values from second task)
   - Preserve blocking=True if either task is blocking
   - Maintain task_type and agent from first task

3. **Logging**:
   - Debug level ([WHISPER]) for individual merges with similarity key
   - Info level ([WHISPER]) for final deduplication count if any tasks were merged

### Test Results
All 19 tests passing:
- 10 tests for deduplication behavior
- 5 tests for similarity key generation
- 4 tests for task merging

### Completed: 2026-01-16
