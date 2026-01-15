# Query Patterns - Navigator Devnotes

## Thread Cooldown Detection (T036)

**Date**: 2026-01-15
**Status**: Implemented

### Purpose
Enable the Archivist agent to efficiently identify inactive threads ready for archival. Threads are considered "cold" when they've been inactive for a configurable cooldown period (default: 60 minutes).

### Implementation

#### Method Signature
```python
async def get_inactive_threads(
    self,
    cooldown_minutes: int = 60,
    limit: int = 10,
    trace_id: str | None = None,
) -> list[str]
```

#### Cypher Query
```cypher
MATCH (t:Thread)
WHERE t.status = 'active'
  AND t.last_message_at < $cutoff_timestamp
RETURN t.uuid
ORDER BY t.last_message_at ASC
LIMIT $limit
```

#### Key Characteristics

1. **Filtering**:
   - Only `active` threads (excludes `archiving` and `archived`)
   - `last_message_at` older than cutoff timestamp

2. **Ordering**:
   - ASC by `last_message_at` (oldest inactive threads first)
   - Ensures fair processing across all cold threads

3. **Limiting**:
   - Default: 10 threads per query
   - Prevents overwhelming the archival pipeline
   - Allows steady progress through backlog

4. **Return Type**:
   - Returns only UUIDs (not full ThreadNode objects)
   - Minimizes memory overhead during batch processing

5. **Safety**:
   - Fully parameterized (no f-strings)
   - Injection-safe

### Performance Notes

- **Index**: Query benefits from composite index on `(status, last_message_at)`
- **Query Plan**: Filters on `status = 'active'` first, then applies timestamp filter
- **Complexity**: O(log n) for index lookup + O(limit) for result fetching

### Usage Example

```python
# In Archivist agent
thread_manager = ThreadManager(neo4j_client)

# Poll for inactive threads
inactive_thread_uuids = await thread_manager.get_inactive_threads(
    cooldown_minutes=60,
    limit=10,
    trace_id=trace_id
)

# Process each thread
for thread_uuid in inactive_thread_uuids:
    await archive_thread(thread_uuid)
```

### Testing

Comprehensive test suite in `tests/unit/test_thread_manager.py`:
- Basic functionality
- Custom cooldown periods
- Custom limits
- Empty results
- Trace ID propagation
- Return value structure
- Query safety
- Ordering verification
- Status filtering
- Typical Archivist usage patterns
- Pipeline protection

**Test Results**: 11/11 passed

### Related Tasks
- T037: Archivist Agent (depends on this query)
- T011: Thread Manager (foundation)

### Future Enhancements

1. **Priority Scoring**: Could add message count to prioritize busier threads
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

2. **Channel-Specific Cooldowns**: Different cooldown periods per channel type

3. **Activity Score**: Consider not just last message time but activity patterns

### Lessons Learned

1. **Return UUIDs Only**: Returning full objects was considered but rejected to minimize memory usage during batch operations
2. **Simple First**: Deliberately kept query simple rather than adding priority scoring in initial implementation
3. **Order Matters**: ASC ordering ensures fairness - oldest threads get archived first

---

## Query Pattern Guidelines

### Parametrization
Always use `$parameter` syntax:
```cypher
WHERE t.uuid = $uuid  // Good
WHERE t.uuid = '{uuid}'  // Bad - injection risk
```

### Temporal Filtering
Use Unix timestamps for consistency:
```python
cutoff = time.time() - (minutes * 60)
```

### Limiting Results
Always include a LIMIT clause for batch operations:
```cypher
RETURN t.uuid
LIMIT $limit  // Prevent runaway queries
```

### Ordering for Fairness
For batch processing, order by timestamp ASC:
```cypher
ORDER BY t.last_message_at ASC  // Oldest first
```

### Index-Friendly Filters
Structure WHERE clauses to match index order:
```cypher
WHERE t.status = 'active'  // Indexed field first
  AND t.last_message_at < $cutoff  // Then range filter
```
