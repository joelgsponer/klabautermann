"""
Smoke tests for application startup.

These tests verify that main.py can initialize without crashing.
They catch issues like mismatched constructor signatures between
main.py and agent classes.

Reference: CLAUDE.md testing philosophy
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAppStartup:
    """Smoke tests for Klabautermann app initialization."""

    @pytest.fixture
    def mock_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Set required environment variables."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
        monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
        monkeypatch.setenv("NEO4J_PASSWORD", "test-password")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    @pytest.fixture
    def mock_neo4j(self) -> MagicMock:
        """Mock Neo4j client."""
        mock = MagicMock()
        mock.connect = AsyncMock()
        mock.disconnect = AsyncMock()
        mock.is_connected = True
        return mock

    @pytest.fixture
    def mock_graphiti(self) -> MagicMock:
        """Mock Graphiti client."""
        mock = MagicMock()
        mock.connect = AsyncMock()
        mock.disconnect = AsyncMock()
        mock.is_connected = True
        return mock

    @pytest.mark.asyncio
    async def test_app_initializes_without_crashing(
        self,
        mock_env: None,
        mock_neo4j: MagicMock,
        mock_graphiti: MagicMock,
    ) -> None:
        """App can initialize all components without errors.

        This is the critical smoke test that would have caught the
        'Ingestor.__init__() got an unexpected keyword argument' bug.
        """
        # Import here to avoid path issues
        import sys

        main_path = Path(__file__).parent.parent.parent
        if str(main_path) not in sys.path:
            sys.path.insert(0, str(main_path))

        from main import Klabautermann

        app = Klabautermann()

        # Patch external services
        with (
            patch("main.Neo4jClient", return_value=mock_neo4j),
            patch("main.GraphitiClient", return_value=mock_graphiti),
            patch("main.load_dotenv"),
        ):
            await app.initialize()

            # Verify all expected agents are created
            assert "orchestrator" in app.agents, "Orchestrator not created"
            assert "researcher" in app.agents, "Researcher not created"
            assert "executor" in app.agents, "Executor not created"
            # Ingestor requires Graphiti
            assert "ingestor" in app.agents, "Ingestor not created"
            # Scheduler agents must be available
            assert "archivist" in app.agents, "Archivist not created"
            assert "scribe" in app.agents, "Scribe not created"

            # Verify ThreadManager is wired to Orchestrator
            orchestrator = app.agents["orchestrator"]
            assert orchestrator.thread_manager is not None, (
                "ThreadManager not wired to Orchestrator"
            )
            assert app.thread_manager is not None, "ThreadManager not created"

            # Verify ThreadManager is wired to Archivist
            archivist = app.agents["archivist"]
            assert archivist.thread_manager is not None, "ThreadManager not wired to Archivist"

    @pytest.mark.asyncio
    async def test_app_initializes_without_graphiti(
        self,
        mock_env: None,
        mock_neo4j: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """App can initialize without Graphiti (no OpenAI key)."""
        # Remove OpenAI key
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        import sys

        main_path = Path(__file__).parent.parent.parent
        if str(main_path) not in sys.path:
            sys.path.insert(0, str(main_path))

        from main import Klabautermann

        app = Klabautermann()

        with patch("main.Neo4jClient", return_value=mock_neo4j), patch("main.load_dotenv"):
            await app.initialize()

            # Core agents should still work
            assert "orchestrator" in app.agents
            assert "researcher" in app.agents
            assert "executor" in app.agents
            # Ingestor should NOT be created without Graphiti
            assert "ingestor" not in app.agents
            # Scheduler agents don't depend on Graphiti
            assert "archivist" in app.agents, "Archivist should work without Graphiti"
            assert "scribe" in app.agents, "Scribe should work without Graphiti"

    @pytest.mark.asyncio
    async def test_agents_have_registry_wired(
        self,
        mock_env: None,
        mock_neo4j: MagicMock,
        mock_graphiti: MagicMock,
    ) -> None:
        """All agents have agent_registry set after initialization."""
        import sys

        main_path = Path(__file__).parent.parent.parent
        if str(main_path) not in sys.path:
            sys.path.insert(0, str(main_path))

        from main import Klabautermann

        app = Klabautermann()

        with (
            patch("main.Neo4jClient", return_value=mock_neo4j),
            patch("main.GraphitiClient", return_value=mock_graphiti),
            patch("main.load_dotenv"),
        ):
            await app.initialize()

            # All agents should have registry
            for name, agent in app.agents.items():
                assert agent.agent_registry is not None, f"{name} missing agent_registry"
                assert agent.agent_registry is app.agents, f"{name} has wrong registry"

    @pytest.mark.asyncio
    async def test_agent_constructors_match_main_py(
        self,
        mock_env: None,
        mock_neo4j: MagicMock,
        mock_graphiti: MagicMock,
    ) -> None:
        """Verify agent constructors accept the args main.py passes.

        This test explicitly documents which args each agent receives.
        If you change an agent's __init__, update main.py too!
        """
        import sys

        main_path = Path(__file__).parent.parent.parent
        if str(main_path) not in sys.path:
            sys.path.insert(0, str(main_path))

        # These imports should NOT fail
        from klabautermann.agents.executor import Executor
        from klabautermann.agents.ingestor import Ingestor
        from klabautermann.agents.orchestrator import Orchestrator
        from klabautermann.agents.researcher import Researcher

        # Test that constructors accept what main.py passes
        # If any of these fail, the smoke test catches it

        orchestrator = Orchestrator(
            graphiti=mock_graphiti,
            thread_manager=None,
            config={"model": "test"},
        )
        assert orchestrator is not None

        ingestor = Ingestor(
            name="ingestor",
            config={"model": "test"},
            graphiti_client=mock_graphiti,
        )
        assert ingestor is not None

        researcher = Researcher(
            name="researcher",
            config={"model": "test"},
            graphiti=mock_graphiti,
            neo4j=mock_neo4j,
        )
        assert researcher is not None

        executor = Executor(
            name="executor",
            config={"model": "test"},
            google_bridge=None,
        )
        assert executor is not None

    @pytest.mark.asyncio
    async def test_orchestrator_can_find_researcher(
        self,
        mock_env: None,
        mock_neo4j: MagicMock,
        mock_graphiti: MagicMock,
    ) -> None:
        """Orchestrator's _has_agent can find the researcher.

        This catches the bug where agent_registry wasn't properly wired,
        causing _has_agent('researcher') to return False and fall back
        to Claude roleplay instead of actual dispatch.
        """
        import sys

        main_path = Path(__file__).parent.parent.parent
        if str(main_path) not in sys.path:
            sys.path.insert(0, str(main_path))

        from main import Klabautermann

        app = Klabautermann()

        with (
            patch("main.Neo4jClient", return_value=mock_neo4j),
            patch("main.GraphitiClient", return_value=mock_graphiti),
            patch("main.load_dotenv"),
        ):
            await app.initialize()

            orchestrator = app.agents["orchestrator"]

            # This is the critical check - orchestrator must be able to find researcher
            assert orchestrator._has_agent("researcher"), (
                "Orchestrator cannot find researcher - agent_registry not wired correctly"
            )
            assert orchestrator._has_agent("executor"), "Orchestrator cannot find executor"
            assert orchestrator._has_agent("ingestor"), "Orchestrator cannot find ingestor"

    @pytest.mark.asyncio
    async def test_search_intent_does_not_trigger_ingestion(
        self,
        mock_env: None,
        mock_neo4j: MagicMock,
        mock_graphiti: MagicMock,
    ) -> None:
        """SEARCH intent should NOT trigger ingestion.

        Only INGESTION intent should add data to the knowledge graph.
        Search queries like 'who is Sarah' should not pollute the graph.
        """
        import json
        import sys

        main_path = Path(__file__).parent.parent.parent
        if str(main_path) not in sys.path:
            sys.path.insert(0, str(main_path))

        from main import Klabautermann

        app = Klabautermann()

        with (
            patch("main.Neo4jClient", return_value=mock_neo4j),
            patch("main.GraphitiClient", return_value=mock_graphiti),
            patch("main.load_dotenv"),
        ):
            await app.initialize()

            orchestrator = app.agents["orchestrator"]

            # Mock classification to return SEARCH
            mock_response = json.dumps(
                {
                    "intent_type": "search",
                    "confidence": 0.9,
                    "reasoning": "User asking about a person",
                    "extracted_query": "who is Sarah",
                    "extracted_action": None,
                }
            )

            # Track if ingestion was triggered
            ingest_called = False
            original_ingest = orchestrator._ingest_conversation

            async def tracking_ingest(*args, **kwargs):
                nonlocal ingest_called
                ingest_called = True
                return await original_ingest(*args, **kwargs)

            with (
                patch.object(
                    orchestrator, "_call_classification_model", new_callable=AsyncMock
                ) as mock_classify,
                patch.object(orchestrator, "_ingest_conversation", side_effect=tracking_ingest),
                patch.object(orchestrator, "_call_claude", new_callable=AsyncMock) as mock_claude,
            ):
                mock_classify.return_value = mock_response
                mock_claude.return_value = "I couldn't find Sarah in The Locker."

                await orchestrator.handle_user_input(
                    thread_id="test-thread",
                    text="who is Sarah",
                )

            # SEARCH should NOT trigger ingestion
            assert not ingest_called, "SEARCH intent incorrectly triggered ingestion"
