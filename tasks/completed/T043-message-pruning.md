# Message Pruning After Archival

## Metadata
- **ID**: T043
- **Priority**: P1
- **Category**: core
- **Effort**: S
- **Status**: completed
- **Assignee**: navigator

## Specs
- Primary: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 3.2 (archive_thread)
- Related: [OPTIMIZATIONS.md](../../specs/quality/OPTIMIZATIONS.md)

## Dependencies
- [x] T040 - Archivist Agent Skeleton
- [x] T041 - Note Node Creation
- [x] T011 - Thread Manager

## Context
After a thread is successfully archived (summary created, Note linked), the original Message nodes are deleted to save space and reduce noise in graph queries. This is aggressive pruning - only the summary survives. The Thread node remains as a reference point.

## Requirements
- [x] Add method to `ThreadManager` or queries module:

### Message Deletion
- [x] `prune_thread_messages(thread_uuid: str) -> int`
  - Delete all Message nodes linked to thread
  - Delete [:CONTAINS] relationships
  - Delete [:PRECEDES] relationships between messages
  - Return count of deleted messages

### Safety Checks
- [x] Only prune if thread status is 'archived'
- [x] Only prune if thread has a linked [:SUMMARY_OF] Note
- [x] Log warning if attempting to prune non-archived thread

### Verification
- [x] `verify_thread_archived(thread_uuid: str) -> bool`
  - Check status = 'archived'
  - Check [:SUMMARY_OF] relationship exists
  - Return True only if both conditions met

## Acceptance Criteria
- [x] Messages deleted for archived threads only
- [x] All [:CONTAINS] and [:PRECEDES] relationships removed
- [x] Thread node preserved (for reference)
- [x] Note node preserved with [:SUMMARY_OF] link
- [x] Safety check prevents accidental pruning
- [x] Return count of deleted messages
- [x] Unit tests verify deletion and safety checks

## Implementation Notes

```python
async def prune_thread_messages(
    driver: AsyncDriver,
    thread_uuid: str
) -> int:
    """
    Delete all Message nodes from an archived thread.

    Only works if thread is in 'archived' status with a linked summary.
    Returns count of deleted messages.
    """
    async with driver.session() as session:
        # First verify thread is safely archived
        verify_result = await session.run(
            """
            MATCH (t:Thread {uuid: $thread_uuid})
            WHERE t.status = 'archived'
            MATCH (n:Note)-[:SUMMARY_OF]->(t)
            RETURN t.uuid, n.uuid as note_uuid
            """,
            {"thread_uuid": thread_uuid}
        )
        verification = await verify_result.single()

        if not verification:
            logger.warning(
                f"[SWELL] Cannot prune thread {thread_uuid}: "
                "not archived or missing summary"
            )
            return 0

        # Delete messages
        delete_result = await session.run(
            """
            MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
            WITH m
            DETACH DELETE m
            RETURN count(m) as deleted_count
            """,
            {"thread_uuid": thread_uuid}
        )
        record = await delete_result.single()
        deleted_count = record["deleted_count"] if record else 0

        logger.info(
            f"[BEACON] Pruned {deleted_count} messages from thread {thread_uuid}"
        )
        return deleted_count
```

### Alternative: Batch Pruning
For cleanup tasks, prune all eligible threads at once:
```cypher
// Find and prune all archived threads with summaries
MATCH (t:Thread {status: 'archived'})
WHERE EXISTS((n:Note)-[:SUMMARY_OF]->(t))
MATCH (t)-[:CONTAINS]->(m:Message)
DETACH DELETE m
RETURN count(m) as total_pruned
```

### Audit Trail (Optional Enhancement)
Consider adding pruning metadata to Thread:
```cypher
SET t.messages_pruned_at = timestamp(),
    t.messages_pruned_count = $count
```
This helps with debugging and audit trails.

### Warning
This operation is **irreversible**. The original conversation text is lost after pruning. Only the summary remains. Ensure the summary Note is verified to exist before pruning.

---

## Development Notes

### Implementation Summary
**Date**: 2026-01-15
**Status**: Completed

Implemented message pruning functionality in `ThreadManager` with comprehensive safety checks and audit trail.

### Files Modified
1. **src/klabautermann/memory/thread_manager.py**
   - Added `verify_thread_archived()` method (lines 612-657)
   - Added `prune_thread_messages()` method (lines 659-723)
   - Both methods use parameterized queries for injection safety
   - Integrated with existing Neo4j client pattern

2. **tests/unit/test_thread_manager.py**
   - Added 10 new tests for pruning functionality (lines 654-895)
   - Tests cover success cases, safety checks, edge cases
   - All 36 tests pass (7 pruning + 3 verify + 26 existing)

### Implementation Decisions

**1. Two-Phase Verification**
- `verify_thread_archived()` as separate method for reusability
- Called before pruning to ensure thread is safely archived
- Returns early with warning if verification fails

**2. Audit Trail Enhancement**
- Added pruning metadata to Thread node (beyond spec requirement):
  - `messages_pruned_at`: timestamp of pruning
  - `messages_pruned_count`: count of deleted messages
  - `updated_at`: updated on pruning
- This provides debugging capability and audit trail

**3. DETACH DELETE Implementation**
- Used Cypher's `DETACH DELETE` to remove both:
  - Message nodes
  - All relationships ([:CONTAINS] from Thread, [:PRECEDES] between Messages)
- Implemented using FOREACH pattern to ensure atomic deletion:
  ```cypher
  WITH t, count(m) as message_count, collect(m) as messages
  FOREACH (msg IN messages | DETACH DELETE msg)
  ```

**4. Safety Through Verification**
- Pruning ONLY proceeds if both conditions met:
  1. Thread status = 'archived'
  2. Note-[:SUMMARY_OF]->Thread relationship exists
- If either condition fails, returns 0 and logs warning
- This prevents accidental data loss

**5. Logging Strategy**
- [SWELL] warning when attempting to prune non-archived thread
- [BEACON] info when successfully pruning messages
- [WHISPER] debug for verification results
- Follows existing nautical logging pattern

### Testing Coverage
All test cases from spec requirements implemented:
1. verify_thread_archived returns True for archived with summary
2. verify_thread_archived returns False for non-archived
3. verify_thread_archived returns False for archived without summary
4. prune_thread_messages deletes messages successfully
5. prune_thread_messages returns 0 for non-archived thread (logs warning)
6. prune_thread_messages uses parameterized queries (injection safety)
7. prune_thread_messages preserves Thread node while deleting messages
8. prune_thread_messages sets pruning metadata
9. prune_thread_messages propagates trace_id
10. prune_thread_messages handles empty threads

### Patterns Established
- **Verification Before Mutation**: Always verify thread state before destructive operations
- **Audit Metadata**: Store operation metadata on affected nodes for debugging
- **Atomic Cypher**: Use WITH + FOREACH for counting before deletion
- **Trace ID Propagation**: Pass trace_id through all database calls
- **Early Return Pattern**: Return 0 with warning rather than throwing exceptions

### Integration Points
This functionality will be called by:
- Archivist agent after creating summary Note (automatic pruning)
- Potential batch cleanup job (prune all archived threads)
- Manual admin operations (via CLI or API)

### Performance Considerations
- Single query for verification (1 roundtrip)
- Single query for deletion with metadata update (1 roundtrip)
- Total: 2 database roundtrips per thread
- DETACH DELETE handles cascade efficiently in Neo4j
- For batch operations, could optimize to single query (see Alternative pattern in Implementation Notes)

### Future Enhancements (Not Required)
- Batch pruning method: `prune_all_archived_threads(limit: int) -> dict[str, int]`
- Configurable retention period (e.g., keep messages for N days after archival)
- Soft delete option (mark messages as pruned instead of deleting)
- Metrics collection (total messages pruned, space saved)
