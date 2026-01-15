# Scribe Analytics Queries

## Metadata
- **ID**: T044
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: navigator

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.6 (Scribe Analytics Queries)
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 5 (Day Nodes)

## Dependencies
- [x] T010 - Neo4j client
- [x] T042 - Day Node Management

## Context
The Scribe generates daily reflections by analyzing the day's activity. These analytics queries gather statistics: interaction count, new entities created, tasks completed, projects discussed. The data feeds into the journal generation pipeline, giving the Scribe material to craft a meaningful reflection.

## Requirements
- [ ] Create `src/klabautermann/memory/analytics.py` or add to `queries.py`:

### Daily Statistics
- [ ] `get_daily_interaction_count(date: str) -> int`
  - Count messages across all threads for the day
  - Uses timestamp range (day_start to day_end)

- [ ] `get_daily_entity_counts(date: str) -> dict[str, int]`
  - Count new nodes created that day by type
  - Return: {"Person": 2, "Organization": 1, "Project": 0, ...}

- [ ] `get_daily_task_stats(date: str) -> dict`
  - Tasks completed that day (by completed_at)
  - Tasks created that day (by created_at)
  - Return: {"completed": 3, "created": 5}

- [ ] `get_daily_projects_discussed(date: str, limit: int = 3) -> list[dict]`
  - Projects mentioned in notes/events that day
  - Return top N by mention count
  - Return: [{"name": "Q1 Budget", "mentions": 5}, ...]

### Aggregated Daily Summary
- [ ] `get_daily_analytics(date: str) -> DailyAnalytics`
  - Combine all above into single call
  - Return Pydantic model for type safety

### DailyAnalytics Model
- [ ] Add to `core/models.py`:
  ```python
  class DailyAnalytics(BaseModel):
      date: str
      interaction_count: int
      new_entities: dict[str, int]
      tasks_completed: int
      tasks_created: int
      top_projects: list[dict]
      notes_created: int
      events_count: int
  ```

## Acceptance Criteria
- [ ] Interaction count reflects messages sent that day
- [ ] Entity counts are accurate by type
- [ ] Task stats use correct timestamp fields
- [ ] Projects ranked by mention frequency
- [ ] All queries use parameterized date range
- [ ] Unit tests with sample graph data

## Implementation Notes

```python
from datetime import datetime, timedelta

def get_day_bounds(date: str) -> tuple[float, float]:
    """Get timestamp bounds for a day (start, end)."""
    day_dt = datetime.strptime(date, "%Y-%m-%d")
    day_start = day_dt.replace(hour=0, minute=0, second=0).timestamp()
    day_end = (day_dt + timedelta(days=1)).replace(
        hour=0, minute=0, second=0
    ).timestamp()
    return day_start, day_end


async def get_daily_interaction_count(
    driver: AsyncDriver,
    date: str
) -> int:
    """Count all messages for a specific day."""
    day_start, day_end = get_day_bounds(date)

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (t:Thread)-[:CONTAINS]->(m:Message)
            WHERE m.timestamp >= $day_start AND m.timestamp < $day_end
            RETURN count(m) as interaction_count
            """,
            {"day_start": day_start, "day_end": day_end}
        )
        record = await result.single()
        return record["interaction_count"] if record else 0


async def get_daily_entity_counts(
    driver: AsyncDriver,
    date: str
) -> dict[str, int]:
    """Count new entities created that day by type."""
    day_start, day_end = get_day_bounds(date)

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n)
            WHERE n.created_at >= $day_start AND n.created_at < $day_end
              AND NOT n:Message AND NOT n:Thread AND NOT n:Day
            RETURN labels(n)[0] as type, count(n) as count
            """,
            {"day_start": day_start, "day_end": day_end}
        )
        records = await result.data()
        return {r["type"]: r["count"] for r in records}


async def get_daily_projects_discussed(
    driver: AsyncDriver,
    date: str,
    limit: int = 3
) -> list[dict]:
    """Get top projects mentioned in notes that day."""
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (d:Day {date: $date})<-[:OCCURRED_ON]-(n:Note)
            MATCH (n)-[:DISCUSSED]->(p:Project)
            RETURN p.name as name, p.uuid as uuid, count(n) as mentions
            ORDER BY mentions DESC
            LIMIT $limit
            """,
            {"date": date, "limit": limit}
        )
        return await result.data()
```

### Testing Strategy
Create test fixtures with:
- Messages at specific timestamps
- Entities with created_at in target day
- Tasks with completed_at in target day
- Notes linked to Day with [:DISCUSSED] to Projects
