"""
Unit tests for Orchestrator v2 main workflow (T059).

Tests the full Think-Dispatch-Synthesize pattern including:
- Full workflow execution
- Direct response handling
- Iterative deepening
- Error handling
- Response storage
- Personality application
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import (
    ChannelType,
    EnrichedContext,
    PlannedTask,
    TaskPlan,
)


class TestHandleUserInputV2:
    """Tests for the main handle_user_input_v2 method."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator with mocked dependencies."""
        mock_graphiti = MagicMock()
        mock_thread_manager = MagicMock()
        mock_neo4j = MagicMock()
        return Orchestrator(
            graphiti=mock_graphiti,
            thread_manager=mock_thread_manager,
            neo4j_client=mock_neo4j,
        )

    @pytest.fixture
    def mock_context(self) -> EnrichedContext:
        """Create mock enriched context."""
        return EnrichedContext(
            thread_uuid="thread-123",
            channel_type=ChannelType.CLI,
            messages=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            recent_summaries=[],
            pending_tasks=[],
            recent_entities=[],
            relevant_islands=None,
        )

    @pytest.fixture
    def mock_task_plan_with_tasks(self) -> TaskPlan:
        """Create mock task plan with tasks."""
        return TaskPlan(
            reasoning="User is asking about Sarah and providing new info",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Ingest: Sarah studied at Harvard",
                    agent="ingestor",
                    payload={"text": "Sarah studied at Harvard"},
                    blocking=False,
                ),
                PlannedTask(
                    task_type="research",
                    description="Search for Sarah in knowledge graph",
                    agent="researcher",
                    payload={"query": "What do I know about Sarah?"},
                    blocking=True,
                ),
            ],
            direct_response=None,
        )

    @pytest.fixture
    def mock_task_plan_direct_response(self) -> TaskPlan:
        """Create mock task plan with direct response."""
        return TaskPlan(
            reasoning="Simple greeting, no tasks needed",
            tasks=[],
            direct_response="Hello! How can I help you today?",
        )

    @pytest.mark.asyncio
    async def test_full_workflow_executes_successfully(
        self,
        orchestrator: Orchestrator,
        mock_context: EnrichedContext,
        mock_task_plan_with_tasks: TaskPlan,
    ) -> None:
        """Full v2 workflow executes for multi-intent message."""
        # Mock all the workflow steps
        with (
            patch.object(
                orchestrator, "_build_context_safe", return_value=mock_context
            ) as mock_build_context,
            patch.object(
                orchestrator, "_plan_tasks", return_value=mock_task_plan_with_tasks
            ) as mock_plan_tasks,
            patch.object(
                orchestrator,
                "_execute_parallel_safe",
                return_value={
                    "Search for Sarah in knowledge graph": {
                        "agent": "researcher",
                        "response": "Sarah is a PM at Acme Corp",
                        "task_type": "research",
                    }
                },
            ) as mock_execute,
            patch.object(
                orchestrator,
                "_needs_deeper_research",
                return_value=False,
            ) as mock_needs_deeper,
            patch.object(
                orchestrator,
                "_synthesize_response",
                return_value="I found that Sarah is a PM at Acme Corp. I've also noted that she studied at Harvard.",
            ) as mock_synthesize,
            patch.object(
                orchestrator, "_apply_personality", side_effect=lambda x, _: x
            ) as mock_personality,
            patch.object(orchestrator, "_store_response", return_value=None) as mock_store,
        ):
            response = await orchestrator.handle_user_input_v2(
                text="Sarah studied at Harvard. What do I know about her?",
                thread_uuid="thread-123",
                trace_id="trace-456",
            )

            # Verify workflow steps were called
            mock_build_context.assert_called_once_with("thread-123", "trace-456")
            mock_plan_tasks.assert_called_once()
            mock_execute.assert_called_once()
            mock_needs_deeper.assert_called_once()
            mock_synthesize.assert_called_once()
            mock_personality.assert_called_once()
            mock_store.assert_called_once_with("thread-123", response, "trace-456")

            assert "Sarah is a PM at Acme Corp" in response

    @pytest.mark.asyncio
    async def test_direct_response_no_tasks(
        self,
        orchestrator: Orchestrator,
        mock_context: EnrichedContext,
        mock_task_plan_direct_response: TaskPlan,
    ) -> None:
        """Direct response handling when no tasks needed."""
        with (
            patch.object(orchestrator, "_build_context_safe", return_value=mock_context),
            patch.object(orchestrator, "_plan_tasks", return_value=mock_task_plan_direct_response),
            patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
            patch.object(orchestrator, "_store_response", return_value=None) as mock_store,
            patch.object(orchestrator, "_execute_parallel_safe") as mock_execute,
        ):
            response = await orchestrator.handle_user_input_v2(
                text="Hello!",
                thread_uuid="thread-123",
                trace_id="trace-456",
            )

            # Execute should NOT be called for direct response
            mock_execute.assert_not_called()

            # Response should be stored
            mock_store.assert_called_once()

            assert response == "Hello! How can I help you today?"

    @pytest.mark.asyncio
    async def test_iterative_deepening_triggers(
        self,
        orchestrator: Orchestrator,
        mock_context: EnrichedContext,
    ) -> None:
        """Iterative deepening triggers when results insufficient."""
        task_plan = TaskPlan(
            reasoning="Need to search for info",
            tasks=[
                PlannedTask(
                    task_type="research",
                    description="Search for John",
                    agent="researcher",
                    payload={"query": "Who is John?"},
                    blocking=True,
                )
            ],
        )

        # First results are minimal (triggers deepening)
        initial_results = {
            "Search for John": {
                "agent": "researcher",
                "response": "No results",
                "task_type": "research",
            }
        }

        # Deeper results find something
        deeper_results = {
            "Follow-up: Find more about Acme": {
                "agent": "researcher",
                "response": "Acme is a software company",
                "task_type": "research",
            }
        }

        with (
            patch.object(orchestrator, "_build_context_safe", return_value=mock_context),
            patch.object(orchestrator, "_plan_tasks", return_value=task_plan),
            patch.object(
                orchestrator, "_execute_parallel_safe", return_value=initial_results
            ) as mock_execute,
            patch.object(orchestrator, "_needs_deeper_research", side_effect=[True, False]),
            patch.object(orchestrator, "_deepen_research", return_value=deeper_results),
            patch.object(
                orchestrator, "_synthesize_response", return_value="Found info about Acme"
            ),
            patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
            patch.object(orchestrator, "_store_response", return_value=None),
        ):
            response = await orchestrator.handle_user_input_v2(
                text="Who is John?",
                thread_uuid="thread-123",
                trace_id="trace-456",
            )

            # Execute_parallel_safe should be called once, _deepen_research handles deepening
            assert mock_execute.call_count == 1

            assert "Found info about Acme" in response

    @pytest.mark.asyncio
    async def test_error_handling_doesnt_crash(
        self,
        orchestrator: Orchestrator,
    ) -> None:
        """Error handling prevents workflow crash."""
        with patch.object(
            orchestrator, "_build_context_safe", side_effect=Exception("Database connection failed")
        ):
            response = await orchestrator.handle_user_input_v2(
                text="Test message",
                thread_uuid="thread-123",
                trace_id="trace-456",
            )

            # Should return error message, not crash
            assert "trouble processing" in response.lower()
            assert "try again" in response.lower()

    @pytest.mark.asyncio
    async def test_response_stored_in_thread(
        self,
        orchestrator: Orchestrator,
        mock_context: EnrichedContext,
        mock_task_plan_direct_response: TaskPlan,
    ) -> None:
        """Response is stored in thread manager."""
        mock_thread_manager = AsyncMock()
        orchestrator.thread_manager = mock_thread_manager

        with (
            patch.object(orchestrator, "_build_context_safe", return_value=mock_context),
            patch.object(orchestrator, "_plan_tasks", return_value=mock_task_plan_direct_response),
            patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
        ):
            response = await orchestrator.handle_user_input_v2(
                text="Hello!",
                thread_uuid="thread-123",
                trace_id="trace-456",
            )

            # Verify add_message was called once (assistant response only)
            mock_thread_manager.add_message.assert_called_once_with(
                thread_uuid="thread-123",
                role="assistant",
                content=response,
                trace_id="trace-456",
            )

    @pytest.mark.asyncio
    async def test_personality_applied_to_response(
        self,
        orchestrator: Orchestrator,
        mock_context: EnrichedContext,
        mock_task_plan_direct_response: TaskPlan,
    ) -> None:
        """Personality is applied to final response."""
        with (
            patch.object(orchestrator, "_build_context_safe", return_value=mock_context),
            patch.object(orchestrator, "_plan_tasks", return_value=mock_task_plan_direct_response),
            patch.object(
                orchestrator,
                "_apply_personality",
                return_value="Ahoy! Hello! How can I help you today?",
            ) as mock_personality,
            patch.object(orchestrator, "_store_response", return_value=None),
        ):
            response = await orchestrator.handle_user_input_v2(
                text="Hello!",
                thread_uuid="thread-123",
                trace_id="trace-456",
            )

            # Personality should be applied
            mock_personality.assert_called_once()
            assert "Ahoy!" in response

    @pytest.mark.asyncio
    async def test_trace_id_generated_if_not_provided(
        self,
        orchestrator: Orchestrator,
        mock_context: EnrichedContext,
        mock_task_plan_direct_response: TaskPlan,
    ) -> None:
        """Trace ID is generated if not provided."""
        with (
            patch.object(
                orchestrator, "_build_context_safe", return_value=mock_context
            ) as mock_build_context,
            patch.object(
                orchestrator, "_plan_tasks", return_value=mock_task_plan_direct_response
            ) as mock_plan,
            patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
            patch.object(orchestrator, "_store_response", return_value=None),
        ):
            await orchestrator.handle_user_input_v2(
                text="Hello!",
                thread_uuid="thread-123",
                trace_id=None,  # Not provided
            )

            # Build context should have been called with a generated trace_id
            call_args = mock_build_context.call_args
            assert call_args[0][1] is not None  # trace_id was generated
            assert len(call_args[0][1]) > 0

            # Plan tasks should also have received the trace_id
            plan_call_args = mock_plan.call_args
            assert plan_call_args[0][2] is not None


class TestNeedsDeeperResearch:
    """Tests for the _needs_deeper_research helper."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator."""
        return Orchestrator(graphiti=None, thread_manager=None)

    def test_no_research_tasks_returns_false(self, orchestrator: Orchestrator) -> None:
        """No deepening needed if no research tasks."""
        task_plan = TaskPlan(
            reasoning="Only ingestion",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Ingest info",
                    agent="ingestor",
                    payload={},
                    blocking=False,
                )
            ],
        )

        assert not orchestrator._needs_deeper_research({}, task_plan)

    def test_successful_research_returns_false(self, orchestrator: Orchestrator) -> None:
        """No deepening needed if research succeeded."""
        task_plan = TaskPlan(
            reasoning="Search for info",
            tasks=[
                PlannedTask(
                    task_type="research",
                    description="Find Sarah",
                    agent="researcher",
                    payload={"query": "Who is Sarah?"},
                    blocking=True,
                )
            ],
        )

        results = {
            "Find Sarah": {
                "agent": "researcher",
                "response": "Sarah is a PM at Acme Corp with 5 years experience",
                "task_type": "research",
            }
        }

        assert not orchestrator._needs_deeper_research(results, task_plan)

    def test_minimal_results_returns_true(self, orchestrator: Orchestrator) -> None:
        """Deepening needed if results are minimal."""
        task_plan = TaskPlan(
            reasoning="Search for info",
            tasks=[
                PlannedTask(
                    task_type="research",
                    description="Find John",
                    agent="researcher",
                    payload={"query": "Who is John?"},
                    blocking=True,
                )
            ],
        )

        results = {
            "Find John": {"agent": "researcher", "response": "No results", "task_type": "research"}
        }

        assert orchestrator._needs_deeper_research(results, task_plan)

    def test_error_results_returns_true(self, orchestrator: Orchestrator) -> None:
        """Deepening needed if results contain errors."""
        task_plan = TaskPlan(
            reasoning="Search for info",
            tasks=[
                PlannedTask(
                    task_type="research",
                    description="Find data",
                    agent="researcher",
                    payload={"query": "test"},
                    blocking=True,
                )
            ],
        )

        results = {"Find data": {"error": "Database timeout"}}

        assert orchestrator._needs_deeper_research(results, task_plan)


class TestExtractMentionsFromResults:
    """Tests for the _extract_mentions_from_results helper."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator."""
        return Orchestrator(graphiti=None, thread_manager=None)

    def test_extracts_capitalized_names(self, orchestrator: Orchestrator) -> None:
        """Extracts capitalized entity names from results."""
        results = {
            "task1": {"response": "Sarah works at Acme Corp and knows John Smith"},
            "task2": {"response": "Project Alpha is managed by Sarah"},
        }

        mentions = orchestrator._extract_mentions_from_results(results)

        # Should find capitalized names
        assert "Sarah" in mentions or "Acme" in mentions or "John" in mentions

    def test_handles_empty_results(self, orchestrator: Orchestrator) -> None:
        """Handles empty results gracefully."""
        results = {}

        mentions = orchestrator._extract_mentions_from_results(results)

        assert mentions == []

    def test_handles_non_dict_results(self, orchestrator: Orchestrator) -> None:
        """Handles non-dict results gracefully."""
        results = {"task1": "not a dict"}

        mentions = orchestrator._extract_mentions_from_results(results)

        assert isinstance(mentions, list)


class TestMergeResults:
    """Tests for the _merge_results helper."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator."""
        return Orchestrator(graphiti=None, thread_manager=None)

    def test_merges_non_overlapping_results(self, orchestrator: Orchestrator) -> None:
        """Merges results without conflicts."""
        original = {"task1": {"result": "data1"}}
        deeper = {"task2": {"result": "data2"}}

        merged = orchestrator._merge_results(original, deeper)

        assert merged == {"task1": {"result": "data1"}, "task2": {"result": "data2"}}

    def test_preserves_original_on_conflict(self, orchestrator: Orchestrator) -> None:
        """Preserves original results when keys conflict."""
        original = {"task1": {"result": "original"}}
        deeper = {"task1": {"result": "deeper"}}

        merged = orchestrator._merge_results(original, deeper)

        # Original should be preserved
        assert merged["task1"]["result"] == "original"

    def test_handles_empty_inputs(self, orchestrator: Orchestrator) -> None:
        """Handles empty result sets."""
        assert orchestrator._merge_results({}, {}) == {}
        assert orchestrator._merge_results({"task1": {}}, {}) == {"task1": {}}
        assert orchestrator._merge_results({}, {"task1": {}}) == {"task1": {}}


class TestStoreResponse:
    """Tests for the _store_response helper."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator with mock thread manager."""
        mock_thread_manager = AsyncMock()
        return Orchestrator(
            graphiti=None,
            thread_manager=mock_thread_manager,
        )

    @pytest.mark.asyncio
    async def test_stores_response_successfully(self, orchestrator: Orchestrator) -> None:
        """Successfully stores assistant response in thread manager."""
        await orchestrator._store_response(
            thread_uuid="thread-123",
            response="Test response",
            trace_id="trace-456",
        )

        # Verify assistant response was stored
        orchestrator.thread_manager.add_message.assert_called_once_with(
            thread_uuid="thread-123",
            role="assistant",
            content="Test response",
            trace_id="trace-456",
        )

    @pytest.mark.asyncio
    async def test_handles_storage_failure_gracefully(self, orchestrator: Orchestrator) -> None:
        """Handles storage failure without crashing."""
        orchestrator.thread_manager.add_message.side_effect = Exception("Database error")

        # Should not raise exception
        await orchestrator._store_response(
            thread_uuid="thread-123",
            response="Test response",
            trace_id="trace-456",
        )

    @pytest.mark.asyncio
    async def test_does_nothing_if_no_thread_manager(self) -> None:
        """Does nothing if thread manager not available."""
        orchestrator = Orchestrator(graphiti=None, thread_manager=None)

        # Should not raise exception
        await orchestrator._store_response(
            thread_uuid="thread-123",
            response="Test response",
            trace_id="trace-456",
        )
