# Thread Status Lifecycle

## Metadata
- **ID**: T037
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: completed
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
- [x] Thread transitions: active -> archiving -> archived
- [x] Archiving thread receiving message reverts to active
- [x] Cannot archive already-archiving thread (returns False)
- [x] Cannot archive already-archived thread
- [x] All status changes logged with thread UUID
- [x] Unit tests cover all state transitions

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

---

## Development Notes

### Implementation Summary

Successfully implemented the thread status lifecycle state machine with three methods:

1. **mark_archiving()** - Atomic transition from active → archiving
   - Returns bool indicating success
   - Sets `archiving_started_at` timestamp
   - Uses WHERE clause for atomicity (prevents race conditions)

2. **mark_archived()** - Transition from archiving → archived
   - Returns bool indicating success
   - Creates [:SUMMARY_OF] relationship to Note
   - Sets `archived_at` timestamp
   - Only succeeds if thread is in 'archiving' state

3. **reactivate_thread()** - Revert from archiving → active
   - Returns bool indicating success
   - Removes `archiving_started_at` timestamp
   - Used when archival fails or new message arrives

### Key Design Decisions

**Atomic State Transitions**
All lifecycle methods use WHERE clauses to ensure atomic check-and-update operations. This prevents race conditions where multiple processes try to archive the same thread.

**Boolean Return Values**
Methods return True/False instead of raising exceptions for invalid transitions. This makes error handling cleaner for the Archivist agent.

**Automatic Reactivation**
Modified `add_message()` to automatically reactivate threads in 'archiving' state. This prevents message loss when users send messages while archival is in progress.

**Parameterized Queries**
All Cypher queries use parameterized values ($thread_uuid, $summary_uuid, $now) to prevent injection attacks.

### Files Modified

- `/home/klabautermann/klabautermann3/src/klabautermann/memory/thread_manager.py`
  - Added `mark_archiving()` method (lines 416-462)
  - Added `mark_archived()` method (lines 464-514)
  - Added `reactivate_thread()` method (lines 516-561)
  - Updated `add_message()` to check status and reactivate if needed (lines 184-191)

- `/home/klabautermann/klabautermann3/tests/unit/test_thread_manager.py`
  - Added 15 new tests covering lifecycle methods (lines 309-648)
  - Tests verify atomic transitions, failure cases, and full lifecycle flows
  - Tests verify parameterized query safety and trace_id propagation

### Test Coverage

All 26 tests pass including:
- State transition success/failure cases
- Atomic check-and-update verification
- Double-archiving prevention (race condition)
- Full lifecycle flows (active → archiving → archived)
- Reactivation flow (archiving → active)
- Message addition during archiving (automatic reactivation)
- Trace ID propagation
- Parameterized query safety

### Notes for Downstream Tasks

**For Archivist Agent (T038, T039)**
- Call `mark_archiving()` before starting summarization
- Check return value - False means another process claimed the thread
- Call `mark_archived()` after summary is complete with summary_uuid
- If archival fails, call `reactivate_thread()` to reset state

**Integration Points**
- ThreadStatus enum already exists in `src/klabautermann/core/models.py` (lines 195-200)
- All methods accept optional trace_id for debugging
- Logging uses nautical levels ([CHART], [BEACON], [WHISPER])

### Quality Checks
- [x] Type hints on all methods
- [x] Docstrings on all lifecycle methods
- [x] Proper exception handling (returns bool, no exceptions)
- [x] structlog used for all logging
- [x] Parameterized queries (no f-strings)
- [x] No blocking calls (all async)
- [x] 26/26 tests passing
