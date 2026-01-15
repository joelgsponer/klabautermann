# End-to-End Integration Test

## Metadata
- **ID**: T019
- **Priority**: P1
- **Category**: maintenance
- **Effort**: M
- **Status**: pending
- **Assignee**: @qa-engineer

## Specs
- Primary: [TESTING.md](../../specs/quality/TESTING.md)
- Related: [PRD.md](../../specs/PRD.md) Section 10.2

## Dependencies
- [ ] T018 - Main application entry point

## Context
The E2E test validates that Sprint 1 achieves its goal: a working foundation where "I met Sarah from Acme" creates nodes in the graph. This is the first of the Golden Scenarios from the testing spec.

## Requirements
- [ ] Create `tests/e2e/test_sprint1_foundation.py` with:

### Golden Scenario 1: New Contact
- [ ] Test input: "I met Sarah Chen (sarah@acme.com). She's a PM at Acme Corp."
- [ ] Verify Person node created for "Sarah Chen"
- [ ] Verify Organization node created for "Acme Corp"
- [ ] Verify WORKS_AT relationship with title "PM"
- [ ] Verify email property on Person node

### Context Persistence Test
- [ ] Add message about Sarah
- [ ] Add follow-up message
- [ ] Verify context window includes both messages
- [ ] Verify thread has correct message count

### Response Generation Test
- [ ] Send message to orchestrator
- [ ] Verify response is non-empty
- [ ] Verify response time under 5 seconds

### Test Infrastructure
- [ ] Use test database (separate from production)
- [ ] Clean up test data after each test
- [ ] Proper fixtures for component initialization

## Acceptance Criteria
- [ ] `pytest tests/e2e/test_sprint1_foundation.py -v` passes
- [ ] Test runs against Docker containers
- [ ] Test data cleaned up after completion
- [ ] Clear error messages on failure

## Implementation Notes

```python
"""
Sprint 1 End-to-End Tests

These tests validate the Golden Scenario for Sprint 1:
"I met Sarah from Acme" creates appropriate graph nodes.
"""
import asyncio
import os
import pytest
import uuid

from klabautermann.memory.neo4j_client import Neo4jClient
from klabautermann.memory.graphiti_client import GraphitiClient
from klabautermann.memory.thread_manager import ThreadManager
from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.ontology import NodeLabel, RelationType


@pytest.fixture(scope="module")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def neo4j_client():
    """Initialize Neo4j client for tests."""
    client = Neo4jClient(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        username=os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "test-password"),
        database="neo4j",  # Use test database
    )
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture(scope="module")
async def graphiti_client(neo4j_client):
    """Initialize Graphiti client for tests."""
    client = GraphitiClient(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USERNAME", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "test-password"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
    )
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
async def test_thread_id():
    """Generate unique thread ID for test isolation."""
    return f"test-{uuid.uuid4()}"


@pytest.fixture
async def cleanup_test_data(neo4j_client, test_thread_id):
    """Clean up test data after each test."""
    yield
    # Cleanup: remove test thread and messages
    await neo4j_client.execute_query(
        """
        MATCH (t:Thread {external_id: $thread_id})
        OPTIONAL MATCH (t)-[:CONTAINS]->(m:Message)
        DETACH DELETE t, m
        """,
        {"thread_id": test_thread_id},
    )


class TestSprint1Foundation:
    """End-to-end tests for Sprint 1 foundation."""

    @pytest.mark.asyncio
    async def test_golden_scenario_new_contact(
        self,
        neo4j_client,
        graphiti_client,
        test_thread_id,
        cleanup_test_data,
    ):
        """
        Golden Scenario 1: New Contact

        Input: "I met Sarah Chen (sarah@acme.com). She's a PM at Acme Corp."
        Expected: Person + Organization + WORKS_AT relationship
        """
        # Arrange
        thread_manager = ThreadManager(neo4j_client)
        orchestrator = Orchestrator(
            graphiti=graphiti_client,
            thread_manager=thread_manager,
        )

        test_input = "I met Sarah Chen (sarah@acme.com). She's a PM at Acme Corp."

        # Act
        response = await orchestrator.handle_user_input(
            thread_id=test_thread_id,
            text=test_input,
            trace_id="test-golden-1",
        )

        # Allow time for background ingestion
        await asyncio.sleep(3)

        # Assert - response generated
        assert response is not None
        assert len(response) > 0

        # Assert - Person node created
        person_result = await neo4j_client.execute_query(
            "MATCH (p:Person {name: 'Sarah Chen'}) RETURN p",
        )
        assert len(person_result) > 0, "Person node not created"

        person = person_result[0]["p"]
        assert person.get("email") == "sarah@acme.com"

        # Assert - Organization node created
        org_result = await neo4j_client.execute_query(
            "MATCH (o:Organization {name: 'Acme Corp'}) RETURN o",
        )
        assert len(org_result) > 0, "Organization node not created"

        # Assert - WORKS_AT relationship exists
        rel_result = await neo4j_client.execute_query(
            """
            MATCH (p:Person {name: 'Sarah Chen'})-[r:WORKS_AT]->(o:Organization {name: 'Acme Corp'})
            RETURN r
            """,
        )
        assert len(rel_result) > 0, "WORKS_AT relationship not created"

    @pytest.mark.asyncio
    async def test_context_persistence(
        self,
        neo4j_client,
        test_thread_id,
        cleanup_test_data,
    ):
        """Test that messages persist and context window works."""
        # Arrange
        thread_manager = ThreadManager(neo4j_client)

        # Act - create thread and add messages
        thread = await thread_manager.get_or_create_thread(
            external_id=test_thread_id,
            channel_type="test",
        )

        await thread_manager.add_message(
            thread_uuid=thread.uuid,
            role="user",
            content="First message",
        )

        await thread_manager.add_message(
            thread_uuid=thread.uuid,
            role="assistant",
            content="First response",
        )

        await thread_manager.add_message(
            thread_uuid=thread.uuid,
            role="user",
            content="Second message",
        )

        # Assert - context window returns messages in order
        context = await thread_manager.get_context_window(
            thread_uuid=thread.uuid,
            limit=10,
        )

        assert context.message_count == 3
        assert context.messages[0]["content"] == "First message"
        assert context.messages[1]["content"] == "First response"
        assert context.messages[2]["content"] == "Second message"

    @pytest.mark.asyncio
    async def test_response_time(
        self,
        neo4j_client,
        graphiti_client,
        test_thread_id,
    ):
        """Test that response time is under 5 seconds."""
        import time

        thread_manager = ThreadManager(neo4j_client)
        orchestrator = Orchestrator(
            graphiti=graphiti_client,
            thread_manager=thread_manager,
        )

        start = time.time()
        response = await orchestrator.handle_user_input(
            thread_id=test_thread_id,
            text="Hello, how are you?",
        )
        elapsed = time.time() - start

        assert elapsed < 5.0, f"Response took {elapsed:.2f}s, expected <5s"
        assert response is not None
```

**Test Database**: Consider using a separate Neo4j database for tests to avoid polluting production data. This can be configured via environment variables.

**CI Integration**: These tests should run in the GitHub Actions pipeline created in Sprint 4.
