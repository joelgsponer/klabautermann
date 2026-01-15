# Note Node Creation from Thread Summary

## Metadata
- **ID**: T041
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending
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
- [ ] Create or extend `src/klabautermann/memory/queries.py`:

### Note Creation
- [ ] `create_note_from_summary(thread_uuid: str, summary: ThreadSummary) -> str`
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
- [ ] `link_note_to_thread(note_uuid: str, thread_uuid: str) -> None`
  - Create `[:SUMMARY_OF]` relationship

- [ ] `link_entities_to_note(note_uuid: str, entity_names: list[str]) -> int`
  - For each participant/entity mentioned
  - Find existing Person/Org nodes by name
  - Create `[:MENTIONED_IN]` relationships
  - Return count of links created

### Vector Embedding (Optional - can defer)
- [ ] Prepare Note for vector search (embedding generation can be separate task)
- [ ] Leave `vector_embedding` field null initially
- [ ] Document where embedding will be added

## Acceptance Criteria
- [ ] Note node created with all required fields
- [ ] Note linked to Thread via [:SUMMARY_OF]
- [ ] Topics stored as queryable array
- [ ] Action items serialized as JSON
- [ ] Mentioned entities linked via [:MENTIONED_IN]
- [ ] All queries use parameterized values
- [ ] Unit tests with mock Neo4j session

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
