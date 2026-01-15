# Message Pruning After Archival

## Metadata
- **ID**: T043
- **Priority**: P1
- **Category**: core
- **Effort**: S
- **Status**: pending
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
- [ ] Add method to `ThreadManager` or queries module:

### Message Deletion
- [ ] `prune_thread_messages(thread_uuid: str) -> int`
  - Delete all Message nodes linked to thread
  - Delete [:CONTAINS] relationships
  - Delete [:PRECEDES] relationships between messages
  - Return count of deleted messages

### Safety Checks
- [ ] Only prune if thread status is 'archived'
- [ ] Only prune if thread has a linked [:SUMMARY_OF] Note
- [ ] Log warning if attempting to prune non-archived thread

### Verification
- [ ] `verify_thread_archived(thread_uuid: str) -> bool`
  - Check status = 'archived'
  - Check [:SUMMARY_OF] relationship exists
  - Return True only if both conditions met

## Acceptance Criteria
- [ ] Messages deleted for archived threads only
- [ ] All [:CONTAINS] and [:PRECEDES] relationships removed
- [ ] Thread node preserved (for reference)
- [ ] Note node preserved with [:SUMMARY_OF] link
- [ ] Safety check prevents accidental pruning
- [ ] Return count of deleted messages
- [ ] Unit tests verify deletion and safety checks

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
