"""
Unit tests for Orchestrator v2 error handling (T068).

Tests comprehensive error handling for each phase of the v2 workflow:
- Context building failures (partial tolerance)
- Task planning failures (fallback to direct response)
- Task execution failures (individual capture)
- Synthesis failures (fallback to results summary)
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


class TestBuildContextSafe:
    """Tests for _build_context_safe with partial failure tolerance."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator with mocked dependencies."""
        mock_graphiti = MagicMock()
        mock_thread_manager = AsyncMock()
        mock_neo4j = MagicMock()
        return Orchestrator(
            graphiti=mock_graphiti,
            thread_manager=mock_thread_manager,
            neo4j_client=mock_neo4j,
        )

    @pytest.mark.asyncio
    async def test_handles_messages_failure(self, orchestrator: Orchestrator) -> None:
        """Context building succeeds even if message loading fails."""
        # Mock thread_manager to raise exception
        orchestrator.thread_manager.get_context_window.side_effect = Exception("Database timeout")

        # Should not raise exception
        context = await orchestrator._build_context_safe("thread-123", "trace-456")

        # Should have empty messages but valid context
        assert isinstance(context, EnrichedContext)
        assert context.messages == []
        assert context.thread_uuid == "thread-123"

    @pytest.mark.asyncio
    async def test_handles_summaries_failure(self, orchestrator: Orchestrator) -> None:
        """Context building succeeds even if summaries query fails."""
        # Mock successful thread context
        from klabautermann.core.models import ThreadContext

        mock_thread_context = ThreadContext(
            thread_uuid="thread-123",
            channel_type=ChannelType.CLI,
            messages=[],
            max_messages=20,
        )
        orchestrator.thread_manager.get_context_window.return_value = mock_thread_context

        with patch(
            "klabautermann.agents.orchestrator.get_recent_summaries",
            side_effect=Exception("Neo4j connection lost"),
        ):
            context = await orchestrator._build_context_safe("thread-123", "trace-456")

            # Should have empty summaries but valid context
            assert isinstance(context, EnrichedContext)
            assert context.recent_summaries == []

    @pytest.mark.asyncio
    async def test_handles_multiple_failures(self, orchestrator: Orchestrator) -> None:
        """Context building succeeds even if multiple queries fail."""
        # Set thread_manager to raise exception
        orchestrator.thread_manager.get_context_window.side_effect = Exception("DB error 1")

        with (
            patch(
                "klabautermann.agents.orchestrator.get_recent_summaries",
                side_effect=Exception("DB error 2"),
            ),
            patch(
                "klabautermann.agents.orchestrator.get_pending_tasks",
                side_effect=Exception("DB error 3"),
            ),
        ):
            context = await orchestrator._build_context_safe("thread-123", "trace-456")

            # Should still return valid context with empty defaults
            assert isinstance(context, EnrichedContext)
            assert context.messages == []
            assert context.recent_summaries == []
            assert context.pending_tasks == []

    @pytest.mark.asyncio
    async def test_partial_success_returns_available_data(self, orchestrator: Orchestrator) -> None:
        """Context building returns whatever data is available."""
        # Mock successful message loading
        from klabautermann.core.models import ThreadContext

        mock_thread_context = ThreadContext(
            thread_uuid="thread-123",
            channel_type=ChannelType.CLI,
            messages=[{"role": "user", "content": "Hello"}],
            max_messages=20,
        )
        orchestrator.thread_manager.get_context_window.return_value = mock_thread_context

        # Mock failed summaries
        with patch(
            "klabautermann.agents.orchestrator.get_recent_summaries",
            side_effect=Exception("DB error"),
        ):
            context = await orchestrator._build_context_safe("thread-123", "trace-456")

            # Should have messages but no summaries
            assert len(context.messages) == 1
            assert context.recent_summaries == []


class TestFallbackDirectResponse:
    """Tests for _fallback_direct_response when task planning fails."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator."""
        return Orchestrator(graphiti=None, thread_manager=None)

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

    @pytest.mark.asyncio
    async def test_generates_direct_response(
        self, orchestrator: Orchestrator, mock_context: EnrichedContext
    ) -> None:
        """Generates response by calling Claude directly."""
        with patch.object(
            orchestrator,
            "_call_claude",
            return_value="I'm here to help!",
        ) as mock_claude:
            response = await orchestrator._fallback_direct_response(
                "How can you help me?", mock_context, "trace-456"
            )

            # Should call Claude with context
            mock_claude.assert_called_once()
            assert response == "I'm here to help!"

    @pytest.mark.asyncio
    async def test_includes_recent_context_messages(
        self, orchestrator: Orchestrator, mock_context: EnrichedContext
    ) -> None:
        """Includes recent messages for conversation continuity."""
        with patch.object(orchestrator, "_call_claude", return_value="Response") as mock_claude:
            await orchestrator._fallback_direct_response(
                "Follow up question", mock_context, "trace-456"
            )

            # Check that context messages were included
            call_args = mock_claude.call_args
            messages = call_args[0][0]

            # Should include previous messages + current message
            assert len(messages) >= 2
            assert any("Hello" in str(m) for m in messages)

    @pytest.mark.asyncio
    async def test_handles_claude_call_failure(
        self, orchestrator: Orchestrator, mock_context: EnrichedContext
    ) -> None:
        """Handles failure when Claude call itself fails."""
        with patch.object(orchestrator, "_call_claude", side_effect=Exception("API timeout")):
            response = await orchestrator._fallback_direct_response(
                "Test", mock_context, "trace-456"
            )

            # Should return error message, not raise exception
            assert "trouble processing" in response.lower()


class TestFallbackResultsSummary:
    """Tests for _fallback_results_summary when synthesis fails."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator."""
        return Orchestrator(graphiti=None, thread_manager=None)

    def test_formats_successful_results(self, orchestrator: Orchestrator) -> None:
        """Formats successful results into readable text."""
        results = {
            "Research Sarah": {
                "agent": "researcher",
                "response": "Sarah is a PM at Acme Corp",
                "task_type": "research",
            },
            "Research John": {
                "agent": "researcher",
                "response": "John is a developer",
                "task_type": "research",
            },
        }

        summary = orchestrator._fallback_results_summary(results)

        assert "Here's what I found:" in summary
        assert "Sarah is a PM" in summary
        assert "John is a developer" in summary

    def test_includes_errors_separately(self, orchestrator: Orchestrator) -> None:
        """Shows errors separately from successful results."""
        results = {
            "Research Sarah": {
                "agent": "researcher",
                "response": "Sarah is a PM",
                "task_type": "research",
            },
            "Execute email": {"error": "Recipient not found"},
        }

        summary = orchestrator._fallback_results_summary(results)

        assert "Here's what I found:" in summary
        assert "Some tasks encountered issues:" in summary
        assert "Recipient not found" in summary

    def test_handles_empty_results(self, orchestrator: Orchestrator) -> None:
        """Handles empty results gracefully."""
        summary = orchestrator._fallback_results_summary({})

        assert "couldn't find any relevant information" in summary.lower()

    def test_limits_displayed_results(self, orchestrator: Orchestrator) -> None:
        """Limits number of results to avoid overwhelming user."""
        results = {f"Task {i}": {"response": f"Result {i}"} for i in range(10)}

        summary = orchestrator._fallback_results_summary(results)

        # Should only show first 3 results (check by counting lines with "Result")
        result_count = summary.count("Result")
        assert result_count <= 3


class TestExecuteParallelSafe:
    """Tests for _execute_parallel_safe with individual failure capture."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator."""
        return Orchestrator(graphiti=None, thread_manager=None)

    @pytest.fixture
    def task_plan(self) -> TaskPlan:
        """Create sample task plan."""
        return TaskPlan(
            reasoning="Test reasoning",
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

    @pytest.mark.asyncio
    async def test_calls_execute_parallel(
        self, orchestrator: Orchestrator, task_plan: TaskPlan
    ) -> None:
        """Delegates to _execute_parallel for actual execution."""
        with patch.object(
            orchestrator,
            "_execute_parallel",
            return_value={"Find Sarah": {"response": "Sarah is a PM"}},
        ) as mock_execute:
            results = await orchestrator._execute_parallel_safe(task_plan, "trace-456")

            mock_execute.assert_called_once_with(task_plan, "trace-456")
            assert "Find Sarah" in results

    @pytest.mark.asyncio
    async def test_logs_partial_failures(
        self, orchestrator: Orchestrator, task_plan: TaskPlan
    ) -> None:
        """Logs warning when some tasks fail."""
        with patch.object(
            orchestrator,
            "_execute_parallel",
            return_value={
                "Task 1": {"response": "Success"},
                "Task 2": {"error": "Failed"},
            },
        ):
            results = await orchestrator._execute_parallel_safe(task_plan, "trace-456")

            # Should return both successful and failed results
            assert "Task 1" in results
            assert "Task 2" in results

    @pytest.mark.asyncio
    async def test_handles_total_execution_failure(
        self, orchestrator: Orchestrator, task_plan: TaskPlan
    ) -> None:
        """Returns empty dict if execution fails entirely."""
        with patch.object(
            orchestrator, "_execute_parallel", side_effect=Exception("System failure")
        ):
            results = await orchestrator._execute_parallel_safe(task_plan, "trace-456")

            # Should return empty results, not raise exception
            assert results == {}


class TestWorkflowErrorHandling:
    """Integration tests for error handling across the entire workflow."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator with mocked dependencies."""
        mock_graphiti = MagicMock()
        mock_thread_manager = AsyncMock()
        mock_neo4j = MagicMock()
        return Orchestrator(
            graphiti=mock_graphiti,
            thread_manager=mock_thread_manager,
            neo4j_client=mock_neo4j,
        )

    @pytest.mark.asyncio
    async def test_planning_failure_triggers_fallback(self, orchestrator: Orchestrator) -> None:
        """When planning fails, system falls back to direct response."""
        mock_context = EnrichedContext(
            thread_uuid="thread-123",
            channel_type=ChannelType.CLI,
            messages=[],
            recent_summaries=[],
            pending_tasks=[],
            recent_entities=[],
            relevant_islands=None,
        )

        with (
            patch.object(orchestrator, "_build_context_safe", return_value=mock_context),
            patch.object(orchestrator, "_plan_tasks", side_effect=Exception("LLM timeout")),
            patch.object(
                orchestrator,
                "_fallback_direct_response",
                return_value="Fallback response",
            ) as mock_fallback,
        ):
            response = await orchestrator.handle_user_input_v2(
                "Test message", "thread-123", "trace-456"
            )

            # Should use fallback
            mock_fallback.assert_called_once()
            assert response == "Fallback response"

    @pytest.mark.asyncio
    async def test_synthesis_failure_triggers_fallback(self, orchestrator: Orchestrator) -> None:
        """When synthesis fails, system formats raw results."""
        mock_context = EnrichedContext(
            thread_uuid="thread-123",
            channel_type=ChannelType.CLI,
            messages=[],
            recent_summaries=[],
            pending_tasks=[],
            recent_entities=[],
            relevant_islands=None,
        )

        task_plan = TaskPlan(
            reasoning="Test",
            tasks=[
                PlannedTask(
                    task_type="research",
                    description="Test task",
                    agent="researcher",
                    payload={},
                    blocking=True,
                )
            ],
        )

        results = {"Test task": {"response": "Test result"}}

        with (
            patch.object(orchestrator, "_build_context_safe", return_value=mock_context),
            patch.object(orchestrator, "_plan_tasks", return_value=task_plan),
            patch.object(orchestrator, "_execute_parallel_safe", return_value=results),
            patch.object(orchestrator, "_needs_deeper_research", return_value=False),
            patch.object(orchestrator, "_synthesize_response", side_effect=Exception("LLM error")),
            patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
            patch.object(orchestrator, "_store_response", return_value=None),
        ):
            response = await orchestrator.handle_user_input_v2("Test", "thread-123", "trace-456")

            # Should contain fallback summary
            assert "Here's what I found:" in response or "Test result" in response

    @pytest.mark.asyncio
    async def test_complete_workflow_failure_returns_error(
        self, orchestrator: Orchestrator
    ) -> None:
        """Complete workflow failure returns user-friendly error."""
        with patch.object(
            orchestrator, "_build_context_safe", side_effect=Exception("Total failure")
        ):
            response = await orchestrator.handle_user_input_v2("Test", "thread-123", "trace-456")

            # Should return error message, not crash
            assert "trouble processing" in response.lower()
            assert "try again" in response.lower()
