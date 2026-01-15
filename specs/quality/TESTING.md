# Klabautermann Testing Protocol

**Version**: 1.0
**Purpose**: Comprehensive testing strategy for the agentic system

---

## Overview

Testing an agentic system requires validating not just "does the code run?" but "is the agent's reasoning grounded in truth?" This protocol covers unit tests, integration tests, agentic behavioral tests, and the critical **Golden Scenarios** that must pass before any release.

---

## 1. Testing Pyramid

```
                      /\
                     /  \
                    / E2E \ (Golden Scenarios - 5 mandatory)
                   /------\
                  /        \
                 /Integration\ (Agent interactions, MCP)
                /------------\
               /              \
              /  Unit Tests    \ (Models, queries, logic)
             /------------------\
```

| Layer | Focus | Tools | Run Frequency |
|-------|-------|-------|---------------|
| Unit | Logic, models, queries | pytest | Every commit |
| Integration | Agent communication, MCP | pytest + containers | Every PR |
| E2E | Full user flows | Manual + automated | Every release |

---

## 2. Unit Tests

### 2.1 What to Test

| Component | Test Focus |
|-----------|------------|
| **Models** | Pydantic validation, serialization |
| **Ontology** | Node/relationship type validation |
| **Queries** | Cypher syntax, parameter handling |
| **Persona** | Lexicon replacement, tidbit selection |
| **Utils** | Retry logic, rate limiting |

### 2.2 Example: Model Validation

```python
# tests/unit/test_models.py
import pytest
from pydantic import ValidationError
from klabautermann.core.models import (
    StandardizedMessage,
    AgentMessage,
    PersonNode
)

class TestStandardizedMessage:
    def test_valid_message(self):
        msg = StandardizedMessage(
            thread_id="abc-123",
            external_id="cli-session",
            user_id="user-1",
            content="Hello",
            timestamp=1234567890.0,
            channel_type="cli"
        )
        assert msg.content == "Hello"
        assert msg.channel_type == "cli"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            StandardizedMessage(
                thread_id="abc-123",
                # Missing external_id
                user_id="user-1",
                content="Hello",
                timestamp=1234567890.0,
                channel_type="cli"
            )

    def test_metadata_default(self):
        msg = StandardizedMessage(
            thread_id="abc-123",
            external_id="cli-session",
            user_id="user-1",
            content="Hello",
            timestamp=1234567890.0,
            channel_type="cli"
        )
        assert msg.metadata == {}

class TestPersonNode:
    def test_valid_person(self):
        person = PersonNode(
            uuid="person-123",
            name="Sarah Chen",
            email="sarah@acme.com",
            created_at=1234567890.0,
            updated_at=1234567890.0
        )
        assert person.name == "Sarah Chen"

    def test_optional_fields(self):
        person = PersonNode(
            uuid="person-123",
            name="John Doe",
            created_at=1234567890.0,
            updated_at=1234567890.0
        )
        assert person.email is None
        assert person.bio is None
```

### 2.3 Example: Query Syntax

```python
# tests/unit/test_queries.py
import pytest
from klabautermann.memory.queries import TemporalQueries

class TestTemporalQueries:
    def test_get_current_employer_syntax(self):
        query, params = TemporalQueries.get_current_employer("person-uuid")

        assert "MATCH" in query
        assert "WORKS_AT" in query
        assert "expired_at IS NULL" in query
        assert params["person_uuid"] == "person-uuid"

    def test_get_employer_at_time_params(self):
        query, params = TemporalQueries.get_employer_at_time("person-uuid", 1234567890.0)

        assert params["person_uuid"] == "person-uuid"
        assert params["as_of"] == 1234567890.0
        assert "created_at <=" in query
        assert "expired_at" in query
```

### 2.4 Example: Persona Logic

```python
# tests/unit/test_persona.py
import pytest
from klabautermann.persona.voice import apply_lexicon
from klabautermann.persona.tidbits import TIDBITS, maybe_add_tidbit

class TestLexicon:
    def test_database_replacement(self):
        text = "Checking the database for your information."
        result = apply_lexicon(text, intensity=1.0)

        # Should replace "database" with "Locker"
        assert "Locker" in result or "database" not in result.lower()

    def test_zero_intensity_no_change(self):
        text = "Searching the database."
        result = apply_lexicon(text, intensity=0.0)

        assert result == text

class TestTidbits:
    def test_tidbits_exist(self):
        assert len(TIDBITS) > 0

    def test_no_pirate_speak(self):
        forbidden = ["arrr", "matey", "avast", "shiver me timbers"]
        for tidbit in TIDBITS:
            for word in forbidden:
                assert word.lower() not in tidbit.lower()

    def test_maybe_add_tidbit_probability(self):
        response = "Test response"

        # Run many times to verify probability
        added_count = 0
        iterations = 1000
        for _ in range(iterations):
            result = maybe_add_tidbit(response, probability=0.1)
            if result != response:
                added_count += 1

        # Should be roughly 10% (allow 5-15%)
        assert 50 < added_count < 150
```

---

## 3. Integration Tests

### 3.1 Test Containers Setup

```python
# tests/conftest.py
import pytest
import asyncio
from testcontainers.neo4j import Neo4jContainer

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="module")
async def neo4j_container():
    """Spin up Neo4j container for integration tests"""
    with Neo4jContainer("neo4j:5.26-community") as container:
        yield {
            "uri": container.get_connection_url(),
            "user": "neo4j",
            "password": "test"
        }

@pytest.fixture
async def graph_client(neo4j_container):
    """Create GraphitiClient connected to test container"""
    from klabautermann.memory.graphiti_client import GraphitiClient

    client = GraphitiClient(
        uri=neo4j_container["uri"],
        user=neo4j_container["user"],
        password=neo4j_container["password"]
    )
    await client.initialize()
    yield client
    await client.close()

@pytest.fixture
async def thread_manager(neo4j_container):
    """Create ThreadManager for tests"""
    from neo4j import AsyncGraphDatabase
    from klabautermann.memory.thread_manager import ThreadManager

    driver = AsyncGraphDatabase.driver(
        neo4j_container["uri"],
        auth=(neo4j_container["user"], neo4j_container["password"])
    )
    yield ThreadManager(driver)
    await driver.close()
```

### 3.2 Agent Communication Tests

```python
# tests/integration/test_agent_communication.py
import pytest
from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.agents.ingestor import Ingestor
from klabautermann.agents.researcher import Researcher

@pytest.mark.integration
@pytest.mark.asyncio
async def test_orchestrator_delegates_to_ingestor(graph_client, mocker):
    """Test that Orchestrator dispatches ingestion requests"""
    config = {"model": "claude-3-haiku-20240307"}

    orchestrator = Orchestrator(config, graph_client, {})
    ingestor = Ingestor(config, graph_client, {})

    # Track ingestor calls
    ingestor_called = False
    original_process = ingestor.process_message

    async def mock_process(msg):
        nonlocal ingestor_called
        ingestor_called = True
        return await original_process(msg)

    ingestor.process_message = mock_process
    orchestrator.sub_agents["ingestor"] = ingestor

    # Trigger ingestion
    await orchestrator.handle_user_input(
        thread_id="test-thread",
        text="I met Sarah from Acme today"
    )

    # Wait for async ingestion
    await asyncio.sleep(2)

    assert ingestor_called, "Orchestrator should have dispatched to Ingestor"

@pytest.mark.integration
@pytest.mark.asyncio
async def test_researcher_finds_ingested_entity(graph_client):
    """Test end-to-end: ingest then search"""
    # Ingest
    await graph_client.ingest_episode(
        name="Test Episode",
        content="Sarah Chen is a PM at Acme Corp. She works on the Q1 budget.",
        source_description="Test"
    )

    # Search
    results = await graph_client.search("Who is Sarah?", limit=5)

    assert len(results) > 0
    assert any("Sarah" in r.fact for r in results)
```

### 3.3 Thread Isolation Tests

```python
# tests/integration/test_thread_isolation.py
import pytest

@pytest.mark.integration
@pytest.mark.asyncio
async def test_threads_are_isolated(thread_manager):
    """Verify CLI and Telegram threads don't share context"""

    # Create CLI thread
    cli_thread = await thread_manager.get_or_create_thread(
        external_id="cli-test",
        channel_type="cli",
        user_id="user-1"
    )

    # Create Telegram thread
    tg_thread = await thread_manager.get_or_create_thread(
        external_id="tg-12345",
        channel_type="telegram",
        user_id="user-1"
    )

    # Verify different UUIDs
    assert cli_thread != tg_thread

    # Add different messages
    await thread_manager.add_message(cli_thread, "user", "Working on Project A")
    await thread_manager.add_message(tg_thread, "user", "Working on Project B")

    # Verify isolation
    cli_context = await thread_manager.get_context(cli_thread)
    tg_context = await thread_manager.get_context(tg_thread)

    assert len(cli_context) == 1
    assert len(tg_context) == 1
    assert "Project A" in cli_context[0]["content"]
    assert "Project B" in tg_context[0]["content"]
```

### 3.4 MCP Integration Tests

```python
# tests/integration/test_mcp.py
import pytest
import os

@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("GOOGLE_REFRESH_TOKEN"), reason="No Google credentials")
@pytest.mark.asyncio
async def test_gmail_search():
    """Test Gmail MCP tool integration"""
    from klabautermann.mcp.client import MCPClient, ToolInvocationContext

    mcp = MCPClient({
        "google_workspace": ["npx", "-y", "@anthropic-ai/mcp-server-google-workspace"]
    })

    context = ToolInvocationContext(
        trace_id="test-123",
        agent_name="test",
        user_intent="search emails"
    )

    result = await mcp.call_tool(
        "google_workspace",
        "gmail_search_messages",
        {"query": "is:unread", "max_results": 5},
        context
    )

    assert result["success"] is True
    await mcp.disconnect_all()
```

---

## 4. Graph Integrity Tests

### 4.1 Orphan Node Detection

```python
# tests/integration/test_graph_integrity.py
import pytest

@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_orphan_nodes(graph_client):
    """Verify all nodes have at least one relationship"""

    async with graph_client.driver.session() as session:
        result = await session.run("""
            MATCH (n)
            WHERE NOT (n)--()
              AND NOT n:Day  // Days can temporarily be orphaned
              AND NOT n:Thread  // New threads start orphaned
            RETURN labels(n)[0] as type, n.uuid as uuid, n.name as name
            LIMIT 10
        """)
        orphans = await result.data()

    assert len(orphans) == 0, f"Found orphan nodes: {orphans}"
```

### 4.2 Temporal Consistency

```python
# tests/integration/test_temporal_integrity.py
import pytest
from datetime import datetime, timezone

@pytest.mark.integration
@pytest.mark.asyncio
async def test_temporal_versioning(graph_client):
    """Verify temporal updates preserve history"""

    # Create initial relationship
    await graph_client.execute("""
        CREATE (p:Person {uuid: 'test-person', name: 'Test User'})
        CREATE (o1:Organization {uuid: 'org-1', name: 'Company A'})
        CREATE (p)-[:WORKS_AT {created_at: $t1, expired_at: null, title: 'Engineer'}]->(o1)
    """, {"t1": datetime(2024, 1, 1).timestamp()})

    # Expire old and create new
    await graph_client.execute("""
        MATCH (p:Person {uuid: 'test-person'})-[r:WORKS_AT]->(o:Organization {name: 'Company A'})
        SET r.expired_at = $t2

        WITH p
        CREATE (o2:Organization {uuid: 'org-2', name: 'Company B'})
        CREATE (p)-[:WORKS_AT {created_at: $t2, expired_at: null, title: 'Senior Engineer'}]->(o2)
    """, {"t2": datetime(2025, 1, 1).timestamp()})

    # Verify both relationships exist
    async with graph_client.driver.session() as session:
        result = await session.run("""
            MATCH (p:Person {uuid: 'test-person'})-[r:WORKS_AT]->(o:Organization)
            RETURN o.name as company, r.expired_at as expired
            ORDER BY r.created_at
        """)
        records = await result.data()

    assert len(records) == 2
    assert records[0]["company"] == "Company A"
    assert records[0]["expired"] is not None  # Should be expired
    assert records[1]["company"] == "Company B"
    assert records[1]["expired"] is None  # Should be current
```

---

## 5. Golden Scenarios (Mandatory E2E)

These five scenarios must pass before any release. They validate the complete system end-to-end.

### 5.1 Scenario 1: New Contact

**Input**: "I just met John Doe (john@example.com). He's a PM at Acme Corp."

**Expected**:
- Person node created: `{name: "John Doe", email: "john@example.com"}`
- Organization node created: `{name: "Acme Corp"}`
- Relationship created: `(John Doe)-[:WORKS_AT {title: "PM"}]->(Acme Corp)`

```python
# tests/e2e/test_golden_scenarios.py
import pytest

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_scenario_1_new_contact(app, graph_client):
    """Golden Scenario 1: New Contact"""

    # Send message
    response = await app.handle_message(
        thread_id="test-thread",
        content="I just met John Doe (john@example.com). He's a PM at Acme Corp."
    )

    # Verify response acknowledges
    assert "John" in response.content

    # Wait for async ingestion
    await asyncio.sleep(3)

    # Verify graph state
    async with graph_client.driver.session() as session:
        # Check Person
        person_result = await session.run("""
            MATCH (p:Person {name: 'John Doe'})
            RETURN p.email as email
        """)
        person = await person_result.single()
        assert person is not None
        assert person["email"] == "john@example.com"

        # Check Organization
        org_result = await session.run("""
            MATCH (o:Organization {name: 'Acme Corp'})
            RETURN o
        """)
        org = await org_result.single()
        assert org is not None

        # Check Relationship
        rel_result = await session.run("""
            MATCH (p:Person {name: 'John Doe'})-[r:WORKS_AT]->(o:Organization {name: 'Acme Corp'})
            WHERE r.expired_at IS NULL
            RETURN r.title as title
        """)
        rel = await rel_result.single()
        assert rel is not None
        assert rel["title"] == "PM"
```

### 5.2 Scenario 2: Contextual Retrieval

**Prerequisite**: Scenario 1 completed
**Input**: "What did I talk about with John yesterday?"

**Expected**: Agent retrieves the thread and summarizes the "PM at Acme" fact.

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_scenario_2_contextual_retrieval(app, graph_client):
    """Golden Scenario 2: Contextual Retrieval"""

    # Prerequisite: Create John
    await app.handle_message(
        thread_id="test-thread",
        content="I met John Doe from Acme Corp yesterday."
    )
    await asyncio.sleep(3)

    # Query about John
    response = await app.handle_message(
        thread_id="test-thread",
        content="What do I know about John?"
    )

    # Should find and return John's info
    assert "John" in response.content
    assert "Acme" in response.content
```

### 5.3 Scenario 3: Blocked Task

**Input**: "I can't finish the Project Alpha report until John sends the stats."

**Expected**: BLOCKS or DEPENDS_ON relationship created between Task and John.

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_scenario_3_blocked_task(app, graph_client):
    """Golden Scenario 3: Blocked Task Logic"""

    # Create blocking relationship
    response = await app.handle_message(
        thread_id="test-thread",
        content="I can't finish the Q1 report until John sends the stats."
    )
    await asyncio.sleep(3)

    # Verify blocking relationship
    async with graph_client.driver.session() as session:
        result = await session.run("""
            MATCH (t:Task)-[r:BLOCKS|DEPENDS_ON]-(other)
            WHERE t.action CONTAINS 'report' OR t.action CONTAINS 'Q1'
            RETURN t.action as task, type(r) as rel_type
        """)
        records = await result.data()

    assert len(records) > 0, "Should create blocking relationship"
```

### 5.4 Scenario 4: Temporal Time-Travel

**Prerequisite**: Create John at Company A, then update to Company B
**Input**: "Who did John work for last week?"

**Expected**: Returns "Company A" (historical state).

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_scenario_4_temporal_time_travel(app, graph_client):
    """Golden Scenario 4: Temporal Time-Travel"""

    # Initial state
    await app.handle_message(
        thread_id="test-thread",
        content="John works at StartupX as CTO."
    )
    await asyncio.sleep(3)

    # Update state
    await app.handle_message(
        thread_id="test-thread",
        content="John left StartupX and joined BigCorp as VP."
    )
    await asyncio.sleep(3)

    # Query historical state
    response = await app.handle_message(
        thread_id="test-thread",
        content="Where did John work before BigCorp?"
    )

    # Should return historical employer
    assert "StartupX" in response.content
```

### 5.5 Scenario 5: Multi-Channel Threading

**Input**: Start conversation on CLI, send message on Telegram
**Expected**: Separate threads, no context bleed.

```python
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_scenario_5_multi_channel_threading(app, thread_manager):
    """Golden Scenario 5: Multi-Channel Threading"""

    # CLI conversation
    cli_response = await app.handle_message(
        thread_id=None,  # Auto-create
        channel_type="cli",
        external_id="cli-session",
        content="I'm working on Project Alpha."
    )
    cli_thread = cli_response.thread_id

    # Telegram conversation
    tg_response = await app.handle_message(
        thread_id=None,  # Auto-create
        channel_type="telegram",
        external_id="tg-12345",
        content="I'm working on Project Beta."
    )
    tg_thread = tg_response.thread_id

    # Verify different threads
    assert cli_thread != tg_thread

    # Query from each channel
    cli_query = await app.handle_message(
        thread_id=cli_thread,
        channel_type="cli",
        content="What project am I working on?"
    )

    tg_query = await app.handle_message(
        thread_id=tg_thread,
        channel_type="telegram",
        content="What project am I working on?"
    )

    # Should return different projects
    assert "Alpha" in cli_query.content
    assert "Beta" in tg_query.content
```

---

## 6. Running Tests

### 6.1 Local Development

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run all unit tests
pytest tests/unit/ -v

# Run with coverage
pytest tests/unit/ --cov=klabautermann --cov-report=html

# Run specific test
pytest tests/unit/test_models.py::TestPersonNode -v
```

### 6.2 Integration Tests

```bash
# Requires Docker
pytest tests/integration/ -v --tb=short

# Run specific integration test
pytest tests/integration/test_agent_communication.py -v
```

### 6.3 Golden Scenarios

```bash
# Run all Golden Scenarios
pytest tests/e2e/test_golden_scenarios.py -v

# These require full system (Neo4j, app running)
docker-compose up -d
pytest tests/e2e/ -v
```

### 6.4 CI Configuration

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      neo4j:
        image: neo4j:5.26-community
        env:
          NEO4J_AUTH: neo4j/testpassword
        ports:
          - 7687:7687

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -e ".[dev]"

      - name: Run linting
        run: ruff check .

      - name: Run type checking
        run: mypy klabautermann/

      - name: Run unit tests
        run: pytest tests/unit/ -v --tb=short

      - name: Run integration tests
        run: pytest tests/integration/ -v --tb=short
        env:
          NEO4J_URI: bolt://localhost:7687
          NEO4J_USER: neo4j
          NEO4J_PASSWORD: testpassword
```

---

## 7. Failure Analysis

### 7.1 Common Failure Patterns

| Symptom | Probable Cause | Fix |
|---------|----------------|-----|
| "I don't know who Sarah is" | Ingestor failed | Check Ingestor logs for extraction errors |
| Wrong agent called | Intent classification failed | Refine Orchestrator prompt |
| Duplicate nodes | Archivist deduplication failed | Check merge_entities logic |
| Slow queries | Missing indexes | Run init_database.py |
| MCP timeout | API rate limit | Implement exponential backoff |

### 7.2 Debug Helpers

```python
# tests/helpers.py

async def dump_graph_state(driver, label: str = None):
    """Print current graph state for debugging"""
    query = f"MATCH (n{':' + label if label else ''}) RETURN labels(n)[0] as type, properties(n) as props LIMIT 50"
    async with driver.session() as session:
        result = await session.run(query)
        for record in await result.data():
            print(f"{record['type']}: {record['props']}")

async def clear_test_data(driver):
    """Clear all test data from graph"""
    async with driver.session() as session:
        await session.run("MATCH (n) WHERE n.uuid STARTS WITH 'test-' DETACH DELETE n")
```

---

*"A ship that isn't tested sinks. A codebase that isn't tested crashes."* - Klabautermann
