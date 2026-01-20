# Testing Guide

This document describes the testing approach for Klabautermann.

## Testing Philosophy

**Tests define what code SHOULD do according to specs. If tests fail, fix the CODE, not the tests.**

We follow the testing pyramid approach:
- Many fast unit tests (base)
- Fewer integration tests (middle)
- Few E2E/golden scenario tests (top)

## Test Directory Structure

```
tests/
├── conftest.py           # Shared fixtures
├── unit/                 # Fast, isolated unit tests
│   ├── test_models.py
│   ├── test_researcher.py
│   ├── test_gmail_handlers.py
│   └── ...
├── integration/          # Tests requiring services
│   ├── test_neo4j_contract.py
│   └── test_graphiti_contract.py
└── e2e/                  # Full system tests
    └── test_golden_scenarios.py
```

## Unit Tests

Unit tests are fast, isolated, and mock external dependencies.

### When to Write Unit Tests

- Testing Pydantic models and validation
- Testing pure functions and utility methods
- Testing business logic with mocked dependencies
- Testing error handling and edge cases

### Naming Conventions

```python
# File: test_<module_name>.py
# Class: Test<ClassName>
# Method: test_<what>_<condition>_<expected>

def test_format_email_list_empty_returns_message():
    """Test with empty list returns informative message."""
    ...

def test_parse_time_reference_yesterday_returns_range():
    """Test 'yesterday' query returns correct time range."""
    ...
```

### Mocking Patterns

**Mocking Async Functions:**

```python
from unittest.mock import AsyncMock, MagicMock

# Mock async method
mock_client = MagicMock()
mock_client.search = AsyncMock(return_value=[])

# Mock entire class
@pytest.fixture
def mock_graphiti():
    graphiti = MagicMock()
    graphiti.search = AsyncMock(return_value=[])
    graphiti.search_entities = AsyncMock(return_value=[])
    return graphiti
```

**Mocking Anthropic API:**

```python
@pytest.fixture
def mock_anthropic_client():
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text='{"key": "value"}')]
    client.messages.create = AsyncMock(return_value=response)
    return client
```

**Mocking Neo4j:**

```python
@pytest.fixture
def mock_neo4j():
    neo4j = MagicMock()
    neo4j.execute_query = AsyncMock(return_value=[])
    return neo4j
```

### Running Unit Tests

```bash
# Run all unit tests
make test

# Run specific test file
pytest tests/unit/test_researcher.py -v

# Run tests matching pattern
pytest tests/unit/ -k "test_format" -v

# Run with parallel execution
make test-fast
```

## Integration Tests

Integration tests verify components work together with real services.

### When to Write Integration Tests

- Testing Neo4j queries return expected shapes
- Testing Graphiti entity extraction
- Verifying database constraints
- Contract testing between components

### Test Infrastructure

```bash
# Start isolated test Neo4j (port 7688)
make test-docker-up

# Wait for healthy status
docker-compose -f docker-compose.test.yml ps

# Run integration tests
make test-contracts

# Stop test infrastructure
make test-docker-down
```

### Skip Markers

Tests requiring services use skip markers:

```python
from tests.conftest import requires_neo4j, requires_openai

@requires_neo4j
async def test_thread_creation(neo4j_client):
    """Test requires running Neo4j."""
    ...

@requires_openai
async def test_entity_extraction(graphiti_client):
    """Test requires OpenAI API key."""
    ...
```

### Database Fixtures

Use cleanup fixtures to prevent test pollution:

```python
@pytest.fixture
async def cleanup_test_data(neo4j_client):
    """Clean up test data after each test."""
    yield
    await neo4j_client.execute_query(
        "MATCH (n) WHERE n.uuid STARTS WITH 'test-' DETACH DELETE n",
        {}
    )
```

## E2E / Golden Scenario Tests

End-to-end tests verify complete user scenarios.

### Golden Scenarios

Five mandatory E2E tests that must pass before any release:

1. **New Contact**: "I met John (john@example.com), PM at Acme"
   - Creates Person entity
   - Creates Organization entity
   - Creates WORKS_AT relationship

2. **Contextual Retrieval**: "What did I talk about with John?"
   - Finds related threads
   - Summarizes conversations

3. **Blocked Task**: "Can't finish until John sends stats"
   - Creates Task entities
   - Creates BLOCKS relationship

4. **Temporal Time-Travel**: Change employer, ask historical
   - Returns previous employer for historical queries

5. **Multi-Channel Threading**: CLI + Telegram
   - Separate threads per channel
   - No context bleed between channels

### Running Golden Scenarios

```bash
# Requires: Neo4j running + API keys configured
make test-golden
```

### Adding New Scenarios

```python
@pytest.mark.golden
@pytest.mark.e2e
async def test_new_golden_scenario(
    orchestrator,
    thread_manager,
    graphiti_client,
    cleanup_golden_data,
):
    """
    Golden Scenario: Description of what this tests.

    User says: "..."
    Expected: ...
    """
    # 1. Setup
    thread = await thread_manager.get_or_create_thread(
        external_id="golden-scenario-name",
        channel_type="cli",
    )

    # 2. Execute
    response = await orchestrator.process_input(
        "User message here",
        thread_uuid=thread.uuid,
    )

    # 3. Verify
    assert "expected content" in response

    # 4. Verify graph state
    result = await graphiti_client.search("query")
    assert len(result) > 0
```

## Shared Fixtures

Common fixtures are defined in `tests/conftest.py`:

### Thread Fixtures

```python
# Create test threads
thread = thread_factory(channel_type="telegram")

# Create conversations
messages = conversation_factory([
    ("user", "Hello"),
    ("assistant", "Hi!"),
])
```

### Channel Fixtures

```python
# Mock CLI input/output
mock_cli_input.return_value = "User input"
mock_cli_renderer.captured_output  # List of outputs

# Mock Telegram
update = mock_telegram_update
update.message.text = "Hello bot"
```

### Agent Fixtures

```python
# Create mock orchestrator
orchestrator = mock_orchestrator
orchestrator.process_message.return_value = "Response"

# Create agent messages
msg = agent_message_factory(content="Hello")
```

## Coverage

```bash
# Run with coverage report
make test-cov

# View HTML report
open htmlcov/index.html
```

Coverage requirements:
- Minimum: 50% (enforced by CI)
- Target: 80% for core modules

## Continuous Integration

Tests run automatically on every PR via GitHub Actions:

1. **Lint** (ruff)
2. **Type check** (mypy)
3. **Unit tests** (parallel with pytest-xdist)
4. **Coverage** (uploaded to Codecov)

See `.github/workflows/ci.yml` for configuration.

## Quick Reference

| Command | Description |
|---------|-------------|
| `make test` | Run all tests |
| `make test-fast` | Run tests in parallel |
| `make test-cov` | Run with coverage |
| `make test-unit` | Run unit tests only |
| `make test-contracts` | Run integration tests |
| `make test-golden` | Run E2E golden scenarios |
| `make test-docker-up` | Start test Neo4j |
| `make test-docker-down` | Stop test Neo4j |
