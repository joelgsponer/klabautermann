# Background Task Tracking

## Metadata
- **ID**: T074
- **Priority**: P1
- **Category**: core
- **Effort**: S
- **Status**: pending

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 4.4
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- [x] T055 - Parallel Task Execution

## Context
Fire-and-forget tasks (like ingestion) need to be tracked to prevent garbage collection and enable monitoring. Implement proper background task management for v2.

## Requirements
- [ ] Maintain `_background_tasks: set[asyncio.Task]` in orchestrator
- [ ] Add tasks to set when created
- [ ] Remove tasks when completed (via done callback)
- [ ] Log task completion/failure
- [ ] Implement `_get_background_task_count()` for monitoring
- [ ] Handle task cancellation on shutdown

## Acceptance Criteria
- [ ] Fire-and-forget tasks don't get garbage collected
- [ ] Task completion logged
- [ ] Task failures logged (but don't crash)
- [ ] Task count available for health checks
- [ ] Clean shutdown cancels pending tasks

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
