# Cooldown Detection Query

## Metadata
- **ID**: T036
- **Priority**: P0
- **Category**: core
- **Effort**: S
- **Status**: pending
- **Assignee**: navigator

## Specs
- Primary: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 3 (Thread Management)
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) - Thread node schema

## Dependencies
- [x] T011 - Thread Manager

## Context
The Archivist needs to detect threads that have gone "cold" - inactive for 60+ minutes. This query is the foundation for the archival pipeline. It must efficiently find threads ready for summarization without scanning all messages.

## Requirements
- [ ] Add method to `ThreadManager` or create new query module:

### Query Implementation
- [ ] `get_inactive_threads(cooldown_minutes: int = 60) -> List[str]`
- [ ] Query finds threads where:
  - `status = 'active'`
  - `last_message_at < (now - cooldown_minutes)`
- [ ] Return list of thread UUIDs
- [ ] Use parameterized Cypher (no f-strings)

### Performance Considerations
- [ ] Use existing `thread_status` index: `(status, last_message_at)`
- [ ] Limit results to prevent overwhelming the archival pipeline
- [ ] Default limit: 10 threads per scan

### Query Location
- [ ] Add to `src/klabautermann/memory/queries.py` if creating new module
- [ ] Or extend `ThreadManager.get_inactive_threads()` (exists but verify correctness)

## Acceptance Criteria
- [ ] Query returns only active threads past cooldown
- [ ] Query uses index (verify with EXPLAIN)
- [ ] Query uses parameterized values (no injection risk)
- [ ] Results limited to configurable max (default 10)
- [ ] Unit test with mock Neo4j session

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
