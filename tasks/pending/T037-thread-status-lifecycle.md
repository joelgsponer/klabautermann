# Thread Status Lifecycle

## Metadata
- **ID**: T037
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: carpenter

## Specs
- Primary: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 3.1 (Thread Lifecycle)
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) - Thread node schema

## Dependencies
- [x] T011 - Thread Manager
- [x] T036 - Cooldown Detection Query

## Context
Threads progress through a lifecycle: `active -> archiving -> archived`. This task implements the state machine that manages these transitions. The "archiving" state prevents race conditions where a thread receives new messages while being summarized.

## Requirements
- [ ] Extend `ThreadManager` with lifecycle methods:

### Status Enum
- [ ] Add `ThreadStatus` enum to `core/models.py`:
  ```python
  class ThreadStatus(str, Enum):
      ACTIVE = "active"
      ARCHIVING = "archiving"
      ARCHIVED = "archived"
  ```

### State Transitions
- [ ] `mark_archiving(thread_uuid: str) -> bool`
  - Sets status to `archiving`
  - Returns False if thread is not `active` (already being processed)
  - Use atomic update with WHERE clause

- [ ] `mark_archived(thread_uuid: str, summary_uuid: str) -> None`
  - Sets status to `archived`
  - Links summary Note via [:SUMMARY_OF]
  - Only works if current status is `archiving`

- [ ] `reactivate_thread(thread_uuid: str) -> None`
  - Revert from `archiving` back to `active`
  - Used when archival fails or new message arrives during archival

### New Message Handling
- [ ] Update `add_message()` to check thread status
- [ ] If status is `archiving`, reactivate thread first
- [ ] This prevents message loss during archival

### Validation
- [ ] Add `ThreadStatus` field validation in Thread model
- [ ] Ensure status transitions are logged

## Acceptance Criteria
- [ ] Thread transitions: active -> archiving -> archived
- [ ] Archiving thread receiving message reverts to active
- [ ] Cannot archive already-archiving thread (returns False)
- [ ] Cannot archive already-archived thread
- [ ] All status changes logged with thread UUID
- [ ] Unit tests cover all state transitions

## Implementation Notes

```python
async def mark_archiving(self, thread_uuid: str) -> bool:
    """
    Atomically mark thread as archiving.

    Returns True if successful, False if thread not in 'active' state.
    Uses WHERE clause for atomic check-and-update.
    """
    async with self.driver.session() as session:
        result = await session.run(
            """
            MATCH (t:Thread {uuid: $thread_uuid})
            WHERE t.status = 'active'
            SET t.status = 'archiving',
                t.archiving_started_at = timestamp()
            RETURN t.uuid
            """,
            {"thread_uuid": thread_uuid}
        )
        record = await result.single()
        return record is not None
```

The atomic WHERE clause ensures that:
1. Only active threads can transition to archiving
2. Two concurrent archival attempts won't both succeed
3. No race condition between check and update
