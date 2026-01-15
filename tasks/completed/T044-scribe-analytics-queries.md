# Scribe Analytics Queries

## Metadata
- **ID**: T044
- **Priority**: P1
- **Category**: core
- **Effort**: M
- **Status**: completed
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
- [x] Create `src/klabautermann/memory/analytics.py` or add to `queries.py`:

### Daily Statistics
- [x] `get_daily_interaction_count(date: str) -> int`
  - Count messages across all threads for the day
  - Uses timestamp range (day_start to day_end)

- [x] `get_daily_entity_counts(date: str) -> dict[str, int]`
  - Count new nodes created that day by type
  - Return: {"Person": 2, "Organization": 1, "Project": 0, ...}

- [x] `get_daily_task_stats(date: str) -> dict`
  - Tasks completed that day (by completed_at)
  - Tasks created that day (by created_at)
  - Return: {"completed": 3, "created": 5}

- [x] `get_daily_projects_discussed(date: str, limit: int = 3) -> list[dict]`
  - Projects mentioned in notes/events that day
  - Return top N by mention count
  - Return: [{"name": "Q1 Budget", "mentions": 5}, ...]

### Aggregated Daily Summary
- [x] `get_daily_analytics(date: str) -> DailyAnalytics`
  - Combine all above into single call
  - Return Pydantic model for type safety

### DailyAnalytics Model
- [x] Add to `core/models.py`:
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
- [x] Interaction count reflects messages sent that day
- [x] Entity counts are accurate by type
- [x] Task stats use correct timestamp fields
- [x] Projects ranked by mention frequency
- [x] All queries use parameterized date range
- [x] Unit tests with sample graph data

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

---

## Development Notes

### Implementation
**Files Created:**
- `src/klabautermann/memory/analytics.py` - Complete analytics module with all required functions
- `tests/unit/test_analytics.py` - Comprehensive unit tests (21 tests, all passing)

**Files Modified:**
- `src/klabautermann/core/models.py` - Added DailyAnalytics model and export

### Decisions Made

1. **Separate Analytics Module**: Created dedicated `analytics.py` instead of adding to `queries.py`
   - Rationale: Analytics is a distinct concern for the Scribe agent
   - Keeps query library focused on general graph traversal
   - Provides clear API for future journal generation

2. **Neo4jClient Pattern**: Used existing Neo4jClient.execute_query() pattern
   - Follows established patterns from thread_manager.py
   - Ensures all queries are parametrized (injection-safe)
   - Consistent with project's query execution approach

3. **Timestamp Handling**: Used Unix timestamps (float) for day boundaries
   - Matches existing created_at/completed_at/timestamp fields in graph
   - `get_day_bounds()` utility converts YYYY-MM-DD to timestamp range
   - Ensures consistent timezone handling

4. **Entity Type Filtering**: Explicit exclusion of system nodes
   - Query explicitly excludes Message, Thread, Day nodes
   - Only counts knowledge entities (Person, Org, Project, etc.)
   - Prevents system metadata from polluting entity counts

5. **Task Statistics**: Separate queries for completed vs created
   - completed_at field for completion tracking
   - created_at field for creation tracking
   - Allows different timestamp fields per statistic

### Patterns Established

1. **Analytics Function Signature**:
   ```python
   async def get_daily_X(
       neo4j: Neo4jClient,
       date: str,
       trace_id: str | None = None,
   ) -> ReturnType:
   ```

2. **Logging Pattern**:
   - [WHISPER] for query execution
   - [CHART] for aggregation start
   - [BEACON] for completion
   - Always include trace_id in extra data

3. **Parameterized Queries**:
   - All queries use $param placeholders
   - Never use f-strings for user/date input
   - Timestamp ranges via get_day_bounds()

4. **Aggregation Pattern**:
   - `get_daily_analytics()` orchestrates all sub-queries
   - Returns validated Pydantic model
   - Extracts specific counts (notes_created, events_count) from entity dict

### Testing

**Test Coverage:**
- 21 unit tests, all passing
- Test classes organized by function
- Dedicated test suite for parametrized query verification
- Edge cases covered (empty results, missing fields)

**Test Strategy:**
- Mock Neo4jClient.execute_query()
- Verify query structure and parameters
- Test return value transformations
- Validate DailyAnalytics model construction

### Issues Encountered

None. Implementation followed existing patterns cleanly.

### Integration Points

**For Scribe Agent:**
```python
from klabautermann.memory.analytics import get_daily_analytics

analytics = await get_daily_analytics(neo4j, "2026-01-15", trace_id)
# Use analytics.interaction_count, analytics.new_entities, etc.
```

**For Journal Generation:**
- DailyAnalytics model provides all data needed
- Can format into natural language summary
- top_projects list already sorted by mentions
- new_entities dict breaks down by type
