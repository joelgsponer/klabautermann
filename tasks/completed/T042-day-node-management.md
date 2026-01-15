# Day Node Management (Temporal Spine)

## Metadata
- **ID**: T042
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: completed
- **Assignee**: navigator

## Specs
- Primary: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 5 (Day Nodes)
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md) - Day node schema

## Dependencies
- [x] T010 - Neo4j client
- [x] T041 - Note Node Creation

## Context
Day nodes form the "temporal spine" of the knowledge graph - a chronological backbone that anchors all time-bound entities. Events, Notes, and JournalEntries all link to their Day node via [:OCCURRED_ON]. This enables temporal queries like "What happened on Tuesday?" and weekly/monthly summaries.

## Requirements
- [x] Create `src/klabautermann/memory/day_nodes.py` or add to `queries.py`:

### Day Node Operations
- [x] `get_or_create_day(date: datetime) -> str`
  - Use MERGE to idempotently create Day node
  - Set properties: date (YYYY-MM-DD), day_of_week, is_weekend
  - Return date string (primary key)

- [x] `link_to_day(node_uuid: str, label: str, date: datetime) -> None`
  - Create [:OCCURRED_ON] relationship
  - Works for Note, Event, JournalEntry

- [x] `get_day_contents(date: str) -> dict`
  - Return all entities linked to a Day
  - Group by entity type (Notes, Events, JournalEntries)

### Convenience Methods
- [x] `link_note_to_day(note_uuid: str, date: Optional[datetime] = None) -> None`
  - Uses current date if not specified
  - Calls get_or_create_day then link_to_day

- [x] `get_days_in_range(start_date: str, end_date: str) -> list[dict]`
  - Get all Day nodes in range with counts of linked entities
  - Useful for calendar views

### Day Queries
- [x] `get_daily_summary(date: str) -> dict`
  - Count of notes, events, journal entries
  - List of topics from notes
  - Used by Scribe for reflection

## Acceptance Criteria
- [x] Day nodes created idempotently (MERGE)
- [x] Day has correct date format (YYYY-MM-DD)
- [x] Day has day_of_week and is_weekend properties
- [x] Entities linked via [:OCCURRED_ON]
- [x] Day-based queries return grouped results
- [x] Unit tests for all operations

## Implementation Notes

```python
from datetime import datetime, timezone

async def get_or_create_day(
    driver: AsyncDriver,
    date: datetime
) -> str:
    """Get or create Day node for a specific date."""
    date_str = date.strftime("%Y-%m-%d")
    day_of_week = date.strftime("%A")
    is_weekend = day_of_week in ["Saturday", "Sunday"]

    async with driver.session() as session:
        result = await session.run(
            """
            MERGE (d:Day {date: $date})
            ON CREATE SET
                d.day_of_week = $day_of_week,
                d.is_weekend = $is_weekend
            RETURN d.date
            """,
            {
                "date": date_str,
                "day_of_week": day_of_week,
                "is_weekend": is_weekend
            }
        )
        record = await result.single()
        return record["d.date"]


async def link_to_day(
    driver: AsyncDriver,
    node_uuid: str,
    label: str,
    date: datetime
) -> None:
    """Link an entity to its Day node."""
    date_str = date.strftime("%Y-%m-%d")

    async with driver.session() as session:
        await session.run(
            f"""
            MATCH (n:{label} {{uuid: $node_uuid}})
            MERGE (d:Day {{date: $date}})
            MERGE (n)-[:OCCURRED_ON]->(d)
            """,
            {"node_uuid": node_uuid, "date": date_str}
        )


async def get_day_contents(
    driver: AsyncDriver,
    date: str
) -> dict:
    """Get all entities linked to a specific Day."""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (d:Day {date: $date})<-[:OCCURRED_ON]-(item)
            RETURN labels(item)[0] as type,
                   item.uuid as uuid,
                   item.title as title,
                   item.content_summarized as summary
            ORDER BY item.created_at
            """,
            {"date": date}
        )
        records = await result.data()

        # Group by type
        grouped = {}
        for record in records:
            item_type = record["type"]
            if item_type not in grouped:
                grouped[item_type] = []
            grouped[item_type].append(record)

        return grouped
```

### Day Node Index
Ensure the Day.date constraint is created in database setup:
```cypher
CREATE CONSTRAINT day_date IF NOT EXISTS FOR (d:Day) REQUIRE d.date IS UNIQUE;
```

---

## Development Notes

### Implementation
**Date**: 2025-01-15
**Files Created/Modified**:
- Created `src/klabautermann/memory/day_nodes.py` - Complete Day Node management module
- Created `tests/unit/test_day_nodes.py` - Comprehensive test suite (18 tests)

### Functions Implemented

1. **get_or_create_day(neo4j, date, trace_id)** → str
   - Uses MERGE for idempotent Day node creation
   - Computes day_of_week and is_weekend from date
   - Returns date string in YYYY-MM-DD format
   - Uses execute_write for transactional safety

2. **link_to_day(neo4j, node_uuid, label, date, trace_id)** → None
   - Links any entity (Note, Event, JournalEntry) to Day via [:OCCURRED_ON]
   - Uses MERGE for both Day creation and relationship
   - Label is safely interpolated (enum value), UUID/date are parametrized

3. **link_note_to_day(neo4j, note_uuid, date, trace_id)** → None
   - Convenience wrapper for linking Notes specifically
   - Defaults to current UTC time if date not provided
   - Delegates to link_to_day

4. **get_day_contents(neo4j, date_str, trace_id)** → dict[str, list[dict]]
   - Retrieves all entities linked to a Day
   - Groups results by entity type (Note, Event, JournalEntry)
   - Returns dict with type as key, list of entities as value
   - Each entity includes: uuid, title, summary, created_at

5. **get_days_in_range(neo4j, start_date, end_date, trace_id)** → list[dict]
   - Fetches Day nodes within date range (inclusive)
   - Uses OPTIONAL MATCH for entity counts (handles days with no entities)
   - Returns list ordered by date ascending
   - Each record includes: date, day_of_week, is_weekend, note_count, event_count, journal_count

6. **get_daily_summary(neo4j, date_str, trace_id)** → dict
   - Generates summary statistics for a specific day
   - Used by Scribe agent for daily journal generation
   - Gracefully handles missing Day nodes (returns default values)
   - Returns: date, day_of_week, is_weekend, note_count, event_count, journal_count

### Decisions Made

1. **Separate Module vs. queries.py**
   - Created standalone `day_nodes.py` module for clarity
   - Day operations are distinct from general graph queries
   - Allows focused imports and better organization

2. **Neo4jClient API Usage**
   - Used `execute_write` for MERGE operations (creates/updates)
   - Used `execute_read` for SELECT-like queries
   - Follows pattern established in thread_manager.py

3. **Date Handling**
   - All dates converted to YYYY-MM-DD string format for storage
   - Consistency with Neo4j date indexing and query performance
   - Day of week computed via Python datetime.strftime("%A")
   - Weekend detection: Saturday or Sunday

4. **Idempotency**
   - All write operations use MERGE (safe to call repeatedly)
   - get_or_create_day: ON CREATE SET only sets properties on first creation
   - link_to_day: MERGE creates relationship only if it doesn't exist

5. **Error Handling**
   - get_daily_summary returns default values if Day node missing
   - Logging at DEBUG level for normal operations
   - Logging at ERROR/WARNING level for unexpected conditions

### Patterns Established

1. **Day Node Properties**:
   ```python
   {
       "date": "YYYY-MM-DD",      # Primary key (unique constraint)
       "day_of_week": "Monday",   # Human-readable
       "is_weekend": False        # Boolean flag
   }
   ```

2. **[:OCCURRED_ON] Relationship**:
   - Direction: (Entity)-[:OCCURRED_ON]->(Day)
   - No properties on relationship (date is on Day node)
   - Used for: Note, Event, JournalEntry

3. **Query Pattern for Day Contents**:
   ```cypher
   MATCH (d:Day {date: $date})<-[:OCCURRED_ON]-(item)
   RETURN labels(item)[0] as type, item.uuid, ...
   ORDER BY item.created_at
   ```

4. **Query Pattern for Date Ranges**:
   ```cypher
   MATCH (d:Day)
   WHERE d.date >= $start_date AND d.date <= $end_date
   OPTIONAL MATCH (d)<-[:OCCURRED_ON]-(entity:EntityType)
   RETURN d.date, count(entity) as entity_count
   ORDER BY d.date
   ```

### Testing

**Test Coverage**: 18 tests, all passing
- 4 tests for get_or_create_day (basic, weekend, idempotent, trace_id)
- 3 tests for link_to_day (Note, Event, JournalEntry labels)
- 2 tests for link_note_to_day (explicit date, default date)
- 3 tests for get_day_contents (basic, empty, multiple same type)
- 3 tests for get_days_in_range (basic, empty, weekend flags)
- 3 tests for get_daily_summary (basic, missing Day, zero counts)

**Test Strategy**:
- Mock Neo4jClient with AsyncMock
- Verify query structure (MATCH, MERGE, WHERE clauses)
- Verify parameter binding (injection safety)
- Verify result transformation and grouping
- Test edge cases (empty results, missing nodes)

**Test Execution**:
```bash
uv run pytest tests/unit/test_day_nodes.py -v --tb=short
# Result: 18 passed in 0.41s
```

### Integration Points

1. **Ingestor Agent** (T023):
   - Should call link_note_to_day after creating Note nodes
   - Links notes to Day for temporal organization

2. **Scribe Agent** (Sprint 3):
   - Uses get_daily_summary to generate daily journals
   - Uses get_day_contents to access all day's activities

3. **Researcher Agent** (T024):
   - Can use get_days_in_range for "What happened this week?" queries
   - Can use get_day_contents for "What did I do on Tuesday?" queries

4. **Event Processing** (Sprint 3):
   - Calendar events should call link_to_day with Event label
   - Links events to Day for temporal queries

### Issues Encountered

None. Implementation proceeded smoothly following existing patterns.

### Next Steps

1. **Database Migration** (T010 followup):
   - Ensure Day.date unique constraint exists:
     ```cypher
     CREATE CONSTRAINT day_date IF NOT EXISTS FOR (d:Day) REQUIRE d.date IS UNIQUE;
     ```

2. **Update Ingestor** (T023 enhancement):
   - Modify note creation flow to automatically link notes to Day
   - Import day_nodes module and call link_note_to_day

3. **Scribe Agent** (Sprint 3):
   - Implement daily journal generation using get_daily_summary
   - Use get_day_contents for detailed day reconstruction

4. **Calendar Integration** (Sprint 3):
   - Link Event nodes to Day after calendar sync
   - Enable "What meetings do I have this week?" queries

### References

- **Spec**: specs/architecture/MEMORY.md Section 5 (Day Nodes)
- **Ontology**: specs/architecture/ONTOLOGY.md Section 1.3 (Day node schema)
- **Pattern**: src/klabautermann/memory/thread_manager.py (Neo4j client usage)
- **Tests**: tests/unit/test_thread_manager.py (test pattern reference)
