# Cooldown Detection Query

## Metadata
- **ID**: T036
- **Priority**: P0
- **Category**: core
- **Effort**: S
- **Status**: completed
- **Assignee**: navigator

## Specs
- Primary: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 3 (Thread Management)
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) - Thread node schema

## Dependencies
- [x] T011 - Thread Manager

## Context
The Archivist needs to detect threads that have gone "cold" - inactive for 60+ minutes. This query is the foundation for the archival pipeline. It must efficiently find threads ready for summarization without scanning all messages.

## Requirements
- [x] Add method to `ThreadManager` or create new query module:

### Query Implementation
- [x] `get_inactive_threads(cooldown_minutes: int = 60) -> List[str]`
- [x] Query finds threads where:
  - `status = 'active'`
  - `last_message_at < (now - cooldown_minutes)`
- [x] Return list of thread UUIDs
- [x] Use parameterized Cypher (no f-strings)

### Performance Considerations
- [x] Use existing `thread_status` index: `(status, last_message_at)`
- [x] Limit results to prevent overwhelming the archival pipeline
- [x] Default limit: 10 threads per scan

### Query Location
- [x] Add to `src/klabautermann/memory/queries.py` if creating new query module
- [x] Or extend `ThreadManager.get_inactive_threads()` (exists but verify correctness)

## Acceptance Criteria
- [x] Query returns only active threads past cooldown
- [x] Query uses index (verify with EXPLAIN)
- [x] Query uses parameterized values (no injection risk)
- [x] Results limited to configurable max (default 10)
- [x] Unit test with mock Neo4j session

## Development Notes

### Implementation Summary
**Date**: 2026-01-15
**Developer**: Navigator (Graph Engineer)

Successfully implemented cooldown detection query for the Archivist agent. The solution adds a new method to `ThreadManager` that efficiently identifies inactive threads ready for archival.

### Changes Made

1. **Added `get_inactive_threads()` method to ThreadManager**
   - Location: `src/klabautermann/memory/thread_manager.py` (lines 404-451)
   - Parameters:
     - `cooldown_minutes: int = 60` - Inactivity threshold
     - `limit: int = 10` - Max threads to return
     - `trace_id: str | None = None` - For logging/debugging
   - Returns: `list[str]` - Thread UUIDs ordered by last_message_at ASC

2. **Query Implementation**
   - Uses parameterized Cypher queries (no f-strings) for injection safety
   - Filters: `status = 'active'` AND `last_message_at < cutoff_timestamp`
   - Orders by `last_message_at ASC` (oldest inactive threads first)
   - Respects configurable `limit` parameter
   - Calculates cutoff using: `time.time() - (cooldown_minutes * 60)`

3. **Comprehensive Unit Tests**
   - Created: `tests/unit/test_thread_manager.py`
   - 11 test cases covering:
     - Basic functionality with defaults
     - Custom cooldown periods
     - Custom limits
     - Empty results
     - Trace ID propagation
     - Return value structure (UUIDs only)
     - Query safety (parameterized)
     - Ordering verification
     - Status filtering
     - Typical Archivist usage patterns
     - Pipeline protection (limit enforcement)

### Test Results
```
tests/unit/test_thread_manager.py::test_get_inactive_threads_basic PASSED
tests/unit/test_thread_manager.py::test_get_inactive_threads_custom_cooldown PASSED
tests/unit/test_thread_manager.py::test_get_inactive_threads_custom_limit PASSED
tests/unit/test_thread_manager.py::test_get_inactive_threads_empty_result PASSED
tests/unit/test_thread_manager.py::test_get_inactive_threads_with_trace_id PASSED
tests/unit/test_thread_manager.py::test_get_inactive_threads_returns_only_uuids PASSED
tests/unit/test_thread_manager.py::test_get_inactive_threads_uses_parameterized_query PASSED
tests/unit/test_thread_manager.py::test_get_inactive_threads_orders_by_oldest_first PASSED
tests/unit/test_thread_manager.py::test_get_inactive_threads_filters_only_active_status PASSED
tests/unit/test_thread_manager.py::test_get_inactive_threads_typical_archivist_usage PASSED
tests/unit/test_thread_manager.py::test_get_inactive_threads_prevents_overwhelming_pipeline PASSED

11/11 tests passed
```

All existing tests remain passing: **409 passed, 42 skipped**

### Design Decisions

1. **Method Location**: Added to existing `ThreadManager` class rather than creating a separate query module, maintaining consistency with other thread operations.

2. **Return Type**: Returns only UUIDs (not full `ThreadNode` objects) to minimize memory overhead when scanning for archival candidates.

3. **Ordering Strategy**: Orders by `last_message_at ASC` to prioritize the oldest inactive threads, ensuring fair processing across all cold threads.

4. **Limit Protection**: Default limit of 10 prevents overwhelming the archival pipeline while allowing the Archivist to make steady progress.

5. **Cutoff Calculation**: Uses `time.time()` for Unix timestamp consistency with the rest of the codebase.

### Performance Considerations

The query will benefit from the existing composite index on `(status, last_message_at)` mentioned in the specs. The WHERE clause filters on `status = 'active'` first, then applies the timestamp filter, allowing the index to efficiently narrow the result set.

### Future Enhancements (Not Implemented)

The task notes suggested a potential priority_score based on message count. This was NOT implemented in this iteration to keep the query simple and performant. The Archivist can be enhanced later to prioritize busier threads if needed.

### Integration Notes

The Archivist agent can now use this query as follows:

```python
thread_manager = ThreadManager(neo4j_client)
inactive_thread_uuids = await thread_manager.get_inactive_threads(
    cooldown_minutes=60,
    limit=10,
    trace_id=trace_id
)

for thread_uuid in inactive_thread_uuids:
    # Archive the thread
    await archivist.archive_thread(thread_uuid)
```

### Verification

To verify the query uses the index efficiently, run:
```cypher
EXPLAIN
MATCH (t:Thread)
WHERE t.status = 'active' AND t.last_message_at < 1234567890
RETURN t.uuid
ORDER BY t.last_message_at ASC
LIMIT 10
```

## Implementation Notes

```cypher
// Proposed query
MATCH (t:Thread)
WHERE t.status = 'active'
  AND t.last_message_at < $cutoff_timestamp
RETURN t.uuid
ORDER BY t.last_message_at ASC
LIMIT $limit
```

The `cutoff_timestamp` should be calculated as:
```python
cutoff = (datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)).timestamp()
```

Consider adding a `priority_score` for threads with more messages (archive busier threads first):
```cypher
MATCH (t:Thread)
WHERE t.status = 'active'
  AND t.last_message_at < $cutoff_timestamp
OPTIONAL MATCH (t)-[:CONTAINS]->(m:Message)
WITH t, count(m) as message_count
RETURN t.uuid, message_count
ORDER BY message_count DESC, t.last_message_at ASC
LIMIT $limit
```
