"""
Sprint 2 Integration Tests

Tests the multi-agent architecture including delegation,
extraction, search, and MCP integration.

Reference: specs/quality/TESTING.md Section 3, specs/architecture/AGENTS.md

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""
# ruff: noqa: SIM105, B017

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.executor import Executor
from klabautermann.agents.ingestor import Ingestor
from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.agents.researcher import Researcher
from klabautermann.config.manager import ConfigManager
from klabautermann.core.models import (
    AgentMessage,
    IntentType,
)


# ====================
# FIXTURES
# ====================


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Mock Anthropic client for testing."""
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text='{"entities": [], "relationships": [], "facts": []}')]
    client.messages.create = MagicMock(return_value=response)
    return client


@pytest.fixture
def mock_graphiti_client() -> MagicMock:
    """Mock Graphiti client for testing."""
    client = MagicMock()
    client.search = AsyncMock(return_value=[])
    client.add_episode = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_neo4j_client() -> MagicMock:
    """Mock Neo4j client for testing."""
    client = MagicMock()

    # Mock session context manager
    session = MagicMock()
    session.run = AsyncMock(return_value=MagicMock(data=AsyncMock(return_value=[])))

    async def async_context_manager(*args: Any, **kwargs: Any) -> Any:
        class AsyncContextManager:
            async def __aenter__(self) -> Any:
                return session

            async def __aexit__(self, *args: Any) -> None:
                pass

        return AsyncContextManager()

    client.session = MagicMock(side_effect=async_context_manager)
    return client


@pytest.fixture
def mock_google_bridge() -> MagicMock:
    """Mock Google Workspace bridge for testing."""
    bridge = MagicMock()
    bridge.get_recent_emails = AsyncMock(return_value=[])
    bridge.search_emails = AsyncMock(return_value=[])
    bridge.send_email = AsyncMock(return_value=MagicMock(success=True, message_id="123"))
    bridge.get_todays_events = AsyncMock(return_value=[])
    bridge.list_events = AsyncMock(return_value=[])
    bridge.create_event = AsyncMock(return_value=MagicMock(success=True, event_id="456"))
    return bridge


@pytest.fixture
def config_manager(tmp_path: Path) -> ConfigManager:
    """Config manager with temp directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create minimal config files
    (config_dir / "orchestrator.yaml").write_text(
        """
model:
  primary: claude-3-5-sonnet-20241022
  temperature: 0.7
"""
    )

    (config_dir / "ingestor.yaml").write_text(
        """
model:
  primary: claude-3-haiku-20240307
  temperature: 0.0
"""
    )

    (config_dir / "researcher.yaml").write_text(
        """
model:
  primary: claude-3-haiku-20240307
  temperature: 0.0
"""
    )

    (config_dir / "executor.yaml").write_text(
        """
model:
  primary: claude-3-5-sonnet-20241022
  temperature: 0.7
"""
    )

    return ConfigManager(config_dir)


# ====================
# INTENT CLASSIFICATION TESTS
# ====================


def _mock_classification_response(
    intent_type: str,
    confidence: float = 0.9,
    reasoning: str = "Test classification",
    extracted_query: str | None = None,
    extracted_action: str | None = None,
) -> str:
    """Helper to create mock LLM classification response JSON."""
    return json.dumps(
        {
            "intent_type": intent_type.lower(),
            "confidence": confidence,
            "reasoning": reasoning,
            "extracted_query": extracted_query,
            "extracted_action": extracted_action,
        }
    )


class TestIntentClassification:
    """Test intent classification in Orchestrator."""

    @pytest.fixture
    def orchestrator(
        self,
        mock_llm_client: MagicMock,
        mock_graphiti_client: MagicMock,
    ) -> Orchestrator:
        """Create Orchestrator for testing."""
        return Orchestrator(
            graphiti=mock_graphiti_client,
            thread_manager=None,
            config={"model": "claude-3-5-sonnet-20241022"},
        )

    @pytest.mark.asyncio
    async def test_search_intent_who(self, orchestrator: Orchestrator) -> None:
        """'Who is X' triggers search intent."""
        mock_response = _mock_classification_response(
            "SEARCH", 0.9, "User asking about a person", "Who is Sarah?"
        )
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response
            intent = await orchestrator._classify_intent("Who is Sarah?", None, "test-trace")
            assert intent.type == IntentType.SEARCH
            assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_search_intent_what(self, orchestrator: Orchestrator) -> None:
        """'What is X' triggers search intent."""
        mock_response = _mock_classification_response(
            "SEARCH", 0.9, "User asking for information", "What is the Q1 budget?"
        )
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response
            intent = await orchestrator._classify_intent(
                "What is the Q1 budget?", None, "test-trace"
            )
            assert intent.type == IntentType.SEARCH
            assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_action_intent_send(self, orchestrator: Orchestrator) -> None:
        """'Send email' triggers action intent."""
        mock_response = _mock_classification_response(
            "ACTION", 0.9, "User wants to send email", None, "Send an email to John"
        )
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response
            intent = await orchestrator._classify_intent(
                "Send an email to John", None, "test-trace"
            )
            assert intent.type == IntentType.ACTION
            assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_action_intent_schedule(self, orchestrator: Orchestrator) -> None:
        """'Schedule meeting' triggers action intent."""
        mock_response = _mock_classification_response(
            "ACTION", 0.9, "User wants to schedule meeting", None, "Schedule a meeting tomorrow"
        )
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response
            intent = await orchestrator._classify_intent(
                "Schedule a meeting tomorrow", None, "test-trace"
            )
            assert intent.type == IntentType.ACTION
            assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_ingestion_intent_i_met(self, orchestrator: Orchestrator) -> None:
        """'I met X' triggers ingestion intent."""
        mock_response = _mock_classification_response(
            "INGESTION", 0.8, "User sharing information about a person"
        )
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response
            intent = await orchestrator._classify_intent(
                "I met Sarah from Acme", None, "test-trace"
            )
            assert intent.type == IntentType.INGESTION
            assert intent.confidence == 0.8

    @pytest.mark.asyncio
    async def test_conversation_default(self, orchestrator: Orchestrator) -> None:
        """Generic input defaults to conversation."""
        mock_response = _mock_classification_response(
            "CONVERSATION", 0.7, "Greeting/social interaction"
        )
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response
            intent = await orchestrator._classify_intent("Hello, how are you?", None, "test-trace")
            assert intent.type == IntentType.CONVERSATION
            assert intent.confidence == 0.7


# ====================
# AGENT DELEGATION TESTS
# ====================


class TestAgentDelegation:
    """Test agent-to-agent delegation patterns."""

    @pytest.mark.asyncio
    async def test_search_delegates_to_researcher(
        self,
        mock_llm_client: MagicMock,
        mock_graphiti_client: MagicMock,
        mock_neo4j_client: MagicMock,
    ) -> None:
        """Search intent delegates to Researcher via dispatch-and-wait."""
        # Create orchestrator and researcher
        orchestrator = Orchestrator(
            graphiti=mock_graphiti_client,
            thread_manager=None,
            config={"model": "claude-3-5-sonnet-20241022"},
        )

        researcher = Researcher(
            graphiti=mock_graphiti_client,
            neo4j=mock_neo4j_client,
            config={"model": "claude-3-haiku-20240307"},
        )

        # Wire up agent registry
        orchestrator._agent_registry = {"researcher": researcher}
        researcher._agent_registry = {"orchestrator": orchestrator}

        # Start researcher in background
        researcher_task = asyncio.create_task(researcher.run())

        try:
            # Dispatch search request
            response = await orchestrator._dispatch_and_wait(
                "researcher",
                {"query": "Who is Sarah?", "intent": "search"},
                "test-trace",
                timeout=5.0,
            )

            # Verify response received
            assert response is not None
            assert response.source_agent == "researcher"
            assert response.target_agent == "orchestrator"

        finally:
            await researcher.stop()
            researcher_task.cancel()
            try:
                await researcher_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_ingestion_fire_and_forget(
        self,
        mock_llm_client: MagicMock,
        mock_graphiti_client: MagicMock,
    ) -> None:
        """Ingestion is fire-and-forget (non-blocking)."""
        orchestrator = Orchestrator(
            graphiti=mock_graphiti_client,
            thread_manager=None,
            config={"model": "claude-3-5-sonnet-20241022"},
        )

        ingestor = Ingestor(
            graphiti_client=mock_graphiti_client,
            config={"model": "claude-3-haiku-20240307"},
        )

        orchestrator._agent_registry = {"ingestor": ingestor}

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
    """Test entity extraction in Ingestor.

    NOTE: Entity extraction is delegated to Graphiti's internal LLM.
    The Ingestor cleans input and passes to Graphiti - it doesn't extract directly.
    These tests validate that the Ingestor correctly passes data to Graphiti.
    """

    @pytest.fixture
    def ingestor(self, mock_graphiti_client: MagicMock) -> Ingestor:
        """Ingestor with mock Graphiti client."""
        return Ingestor(
            graphiti_client=mock_graphiti_client,
            config={"model": "claude-3-haiku-20240307"},
        )

    @pytest.mark.asyncio
    async def test_ingestor_passes_cleaned_text_to_graphiti(
        self, ingestor: Ingestor, mock_graphiti_client: MagicMock
    ) -> None:
        """Ingestor cleans input and passes to Graphiti add_episode."""
        mock_graphiti_client.is_connected = True
        mock_graphiti_client.add_episode = AsyncMock()

        from klabautermann.core.models import AgentMessage

        msg = AgentMessage(
            trace_id="test-trace",
            source_agent="orchestrator",
            target_agent="ingestor",
            intent="ingest",
            payload={"text": "User: I met Sarah from Acme Corp"},
        )

        await ingestor.process_message(msg)

        # Verify Graphiti was called with cleaned text
        mock_graphiti_client.add_episode.assert_called_once()
        call_kwargs = mock_graphiti_client.add_episode.call_args.kwargs
        # "User: " prefix should be stripped
        assert "User:" not in call_kwargs["content"]
        assert "Sarah" in call_kwargs["content"]
        assert "Acme Corp" in call_kwargs["content"]

    @pytest.mark.asyncio
    async def test_ingestor_cleans_role_prefixes(self, ingestor: Ingestor) -> None:
        """Ingestor strips role prefixes from input."""
        text = "User: I met Sarah from Acme\nAssistant: Nice!"
        cleaned = ingestor.clean_input(text)

        assert "User:" not in cleaned
        assert "Assistant:" not in cleaned
        assert "Sarah" in cleaned

    @pytest.mark.asyncio
    async def test_ingestor_handles_empty_input(
        self, ingestor: Ingestor, mock_graphiti_client: MagicMock
    ) -> None:
        """Ingestor skips empty input."""
        mock_graphiti_client.add_episode = AsyncMock()

        from klabautermann.core.models import AgentMessage

        msg = AgentMessage(
            trace_id="test-trace",
            source_agent="orchestrator",
            target_agent="ingestor",
            intent="ingest",
            payload={"text": ""},
        )

        result = await ingestor.process_message(msg)

        assert result is None
        mock_graphiti_client.add_episode.assert_not_called()


# ====================
# HYBRID SEARCH TESTS
# ====================


@pytest.mark.skip(
    reason="SearchType API removed - Researcher now uses LLM-based planning (see test_researcher.py)"
)
class TestHybridSearch:
    """
    Test hybrid search classification in Researcher.

    DEPRECATED: The _classify_search_type method was removed in the
    Intelligent Researcher refactor (Sprint 4). Search technique selection
    is now done via LLM-based planning. See test_researcher.py for new tests.
    """

    @pytest.fixture
    def researcher(
        self,
        mock_graphiti_client: MagicMock,
        mock_neo4j_client: MagicMock,
    ) -> Researcher:
        """Create Researcher for testing."""
        return Researcher(
            graphiti=mock_graphiti_client,
            neo4j=mock_neo4j_client,
            config={"model": "claude-3-haiku-20240307"},
        )

    def test_search_type_semantic(self, researcher: Researcher) -> None:
        """Generic query classified as semantic."""
        pytest.skip("_classify_search_type removed in v2")

    def test_search_type_structural(self, researcher: Researcher) -> None:
        """Relationship query classified as structural."""
        pytest.skip("_classify_search_type removed in v2")

    def test_search_type_temporal(self, researcher: Researcher) -> None:
        """Time-based query classified as temporal."""
        pytest.skip("_classify_search_type removed in v2")

    def test_search_type_hybrid_works_at(self, researcher: Researcher) -> None:
        """Query with relationship and time classified as hybrid."""
        pytest.skip("_classify_search_type removed in v2")


# ====================
# MCP INTEGRATION TESTS (MOCKED)
# ====================


class TestMCPIntegration:
    """Test MCP integration with mocked Google Bridge."""

    @pytest.fixture
    def executor(
        self,
        mock_google_bridge: MagicMock,
    ) -> Executor:
        """Create Executor with mocked Google Bridge."""
        # Executor doesn't use anthropic - it uses GoogleWorkspaceBridge directly
        return Executor(
            google_bridge=mock_google_bridge,
            config={"model": "claude-3-5-sonnet-20241022"},
        )

    @pytest.mark.asyncio
    async def test_gmail_search(self, executor: Executor, mock_google_bridge: MagicMock) -> None:
        """Gmail search invokes MCP correctly."""
        msg = AgentMessage(
            trace_id="test",
            source_agent="orchestrator",
            target_agent="executor",
            intent="action",
            payload={"action": "Check my emails"},
            timestamp=0,
        )

        # Process message (which delegates to handlers)
        await executor.process_message(msg)

        # Should have tried to call Gmail methods
        # Note: Actual invocation depends on action parsing
        assert (
            mock_google_bridge.get_recent_emails.called or mock_google_bridge.search_emails.called
        )

    @pytest.mark.asyncio
    async def test_calendar_list(self, executor: Executor, mock_google_bridge: MagicMock) -> None:
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

        # Should have tried to call calendar methods
        assert mock_google_bridge.get_todays_events.called or mock_google_bridge.list_events.called

    @pytest.mark.asyncio
    async def test_mcp_error_handling(
        self, executor: Executor, mock_google_bridge: MagicMock
    ) -> None:
        """MCP errors are handled gracefully."""
        # Make both email methods raise an error (executor may call either)
        mock_google_bridge.get_recent_emails.side_effect = Exception("API connection failed")
        mock_google_bridge.search_emails.side_effect = Exception("API connection failed")

        msg = AgentMessage(
            trace_id="test",
            source_agent="orchestrator",
            target_agent="executor",
            intent="action",
            payload={"action": "Check my emails"},
            timestamp=0,
        )

        # Should not crash, but handle error
        response = await executor.process_message(msg)

        # Should return an error response
        if response:
            assert not response.payload.get("success", False)


# ====================
# CONFIG HOT-RELOAD TESTS
# ====================


class TestConfigHotReload:
    """Test configuration hot-reload functionality."""

    @pytest.mark.asyncio
    async def test_config_change_detected(self, tmp_path: Path) -> None:
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
    async def test_config_unchanged_not_reloaded(self, tmp_path: Path) -> None:
        """Unchanged config is not reloaded."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        config_file = config_dir / "orchestrator.yaml"
        config_file.write_text("model:\n  primary: claude-3-haiku-20240307")

        manager = ConfigManager(config_dir)

        # Reload without changes
        changed = manager.reload("orchestrator")
        assert not changed

    @pytest.mark.asyncio
    async def test_invalid_config_handled(self, tmp_path: Path) -> None:
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
# INTEGRATION FLOW TESTS
# ====================


class TestEndToEndFlows:
    """Test complete end-to-end flows across multiple agents."""

    @pytest.mark.asyncio
    async def test_search_flow_orchestrator_to_researcher(
        self,
        mock_llm_client: MagicMock,
        mock_graphiti_client: MagicMock,
        mock_neo4j_client: MagicMock,
    ) -> None:
        """Complete search flow from Orchestrator to Researcher."""
        # Setup agents
        orchestrator = Orchestrator(
            graphiti=mock_graphiti_client,
            thread_manager=None,
            config={"model": "claude-3-5-sonnet-20241022"},
        )

        researcher = Researcher(
            graphiti=mock_graphiti_client,
            neo4j=mock_neo4j_client,
            config={"model": "claude-3-haiku-20240307"},
        )

        # Wire up registry
        orchestrator._agent_registry = {"researcher": researcher}
        researcher._agent_registry = {"orchestrator": orchestrator}

        # Start researcher
        researcher_task = asyncio.create_task(researcher.run())

        try:
            # Classify intent
            intent = await orchestrator._classify_intent("Who is Sarah?", None, "test-trace")
            assert intent.type == IntentType.SEARCH

            # Delegate to researcher
            response = await orchestrator._dispatch_and_wait(
                "researcher",
                {"query": intent.query, "intent": "search"},
                "test-trace",
                timeout=5.0,
            )

            # Verify response
            assert response is not None
            assert response.source_agent == "researcher"

        finally:
            await researcher.stop()
            researcher_task.cancel()
            try:
                await researcher_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_ingestion_flow_fire_and_forget(
        self,
        mock_llm_client: MagicMock,
        mock_graphiti_client: MagicMock,
    ) -> None:
        """Ingestion flow is non-blocking fire-and-forget."""
        orchestrator = Orchestrator(
            graphiti=mock_graphiti_client,
            thread_manager=None,
            config={"model": "claude-3-5-sonnet-20241022"},
        )

        ingestor = Ingestor(
            graphiti_client=mock_graphiti_client,
            config={"model": "claude-3-haiku-20240307"},
        )

        orchestrator._agent_registry = {"ingestor": ingestor}

        # Classify ingestion intent
        intent = await orchestrator._classify_intent(
            "I met Sarah from Acme Corp", None, "test-trace"
        )
        assert intent.type == IntentType.INGESTION

        # Fire and forget to ingestor
        await orchestrator._dispatch_fire_and_forget(
            "ingestor",
            {"text": "I met Sarah from Acme Corp", "intent": "ingest"},
            "test-trace",
        )

        # Message queued, orchestrator doesn't wait
        assert ingestor.inbox.qsize() == 1


# ====================
# RUN TESTS
# ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
