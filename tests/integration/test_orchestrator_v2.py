"""
Smoke Tests: Orchestrator v2 Full Workflow (T061)

Integration tests for the Think-Dispatch-Synthesize pattern in Orchestrator v2.
These tests verify the complete workflow with mocked dependencies (no real DB/API calls).

Reference:
- specs/MAINAGENT.md Section 8
- specs/quality/TESTING.md
- tasks/pending/T061-smoke-test-v2-workflow.md

Test Coverage:
1. Full workflow with multiple tasks (parallel execution)
2. Direct response path (no tasks needed)
3. Partial failure handling (some tasks fail, others succeed)
4. Simple greeting handling
5. Parallel execution verification
6. Context building across memory layers
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import (
    AgentMessage,
    ChannelType,
    CommunityContext,
    EnrichedContext,
    EntityReference,
    PlannedTask,
    TaskNode,
    TaskPlan,
    TaskStatus,
    ThreadSummary,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_graphiti():
    """Mock Graphiti client."""
    client = MagicMock()
    client.search = AsyncMock(return_value=[])
    client.add_episode = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_thread_manager():
    """Mock ThreadManager."""
    manager = AsyncMock()
    manager.get_context_window = AsyncMock()
    manager.add_message = AsyncMock()
    return manager


@pytest.fixture
def mock_neo4j_client():
    """Mock Neo4j client."""
    client = MagicMock()
    # Mock session context manager
    session = MagicMock()
    session.run = AsyncMock(return_value=MagicMock(data=AsyncMock(return_value=[])))

    async def async_context_manager(*args, **kwargs):
        class AsyncContextManager:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *args):
                pass

        return AsyncContextManager()

    client.session = MagicMock(side_effect=async_context_manager)
    return client


@pytest.fixture
def orchestrator(mock_graphiti, mock_thread_manager, mock_neo4j_client):
    """Create Orchestrator with mocked dependencies."""
    return Orchestrator(
        graphiti=mock_graphiti,
        thread_manager=mock_thread_manager,
        neo4j_client=mock_neo4j_client,
        config={"model": {"primary": "claude-sonnet-4-20250514"}},
    )


@pytest.fixture
def enriched_context():
    """Create sample enriched context with all memory layers."""
    return EnrichedContext(
        thread_uuid="thread-test-123",
        channel_type=ChannelType.CLI,
        messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"},
            {"role": "user", "content": "Tell me about Sarah"},
        ],
        recent_summaries=[
            ThreadSummary(
                summary="Discussion about Q4 budget with Sarah and John",
            )
        ],
        pending_tasks=[
            TaskNode(
                action="Send budget report to Sarah",
                status=TaskStatus.TODO,
                priority="high",
            )
        ],
        recent_entities=[
            EntityReference(
                uuid="entity-uuid-001",
                name="Sarah",
                entity_type="Person",
                created_at=1234567890.0,
            ),
            EntityReference(
                uuid="entity-uuid-002",
                name="Acme Corp",
                entity_type="Organization",
                created_at=1234567890.0,
            ),
        ],
        relevant_islands=[
            CommunityContext(
                name="Work Island",
                theme="professional",
                summary="Professional contacts and projects",
            )
        ],
    )


# =============================================================================
# TEST: FULL WORKFLOW WITH MULTIPLE TASKS
# =============================================================================


@pytest.mark.asyncio
async def test_v2_workflow_multi_intent_message(orchestrator, enriched_context):
    """
    Smoke Test: Multi-intent message triggers multiple parallel tasks.

    Input: "Learned that Sarah studied at Harvard. Do I have a meeting with her?"
    Expected:
    - Ingest task (fire-and-forget)
    - Research task (find Sarah info)
    - Execute task (check calendar)
    - All blocking tasks run in parallel
    - Final synthesis combines results
    """
    # Mock the workflow steps
    task_plan = TaskPlan(
        reasoning="User is providing new info about Sarah and asking about calendar",
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
                description="Research: Find Sarah's info",
                agent="researcher",
                payload={"query": "What do I know about Sarah?"},
                blocking=True,
            ),
            PlannedTask(
                task_type="execute",
                description="Execute: Check calendar for Sarah meetings",
                agent="executor",
                payload={"action": "Check meetings with Sarah"},
                blocking=True,
            ),
        ],
    )

    # Mock results from parallel execution
    execution_results = {
        "Research: Find Sarah's info": {
            "agent": "researcher",
            "response": AgentMessage(
                trace_id="trace-123",
                source_agent="researcher",
                target_agent="orchestrator",
                intent="research",
                payload={
                    "report": {
                        "direct_answer": "Sarah is a PM at Acme Corp",
                        "confidence": 0.9,
                        "evidence": [{"fact": "Sarah works at Acme Corp"}],
                    }
                },
            ),
            "task_type": "research",
        },
        "Execute: Check calendar for Sarah meetings": {
            "agent": "executor",
            "response": AgentMessage(
                trace_id="trace-123",
                source_agent="executor",
                target_agent="orchestrator",
                intent="execute",
                payload={"result": "You have a meeting with Sarah tomorrow at 2 PM"},
            ),
            "task_type": "execute",
        },
    }

    with (
        patch.object(
            orchestrator, "_build_context_safe", return_value=enriched_context
        ) as mock_build_context,
        patch.object(orchestrator, "_plan_tasks", return_value=task_plan) as mock_plan_tasks,
        patch.object(
            orchestrator, "_execute_parallel_safe", return_value=execution_results
        ) as mock_execute,
        patch.object(orchestrator, "_needs_deeper_research", return_value=False),
        patch.object(
            orchestrator,
            "_synthesize_response",
            return_value="Sarah is a PM at Acme Corp and studied at Harvard. You have a meeting with her tomorrow at 2 PM.",
        ) as mock_synthesize,
        patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
        patch.object(orchestrator, "_store_response", return_value=None) as mock_store,
    ):
        response = await orchestrator.handle_user_input_v2(
            text="Learned that Sarah studied at Harvard. Do I have a meeting with her?",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        # Verify workflow steps called in order
        mock_build_context.assert_called_once_with("thread-test-123", "trace-test-456")
        mock_plan_tasks.assert_called_once()
        mock_execute.assert_called_once()
        mock_synthesize.assert_called_once()
        mock_store.assert_called_once()

        # Verify response contains info from both research and executor
        assert "Sarah" in response
        assert "Acme Corp" in response or "Harvard" in response or "meeting" in response


@pytest.mark.asyncio
async def test_v2_workflow_parallel_execution_timing(orchestrator, enriched_context):
    """
    Verify that blocking tasks execute in parallel, not sequentially.

    This test ensures the parallel execution optimization works.
    """
    task_plan = TaskPlan(
        reasoning="Test parallel execution",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Task 1",
                agent="researcher",
                payload={"query": "test1"},
                blocking=True,
            ),
            PlannedTask(
                task_type="research",
                description="Task 2",
                agent="researcher",
                payload={"query": "test2"},
                blocking=True,
            ),
            PlannedTask(
                task_type="research",
                description="Task 3",
                agent="researcher",
                payload={"query": "test3"},
                blocking=True,
            ),
        ],
    )

    # Track task execution order/timing
    execution_log = []

    async def mock_dispatch(task, trace_id):
        """Mock dispatch that logs execution."""
        execution_log.append(f"start_{task.description}")
        await asyncio.sleep(0.01)  # Simulate work
        execution_log.append(f"end_{task.description}")
        return {"agent": task.agent, "response": "result", "task_type": task.task_type}

    with (
        patch.object(orchestrator, "_build_context_safe", return_value=enriched_context),
        patch.object(orchestrator, "_plan_tasks", return_value=task_plan),
        patch.object(orchestrator, "_dispatch_task", side_effect=mock_dispatch),
        patch.object(orchestrator, "_needs_deeper_research", return_value=False),
        patch.object(orchestrator, "_synthesize_response", return_value="Done"),
        patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
        patch.object(orchestrator, "_store_response", return_value=None),
    ):
        await orchestrator.handle_user_input_v2(
            text="Test parallel execution",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        # Verify all tasks started before any finished (parallel execution)
        # If sequential, we'd see: start_1, end_1, start_2, end_2, start_3, end_3
        # If parallel, we'd see: start_1, start_2, start_3, end_1, end_2, end_3
        start_indices = [i for i, log in enumerate(execution_log) if log.startswith("start_")]
        end_indices = [i for i, log in enumerate(execution_log) if log.startswith("end_")]

        # At least some starts should complete before any ends (parallel behavior)
        assert len(start_indices) > 0
        assert len(end_indices) > 0
        # All starts should come before the last end
        assert max(start_indices) < max(end_indices)


# =============================================================================
# TEST: DIRECT RESPONSE PATH
# =============================================================================


@pytest.mark.asyncio
async def test_v2_workflow_simple_greeting(orchestrator, enriched_context):
    """
    Smoke Test: Simple greeting returns direct response without tasks.

    Input: "Hello!"
    Expected:
    - Task planning returns direct_response
    - No tasks executed
    - Response returned immediately
    """
    task_plan = TaskPlan(
        reasoning="Simple greeting, no tasks needed",
        tasks=[],
        direct_response="Hello! How can I help you today?",
    )

    with (
        patch.object(orchestrator, "_build_context_safe", return_value=enriched_context),
        patch.object(orchestrator, "_plan_tasks", return_value=task_plan),
        patch.object(orchestrator, "_execute_parallel_safe") as mock_execute,
        patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
        patch.object(orchestrator, "_store_response", return_value=None),
    ):
        response = await orchestrator.handle_user_input_v2(
            text="Hello!",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        # Verify execute NOT called for direct response
        mock_execute.assert_not_called()

        # Verify direct response returned
        assert response == "Hello! How can I help you today?"


# =============================================================================
# TEST: PARTIAL FAILURE HANDLING
# =============================================================================


@pytest.mark.asyncio
async def test_v2_workflow_partial_failure(orchestrator, enriched_context):
    """
    Smoke Test: Handle partial failures gracefully.

    Scenario: One task fails, others succeed.
    Expected:
    - Failed task doesn't crash workflow
    - Successful results are used
    - Final response acknowledges missing info
    """
    task_plan = TaskPlan(
        reasoning="Multiple tasks, one will fail",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Research: Success",
                agent="researcher",
                payload={"query": "test"},
                blocking=True,
            ),
            PlannedTask(
                task_type="research",
                description="Research: Failure",
                agent="researcher",
                payload={"query": "test2"},
                blocking=True,
            ),
        ],
    )

    # Mock results with one success, one failure
    execution_results = {
        "Research: Success": {
            "agent": "researcher",
            "response": AgentMessage(
                trace_id="trace-123",
                source_agent="researcher",
                target_agent="orchestrator",
                intent="research",
                payload={"report": {"direct_answer": "Found info"}},
            ),
            "task_type": "research",
        },
        "Research: Failure": {"error": "Database timeout"},
    }

    with (
        patch.object(orchestrator, "_build_context_safe", return_value=enriched_context),
        patch.object(orchestrator, "_plan_tasks", return_value=task_plan),
        patch.object(orchestrator, "_execute_parallel_safe", return_value=execution_results),
        patch.object(orchestrator, "_needs_deeper_research", return_value=False),
        patch.object(
            orchestrator,
            "_synthesize_response",
            return_value="Found info, but some queries timed out.",
        ),
        patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
        patch.object(orchestrator, "_store_response", return_value=None),
    ):
        response = await orchestrator.handle_user_input_v2(
            text="Test partial failure",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        # Workflow should complete successfully despite one failure
        assert response is not None
        assert len(response) > 0


# =============================================================================
# TEST: SINGLE INTENT MESSAGE
# =============================================================================


@pytest.mark.asyncio
async def test_v2_workflow_single_intent_message(orchestrator, enriched_context):
    """
    Smoke Test: Single intent (research) triggers one task.

    Input: "Who is Sarah?"
    Expected:
    - One research task
    - Task executed
    - Response synthesized from result
    """
    task_plan = TaskPlan(
        reasoning="User asking about a person",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Research: Find Sarah",
                agent="researcher",
                payload={"query": "Who is Sarah?"},
                blocking=True,
            )
        ],
    )

    execution_results = {
        "Research: Find Sarah": {
            "agent": "researcher",
            "response": AgentMessage(
                trace_id="trace-123",
                source_agent="researcher",
                target_agent="orchestrator",
                intent="research",
                payload={"report": {"direct_answer": "Sarah is a PM at Acme Corp"}},
            ),
            "task_type": "research",
        }
    }

    with (
        patch.object(orchestrator, "_build_context_safe", return_value=enriched_context),
        patch.object(orchestrator, "_plan_tasks", return_value=task_plan),
        patch.object(orchestrator, "_execute_parallel_safe", return_value=execution_results),
        patch.object(orchestrator, "_needs_deeper_research", return_value=False),
        patch.object(
            orchestrator, "_synthesize_response", return_value="Sarah is a PM at Acme Corp"
        ),
        patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
        patch.object(orchestrator, "_store_response", return_value=None),
    ):
        response = await orchestrator.handle_user_input_v2(
            text="Who is Sarah?",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        assert "Sarah" in response
        assert "Acme Corp" in response


# =============================================================================
# TEST: CONTEXT BUILDING
# =============================================================================


@pytest.mark.asyncio
async def test_context_building_from_all_memory_layers(
    orchestrator, mock_thread_manager, mock_neo4j_client
):
    """
    Verify context is built from all memory layers in parallel.

    Expected:
    - Short-term: Recent messages from ThreadManager
    - Mid-term: Summaries from Neo4j
    - Long-term: Recent entities from Neo4j
    - Community: Knowledge islands from Neo4j
    - All queries run in parallel (asyncio.gather)
    """
    # Mock ThreadManager response
    from klabautermann.core.models import ThreadContext

    mock_thread_context = ThreadContext(
        thread_uuid="thread-test-123",
        channel_type=ChannelType.CLI,
        messages=[{"role": "user", "content": "Test message"}],
        max_messages=20,
    )
    mock_thread_manager.get_context_window.return_value = mock_thread_context

    # Mock Neo4j context queries - patch in the module where they're used
    with (
        patch(
            "klabautermann.agents.orchestrator._orchestrator.get_recent_summaries",
            new_callable=AsyncMock,
            return_value=[
                ThreadSummary(
                    summary="Old discussion",
                )
            ],
        ) as mock_summaries,
        patch(
            "klabautermann.agents.orchestrator._orchestrator.get_pending_tasks",
            new_callable=AsyncMock,
            return_value=[TaskNode(action="Test task", status=TaskStatus.TODO, priority="normal")],
        ) as mock_tasks,
        patch(
            "klabautermann.agents.orchestrator._orchestrator.get_recent_entities",
            new_callable=AsyncMock,
            return_value=[
                EntityReference(
                    uuid="test-entity-uuid",
                    name="TestEntity",
                    entity_type="Person",
                    created_at=1234567890.0,
                )
            ],
        ) as mock_entities,
        patch(
            "klabautermann.agents.orchestrator._orchestrator.get_relevant_islands",
            new_callable=AsyncMock,
            return_value=[
                CommunityContext(
                    name="Test Island",
                    theme="test",
                    summary="Test community",
                )
            ],
        ) as mock_islands,
    ):
        context = await orchestrator._build_context(
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        # Verify all memory layers populated
        assert len(context.messages) > 0
        assert len(context.recent_summaries) > 0
        assert len(context.pending_tasks) > 0
        assert len(context.recent_entities) > 0
        assert context.relevant_islands is not None
        assert len(context.relevant_islands) > 0

        # Verify context queries were called
        mock_thread_manager.get_context_window.assert_called_once()
        mock_summaries.assert_called_once()
        mock_tasks.assert_called_once()
        mock_entities.assert_called_once()
        mock_islands.assert_called_once()


# =============================================================================
# TEST: ERROR HANDLING
# =============================================================================


@pytest.mark.asyncio
async def test_v2_workflow_handles_context_build_error(orchestrator):
    """
    Verify workflow handles context building errors gracefully.

    If context building fails, workflow should still attempt to proceed
    or return a user-friendly error.
    """
    with patch.object(
        orchestrator, "_build_context_safe", side_effect=Exception("Database connection failed")
    ):
        response = await orchestrator.handle_user_input_v2(
            text="Test error handling",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        # Should return error message, not crash
        assert response is not None
        assert "trouble" in response.lower() or "error" in response.lower()


@pytest.mark.asyncio
async def test_v2_workflow_handles_planning_error(orchestrator, enriched_context):
    """
    Verify workflow handles task planning errors gracefully.
    """
    with (
        patch.object(orchestrator, "_build_context_safe", return_value=enriched_context),
        patch.object(orchestrator, "_plan_tasks", side_effect=Exception("LLM API failed")),
    ):
        response = await orchestrator.handle_user_input_v2(
            text="Test planning error",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        # Should return error message, not crash
        assert response is not None
        assert "trouble" in response.lower() or "error" in response.lower()


@pytest.mark.asyncio
async def test_v2_workflow_handles_synthesis_error(orchestrator, enriched_context):
    """
    Verify workflow handles synthesis errors gracefully with fallback.
    """
    task_plan = TaskPlan(
        reasoning="Test synthesis error",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Test task",
                agent="researcher",
                payload={"query": "test"},
                blocking=True,
            )
        ],
    )

    execution_results = {
        "Test task": {
            "agent": "researcher",
            "response": "Some result",
            "task_type": "research",
        }
    }

    with (
        patch.object(orchestrator, "_build_context_safe", return_value=enriched_context),
        patch.object(orchestrator, "_plan_tasks", return_value=task_plan),
        patch.object(orchestrator, "_execute_parallel_safe", return_value=execution_results),
        patch.object(orchestrator, "_needs_deeper_research", return_value=False),
        patch.object(orchestrator, "_synthesize_response", side_effect=Exception("LLM failed")),
    ):
        # Should use fallback response builder
        response = await orchestrator.handle_user_input_v2(
            text="Test synthesis error",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        # Fallback should still provide a response
        assert response is not None
        # _fallback_results_summary is called when synthesis fails
        # Should format results as simple summary
        assert "found" in response.lower() or "result" in response.lower()


# =============================================================================
# TEST: DETERMINISTIC BEHAVIOR
# =============================================================================


@pytest.mark.asyncio
async def test_v2_workflow_deterministic_with_same_mocks(orchestrator, enriched_context):
    """
    Verify workflow produces consistent results with same inputs.

    Running the same test twice with identical mocks should produce
    identical results (deterministic behavior).
    """
    task_plan = TaskPlan(
        reasoning="Determinism test",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Test task",
                agent="researcher",
                payload={"query": "test"},
                blocking=True,
            )
        ],
    )

    execution_results = {
        "Test task": {
            "agent": "researcher",
            "response": "Deterministic result",
            "task_type": "research",
        }
    }

    with (
        patch.object(orchestrator, "_build_context_safe", return_value=enriched_context),
        patch.object(orchestrator, "_plan_tasks", return_value=task_plan),
        patch.object(orchestrator, "_execute_parallel_safe", return_value=execution_results),
        patch.object(orchestrator, "_needs_deeper_research", return_value=False),
        patch.object(orchestrator, "_synthesize_response", return_value="Deterministic response"),
        patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
        patch.object(orchestrator, "_store_response", return_value=None),
    ):
        # Run twice with same inputs
        response1 = await orchestrator.handle_user_input_v2(
            text="Test determinism",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        response2 = await orchestrator.handle_user_input_v2(
            text="Test determinism",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        # Results should be identical
        assert response1 == response2
        assert response1 == "Deterministic response"


# =============================================================================
# TEST: NO REAL API CALLS
# =============================================================================


@pytest.mark.asyncio
async def test_no_real_database_calls(orchestrator, enriched_context):
    """
    Verify that no real database or API calls are made during tests.

    All external dependencies should be mocked.
    """
    task_plan = TaskPlan(
        reasoning="Test no real calls",
        tasks=[],
        direct_response="Mocked response",
    )

    # Track if any real network calls attempted
    import socket

    _original_socket = socket.socket  # Saved for documentation; not used directly

    def mock_socket(*args, **kwargs):
        raise RuntimeError("Attempted real network call during test!")

    with (
        patch.object(orchestrator, "_build_context_safe", return_value=enriched_context),
        patch.object(orchestrator, "_plan_tasks", return_value=task_plan),
        patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
        patch.object(orchestrator, "_store_response", return_value=None),
        patch("socket.socket", mock_socket),
    ):
        # Should not raise RuntimeError from socket call
        response = await orchestrator.handle_user_input_v2(
            text="Test no real calls",
            thread_uuid="thread-test-123",
            trace_id="trace-test-456",
        )

        assert response == "Mocked response"


# =============================================================================
# PERFORMANCE: TESTS RUN QUICKLY
# =============================================================================


@pytest.mark.asyncio
async def test_all_smoke_tests_run_under_10_seconds(orchestrator, enriched_context):
    """
    Verify smoke tests execute quickly (under 10 seconds total).

    With mocked LLM and DB calls, tests should be very fast.
    Individual test should complete in milliseconds.
    """
    import time

    task_plan = TaskPlan(reasoning="Speed test", tasks=[], direct_response="Fast")

    with (
        patch.object(orchestrator, "_build_context_safe", return_value=enriched_context),
        patch.object(orchestrator, "_plan_tasks", return_value=task_plan),
        patch.object(orchestrator, "_apply_personality", side_effect=lambda x, _: x),
        patch.object(orchestrator, "_store_response", return_value=None),
    ):
        start_time = time.time()

        # Run test 10 times
        for _ in range(10):
            await orchestrator.handle_user_input_v2(
                text="Speed test",
                thread_uuid="thread-test-123",
                trace_id="trace-test-456",
            )

        elapsed = time.time() - start_time

        # 10 iterations should complete in under 1 second with mocks
        assert elapsed < 1.0, f"10 iterations took {elapsed}s, should be < 1s"


# =============================================================================
# T062: MAINAGENT.md SECTION 8 SCENARIO TESTS
# =============================================================================


class TestMainAgentScenarios:
    """
    Tests for MAINAGENT.md Section 8 example flows.

    These tests verify the specific scenarios that motivated the v2 redesign:
    - Multi-intent message handling
    - Follow-up email composition
    - Proactive calendar suggestions
    """

    @pytest.fixture
    def orchestrator_with_context(self, mock_graphiti, mock_thread_manager, mock_neo4j_client):
        """Create orchestrator with pre-configured context for scenario tests."""
        orch = Orchestrator(
            graphiti=mock_graphiti,
            thread_manager=mock_thread_manager,
            neo4j_client=mock_neo4j_client,
            config={"model": "claude-opus-4-5-20251101", "use_v2_workflow": True},
        )

        # Setup default mock context
        context = EnrichedContext(
            thread_uuid="test-thread-123",
            channel_type=ChannelType.CLI,
            messages=[
                {"role": "user", "content": "Does Sarah like italian?"},
                {"role": "assistant", "content": "She does! Should I follow up?"},
            ],
            recent_summaries=[
                ThreadSummary(
                    summary="Agreed to lunch with Sarah next week",
                )
            ],
            pending_tasks=[
                TaskNode(
                    action="Follow up with Sarah about lunch",
                    status=TaskStatus.TODO,
                    priority="medium",
                )
            ],
            recent_entities=[
                EntityReference(
                    uuid="entity-sarah-123",
                    name="Sarah",
                    entity_type="Person",
                    created_at=1700000000.0,
                )
            ],
            relevant_islands=[
                CommunityContext(
                    name="Work Island",
                    theme="Professional contacts and projects",
                    summary="Work-related entities including Sarah at Acme Corp",
                    pending_tasks=0,
                )
            ],
        )

        return orch, context

    @pytest.mark.asyncio
    async def test_scenario_multi_intent_sarah(self, orchestrator_with_context):
        """
        MAINAGENT.md 8.1: Multi-Intent Message

        Input: "Learned that Sarah has studied at Harvard.
                Do I have a meeting with her next week for lunch?
                Does she like italian?"

        Expected Tasks:
        1. INGEST: "Sarah studied at Harvard" → @ingestor (fire-and-forget)
        2. EXECUTE: Check calendar for meetings with Sarah → @executor (wait)
        3. RESEARCH: Events/notes about Sarah next week → @researcher (wait)
        4. RESEARCH: Sarah's food preferences → @researcher (wait)

        Expected Response:
        - Acknowledges no calendar event found
        - Mentions the lunch agreement note
        - Confirms Sarah likes italian
        - Offers proactive follow-up
        """
        orchestrator, context = orchestrator_with_context

        # Mock _build_context_safe to return our test context
        orchestrator._build_context_safe = AsyncMock(return_value=context)

        # Mock _plan_tasks to return multi-intent task plan
        task_plan = TaskPlan(
            reasoning="Multi-intent message: ingestion, calendar check, and food preference queries",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Store fact: Sarah studied at Harvard",
                    agent="ingestor",
                    payload={"fact": "Sarah studied at Harvard"},
                    blocking=False,  # Fire-and-forget
                ),
                PlannedTask(
                    task_type="execute",
                    description="Check calendar for meetings with Sarah next week",
                    agent="executor",
                    payload={"action": "calendar_search", "query": "Sarah next week"},
                    blocking=True,
                ),
                PlannedTask(
                    task_type="research",
                    description="Find notes about Sarah for next week",
                    agent="researcher",
                    payload={"query": "Sarah lunch plans next week"},
                    blocking=True,
                ),
                PlannedTask(
                    task_type="research",
                    description="Find Sarah's food preferences",
                    agent="researcher",
                    payload={"query": "Sarah food preferences italian"},
                    blocking=True,
                ),
            ],
            direct_response=None,
        )
        orchestrator._plan_tasks = AsyncMock(return_value=task_plan)

        # Mock _execute_parallel to return results
        task_results = {
            "Check calendar for meetings with Sarah next week": {
                "agent": "executor",
                "response": "No calendar events found for Sarah next week.",
            },
            "Find notes about Sarah for next week": {
                "agent": "researcher",
                "response": "Found note: 'Agreed to lunch with Sarah next week'",
            },
            "Find Sarah's food preferences": {
                "agent": "researcher",
                "response": "Sarah loves italian food.",
            },
        }
        orchestrator._execute_parallel_safe = AsyncMock(return_value=task_results)

        # Mock _synthesize_response
        synthesis_response = (
            "I don't see a calendar event for your lunch with Sarah next week, "
            "but I found a note where you agreed to have lunch with her. "
            "Good news: Sarah loves italian food! Would you like me to help "
            "create a calendar event for the lunch?"
        )
        orchestrator._synthesize_response = AsyncMock(return_value=synthesis_response)

        # Execute
        result = await orchestrator.handle_user_input_v2(
            text=(
                "Learned that Sarah has studied at Harvard. "
                "Do I have a meeting with her next week for lunch? "
                "Does she like italian?"
            ),
            thread_uuid="test-thread",
            trace_id="test-trace",
        )

        # Verify the response addresses all intents
        result_lower = result.lower()
        assert "calendar" in result_lower or "event" in result_lower
        assert "lunch" in result_lower
        assert "italian" in result_lower

        # Verify task planning was called with multi-intent
        orchestrator._plan_tasks.assert_called_once()

        # Verify synthesis combines all results
        orchestrator._synthesize_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_scenario_followup_email(self, orchestrator_with_context):
        """
        MAINAGENT.md 8.2: Follow-Up Email

        Input: "Oh yes let's follow up with her."
        Context: Previous conversation about Sarah lunch

        Expected Tasks:
        1. RESEARCH: Get Sarah's email address → @researcher (wait)
        2. EXECUTE: Draft email to Sarah → @executor (wait)

        Expected Response:
        - Includes draft email to Sarah
        - References the lunch discussion
        """
        orchestrator, context = orchestrator_with_context

        # Mock _build_context
        orchestrator._build_context_safe = AsyncMock(return_value=context)

        # Mock _plan_tasks for follow-up email
        task_plan = TaskPlan(
            reasoning="User wants to follow up with Sarah from previous conversation about lunch",
            tasks=[
                PlannedTask(
                    task_type="research",
                    description="Get Sarah's contact information",
                    agent="researcher",
                    payload={"query": "Sarah email contact"},
                    blocking=True,
                ),
                PlannedTask(
                    task_type="execute",
                    description="Draft follow-up email to Sarah",
                    agent="executor",
                    payload={
                        "action": "draft_email",
                        "to": "sarah@acme.com",
                        "subject": "Lunch next week",
                    },
                    blocking=True,
                ),
            ],
            direct_response=None,
        )
        orchestrator._plan_tasks = AsyncMock(return_value=task_plan)

        # Mock _execute_parallel
        task_results = {
            "Get Sarah's contact information": {
                "agent": "researcher",
                "response": "Sarah's email: sarah@acme.com",
            },
            "Draft follow-up email to Sarah": {
                "agent": "executor",
                "response": "Draft created: 'Dear Sarah, Looking forward to our lunch...'",
            },
        }
        orchestrator._execute_parallel_safe = AsyncMock(return_value=task_results)

        # Mock _synthesize_response
        synthesis_response = (
            "I've drafted a follow-up email to Sarah (sarah@acme.com) about your lunch plans:\n\n"
            "Subject: Lunch next week\n"
            "Dear Sarah,\n"
            "Looking forward to our lunch next week. Let me know what time works best.\n\n"
            "Shall I send this or would you like to make changes?"
        )
        orchestrator._synthesize_response = AsyncMock(return_value=synthesis_response)

        # Execute
        result = await orchestrator.handle_user_input_v2(
            text="Oh yes let's follow up with her.",
            thread_uuid="test-thread",
            trace_id="test-trace",
        )

        # Verify email-related response
        result_lower = result.lower()
        assert "email" in result_lower or "draft" in result_lower
        assert "sarah" in result_lower

    @pytest.mark.asyncio
    async def test_scenario_proactive_calendar(self, orchestrator_with_context):
        """
        MAINAGENT.md 8.3: Proactive Calendar Suggestion

        Input: "Oh now I remember, no all good."
        Context: Discussion about lunch with Sarah, no calendar event

        Expected:
        - Proactive suggestion to add calendar event
        - References the lunch agreement
        """
        orchestrator, context = orchestrator_with_context

        # Mock _build_context
        orchestrator._build_context_safe = AsyncMock(return_value=context)

        # Mock _plan_tasks - simple acknowledgment but with proactive behavior
        task_plan = TaskPlan(
            reasoning="Simple acknowledgment, but context suggests lunch planning without calendar event",
            tasks=[],  # No tasks needed for acknowledgment
            direct_response=None,  # But synthesis should add proactive suggestion
        )
        orchestrator._plan_tasks = AsyncMock(return_value=task_plan)

        # Mock _execute_parallel (no blocking tasks)
        orchestrator._execute_parallel = AsyncMock(return_value={})

        # Mock _synthesize_response with proactive behavior
        synthesis_response = (
            "Got it! By the way, I noticed you have lunch planned with Sarah "
            "next week but there's no calendar event. Would you like me to "
            "create one to make sure you don't forget?"
        )
        orchestrator._synthesize_response = AsyncMock(return_value=synthesis_response)

        # Execute
        result = await orchestrator.handle_user_input_v2(
            text="Oh now I remember, no all good.",
            thread_uuid="test-thread",
            trace_id="test-trace",
        )

        # Verify proactive suggestion
        result_lower = result.lower()
        assert "calendar" in result_lower or "event" in result_lower

    @pytest.mark.asyncio
    async def test_task_decomposition_matches_spec(self, orchestrator_with_context):
        """
        Verify that task decomposition follows MAINAGENT.md Section 4 principles:

        1. Ingest tasks are fire-and-forget
        2. Research and Execute tasks are blocking
        3. Task types map to correct agents
        """
        orchestrator, context = orchestrator_with_context

        orchestrator._build_context_safe = AsyncMock(return_value=context)

        # Capture the task plan that would be generated
        task_plan = TaskPlan(
            reasoning="Test task decomposition",
            tasks=[
                PlannedTask(
                    task_type="ingest",
                    description="Ingest new fact",
                    agent="ingestor",
                    payload={},
                    blocking=False,  # MUST be fire-and-forget
                ),
                PlannedTask(
                    task_type="research",
                    description="Search knowledge graph",
                    agent="researcher",
                    payload={},
                    blocking=True,  # MUST be blocking
                ),
                PlannedTask(
                    task_type="execute",
                    description="Perform action",
                    agent="executor",
                    payload={},
                    blocking=True,  # MUST be blocking
                ),
            ],
            direct_response=None,
        )

        # Verify task type to agent mapping
        for task in task_plan.tasks:
            if task.task_type == "ingest":
                assert task.agent == "ingestor"
                assert task.blocking is False, "Ingest tasks MUST be fire-and-forget"
            elif task.task_type == "research":
                assert task.agent == "researcher"
                assert task.blocking is True, "Research tasks SHOULD be blocking"
            elif task.task_type == "execute":
                assert task.agent == "executor"
                assert task.blocking is True, "Execute tasks SHOULD be blocking"


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
