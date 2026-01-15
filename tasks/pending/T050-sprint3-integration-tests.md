# Sprint 3 Integration Tests

## Metadata
- **ID**: T050
- **Priority**: P1
- **Category**: maintenance
- **Effort**: L
- **Status**: pending
- **Assignee**: inspector

## Specs
- Primary: [TESTING.md](../../specs/quality/TESTING.md)
- Related: [ROADMAP.md](../../specs/ROADMAP.md) Sprint 3 Verification Criteria

## Dependencies
- [x] T040 - Archivist Agent Skeleton
- [x] T046 - Scribe Agent Implementation
- [x] T041 - Note Node Creation
- [x] T042 - Day Node Management
- [x] T047 - APScheduler Integration

## Context
Sprint 3 introduces the memory lifecycle: archival, summarization, and daily reflection. Integration tests verify these components work together end-to-end. The tests follow Golden Scenario patterns established in TESTING.md.

## Requirements
- [ ] Create `tests/integration/test_memory_lifecycle.py`:

### Test: Thread Archival Flow
- [ ] Create active thread with messages
- [ ] Wait for cooldown (mock time)
- [ ] Trigger archival
- [ ] Verify:
  - Thread status = 'archived'
  - Note node created with summary
  - Note linked to Thread via [:SUMMARY_OF]
  - Messages pruned
  - Topics extracted

### Test: Day Node Integration
- [ ] Create entities with timestamps
- [ ] Verify Day nodes created
- [ ] Verify [:OCCURRED_ON] relationships
- [ ] Query day contents
- [ ] Verify temporal spine integrity

### Test: Scribe Daily Reflection
- [ ] Create day's worth of activity
- [ ] Trigger Scribe reflection
- [ ] Verify:
  - JournalEntry node created
  - Linked to correct Day
  - Contains analytics data
  - No duplicate journals

### Test: Time-Travel Query
- [ ] Create Person with employer
- [ ] Change employer (expire old, create new)
- [ ] Query current employer
- [ ] Query historical employer
- [ ] Verify temporal accuracy

### Test: Conflict Detection
- [ ] Create Person with employer
- [ ] Create thread mentioning new employer
- [ ] Archive thread
- [ ] Verify conflict detected
- [ ] Verify old relationship expired

### Test: Scheduler Integration
- [ ] Start scheduler with mock jobs
- [ ] Verify jobs registered
- [ ] Trigger jobs manually
- [ ] Verify execution logged

## Acceptance Criteria
- [ ] All integration tests pass
- [ ] Tests use isolated test database
- [ ] Tests clean up after themselves
- [ ] Tests can run in CI environment
- [ ] Test coverage for all Sprint 3 success criteria
- [ ] Tests documented with clear assertions

## Implementation Notes

```python
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

@pytest.fixture
async def test_graph(neo4j_driver):
    """Create test graph with sample data."""
    async with neo4j_driver.session() as session:
        # Create test thread with messages
        await session.run("""
            CREATE (t:Thread {
                uuid: 'test-thread-001',
                external_id: 'test-ext-001',
                channel_type: 'cli',
                status: 'active',
                created_at: $created_at,
                last_message_at: $last_message_at
            })
            CREATE (m1:Message {
                uuid: 'msg-001',
                role: 'user',
                content: 'I met Sarah from Acme today',
                timestamp: $msg_timestamp
            })
            CREATE (m2:Message {
                uuid: 'msg-002',
                role: 'assistant',
                content: 'Nice! What does Sarah do at Acme?',
                timestamp: $msg_timestamp + 1
            })
            CREATE (t)-[:CONTAINS]->(m1)
            CREATE (t)-[:CONTAINS]->(m2)
            CREATE (m1)-[:PRECEDES]->(m2)
        """, {
            "created_at": datetime.now(timezone.utc).timestamp(),
            "last_message_at": (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp(),
            "msg_timestamp": (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
        })

    yield

    # Cleanup
    async with neo4j_driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_thread_archival_flow(test_graph, archivist, thread_manager):
    """Test complete thread archival flow."""
    # Get inactive threads
    inactive = await thread_manager.get_inactive_threads(cooldown_minutes=60)
    assert 'test-thread-001' in inactive

    # Archive the thread
    note_uuid = await archivist.archive_thread('test-thread-001')
    assert note_uuid is not None

    # Verify thread status
    async with archivist.driver.session() as session:
        result = await session.run(
            "MATCH (t:Thread {uuid: 'test-thread-001'}) RETURN t.status"
        )
        record = await result.single()
        assert record["t.status"] == "archived"

    # Verify Note created
    async with archivist.driver.session() as session:
        result = await session.run("""
            MATCH (n:Note)-[:SUMMARY_OF]->(t:Thread {uuid: 'test-thread-001'})
            RETURN n.uuid, n.topics, n.content_summarized
        """)
        record = await result.single()
        assert record is not None
        assert record["n.uuid"] == note_uuid

    # Verify messages pruned
    async with archivist.driver.session() as session:
        result = await session.run("""
            MATCH (t:Thread {uuid: 'test-thread-001'})-[:CONTAINS]->(m:Message)
            RETURN count(m) as count
        """)
        record = await result.single()
        assert record["count"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scribe_daily_reflection(test_graph, scribe):
    """Test Scribe generates daily reflection."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    # Generate reflection
    journal_uuid = await scribe.generate_daily_reflection(date=yesterday)

    # Verify JournalEntry created
    async with scribe.driver.session() as session:
        result = await session.run("""
            MATCH (j:JournalEntry)-[:OCCURRED_ON]->(d:Day {date: $date})
            RETURN j.uuid, j.content, j.mood
        """, {"date": yesterday})
        record = await result.single()
        assert record is not None
        assert record["j.content"] is not None

    # Verify idempotency - second call should skip
    duplicate_uuid = await scribe.generate_daily_reflection(date=yesterday)
    assert duplicate_uuid is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_time_travel_query(neo4j_driver):
    """Test temporal queries return historical state."""
    async with neo4j_driver.session() as session:
        # Create person with initial employer
        await session.run("""
            CREATE (p:Person {uuid: 'sarah-001', name: 'Sarah'})
            CREATE (o1:Organization {uuid: 'acme-001', name: 'Acme Corp'})
            CREATE (o2:Organization {uuid: 'newco-001', name: 'NewCo'})
            CREATE (p)-[:WORKS_AT {
                title: 'Engineer',
                created_at: $old_time,
                expired_at: $switch_time
            }]->(o1)
            CREATE (p)-[:WORKS_AT {
                title: 'Senior Engineer',
                created_at: $switch_time,
                expired_at: null
            }]->(o2)
        """, {
            "old_time": (datetime.now(timezone.utc) - timedelta(days=60)).timestamp(),
            "switch_time": (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
        })

        # Query current employer
        current = await session.run("""
            MATCH (p:Person {name: 'Sarah'})-[r:WORKS_AT]->(o:Organization)
            WHERE r.expired_at IS NULL
            RETURN o.name
        """)
        record = await current.single()
        assert record["o.name"] == "NewCo"

        # Query historical employer (30 days ago)
        historical_time = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
        historical = await session.run("""
            MATCH (p:Person {name: 'Sarah'})-[r:WORKS_AT]->(o:Organization)
            WHERE r.created_at <= $as_of
              AND (r.expired_at IS NULL OR r.expired_at > $as_of)
            RETURN o.name
        """, {"as_of": historical_time})
        record = await historical.single()
        assert record["o.name"] == "Acme Corp"
```

### Test Fixtures
- Use pytest-asyncio for async tests
- Use test Neo4j container or in-memory mode
- Mock LLM calls for deterministic results
- Clean up test data after each test

### CI Integration
```yaml
# .github/workflows/ci.yml addition
- name: Run integration tests
  run: |
    docker-compose -f docker-compose.test.yml up -d neo4j
    pytest tests/integration/ -v --tb=short
    docker-compose -f docker-compose.test.yml down
```
