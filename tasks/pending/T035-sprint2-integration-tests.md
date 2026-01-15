# Sprint 2 Integration Tests

## Metadata
- **ID**: T035
- **Priority**: P1
- **Category**: maintenance
- **Effort**: M
- **Status**: pending
- **Assignee**: inspector

## Specs
- Primary: [TESTING.md](../../specs/quality/TESTING.md)
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- [ ] T034 - Main.py multi-agent startup
- All Sprint 2 agent tasks

## Context
Sprint 2 introduces the multi-agent architecture. This task creates integration tests that verify agent delegation, entity extraction, hybrid search, and MCP tool invocation work correctly together.

## Requirements
- [ ] Create integration tests in `tests/integration/`:

### Intent Classification Tests
- [ ] Search intents classified correctly
- [ ] Action intents classified correctly
- [ ] Ingestion triggers detected
- [ ] Ambiguous inputs handled

### Agent Delegation Tests
- [ ] Orchestrator delegates search to Researcher
- [ ] Orchestrator delegates action to Executor
- [ ] Orchestrator fires-and-forgets to Ingestor
- [ ] Response routing works correctly

### Entity Extraction Tests
- [ ] Person extraction works
- [ ] Organization extraction works
- [ ] Relationship extraction works
- [ ] Temporal markers detected

### Hybrid Search Tests
- [ ] Vector search returns results
- [ ] Structural search (WORKS_AT) works
- [ ] Temporal search (last week) works
- [ ] Empty results handled gracefully

### MCP Integration Tests (Mocked)
- [ ] Gmail search invocation
- [ ] Gmail send invocation
- [ ] Calendar list invocation
- [ ] Calendar create invocation
- [ ] Error handling for MCP failures

### Config Hot-Reload Tests
- [ ] Config change detected
- [ ] Config reloaded correctly
- [ ] Invalid config doesn't crash
- [ ] Callbacks invoked

## Acceptance Criteria
- [ ] All tests pass with `pytest tests/integration/`
- [ ] Tests use isolated test database
- [ ] MCP tests use mocks (no real API calls)
- [ ] Tests complete in under 60 seconds
- [ ] Coverage report for Sprint 2 code

## Implementation Notes

```python
# tests/integration/test_sprint2_agents.py
"""
Sprint 2 Integration Tests

Tests the multi-agent architecture including delegation,
extraction, search, and MCP integration.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile

from klabautermann.agents.orchestrator import Orchestrator, IntentType
from klabautermann.agents.ingestor import Ingestor, ExtractionResult
from klabautermann.agents.researcher import Researcher, SearchType
from klabautermann.agents.executor import Executor, ActionResult
from klabautermann.core.models import AgentMessage
from klabautermann.config.manager import ConfigManager
from klabautermann.config.quartermaster import Quartermaster


# ====================
# FIXTURES
# ====================

@pytest.fixture
def mock_llm_client():
    """Mock Anthropic client."""
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text='{"entities": [], "relationships": [], "facts": []}')]
    client.messages.create = AsyncMock(return_value=response)
    return client


@pytest.fixture
def mock_graphiti_client():
    """Mock Graphiti client."""
    client = MagicMock()
    client.search = AsyncMock(return_value=[])
    client.add_episode = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_neo4j_client():
    """Mock Neo4j client."""
    client = MagicMock()
    client.execute_query = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_google_bridge():
    """Mock Google Workspace bridge."""
    bridge = MagicMock()
    bridge.search_emails = AsyncMock(return_value=[])
    bridge.send_email = AsyncMock(return_value=MagicMock(success=True, message_id="123"))
    bridge.list_events = AsyncMock(return_value=[])
    bridge.create_event = AsyncMock(return_value=MagicMock(success=True, event_id="456"))
    return bridge


@pytest.fixture
def config_manager(tmp_path):
    """Config manager with temp directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create minimal config
    (config_dir / "orchestrator.yaml").write_text("""
model:
  primary: claude-3-5-sonnet-20241022
  temperature: 0.7
""")

    return ConfigManager(config_dir)


# ====================
# INTENT CLASSIFICATION TESTS
# ====================

class TestIntentClassification:
    """Test intent classification in Orchestrator."""

    @pytest.fixture
    def orchestrator(self, mock_llm_client, mock_graphiti_client, mock_neo4j_client):
        return Orchestrator(
            name="orchestrator",
            config={},
            graphiti_client=mock_graphiti_client,
            neo4j_client=mock_neo4j_client,
            llm_client=mock_llm_client,
        )

    @pytest.mark.asyncio
    async def test_search_intent_who(self, orchestrator):
        """'Who is X' triggers search intent."""
        intent = await orchestrator._classify_intent("Who is Sarah?", [], "test-trace")
        assert intent.type == IntentType.SEARCH

    @pytest.mark.asyncio
    async def test_search_intent_what(self, orchestrator):
        """'What is X' triggers search intent."""
        intent = await orchestrator._classify_intent("What is the Q1 budget?", [], "test-trace")
        assert intent.type == IntentType.SEARCH

    @pytest.mark.asyncio
    async def test_action_intent_send(self, orchestrator):
        """'Send email' triggers action intent."""
        intent = await orchestrator._classify_intent("Send an email to John", [], "test-trace")
        assert intent.type == IntentType.ACTION

    @pytest.mark.asyncio
    async def test_action_intent_schedule(self, orchestrator):
        """'Schedule meeting' triggers action intent."""
        intent = await orchestrator._classify_intent("Schedule a meeting tomorrow", [], "test-trace")
        assert intent.type == IntentType.ACTION

    @pytest.mark.asyncio
    async def test_ingestion_intent_i_met(self, orchestrator):
        """'I met X' triggers ingestion intent."""
        intent = await orchestrator._classify_intent("I met Sarah from Acme", [], "test-trace")
        assert intent.type == IntentType.INGESTION

    @pytest.mark.asyncio
    async def test_conversation_default(self, orchestrator):
        """Generic input defaults to conversation."""
        intent = await orchestrator._classify_intent("Hello, how are you?", [], "test-trace")
        assert intent.type == IntentType.CONVERSATION


# ====================
# AGENT DELEGATION TESTS
# ====================

class TestAgentDelegation:
    """Test agent-to-agent delegation."""

    @pytest.mark.asyncio
    async def test_search_delegates_to_researcher(
        self, mock_llm_client, mock_graphiti_client, mock_neo4j_client
    ):
        """Search intent delegates to Researcher."""
        orchestrator = Orchestrator(
            name="orchestrator",
            config={},
            graphiti_client=mock_graphiti_client,
            neo4j_client=mock_neo4j_client,
            llm_client=mock_llm_client,
        )

        researcher = Researcher(
            name="researcher",
            config={},
            graphiti_client=mock_graphiti_client,
            neo4j_client=mock_neo4j_client,
            llm_client=mock_llm_client,
        )

        # Wire up registry
        orchestrator.agent_registry = {"researcher": researcher}
        researcher.agent_registry = {"orchestrator": orchestrator}

        # Start researcher in background
        researcher_task = asyncio.create_task(researcher.run())

        try:
            # Make search request
            response = await orchestrator._dispatch_and_wait(
                "researcher",
                {"query": "Who is Sarah?", "intent": "search"},
                "test-trace",
                timeout=5.0,
            )

            # Verify response received
            assert response is not None
            assert response.source_agent == "researcher"

        finally:
            await researcher.stop()
            researcher_task.cancel()

    @pytest.mark.asyncio
    async def test_ingestion_fire_and_forget(
        self, mock_llm_client, mock_graphiti_client, mock_neo4j_client
    ):
        """Ingestion is fire-and-forget (non-blocking)."""
        orchestrator = Orchestrator(
            name="orchestrator",
            config={},
            graphiti_client=mock_graphiti_client,
            neo4j_client=mock_neo4j_client,
            llm_client=mock_llm_client,
        )

        ingestor = Ingestor(
            name="ingestor",
            config={},
            graphiti_client=mock_graphiti_client,
            llm_client=mock_llm_client,
        )

        orchestrator.agent_registry = {"ingestor": ingestor}

        # Fire and forget should return immediately
        await orchestrator._dispatch_fire_and_forget(
            "ingestor",
            {"text": "I met Sarah", "intent": "ingest"},
            "test-trace",
        )

        # Message should be in ingestor queue
        assert ingestor.inbox.qsize() == 1


# ====================
# ENTITY EXTRACTION TESTS
# ====================

class TestEntityExtraction:
    """Test entity extraction in Ingestor."""

    @pytest.fixture
    def ingestor_with_extraction(self, mock_graphiti_client):
        """Ingestor with mock extraction response."""
        client = MagicMock()
        response = MagicMock()
        response.content = [MagicMock(text='''
{
  "entities": [
    {"type": "Person", "name": "Sarah", "properties": {"email": "sarah@acme.com"}},
    {"type": "Organization", "name": "Acme Corp", "properties": {}}
  ],
  "relationships": [
    {"source": "Sarah", "type": "WORKS_AT", "target": "Acme Corp", "properties": {}, "is_historical": false}
  ],
  "facts": ["Sarah works at Acme Corp"]
}
''')]
        client.messages.create = AsyncMock(return_value=response)

        return Ingestor(
            name="ingestor",
            config={},
            graphiti_client=mock_graphiti_client,
            llm_client=client,
        )

    @pytest.mark.asyncio
    async def test_person_extraction(self, ingestor_with_extraction):
        """Extracts Person entities."""
        result = await ingestor_with_extraction._extract(
            "I met Sarah from Acme Corp",
            "test-trace",
        )

        assert len(result.entities) == 2
        person = next(e for e in result.entities if e.type == "Person")
        assert person.name == "Sarah"

    @pytest.mark.asyncio
    async def test_relationship_extraction(self, ingestor_with_extraction):
        """Extracts relationships between entities."""
        result = await ingestor_with_extraction._extract(
            "I met Sarah from Acme Corp",
            "test-trace",
        )

        assert len(result.relationships) == 1
        rel = result.relationships[0]
        assert rel.source == "Sarah"
        assert rel.type == "WORKS_AT"
        assert rel.target == "Acme Corp"


# ====================
# HYBRID SEARCH TESTS
# ====================

class TestHybridSearch:
    """Test hybrid search in Researcher."""

    @pytest.fixture
    def researcher(self, mock_llm_client, mock_graphiti_client, mock_neo4j_client):
        return Researcher(
            name="researcher",
            config={},
            graphiti_client=mock_graphiti_client,
            neo4j_client=mock_neo4j_client,
            llm_client=mock_llm_client,
        )

    def test_search_type_semantic(self, researcher):
        """Generic query classified as semantic."""
        search_type = researcher._classify_search_type("What was that budget thing?")
        assert search_type == SearchType.SEMANTIC

    def test_search_type_structural(self, researcher):
        """Relationship query classified as structural."""
        search_type = researcher._classify_search_type("Who does Sarah work for?")
        assert search_type == SearchType.STRUCTURAL

    def test_search_type_temporal(self, researcher):
        """Time-based query classified as temporal."""
        search_type = researcher._classify_search_type("What happened last week?")
        assert search_type == SearchType.TEMPORAL


# ====================
# MCP INTEGRATION TESTS (MOCKED)
# ====================

class TestMCPIntegration:
    """Test MCP integration with mocked responses."""

    @pytest.fixture
    def executor(self, mock_llm_client, mock_google_bridge):
        return Executor(
            name="executor",
            config={},
            google_bridge=mock_google_bridge,
            llm_client=mock_llm_client,
        )

    @pytest.mark.asyncio
    async def test_gmail_search(self, executor, mock_google_bridge):
        """Gmail search invokes MCP correctly."""
        msg = AgentMessage(
            trace_id="test",
            source_agent="orchestrator",
            target_agent="executor",
            intent="action",
            payload={"action": "Check my emails"},
            timestamp=0,
        )

        await executor.process_message(msg)
        mock_google_bridge.get_recent_emails.assert_called()

    @pytest.mark.asyncio
    async def test_calendar_list(self, executor, mock_google_bridge):
        """Calendar list invokes MCP correctly."""
        msg = AgentMessage(
            trace_id="test",
            source_agent="orchestrator",
            target_agent="executor",
            intent="action",
            payload={"action": "What's on my calendar today?"},
            timestamp=0,
        )

        await executor.process_message(msg)
        mock_google_bridge.get_todays_events.assert_called()


# ====================
# CONFIG HOT-RELOAD TESTS
# ====================

class TestConfigHotReload:
    """Test configuration hot-reload."""

    @pytest.mark.asyncio
    async def test_config_change_detected(self, tmp_path):
        """Config changes are detected."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        config_file = config_dir / "orchestrator.yaml"
        config_file.write_text("model:\n  primary: claude-3-haiku-20240307")

        manager = ConfigManager(config_dir)
        original_checksum = manager.get_checksum("orchestrator")

        # Modify config
        config_file.write_text("model:\n  primary: claude-3-5-sonnet-20241022")

        # Reload
        changed = manager.reload("orchestrator")
        assert changed
        assert manager.get_checksum("orchestrator") != original_checksum

    @pytest.mark.asyncio
    async def test_invalid_config_handled(self, tmp_path):
        """Invalid YAML doesn't crash."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        config_file = config_dir / "orchestrator.yaml"
        config_file.write_text("model:\n  primary: valid")

        manager = ConfigManager(config_dir)

        # Write invalid YAML
        config_file.write_text("model:\n  primary: [invalid")

        # Reload should raise but not crash
        with pytest.raises(Exception):
            manager.reload("orchestrator")


# ====================
# RUN TESTS
# ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

Add to requirements-dev.txt:
```
pytest>=7.0.0
pytest-asyncio>=0.21.0
pytest-cov>=4.0.0
```

Run with: `pytest tests/integration/test_sprint2_agents.py -v`
