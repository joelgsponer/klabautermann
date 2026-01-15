"""
Unit tests for memory query library.

Tests parametrized Cypher query construction and execution safety.
All queries must use parameters - never f-strings with user input.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.neo4j_client import Neo4jClient
from klabautermann.memory.queries import CypherQueries, QueryBuilder, QueryResult


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_neo4j_client() -> Neo4jClient:
    """Create mock Neo4j client."""
    client = MagicMock(spec=Neo4jClient)
    client.execute_query = AsyncMock()
    return client


@pytest.fixture
def query_builder(mock_neo4j_client: Neo4jClient) -> QueryBuilder:
    """Create QueryBuilder with mock client."""
    return QueryBuilder(mock_neo4j_client)


@pytest.fixture
def sample_person_records() -> list[dict[str, Any]]:
    """Sample person query results."""
    return [
        {
            "uuid": "person-001",
            "name": "Sarah Johnson",
            "email": "sarah@example.com",
            "bio": "Product Manager at Acme Corp",
            "created_at": 1705320000.0,
        },
        {
            "uuid": "person-002",
            "name": "John Smith",
            "email": "john@example.com",
            "bio": "Software Engineer",
            "created_at": 1705320100.0,
        },
    ]


@pytest.fixture
def sample_task_records() -> list[dict[str, Any]]:
    """Sample task query results."""
    return [
        {
            "uuid": "task-001",
            "task": "Review budget proposal",
            "status": "todo",
            "priority": "high",
            "due_date": 1705406400.0,
            "created_at": 1705320000.0,
            "project_name": "Q1 Planning",
            "project_uuid": "proj-001",
        },
        {
            "uuid": "task-002",
            "task": "Send follow-up email",
            "status": "todo",
            "priority": "medium",
            "due_date": 1705492800.0,
            "created_at": 1705320200.0,
            "project_name": None,
            "project_uuid": None,
        },
    ]


# ===========================================================================
# QueryResult Tests
# ===========================================================================


def test_query_result_creation():
    """Test QueryResult dataclass creation."""
    records = [{"name": "Test"}]
    result = QueryResult(records=records, query_type="test", execution_time_ms=15.5, record_count=1)

    assert result.records == records
    assert result.query_type == "test"
    assert result.execution_time_ms == 15.5
    assert result.record_count == 1


def test_query_result_from_records():
    """Test QueryResult factory method."""
    records = [{"name": "Test"}]
    start_time = datetime.now().timestamp() - 0.01  # 10ms ago

    result = QueryResult.from_records(records, "test", start_time)

    assert result.records == records
    assert result.query_type == "test"
    assert result.execution_time_ms > 0
    assert result.execution_time_ms < 100  # Should be less than 100ms
    assert result.record_count == 1


# ===========================================================================
# CypherQueries Tests (Query String Validation)
# ===========================================================================


def test_queries_use_parameters_not_fstrings():
    """Verify all queries use $param syntax, not f-strings."""
    queries = CypherQueries()

    # Get all query string constants
    query_attrs = [
        attr for attr in dir(queries) if attr.isupper() and isinstance(getattr(queries, attr), str)
    ]

    for attr_name in query_attrs:
        query = getattr(queries, attr_name)

        # Check for parameter syntax
        assert "$" in query, f"{attr_name} should use $param placeholders"

        # Check it doesn't use f-string patterns (naive check)
        assert "{}" not in query, f"{attr_name} should not use {{}} formatting"
        assert ".format(" not in query, f"{attr_name} should not use .format()"


def test_person_queries_have_required_fields():
    """Test person queries return expected fields."""
    assert "p.uuid" in CypherQueries.FIND_PERSON_BY_NAME
    assert "p.name" in CypherQueries.FIND_PERSON_BY_NAME
    assert "$name" in CypherQueries.FIND_PERSON_BY_NAME
    assert "$limit" in CypherQueries.FIND_PERSON_BY_NAME


def test_temporal_queries_filter_expired():
    """Test temporal queries correctly filter expired relationships."""
    assert "r.expired_at IS NULL" in CypherQueries.FIND_PERSON_ORGANIZATION
    assert "r.expired_at > $as_of_timestamp" in CypherQueries.FIND_PERSON_ORGANIZATION_HISTORICAL


def test_task_queries_include_status_filtering():
    """Test task queries filter by status appropriately."""
    assert "<> 'done'" in CypherQueries.FIND_BLOCKED_TASKS
    assert "$status" in CypherQueries.FIND_TASKS_BY_STATUS


def test_event_queries_use_time_range():
    """Test event queries use proper time range filtering."""
    assert "$start_timestamp" in CypherQueries.FIND_EVENTS_IN_RANGE
    assert "$end_timestamp" in CypherQueries.FIND_EVENTS_IN_RANGE
    assert "e.start_time >=" in CypherQueries.FIND_EVENTS_IN_RANGE


def test_thread_queries_handle_ordering():
    """Test thread queries order results properly."""
    assert "ORDER BY" in CypherQueries.FIND_RECENT_THREADS
    assert "ORDER BY m.timestamp DESC" in CypherQueries.FIND_THREAD_MESSAGES


# ===========================================================================
# QueryBuilder Person Query Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_find_person_basic(
    query_builder: QueryBuilder,
    mock_neo4j_client: Neo4jClient,
    sample_person_records: list[dict[str, Any]],
):
    """Test basic person search by name."""
    mock_neo4j_client.execute_query.return_value = sample_person_records

    result = await query_builder.find_person("sarah", limit=5)

    # Verify query was called with correct parameters
    mock_neo4j_client.execute_query.assert_called_once()
    call_args = mock_neo4j_client.execute_query.call_args

    assert call_args[0][0] == CypherQueries.FIND_PERSON_BY_NAME
    assert call_args[0][1] == {"name": "sarah", "limit": 5}

    # Verify result
    assert result.query_type == "person_search"
    assert result.record_count == 2
    assert result.records == sample_person_records


@pytest.mark.asyncio
async def test_find_person_org(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding person's current organization."""
    org_records = [
        {
            "person": "Sarah Johnson",
            "person_uuid": "person-001",
            "organization": "Acme Corp",
            "org_uuid": "org-001",
            "title": "Product Manager",
            "department": "Engineering",
            "since": 1705320000.0,
        }
    ]
    mock_neo4j_client.execute_query.return_value = org_records

    result = await query_builder.find_person_org("person-001")

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_PERSON_ORGANIZATION
    assert call_args[0][1] == {"person_uuid": "person-001"}

    assert result.query_type == "person_org"
    assert result.record_count == 1
    assert result.records[0]["organization"] == "Acme Corp"


@pytest.mark.asyncio
async def test_find_person_org_historical(
    query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient
):
    """Test time-travel query for person's organization."""
    as_of_date = datetime(2025, 6, 15, 12, 0, 0)
    historical_records = [
        {
            "person": "Sarah Johnson",
            "organization": "OldCorp",
            "title": "Engineer",
            "started": 1700000000.0,
            "ended": 1710000000.0,
        }
    ]
    mock_neo4j_client.execute_query.return_value = historical_records

    result = await query_builder.find_person_org_at_date("person-001", as_of_date)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_PERSON_ORGANIZATION_HISTORICAL
    assert call_args[0][1]["person_uuid"] == "person-001"
    assert call_args[0][1]["as_of_timestamp"] == as_of_date.timestamp()

    assert result.query_type == "person_org_historical"
    assert result.records[0]["organization"] == "OldCorp"


@pytest.mark.asyncio
async def test_find_person_manager(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding person's manager."""
    manager_records = [
        {
            "person": "Sarah Johnson",
            "manager": "John Doe",
            "manager_email": "john.doe@example.com",
            "manager_uuid": "person-mgr-001",
        }
    ]
    mock_neo4j_client.execute_query.return_value = manager_records

    result = await query_builder.find_person_manager("person-001")

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_PERSON_MANAGER
    assert call_args[0][1] == {"person_uuid": "person-001"}

    assert result.query_type == "person_manager"
    assert result.records[0]["manager"] == "John Doe"


@pytest.mark.asyncio
async def test_find_people_at_org(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding all people at an organization."""
    people_records = [
        {
            "uuid": "person-001",
            "name": "Alice",
            "email": "alice@example.com",
            "title": "Engineer",
            "department": "R&D",
        },
        {
            "uuid": "person-002",
            "name": "Bob",
            "email": "bob@example.com",
            "title": "Manager",
            "department": "Operations",
        },
    ]
    mock_neo4j_client.execute_query.return_value = people_records

    result = await query_builder.find_people_at_org("org-001", limit=50)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_PEOPLE_AT_ORG
    assert call_args[0][1] == {"org_uuid": "org-001", "limit": 50}

    assert result.query_type == "org_people"
    assert result.record_count == 2


@pytest.mark.asyncio
async def test_find_person_projects(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding projects associated with a person."""
    project_records = [
        {
            "uuid": "proj-001",
            "name": "Q1 Budget",
            "status": "active",
            "deadline": 1710000000.0,
        }
    ]
    mock_neo4j_client.execute_query.return_value = project_records

    result = await query_builder.find_person_projects("person-001", limit=10)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_PERSON_PROJECTS
    assert call_args[0][1] == {"person_uuid": "person-001", "limit": 10}

    assert result.query_type == "person_projects"
    assert result.records[0]["name"] == "Q1 Budget"


# ===========================================================================
# QueryBuilder Task Query Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_find_blocked_tasks(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding tasks that block other tasks."""
    blocked_records = [
        {
            "blocker_task": "Get approval from legal",
            "blocker_uuid": "task-blocker-001",
            "blocker_status": "in_progress",
            "blocked_task": "Launch new feature",
            "blocked_uuid": "task-blocked-001",
            "blocked_status": "todo",
            "reason": "Legal review required",
        }
    ]
    mock_neo4j_client.execute_query.return_value = blocked_records

    result = await query_builder.find_blocked_tasks()

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_BLOCKED_TASKS
    assert call_args[0][1] == {"limit": 100}

    assert result.query_type == "blocked_tasks"
    assert result.records[0]["blocker_task"] == "Get approval from legal"


@pytest.mark.asyncio
async def test_find_project_tasks(
    query_builder: QueryBuilder,
    mock_neo4j_client: Neo4jClient,
    sample_task_records: list[dict[str, Any]],
):
    """Test finding all tasks for a project."""
    mock_neo4j_client.execute_query.return_value = sample_task_records

    result = await query_builder.find_project_tasks("proj-001", limit=100)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_PROJECT_TASKS
    assert call_args[0][1] == {"project_uuid": "proj-001", "limit": 100}

    assert result.query_type == "project_tasks"
    assert result.record_count == 2


@pytest.mark.asyncio
async def test_find_tasks_by_status(
    query_builder: QueryBuilder,
    mock_neo4j_client: Neo4jClient,
    sample_task_records: list[dict[str, Any]],
):
    """Test finding tasks with a specific status."""
    mock_neo4j_client.execute_query.return_value = sample_task_records

    result = await query_builder.find_tasks_by_status("todo", limit=50)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_TASKS_BY_STATUS
    assert call_args[0][1] == {"status": "todo", "limit": 50}

    assert result.query_type == "tasks_by_status"
    assert all(r["status"] == "todo" for r in result.records)


@pytest.mark.asyncio
async def test_find_task_dependency_chain(
    query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient
):
    """Test finding chain of blocking tasks."""
    chain_records = [
        {
            "chain": [
                {"uuid": "task-1", "action": "Get approval", "status": "in_progress"},
                {"uuid": "task-2", "action": "Complete docs", "status": "todo"},
                {"uuid": "task-3", "action": "Deploy", "status": "todo"},
            ],
            "chain_length": 2,
        }
    ]
    mock_neo4j_client.execute_query.return_value = chain_records

    result = await query_builder.find_task_dependency_chain("task-3")

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_TASK_DEPENDENCY_CHAIN
    assert call_args[0][1] == {"task_uuid": "task-3"}

    assert result.query_type == "task_dependencies"
    assert result.records[0]["chain_length"] == 2


@pytest.mark.asyncio
async def test_find_task_assignee(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding person assigned to a task."""
    assignee_records = [
        {
            "person_uuid": "person-001",
            "name": "Sarah Johnson",
            "email": "sarah@example.com",
        }
    ]
    mock_neo4j_client.execute_query.return_value = assignee_records

    result = await query_builder.find_task_assignee("task-001")

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_TASK_ASSIGNEE
    assert call_args[0][1] == {"task_uuid": "task-001"}

    assert result.query_type == "task_assignee"
    assert result.records[0]["name"] == "Sarah Johnson"


# ===========================================================================
# QueryBuilder Event Query Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_find_events_in_range(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding events in a time range."""
    start = datetime(2026, 1, 15, 9, 0, 0)
    end = datetime(2026, 1, 15, 17, 0, 0)

    event_records = [
        {
            "uuid": "event-001",
            "title": "Team standup",
            "start_time": start.timestamp(),
            "end_time": (start + timedelta(minutes=30)).timestamp(),
            "location": "Conference Room A",
            "description": "Daily sync",
        }
    ]
    mock_neo4j_client.execute_query.return_value = event_records

    result = await query_builder.find_events_in_range(start, end, limit=100)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_EVENTS_IN_RANGE
    assert call_args[0][1]["start_timestamp"] == start.timestamp()
    assert call_args[0][1]["end_timestamp"] == end.timestamp()

    assert result.query_type == "events_in_range"
    assert result.records[0]["title"] == "Team standup"


@pytest.mark.asyncio
async def test_find_event_attendees(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding attendees for an event."""
    attendee_records = [
        {
            "person_uuid": "person-001",
            "name": "Sarah Johnson",
            "email": "sarah@example.com",
            "role": "organizer",
        },
        {
            "person_uuid": "person-002",
            "name": "John Smith",
            "email": "john@example.com",
            "role": "attendee",
        },
    ]
    mock_neo4j_client.execute_query.return_value = attendee_records

    result = await query_builder.find_event_attendees("event-001")

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_EVENT_ATTENDEES
    assert call_args[0][1] == {"event_uuid": "event-001"}

    assert result.query_type == "event_attendees"
    assert result.record_count == 2
    assert result.records[0]["role"] == "organizer"


@pytest.mark.asyncio
async def test_find_events_at_location(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding events at a specific location."""
    event_records = [
        {
            "uuid": "event-001",
            "title": "All Hands Meeting",
            "start_time": 1705320000.0,
            "end_time": 1705323600.0,
            "location": "Main Office",
        }
    ]
    mock_neo4j_client.execute_query.return_value = event_records

    result = await query_builder.find_events_at_location(
        "location-001", start_timestamp=1705000000.0, limit=50
    )

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_EVENTS_AT_LOCATION
    assert call_args[0][1]["location_uuid"] == "location-001"

    assert result.query_type == "events_at_location"


@pytest.mark.asyncio
async def test_find_event_discussions(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding topics discussed in an event."""
    discussion_records = [
        {"item_type": "Project", "uuid": "proj-001", "item_name": "Q1 Budget"},
        {"item_type": "Task", "uuid": "task-001", "item_name": "Review expenses"},
    ]
    mock_neo4j_client.execute_query.return_value = discussion_records

    result = await query_builder.find_event_discussions("event-001")

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_EVENT_DISCUSSIONS
    assert call_args[0][1] == {"event_uuid": "event-001"}

    assert result.query_type == "event_discussions"
    assert result.record_count == 2


# ===========================================================================
# QueryBuilder Temporal Query Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_find_entities_created_in_range(
    query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient
):
    """Test finding entities created in a time range."""
    start = datetime(2026, 1, 1, 0, 0, 0)
    end = datetime(2026, 1, 31, 23, 59, 59)

    entity_records = [
        {
            "type": "Person",
            "uuid": "person-001",
            "name": "New Contact",
            "created_at": start.timestamp() + 1000,
        },
        {
            "type": "Project",
            "uuid": "proj-001",
            "name": "New Project",
            "created_at": start.timestamp() + 2000,
        },
    ]
    mock_neo4j_client.execute_query.return_value = entity_records

    result = await query_builder.find_entities_created_in_range(start, end, limit=100)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_ENTITIES_CREATED_IN_RANGE
    assert call_args[0][1]["start_timestamp"] == start.timestamp()
    assert call_args[0][1]["end_timestamp"] == end.timestamp()

    assert result.query_type == "entities_created"
    assert result.record_count == 2


@pytest.mark.asyncio
async def test_time_travel_query(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test time-travel query for historical graph state."""
    as_of = datetime(2025, 12, 1, 0, 0, 0)

    relationship_records = [
        {
            "source_type": "Person",
            "source_name": "Sarah Johnson",
            "source_uuid": "person-001",
            "relationship": "WORKS_AT",
            "target_type": "Organization",
            "target_name": "OldCorp",
            "target_uuid": "org-001",
            "valid_from": 1700000000.0,
            "valid_until": 1710000000.0,
        }
    ]
    mock_neo4j_client.execute_query.return_value = relationship_records

    result = await query_builder.time_travel_query(as_of, limit=50)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.TIME_TRAVEL_RELATIONSHIPS
    assert call_args[0][1]["as_of_timestamp"] == as_of.timestamp()

    assert result.query_type == "time_travel"
    assert result.records[0]["target_name"] == "OldCorp"


@pytest.mark.asyncio
async def test_find_expired_relationships(
    query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient
):
    """Test finding relationships that expired in a time range."""
    start = datetime(2026, 1, 1, 0, 0, 0)
    end = datetime(2026, 1, 31, 23, 59, 59)

    expired_records = [
        {
            "source_type": "Person",
            "source_name": "Sarah Johnson",
            "relationship": "WORKS_AT",
            "target_type": "Organization",
            "target_name": "OldCorp",
            "created_at": 1700000000.0,
            "expired_at": start.timestamp() + 1000,
        }
    ]
    mock_neo4j_client.execute_query.return_value = expired_records

    result = await query_builder.find_expired_relationships(start, end, limit=50)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_EXPIRED_RELATIONSHIPS
    assert call_args[0][1]["start_timestamp"] == start.timestamp()
    assert call_args[0][1]["end_timestamp"] == end.timestamp()

    assert result.query_type == "expired_relationships"


# ===========================================================================
# QueryBuilder Thread Query Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_find_recent_threads(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding recent threads for a channel."""
    thread_records = [
        {
            "uuid": "thread-001",
            "external_id": "cli-session-001",
            "status": "active",
            "last_activity": 1705320000.0,
            "created_at": 1705300000.0,
        }
    ]
    mock_neo4j_client.execute_query.return_value = thread_records

    result = await query_builder.find_recent_threads("cli", limit=20)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_RECENT_THREADS
    assert call_args[0][1] == {"channel_type": "cli", "limit": 20}

    assert result.query_type == "recent_threads"
    assert result.records[0]["status"] == "active"


@pytest.mark.asyncio
async def test_find_thread_messages(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test getting messages from a thread."""
    message_records = [
        {
            "uuid": "msg-001",
            "role": "assistant",
            "content": "How can I help?",
            "timestamp": 1705320100.0,
            "metadata": None,
        },
        {
            "uuid": "msg-002",
            "role": "user",
            "content": "Show me my tasks",
            "timestamp": 1705320000.0,
            "metadata": None,
        },
    ]
    mock_neo4j_client.execute_query.return_value = message_records

    result = await query_builder.find_thread_messages("thread-001", limit=20)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_THREAD_MESSAGES
    assert call_args[0][1] == {"thread_uuid": "thread-001", "limit": 20}

    assert result.query_type == "thread_messages"
    assert result.record_count == 2


@pytest.mark.asyncio
async def test_find_thread_summary(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding summary note for a thread."""
    summary_records = [
        {
            "uuid": "note-001",
            "title": "Thread Summary",
            "summary": "Discussed tasks and project status",
            "created_at": 1705320000.0,
        }
    ]
    mock_neo4j_client.execute_query.return_value = summary_records

    result = await query_builder.find_thread_summary("thread-001")

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_THREAD_SUMMARY
    assert call_args[0][1] == {"thread_uuid": "thread-001"}

    assert result.query_type == "thread_summary"
    assert result.records[0]["title"] == "Thread Summary"


@pytest.mark.asyncio
async def test_count_thread_messages(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test counting messages in a thread."""
    count_records = [{"message_count": 42}]
    mock_neo4j_client.execute_query.return_value = count_records

    result = await query_builder.count_thread_messages("thread-001")

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.COUNT_THREAD_MESSAGES
    assert call_args[0][1] == {"thread_uuid": "thread-001"}

    assert result.query_type == "thread_message_count"
    assert result.records[0]["message_count"] == 42


# ===========================================================================
# QueryBuilder Graph Traversal Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_find_related_entities(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding entities related to a node."""
    related_records = [
        {"type": "Person", "uuid": "person-001", "name": "Sarah Johnson"},
        {"type": "Project", "uuid": "proj-001", "name": "Q1 Budget"},
    ]
    mock_neo4j_client.execute_query.return_value = related_records

    result = await query_builder.find_related_entities("org-001", limit=20)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_RELATED_ENTITIES
    assert call_args[0][1] == {"entity_uuid": "org-001", "limit": 20}

    assert result.query_type == "related_entities"
    assert result.record_count == 2


@pytest.mark.asyncio
async def test_find_shortest_path(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test finding shortest path between two entities."""
    path_records = [
        {
            "path_nodes": [
                {"type": "Person", "uuid": "person-001", "name": "Sarah"},
                {"type": "Organization", "uuid": "org-001", "name": "Acme Corp"},
                {"type": "Project", "uuid": "proj-001", "name": "Q1 Budget"},
            ],
            "path_relationships": ["WORKS_AT", "CONTRIBUTES_TO"],
            "path_length": 2,
        }
    ]
    mock_neo4j_client.execute_query.return_value = path_records

    result = await query_builder.find_shortest_path("person-001", "proj-001")

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[0][0] == CypherQueries.FIND_SHORTEST_PATH
    assert call_args[0][1] == {"from_uuid": "person-001", "to_uuid": "proj-001"}

    assert result.query_type == "shortest_path"
    assert result.records[0]["path_length"] == 2


# ===========================================================================
# Error Handling and Edge Cases
# ===========================================================================


@pytest.mark.asyncio
async def test_query_with_empty_results(
    query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient
):
    """Test queries that return no results."""
    mock_neo4j_client.execute_query.return_value = []

    result = await query_builder.find_person("nonexistent", limit=5)

    assert result.record_count == 0
    assert result.records == []


@pytest.mark.asyncio
async def test_query_with_trace_id(query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient):
    """Test that trace_id is passed through to Neo4j client."""
    mock_neo4j_client.execute_query.return_value = []
    trace_id = "test-trace-123"

    await query_builder.find_person("sarah", limit=5, trace_id=trace_id)

    call_args = mock_neo4j_client.execute_query.call_args
    assert call_args[1]["trace_id"] == trace_id


@pytest.mark.asyncio
async def test_query_builder_timing_metadata(
    query_builder: QueryBuilder, mock_neo4j_client: Neo4jClient
):
    """Test that QueryResult includes timing metadata."""
    mock_neo4j_client.execute_query.return_value = [{"name": "Test"}]

    result = await query_builder.find_person("test", limit=5)

    assert result.execution_time_ms > 0
    assert result.execution_time_ms < 10000  # Should be under 10 seconds
    assert isinstance(result.execution_time_ms, float)


# ===========================================================================
# Parameter Injection Safety Tests
# ===========================================================================


def test_queries_reject_sql_injection_attempts():
    """Verify parameter binding prevents injection attacks."""
    # This is a compile-time test - if queries use f-strings, they fail
    queries = CypherQueries()

    # Simulate injection attempt
    malicious_name = "'; DROP DATABASE neo4j; --"

    # The query uses $name parameter, so this should be treated as literal string
    query = queries.FIND_PERSON_BY_NAME
    assert "$name" in query
    assert malicious_name not in query  # Query string doesn't contain injected code


def test_all_queries_in_cypherqueries_class():
    """Verify all expected query categories are present."""
    queries = CypherQueries()

    # Check for query categories
    assert hasattr(queries, "FIND_PERSON_BY_NAME")
    assert hasattr(queries, "FIND_BLOCKED_TASKS")
    assert hasattr(queries, "FIND_EVENTS_IN_RANGE")
    assert hasattr(queries, "TIME_TRAVEL_RELATIONSHIPS")
    assert hasattr(queries, "FIND_RECENT_THREADS")


def test_query_builder_has_all_methods():
    """Verify QueryBuilder has methods for all query types."""
    builder = QueryBuilder(MagicMock())

    # Person queries
    assert hasattr(builder, "find_person")
    assert hasattr(builder, "find_person_org")
    assert hasattr(builder, "find_person_manager")

    # Task queries
    assert hasattr(builder, "find_blocked_tasks")
    assert hasattr(builder, "find_project_tasks")
    assert hasattr(builder, "find_tasks_by_status")

    # Event queries
    assert hasattr(builder, "find_events_in_range")
    assert hasattr(builder, "find_event_attendees")

    # Temporal queries
    assert hasattr(builder, "time_travel_query")
    assert hasattr(builder, "find_entities_created_in_range")

    # Thread queries
    assert hasattr(builder, "find_recent_threads")
    assert hasattr(builder, "find_thread_messages")

    # Graph traversal
    assert hasattr(builder, "find_related_entities")
    assert hasattr(builder, "find_shortest_path")
