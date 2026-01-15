# Day Node Management (Temporal Spine)

## Metadata
- **ID**: T042
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending
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
- [ ] Create `src/klabautermann/memory/day_nodes.py` or add to `queries.py`:

### Day Node Operations
- [ ] `get_or_create_day(date: datetime) -> str`
  - Use MERGE to idempotently create Day node
  - Set properties: date (YYYY-MM-DD), day_of_week, is_weekend
  - Return date string (primary key)

- [ ] `link_to_day(node_uuid: str, label: str, date: datetime) -> None`
  - Create [:OCCURRED_ON] relationship
  - Works for Note, Event, JournalEntry

- [ ] `get_day_contents(date: str) -> dict`
  - Return all entities linked to a Day
  - Group by entity type (Notes, Events, JournalEntries)

### Convenience Methods
- [ ] `link_note_to_day(note_uuid: str, date: Optional[datetime] = None) -> None`
  - Uses current date if not specified
  - Calls get_or_create_day then link_to_day

- [ ] `get_days_in_range(start_date: str, end_date: str) -> list[dict]`
  - Get all Day nodes in range with counts of linked entities
  - Useful for calendar views

### Day Queries
- [ ] `get_daily_summary(date: str) -> dict`
  - Count of notes, events, journal entries
  - List of topics from notes
  - Used by Scribe for reflection

## Acceptance Criteria
- [ ] Day nodes created idempotently (MERGE)
- [ ] Day has correct date format (YYYY-MM-DD)
- [ ] Day has day_of_week and is_weekend properties
- [ ] Entities linked via [:OCCURRED_ON]
- [ ] Day-based queries return grouped results
- [ ] Unit tests for all operations

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
