# Note Node Creation from Thread Summary

## Metadata
- **ID**: T041
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: completed
- **Assignee**: navigator

## Specs
- Primary: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) - Note node schema
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 1.2 (Mid-Term Memory)

## Dependencies
- [x] T038 - Thread Summary Models
- [x] T010 - Neo4j client

## Context
When a thread is archived, its summary becomes a Note node in the graph. Notes are the mid-term memory layer - more durable than messages, queryable by vector search, and linked to the temporal spine via Day nodes. This task implements the graph operations to create and link Note nodes.

## Requirements
- [x] Create or extend `src/klabautermann/memory/queries.py`:

### Note Creation
- [x] `create_note_from_summary(thread_uuid: str, summary: ThreadSummary) -> str`
  - Create Note node with:
    - `uuid`: Generated UUID
    - `title`: Generated from topics (first 2-3 topics)
    - `content_summarized`: summary.summary
    - `topics`: summary.topics (as JSON array)
    - `action_items`: Serialized summary.action_items
    - `created_at`: Current timestamp
    - `source`: "thread_summary"
  - Return Note UUID

### Relationship Creation
- [x] `link_note_to_thread(note_uuid: str, thread_uuid: str) -> None`
  - Create `[:SUMMARY_OF]` relationship

- [x] `link_entities_to_note(note_uuid: str, entity_names: list[str]) -> int`
  - For each participant/entity mentioned
  - Find existing Person/Org nodes by name
  - Create `[:MENTIONED_IN]` relationships
  - Return count of links created

### Vector Embedding (Optional - can defer)
- [x] Prepare Note for vector search (embedding generation can be separate task)
- [x] Leave `vector_embedding` field null initially
- [x] Document where embedding will be added

## Acceptance Criteria
- [x] Note node created with all required fields
- [x] Note linked to Thread via [:SUMMARY_OF]
- [x] Topics stored as queryable array
- [x] Action items serialized as JSON
- [x] Mentioned entities linked via [:MENTIONED_IN]
- [x] All queries use parameterized values
- [x] Unit tests with mock Neo4j session

## Implementation Notes

```cypher
// Create Note node
CREATE (n:Note {
    uuid: $uuid,
    title: $title,
    content_summarized: $summary,
    topics: $topics,
    action_items: $action_items,
    source: 'thread_summary',
    requires_user_validation: $has_conflicts,
    created_at: timestamp(),
    updated_at: timestamp()
})
RETURN n.uuid

// Link to Thread
MATCH (n:Note {uuid: $note_uuid})
MATCH (t:Thread {uuid: $thread_uuid})
CREATE (n)-[:SUMMARY_OF]->(t)

// Link mentioned entities (fuzzy match on name)
MATCH (n:Note {uuid: $note_uuid})
UNWIND $entity_names as name
MATCH (e:Person)
WHERE toLower(e.name) = toLower(name)
MERGE (e)-[:MENTIONED_IN]->(n)
```

### Title Generation
Generate title from topics:
```python
def generate_note_title(topics: list[str], max_length: int = 60) -> str:
    if not topics:
        return "Conversation Summary"
    title = " / ".join(topics[:3])
    if len(title) > max_length:
        title = title[:max_length-3] + "..."
    return title
```

### Action Items Serialization
Store action items as JSON for later extraction:
```python
import json

action_items_json = json.dumps([
    item.model_dump() for item in summary.action_items
])
```

---

## Development Notes

### Implementation
**Date**: 2026-01-15

Created `/src/klabautermann/memory/note_queries.py` with the following functions:

1. **`generate_note_title(topics, max_length=60)`**
   - Generates concise title from first 2-3 topics
   - Uses " / " separator for readability
   - Truncates with "..." if exceeds max_length
   - Returns "Conversation Summary" for empty topics

2. **`create_note_from_summary(neo4j, thread_uuid, summary, trace_id)`**
   - Creates Note node with all properties from ThreadSummary
   - Serializes action_items to JSON using `model_dump()`
   - Sets `requires_user_validation=True` if conflicts exist
   - Uses parametrized query with `execute_write` transaction
   - Returns generated Note UUID

3. **`link_note_to_thread(neo4j, note_uuid, thread_uuid, trace_id)`**
   - Creates `[:SUMMARY_OF]` relationship from Note to Thread
   - Includes `created_at` timestamp on relationship
   - Raises RuntimeError if nodes not found

4. **`link_entities_to_note(neo4j, note_uuid, entity_names, trace_id)`**
   - Case-insensitive lookup of Person/Organization nodes by name
   - Uses MERGE to avoid duplicate relationships
   - Creates `[:MENTIONED_IN]` relationships from entities to Note
   - Returns count of successfully created links
   - Handles empty entity list gracefully (returns 0)

5. **`create_note_with_links(neo4j, thread_uuid, summary, trace_id)`**
   - Convenience function orchestrating all three operations
   - Returns dict with `note_uuid` and `entity_link_count`

### Decisions Made

**File Organization**
- Created separate `note_queries.py` instead of extending existing `queries.py`
- Rationale: Note creation is conceptually distinct from read-only queries. The existing `queries.py` is focused on retrieval patterns (CypherQueries constants + QueryBuilder), while note creation involves write operations. This separation follows single responsibility principle.

**Topics Storage**
- Store topics as native Neo4j list property (not JSON string)
- Rationale: Neo4j supports list properties natively, allowing indexed queries like `WHERE 'Budget' IN n.topics`. JSON would require deserialization for filtering.

**Action Items Storage**
- Store action items as JSON string (not native list)
- Rationale: Action items are complex objects with nested properties (action, assignee, status, confidence). Native list would lose structure. JSON preserves full Pydantic schema for later reconstruction.

**Entity Matching**
- Case-insensitive name matching using `toLower()`
- Matches both Person and Organization nodes
- Uses MERGE to prevent duplicate relationships
- Rationale: User might refer to "sarah johnson", "Sarah Johnson", or "SARAH JOHNSON" - all should match same entity.

**Conflict Handling**
- `requires_user_validation` flag set based on conflicts in ThreadSummary
- Rationale: Archivist detects conflicts (e.g., "Sarah changed jobs"). Note node flags this so UI can prompt user review. Follows ontology spec requirement.

### Patterns Established

**Query Safety**
- All queries use parametrized values (never f-strings)
- Example: `{uuid: $uuid}` not `{uuid: '{uuid}'}`
- Prevents Cypher injection attacks

**Transaction Handling**
- Use `execute_write()` for all mutations
- Ensures atomic commit/rollback
- Follows pattern from neo4j_client.py

**Logging Convention**
- `[WHISPER]` for debug-level operations
- `[BEACON]` for successful completions
- `[STORM]` for errors
- Include trace_id, agent_name in all logs

**Error Handling**
- Raise RuntimeError with clear message when nodes not found
- Check result list before accessing (could be empty)
- Let GraphConnectionError bubble up from Neo4jClient

### Testing

Created comprehensive unit tests in `/tests/unit/test_note_queries.py`:

**Test Coverage**:
- Title generation (5 tests): topics, empty, truncation, edge cases
- Note creation (3 tests): success, with conflicts, failure handling
- Thread linking (2 tests): success, node not found
- Entity linking (4 tests): full match, partial match, empty list, case-insensitive
- Integration (2 tests): full workflow, no entities
- Edge cases (3 tests): single long topic, exact max_length, empty action items

**Total**: 19 tests, all passing

**Test Pattern**:
- Mock Neo4jClient with AsyncMock
- Use `execute_write.return_value` to simulate query results
- Assert on query structure and parameters
- Verify correct behavior for success and failure paths

### Vector Embedding Preparation

**Status**: Deferred to future task
- Note node includes `vector_embedding` field (nullable)
- Left as NULL in initial creation
- Future task will add embedding generation pipeline:
  1. Extract embeddings from `content_summarized` using OpenAI
  2. Update Note nodes with embeddings
  3. Enable semantic search via vector index

**Design Note**: Separating embedding generation keeps this task focused on graph structure. Embedding generation is expensive and will be batched/async.

### Integration Points

**Upstream**: Archivist agent (T040)
- Archivist produces ThreadSummary via LLM extraction
- Calls `create_note_with_links()` when archiving thread

**Downstream**: Researcher agent (future)
- Will query Notes via vector similarity
- Will traverse `[:MENTIONED_IN]` relationships for context

**Related**: Thread management (T039)
- Note creation happens during thread archival workflow
- Thread status transitions: `active` → `archiving` → `archived`
- Note created during `archiving` state

### Files Modified
- Created: `/src/klabautermann/memory/note_queries.py` (380 lines)
- Created: `/tests/unit/test_note_queries.py` (423 lines)

### Next Recommended Tasks
1. **T042** - Thread Archival Workflow (integrate note creation)
2. **T043** - Note Vector Embedding Generation
3. **T044** - Day Node Creation and Temporal Linking
