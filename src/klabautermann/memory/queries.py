"""
Cypher query library for Klabautermann knowledge graph.

Provides parametrized, injection-safe queries for structural graph searches.
All queries use $param placeholders - NEVER use f-strings with user input.

Reference: specs/architecture/MEMORY.md Section 4, ONTOLOGY.md Section 5
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


@dataclass
class QueryResult:
    """
    Wrapper for query results with execution metadata.

    Attributes:
        records: List of result records as dictionaries
        query_type: Category of query (person, task, event, temporal, thread)
        execution_time_ms: Query execution time in milliseconds
        record_count: Number of records returned
    """

    records: list[dict[str, Any]]
    query_type: str
    execution_time_ms: float
    record_count: int

    @classmethod
    def from_records(
        cls, records: list[dict[str, Any]], query_type: str, start_time: float
    ) -> QueryResult:
        """Create QueryResult from raw records and timing info."""
        execution_time = (time.time() - start_time) * 1000  # Convert to ms
        return cls(
            records=records,
            query_type=query_type,
            execution_time_ms=round(execution_time, 2),
            record_count=len(records),
        )


class CypherQueries:
    """
    Library of parametrized Cypher queries.

    All queries use $param placeholders for injection safety.
    Never use f-strings or string concatenation with user input.

    Query categories:
    - Person: Find people, organizations, managers, colleagues
    - Task: Find tasks, blockers, dependencies, project chains
    - Event: Find events, attendees, locations, time ranges
    - Temporal: Time-travel queries, historical state, creation ranges
    - Thread: Find threads, messages, summaries
    """

    # ===========================================================================
    # PERSON QUERIES
    # ===========================================================================

    FIND_PERSON_BY_NAME = """
    MATCH (p:Person)
    WHERE toLower(p.name) CONTAINS toLower($name)
    RETURN p.uuid as uuid, p.name as name, p.email as email,
           p.bio as bio, p.created_at as created_at
    LIMIT $limit
    """

    FIND_PERSON_ORGANIZATION = """
    MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o:Organization)
    WHERE r.expired_at IS NULL
    RETURN p.name as person, p.uuid as person_uuid,
           o.name as organization, o.uuid as org_uuid,
           r.title as title, r.department as department,
           r.created_at as since
    """

    FIND_PERSON_ORGANIZATION_HISTORICAL = """
    MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o:Organization)
    WHERE r.created_at <= $as_of_timestamp
      AND (r.expired_at IS NULL OR r.expired_at > $as_of_timestamp)
    RETURN p.name as person, o.name as organization,
           r.title as title, r.created_at as started,
           r.expired_at as ended
    """

    FIND_PERSON_MANAGER = """
    MATCH (p:Person {uuid: $person_uuid})-[r:REPORTS_TO]->(m:Person)
    WHERE r.expired_at IS NULL
    RETURN p.name as person, m.name as manager,
           m.email as manager_email, m.uuid as manager_uuid
    """

    FIND_PEOPLE_AT_ORG = """
    MATCH (p:Person)-[r:WORKS_AT]->(o:Organization {uuid: $org_uuid})
    WHERE r.expired_at IS NULL
    RETURN p.uuid as uuid, p.name as name, p.email as email,
           r.title as title, r.department as department
    ORDER BY p.name
    LIMIT $limit
    """

    FIND_PERSON_PROJECTS = """
    MATCH (p:Person {uuid: $person_uuid})-[:MENTIONED_IN]->(n:Note)-[:DISCUSSED]->(proj:Project)
    WHERE proj.status = 'active'
    RETURN DISTINCT proj.uuid as uuid, proj.name as name,
           proj.status as status, proj.deadline as deadline
    ORDER BY proj.deadline ASC NULLS LAST
    LIMIT $limit
    """

    # ===========================================================================
    # TASK QUERIES
    # ===========================================================================

    FIND_BLOCKED_TASKS = """
    MATCH (blocker:Task)-[r:BLOCKS]->(blocked:Task)
    WHERE blocked.status <> 'done' AND blocker.status <> 'done'
    RETURN blocker.action as blocker_task, blocker.uuid as blocker_uuid,
           blocker.status as blocker_status,
           blocked.action as blocked_task, blocked.uuid as blocked_uuid,
           blocked.status as blocked_status, r.reason as reason
    """

    FIND_PROJECT_TASKS = """
    MATCH (t:Task)-[:PART_OF]->(p:Project {uuid: $project_uuid})
    RETURN t.uuid as uuid, t.action as task, t.status as status,
           t.priority as priority, t.due_date as due_date,
           t.created_at as created_at
    ORDER BY
        CASE t.priority
            WHEN 'urgent' THEN 1
            WHEN 'high' THEN 2
            WHEN 'medium' THEN 3
            WHEN 'low' THEN 4
            ELSE 5
        END,
        t.created_at ASC
    LIMIT $limit
    """

    FIND_TASKS_BY_STATUS = """
    MATCH (t:Task {status: $status})
    OPTIONAL MATCH (t)-[:PART_OF]->(p:Project)
    RETURN t.uuid as uuid, t.action as task, t.priority as priority,
           t.due_date as due_date, t.created_at as created_at,
           p.name as project_name, p.uuid as project_uuid
    ORDER BY
        CASE t.priority
            WHEN 'urgent' THEN 1
            WHEN 'high' THEN 2
            WHEN 'medium' THEN 3
            WHEN 'low' THEN 4
            ELSE 5
        END,
        t.due_date ASC NULLS LAST
    LIMIT $limit
    """

    FIND_TASK_DEPENDENCY_CHAIN = """
    MATCH path = (t:Task)-[:BLOCKS*1..5]->(target:Task {uuid: $task_uuid})
    RETURN [node in nodes(path) | {
        uuid: node.uuid,
        action: node.action,
        status: node.status
    }] as chain,
    length(path) as chain_length
    ORDER BY chain_length
    """

    FIND_TASK_ASSIGNEE = """
    MATCH (t:Task {uuid: $task_uuid})-[:ASSIGNED_TO]->(p:Person)
    RETURN p.uuid as person_uuid, p.name as name, p.email as email
    """

    # ===========================================================================
    # EVENT QUERIES
    # ===========================================================================

    FIND_EVENTS_IN_RANGE = """
    MATCH (e:Event)
    WHERE e.start_time >= $start_timestamp
      AND e.start_time <= $end_timestamp
    RETURN e.uuid as uuid, e.title as title,
           e.start_time as start_time, e.end_time as end_time,
           e.location_context as location, e.description as description
    ORDER BY e.start_time ASC
    LIMIT $limit
    """

    FIND_EVENT_ATTENDEES = """
    MATCH (p:Person)-[r:ATTENDED]->(e:Event {uuid: $event_uuid})
    RETURN p.uuid as person_uuid, p.name as name, p.email as email,
           r.role as role
    ORDER BY
        CASE r.role
            WHEN 'organizer' THEN 1
            WHEN 'speaker' THEN 2
            WHEN 'attendee' THEN 3
            ELSE 4
        END,
        p.name
    """

    FIND_EVENTS_AT_LOCATION = """
    MATCH (e:Event)-[:HELD_AT]->(l:Location {uuid: $location_uuid})
    WHERE e.start_time >= $start_timestamp
    RETURN e.uuid as uuid, e.title as title,
           e.start_time as start_time, e.end_time as end_time,
           l.name as location
    ORDER BY e.start_time DESC
    LIMIT $limit
    """

    FIND_EVENT_DISCUSSIONS = """
    MATCH (e:Event {uuid: $event_uuid})-[:DISCUSSED]->(item)
    RETURN labels(item)[0] as item_type, item.uuid as uuid,
           COALESCE(item.name, item.action, item.description) as item_name
    """

    # ===========================================================================
    # TEMPORAL QUERIES
    # ===========================================================================

    FIND_ENTITIES_CREATED_IN_RANGE = """
    MATCH (n)
    WHERE n.created_at >= $start_timestamp
      AND n.created_at <= $end_timestamp
      AND n.created_at IS NOT NULL
    WITH DISTINCT n, labels(n)[0] as label
    WHERE label IN ['Person', 'Organization', 'Project', 'Task', 'Event',
                    'Note', 'Goal', 'Location', 'Resource']
    RETURN label as type, n.uuid as uuid,
           COALESCE(n.name, n.title, n.action, n.description) as name,
           n.created_at as created_at
    ORDER BY n.created_at DESC
    LIMIT $limit
    """

    TIME_TRAVEL_RELATIONSHIPS = """
    MATCH (a)-[r]->(b)
    WHERE r.created_at IS NOT NULL
      AND r.created_at <= $as_of_timestamp
      AND (r.expired_at IS NULL OR r.expired_at > $as_of_timestamp)
    RETURN labels(a)[0] as source_type,
           COALESCE(a.name, a.title, a.action) as source_name,
           a.uuid as source_uuid,
           type(r) as relationship,
           labels(b)[0] as target_type,
           COALESCE(b.name, b.title, b.action) as target_name,
           b.uuid as target_uuid,
           r.created_at as valid_from,
           r.expired_at as valid_until
    ORDER BY r.created_at DESC
    LIMIT $limit
    """

    FIND_EXPIRED_RELATIONSHIPS = """
    MATCH (a)-[r]->(b)
    WHERE r.expired_at IS NOT NULL
      AND r.expired_at >= $start_timestamp
      AND r.expired_at <= $end_timestamp
    RETURN labels(a)[0] as source_type,
           COALESCE(a.name, a.title, a.action) as source_name,
           type(r) as relationship,
           labels(b)[0] as target_type,
           COALESCE(b.name, b.title, b.action) as target_name,
           r.created_at as created_at,
           r.expired_at as expired_at
    ORDER BY r.expired_at DESC
    LIMIT $limit
    """

    # ===========================================================================
    # THREAD QUERIES
    # ===========================================================================

    FIND_RECENT_THREADS = """
    MATCH (t:Thread)
    WHERE t.channel_type = $channel_type
      AND t.status IN ['active', 'archived']
    RETURN t.uuid as uuid, t.external_id as external_id,
           t.status as status, t.last_message_at as last_activity,
           t.created_at as created_at
    ORDER BY t.last_message_at DESC
    LIMIT $limit
    """

    FIND_THREAD_MESSAGES = """
    MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
    RETURN m.uuid as uuid, m.role as role, m.content as content,
           m.timestamp as timestamp, m.metadata as metadata
    ORDER BY m.timestamp DESC
    LIMIT $limit
    """

    FIND_THREAD_SUMMARY = """
    MATCH (n:Note)-[:SUMMARY_OF]->(t:Thread {uuid: $thread_uuid})
    RETURN n.uuid as uuid, n.title as title,
           n.content_summarized as summary, n.created_at as created_at
    ORDER BY n.created_at DESC
    LIMIT 1
    """

    COUNT_THREAD_MESSAGES = """
    MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
    RETURN count(m) as message_count
    """

    # ===========================================================================
    # RELATIONSHIP TRAVERSAL
    # ===========================================================================

    FIND_RELATED_ENTITIES = """
    MATCH (start {uuid: $entity_uuid})-[r*1..2]-(related)
    WHERE r[0].expired_at IS NULL OR r[0].expired_at > timestamp()
    WITH DISTINCT related, labels(related)[0] as label
    WHERE label IN ['Person', 'Organization', 'Project', 'Task', 'Event',
                    'Note', 'Goal', 'Location']
    RETURN label as type, related.uuid as uuid,
           COALESCE(related.name, related.title, related.action) as name
    LIMIT $limit
    """

    FIND_SHORTEST_PATH = """
    MATCH path = shortestPath(
        (a {uuid: $from_uuid})-[*1..6]-(b {uuid: $to_uuid})
    )
    RETURN [node in nodes(path) | {
        type: labels(node)[0],
        uuid: node.uuid,
        name: COALESCE(node.name, node.title, node.action)
    }] as path_nodes,
    [rel in relationships(path) | type(rel)] as path_relationships,
    length(path) as path_length
    """


class QueryBuilder:
    """
    Helper for building and executing Cypher queries safely.

    All queries use parametrized bindings to prevent injection attacks.
    Wraps Neo4jClient with timing and metadata tracking.
    """

    def __init__(self, neo4j_client: Neo4jClient) -> None:
        """
        Initialize QueryBuilder.

        Args:
            neo4j_client: Connected Neo4jClient instance
        """
        self.neo4j = neo4j_client
        self.queries = CypherQueries()

    async def _execute_with_timing(
        self,
        query: str,
        parameters: dict[str, Any],
        query_type: str,
        trace_id: str | None = None,
    ) -> QueryResult:
        """Execute query and wrap results with timing metadata."""
        start_time = time.time()

        logger.debug(
            f"[WHISPER] Executing {query_type} query",
            extra={
                "trace_id": trace_id,
                "agent_name": "query_builder",
                "params": list(parameters.keys()),
            },
        )

        records = await self.neo4j.execute_query(query, parameters, trace_id=trace_id)

        result = QueryResult.from_records(records, query_type, start_time)

        logger.debug(
            f"[WHISPER] Query returned {result.record_count} records "
            f"in {result.execution_time_ms}ms",
            extra={"trace_id": trace_id, "agent_name": "query_builder"},
        )

        return result

    # ===========================================================================
    # Person Queries
    # ===========================================================================

    async def find_person(
        self,
        name: str,
        limit: int = 5,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find person by name (case-insensitive partial match).

        Args:
            name: Name to search for (partial match supported)
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with matching persons
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_PERSON_BY_NAME,
            {"name": name, "limit": limit},
            "person_search",
            trace_id,
        )

    async def find_person_org(
        self,
        person_uuid: str,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find current organization for a person.

        Args:
            person_uuid: UUID of the person
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with current employment info
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_PERSON_ORGANIZATION,
            {"person_uuid": person_uuid},
            "person_org",
            trace_id,
        )

    async def find_person_org_at_date(
        self,
        person_uuid: str,
        as_of: datetime,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find organization for person at specific point in time (time-travel).

        Args:
            person_uuid: UUID of the person
            as_of: Date to query for
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with historical employment info
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_PERSON_ORGANIZATION_HISTORICAL,
            {"person_uuid": person_uuid, "as_of_timestamp": as_of.timestamp()},
            "person_org_historical",
            trace_id,
        )

    async def find_person_manager(
        self,
        person_uuid: str,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find person's current manager.

        Args:
            person_uuid: UUID of the person
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with manager info
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_PERSON_MANAGER,
            {"person_uuid": person_uuid},
            "person_manager",
            trace_id,
        )

    async def find_people_at_org(
        self,
        org_uuid: str,
        limit: int = 50,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find all people currently working at an organization.

        Args:
            org_uuid: UUID of the organization
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with employee list
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_PEOPLE_AT_ORG,
            {"org_uuid": org_uuid, "limit": limit},
            "org_people",
            trace_id,
        )

    async def find_person_projects(
        self,
        person_uuid: str,
        limit: int = 10,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find active projects associated with a person.

        Args:
            person_uuid: UUID of the person
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with project list
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_PERSON_PROJECTS,
            {"person_uuid": person_uuid, "limit": limit},
            "person_projects",
            trace_id,
        )

    # ===========================================================================
    # Task Queries
    # ===========================================================================

    async def find_blocked_tasks(
        self,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find all tasks that are blocking other tasks.

        Args:
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with blocker/blocked task pairs
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_BLOCKED_TASKS,
            {},
            "blocked_tasks",
            trace_id,
        )

    async def find_project_tasks(
        self,
        project_uuid: str,
        limit: int = 100,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find all tasks for a specific project.

        Args:
            project_uuid: UUID of the project
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with tasks ordered by priority
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_PROJECT_TASKS,
            {"project_uuid": project_uuid, "limit": limit},
            "project_tasks",
            trace_id,
        )

    async def find_tasks_by_status(
        self,
        status: str,
        limit: int = 50,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find tasks with a specific status.

        Args:
            status: Task status ('todo', 'in_progress', 'done', 'cancelled')
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with tasks ordered by priority and due date
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_TASKS_BY_STATUS,
            {"status": status, "limit": limit},
            "tasks_by_status",
            trace_id,
        )

    async def find_task_dependency_chain(
        self,
        task_uuid: str,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find chain of tasks blocking the specified task.

        Args:
            task_uuid: UUID of the blocked task
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with dependency chains
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_TASK_DEPENDENCY_CHAIN,
            {"task_uuid": task_uuid},
            "task_dependencies",
            trace_id,
        )

    async def find_task_assignee(
        self,
        task_uuid: str,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find person assigned to a task.

        Args:
            task_uuid: UUID of the task
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with assignee info
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_TASK_ASSIGNEE,
            {"task_uuid": task_uuid},
            "task_assignee",
            trace_id,
        )

    # ===========================================================================
    # Event Queries
    # ===========================================================================

    async def find_events_in_range(
        self,
        start: datetime,
        end: datetime,
        limit: int = 100,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find events within a time range.

        Args:
            start: Start of time range
            end: End of time range
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with events ordered by start time
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_EVENTS_IN_RANGE,
            {
                "start_timestamp": start.timestamp(),
                "end_timestamp": end.timestamp(),
                "limit": limit,
            },
            "events_in_range",
            trace_id,
        )

    async def find_event_attendees(
        self,
        event_uuid: str,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find attendees for an event.

        Args:
            event_uuid: UUID of the event
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with attendee list ordered by role
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_EVENT_ATTENDEES,
            {"event_uuid": event_uuid},
            "event_attendees",
            trace_id,
        )

    async def find_events_at_location(
        self,
        location_uuid: str,
        start_timestamp: float,
        limit: int = 50,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find events at a specific location.

        Args:
            location_uuid: UUID of the location
            start_timestamp: Only return events after this time
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with events at location
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_EVENTS_AT_LOCATION,
            {
                "location_uuid": location_uuid,
                "start_timestamp": start_timestamp,
                "limit": limit,
            },
            "events_at_location",
            trace_id,
        )

    async def find_event_discussions(
        self,
        event_uuid: str,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find topics discussed in an event.

        Args:
            event_uuid: UUID of the event
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with discussed items (Projects, Tasks, Goals)
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_EVENT_DISCUSSIONS,
            {"event_uuid": event_uuid},
            "event_discussions",
            trace_id,
        )

    # ===========================================================================
    # Temporal Queries
    # ===========================================================================

    async def find_entities_created_in_range(
        self,
        start: datetime,
        end: datetime,
        limit: int = 100,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find entities created within a time range.

        Args:
            start: Start of time range
            end: End of time range
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with entities ordered by creation time
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_ENTITIES_CREATED_IN_RANGE,
            {
                "start_timestamp": start.timestamp(),
                "end_timestamp": end.timestamp(),
                "limit": limit,
            },
            "entities_created",
            trace_id,
        )

    async def time_travel_query(
        self,
        as_of: datetime,
        limit: int = 50,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Query graph state as it existed at a specific point in time.

        Args:
            as_of: Point in time to query for
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with relationships valid at that time
        """
        return await self._execute_with_timing(
            CypherQueries.TIME_TRAVEL_RELATIONSHIPS,
            {"as_of_timestamp": as_of.timestamp(), "limit": limit},
            "time_travel",
            trace_id,
        )

    async def find_expired_relationships(
        self,
        start: datetime,
        end: datetime,
        limit: int = 50,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find relationships that expired within a time range.

        Args:
            start: Start of time range
            end: End of time range
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with expired relationships
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_EXPIRED_RELATIONSHIPS,
            {
                "start_timestamp": start.timestamp(),
                "end_timestamp": end.timestamp(),
                "limit": limit,
            },
            "expired_relationships",
            trace_id,
        )

    # ===========================================================================
    # Thread Queries
    # ===========================================================================

    async def find_recent_threads(
        self,
        channel_type: str,
        limit: int = 20,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find recent threads for a channel.

        Args:
            channel_type: Channel type ('cli', 'telegram', etc.)
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with threads ordered by last activity
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_RECENT_THREADS,
            {"channel_type": channel_type, "limit": limit},
            "recent_threads",
            trace_id,
        )

    async def find_thread_messages(
        self,
        thread_uuid: str,
        limit: int = 20,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Get messages from a thread (rolling window).

        Args:
            thread_uuid: UUID of the thread
            limit: Maximum messages to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with messages ordered by timestamp (newest first)
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_THREAD_MESSAGES,
            {"thread_uuid": thread_uuid, "limit": limit},
            "thread_messages",
            trace_id,
        )

    async def find_thread_summary(
        self,
        thread_uuid: str,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find summary note for a thread.

        Args:
            thread_uuid: UUID of the thread
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with thread summary
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_THREAD_SUMMARY,
            {"thread_uuid": thread_uuid},
            "thread_summary",
            trace_id,
        )

    async def count_thread_messages(
        self,
        thread_uuid: str,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Count messages in a thread.

        Args:
            thread_uuid: UUID of the thread
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with message count
        """
        return await self._execute_with_timing(
            CypherQueries.COUNT_THREAD_MESSAGES,
            {"thread_uuid": thread_uuid},
            "thread_message_count",
            trace_id,
        )

    # ===========================================================================
    # Graph Traversal
    # ===========================================================================

    async def find_related_entities(
        self,
        entity_uuid: str,
        limit: int = 20,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find entities related to a node (1-2 hops).

        Args:
            entity_uuid: UUID of the starting entity
            limit: Maximum results to return
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with related entities
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_RELATED_ENTITIES,
            {"entity_uuid": entity_uuid, "limit": limit},
            "related_entities",
            trace_id,
        )

    async def find_shortest_path(
        self,
        from_uuid: str,
        to_uuid: str,
        trace_id: str | None = None,
    ) -> QueryResult:
        """
        Find shortest path between two entities.

        Args:
            from_uuid: UUID of start entity
            to_uuid: UUID of end entity
            trace_id: Optional trace ID for logging

        Returns:
            QueryResult with path nodes and relationships
        """
        return await self._execute_with_timing(
            CypherQueries.FIND_SHORTEST_PATH,
            {"from_uuid": from_uuid, "to_uuid": to_uuid},
            "shortest_path",
            trace_id,
        )


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["CypherQueries", "QueryBuilder", "QueryResult"]
