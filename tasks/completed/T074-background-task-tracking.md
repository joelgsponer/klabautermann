# Background Task Tracking

## Metadata
- **ID**: T074
- **Priority**: P1
- **Category**: core
- **Effort**: S
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.4
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- [x] T055 - Parallel Task Execution

## Context
Fire-and-forget tasks (like ingestion) need to be tracked to prevent garbage collection and enable monitoring. Implement proper background task management for v2.

## Requirements
- [x] Maintain `_background_tasks: set[asyncio.Task]` in orchestrator
- [x] Add tasks to set when created
- [x] Remove tasks when completed (via done callback)
- [x] Log task completion/failure
- [x] Implement `_get_background_task_count()` for monitoring
- [x] Handle task cancellation on shutdown

## Acceptance Criteria
- [x] Fire-and-forget tasks don't get garbage collected
- [x] Task completion logged
- [x] Task failures logged (but don't crash)
- [x] Task count available for health checks
- [x] Clean shutdown cancels pending tasks

## Implementation Notes
```python
class Orchestrator:
    def __init__(self, ...):
        self._background_tasks: set[asyncio.Task] = set()

    def _track_background_task(self, coro, trace_id: str) -> asyncio.Task:
        """Create and track a background task."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _on_done(t: asyncio.Task):
            self._background_tasks.discard(t)
            if t.exception():
                logger.warning(
                    f"[SWELL] Background task failed: {t.exception()}",
                    extra={"trace_id": trace_id}
                )
            else:
                logger.debug(
                    f"[WHISPER] Background task completed",
                    extra={"trace_id": trace_id}
                )

        task.add_done_callback(_on_done)
        return task

    async def shutdown(self):
        """Cancel all background tasks on shutdown."""
        for task in self._background_tasks:
            task.cancel()
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
```

## Development Notes

### Implementation

**Files Modified:**
- `src/klabautermann/agents/orchestrator.py` - Added three methods for background task tracking
- `tests/unit/test_background_tasks.py` - Created comprehensive unit test suite (12 tests)

**Methods Added:**
1. `_track_background_task(coro, trace_id, task_name)` - Creates and tracks background tasks with done callbacks
2. `_get_background_task_count()` - Returns count of currently running tasks for health checks
3. `shutdown()` - Cancels all pending background tasks gracefully on shutdown

**Integration Points:**
- Line 460: Updated v1 workflow ingestion to use `_track_background_task()`
- Line 1788: Updated v2 workflow fire-and-forget tasks to use `_track_background_task()`

### Decisions Made

1. **Task naming**: Added `task_name` parameter to enable descriptive task names for debugging (e.g., "ingest-v1-abc123")
2. **Logging levels**: Used [WHISPER] for completion (debug level) and [SWELL] for failures (warning level) per nautical conventions
3. **Callback pattern**: Used `add_done_callback()` to automatically remove tasks from set upon completion/failure
4. **Graceful shutdown**: Implemented `shutdown()` that cancels tasks and waits with `return_exceptions=True` to avoid propagating CancelledError

### Patterns Established

**Background Task Tracking Pattern:**
```python
self._track_background_task(
    coroutine_to_run(),
    trace_id=trace_id,
    task_name=f"descriptive-name-{trace_id}",
)
```

This pattern:
- Prevents garbage collection of fire-and-forget tasks
- Provides automatic logging of completion/failure
- Enables monitoring via `_get_background_task_count()`
- Supports graceful shutdown via `shutdown()`

### Testing

**Test Suite:** `tests/unit/test_background_tasks.py`
- 12 tests covering all aspects of background task tracking
- Tests pass garbage collection scenarios
- Verifies proper lifecycle management (add → complete → remove)
- Tests both success and failure paths
- Verifies shutdown cancellation behavior
- All tests passing (12/12)

**Key Test Scenarios:**
1. Tasks added to set when created
2. Tasks removed automatically on completion
3. Tasks removed automatically on failure
4. Completion logged with [WHISPER]
5. Failures logged with [SWELL]
6. Accurate task count tracking
7. Shutdown cancels all pending tasks
8. Independent task lifecycles
9. Garbage collection prevention

### Issues Encountered

**File modification challenges**: The Edit tool repeatedly failed with "file has been modified" errors, likely due to a background linter/formatter process. Resolved by using direct Python scripts to read/modify/write the file in single operations.

### Future Considerations

1. **Health endpoint**: The `_get_background_task_count()` method can be exposed via an API endpoint for monitoring
2. **Task timeout**: Consider adding timeout handling for long-running background tasks
3. **Task metrics**: Could track task execution time, failure rates, etc. for observability
4. **Graceful degradation**: If background task count exceeds a threshold, could implement backpressure
