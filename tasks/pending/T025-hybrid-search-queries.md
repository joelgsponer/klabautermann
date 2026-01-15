# Create Hybrid Search Queries

## Metadata
- **ID**: T025
- **Priority**: P0
- **Category**: core
- **Effort**: M
- **Status**: pending
- **Assignee**: @graph-engineer

## Specs
- Primary: [MEMORY.md](../../specs/architecture/MEMORY.md)
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md)
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.3

## Dependencies
- [ ] T024 - Researcher agent (uses these queries)
- [x] T006 - Ontology constants
- [x] T010 - Neo4j client

## Context
The Researcher agent needs a library of Cypher queries for structural searches. This task creates a comprehensive query module that handles relationship traversals, multi-hop paths, and temporal filtering. These queries complement Graphiti's vector search for hybrid retrieval.

## Requirements
- [ ] Create `src/klabautermann/memory/queries.py`:

### Person Queries
- [ ] Find person by name (case-insensitive)
- [ ] Find person's organization (WORKS_AT)
- [ ] Find person's manager (REPORTS_TO)
- [ ] Find person's projects (CONTRIBUTES_TO)
- [ ] Find people at an organization

### Task Queries
- [ ] Find blocked tasks (BLOCKS relationship)
- [ ] Find tasks for a project (PART_OF)
- [ ] Find tasks by status
- [ ] Find task dependencies (multi-hop BLOCKS)

### Event Queries
- [ ] Find events by time range
- [ ] Find event attendees (ATTENDED)
- [ ] Find events at location (HELD_AT)
- [ ] Find events discussing topic (DISCUSSED)

### Temporal Queries
- [ ] Filter by created_at range
- [ ] Filter by expired_at (historical vs current)
- [ ] Time-travel query (state at specific date)

### Thread Queries
- [ ] Find recent threads by channel
- [ ] Find thread messages (rolling window)
- [ ] Find thread summary (Note with SUMMARY_OF)

### Query Builder
- [ ] Parametrized query construction
- [ ] Injection-safe parameter binding
- [ ] Query result formatting

## Acceptance Criteria
- [ ] All queries use parametrized bindings (no f-strings)
- [ ] Temporal queries correctly filter expired relationships
- [ ] Multi-hop queries return full paths
- [ ] Query builder validates parameters
- [ ] Unit tests for each query type

## Implementation Notes

```python
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass


@dataclass
class QueryResult:
    """Wrapper for query results with metadata."""
    records: List[Dict[str, Any]]
    query_type: str
    execution_time_ms: float


class CypherQueries:
    """
    Library of Cypher queries for the Researcher agent.

    All queries use parametrized bindings for security.
    Never use f-strings with user input.
    """

    # ====================
    # PERSON QUERIES
    # ====================

    FIND_PERSON_BY_NAME = """
    MATCH (p:Person)
    WHERE toLower(p.name) CONTAINS toLower($name)
    RETURN p.uuid as uuid, p.name as name, p.email as email, p.bio as bio
    LIMIT $limit
    """

    FIND_PERSON_ORGANIZATION = """
    MATCH (p:Person {name: $name})-[r:WORKS_AT]->(o:Organization)
    WHERE r.expired_at IS NULL
    RETURN p.name as person, o.name as organization, r.title as title, r.started_at as since
    """

    FIND_PERSON_ORGANIZATION_HISTORICAL = """
    MATCH (p:Person {name: $name})-[r:WORKS_AT]->(o:Organization)
    WHERE r.created_at <= $as_of_date
      AND (r.expired_at IS NULL OR r.expired_at > $as_of_date)
    RETURN p.name as person, o.name as organization, r.title as title
    """

    FIND_PERSON_MANAGER = """
    MATCH (p:Person {name: $name})-[r:REPORTS_TO]->(m:Person)
    WHERE r.expired_at IS NULL
    RETURN p.name as person, m.name as manager, m.email as manager_email
    """

    FIND_PEOPLE_AT_ORG = """
    MATCH (p:Person)-[r:WORKS_AT]->(o:Organization {name: $org_name})
    WHERE r.expired_at IS NULL
    RETURN p.name as name, p.email as email, r.title as title
    ORDER BY p.name
    """

    # ====================
    # TASK QUERIES
    # ====================

    FIND_BLOCKED_TASKS = """
    MATCH (blocker:Task)-[r:BLOCKS]->(blocked:Task)
    WHERE blocked.status <> 'completed'
    RETURN blocker.action as blocker_task, blocker.uuid as blocker_uuid,
           blocked.action as blocked_task, blocked.uuid as blocked_uuid
    """

    FIND_PROJECT_TASKS = """
    MATCH (t:Task)-[r:PART_OF]->(p:Project {name: $project_name})
    RETURN t.action as task, t.status as status, t.priority as priority, t.uuid as uuid
    ORDER BY t.priority DESC, t.created_at ASC
    """

    FIND_TASKS_BY_STATUS = """
    MATCH (t:Task {status: $status})
    RETURN t.action as task, t.priority as priority, t.uuid as uuid
    ORDER BY t.priority DESC
    LIMIT $limit
    """

    FIND_TASK_DEPENDENCY_CHAIN = """
    MATCH path = (t:Task)-[:BLOCKS*1..5]->(blocked:Task {uuid: $task_uuid})
    RETURN [node in nodes(path) | node.action] as chain
    """

    # ====================
    # EVENT QUERIES
    # ====================

    FIND_EVENTS_IN_RANGE = """
    MATCH (e:Event)
    WHERE e.start_time >= $start_time AND e.start_time <= $end_time
    RETURN e.title as title, e.start_time as start, e.end_time as end, e.uuid as uuid
    ORDER BY e.start_time
    """

    FIND_EVENT_ATTENDEES = """
    MATCH (p:Person)-[r:ATTENDED]->(e:Event {uuid: $event_uuid})
    RETURN p.name as attendee, p.email as email
    """

    FIND_EVENTS_AT_LOCATION = """
    MATCH (e:Event)-[r:HELD_AT]->(l:Location {name: $location_name})
    RETURN e.title as event, e.start_time as start, l.name as location
    ORDER BY e.start_time DESC
    LIMIT $limit
    """

    # ====================
    # TEMPORAL QUERIES
    # ====================

    FIND_ENTITIES_CREATED_IN_RANGE = """
    MATCH (n)
    WHERE n.created_at >= $start_date AND n.created_at <= $end_date
    RETURN labels(n)[0] as type, n.name as name, n.uuid as uuid, n.created_at as created
    ORDER BY n.created_at DESC
    LIMIT $limit
    """

    TIME_TRAVEL_RELATIONSHIPS = """
    MATCH (a)-[r]->(b)
    WHERE r.created_at <= $as_of_date
      AND (r.expired_at IS NULL OR r.expired_at > $as_of_date)
    RETURN labels(a)[0] as source_type, a.name as source,
           type(r) as relationship,
           labels(b)[0] as target_type, b.name as target
    LIMIT $limit
    """

    # ====================
    # THREAD QUERIES
    # ====================

    FIND_RECENT_THREADS = """
    MATCH (t:Thread {channel: $channel})
    RETURN t.uuid as uuid, t.status as status, t.last_message_at as last_activity
    ORDER BY t.last_message_at DESC
    LIMIT $limit
    """

    FIND_THREAD_MESSAGES = """
    MATCH (m:Message)-[:BELONGS_TO]->(t:Thread {uuid: $thread_uuid})
    RETURN m.content as content, m.role as role, m.timestamp as timestamp
    ORDER BY m.timestamp DESC
    LIMIT $limit
    """

    FIND_THREAD_SUMMARY = """
    MATCH (n:Note)-[:SUMMARY_OF]->(t:Thread {uuid: $thread_uuid})
    RETURN n.title as title, n.content_summarized as summary, n.created_at as created
    """


class QueryBuilder:
    """
    Helper for building and executing queries safely.
    """

    def __init__(self, neo4j_client):
        self.neo4j = neo4j_client
        self.queries = CypherQueries()

    async def find_person(self, name: str, limit: int = 5) -> List[Dict]:
        """Find person by name (case-insensitive partial match)."""
        return await self.neo4j.execute_query(
            CypherQueries.FIND_PERSON_BY_NAME,
            {"name": name, "limit": limit}
        )

    async def find_person_org(self, name: str) -> List[Dict]:
        """Find what organization a person works at."""
        return await self.neo4j.execute_query(
            CypherQueries.FIND_PERSON_ORGANIZATION,
            {"name": name}
        )

    async def find_person_org_at_date(self, name: str, as_of: datetime) -> List[Dict]:
        """Find what organization a person worked at on a specific date."""
        return await self.neo4j.execute_query(
            CypherQueries.FIND_PERSON_ORGANIZATION_HISTORICAL,
            {"name": name, "as_of_date": as_of.isoformat()}
        )

    async def find_blocked_tasks(self) -> List[Dict]:
        """Find all tasks that are blocking other tasks."""
        return await self.neo4j.execute_query(CypherQueries.FIND_BLOCKED_TASKS, {})

    async def find_events_between(
        self, start: datetime, end: datetime
    ) -> List[Dict]:
        """Find events in a time range."""
        return await self.neo4j.execute_query(
            CypherQueries.FIND_EVENTS_IN_RANGE,
            {"start_time": start.isoformat(), "end_time": end.isoformat()}
        )

    async def time_travel(self, as_of: datetime, limit: int = 50) -> List[Dict]:
        """Get all relationships as they existed at a specific date."""
        return await self.neo4j.execute_query(
            CypherQueries.TIME_TRAVEL_RELATIONSHIPS,
            {"as_of_date": as_of.isoformat(), "limit": limit}
        )

    async def get_thread_context(self, thread_uuid: str, limit: int = 20) -> List[Dict]:
        """Get recent messages from a thread."""
        return await self.neo4j.execute_query(
            CypherQueries.FIND_THREAD_MESSAGES,
            {"thread_uuid": thread_uuid, "limit": limit}
        )
```

**Security Note**: All queries use parametrized bindings. NEVER construct queries with f-strings or string concatenation using user input.
