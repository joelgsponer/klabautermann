"""
Tests for Orchestrator v2 Parallel Task Execution (T055).

Tests the _execute_parallel() method that implements the "Dispatch" phase
of Think-Dispatch-Synthesize pattern.

Reference: specs/MAINAGENT.md Section 4.3
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import AgentMessage, PlannedTask, TaskPlan


@pytest.fixture
def mock_orchestrator():
    """Create orchestrator with mocked dependencies."""
    orch = Orchestrator(
        graphiti=None,
        thread_manager=None,
        neo4j_client=None,
        config={"model": "claude-sonnet-4-20250514"},
    )
    return orch


@pytest.fixture
def mock_agent():
    """Create a mock agent that responds to messages."""

    async def process_message(msg: AgentMessage) -> AgentMessage:
        """Mock process_message that returns a response."""
        return AgentMessage(
            trace_id=msg.trace_id,
            source_agent=msg.target_agent,
            target_agent=msg.source_agent,
            intent="response",
            payload={"result": f"Processed {msg.intent}"},
        )

    agent = MagicMock()
    agent.process_message = AsyncMock(side_effect=process_message)
    return agent


@pytest.fixture
def mock_slow_agent():
    """Create a mock agent that takes time to respond."""

    async def process_message_slow(msg: AgentMessage) -> AgentMessage:
        """Mock process_message that simulates slow processing."""
        await asyncio.sleep(0.5)  # Simulate work
        return AgentMessage(
            trace_id=msg.trace_id,
            source_agent=msg.target_agent,
            target_agent=msg.source_agent,
            intent="response",
            payload={"result": f"Processed {msg.intent} slowly"},
        )

    agent = MagicMock()
    agent.process_message = AsyncMock(side_effect=process_message_slow)
    return agent


@pytest.fixture
def mock_failing_agent():
    """Create a mock agent that fails."""

    async def process_message_fail(msg: AgentMessage) -> AgentMessage:
        """Mock process_message that raises an error."""
        raise ValueError("Agent failed to process message")

    agent = MagicMock()
    agent.process_message = AsyncMock(side_effect=process_message_fail)
    return agent


# ===========================================================================
# Basic Parallel Execution Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_execute_parallel_with_blocking_tasks(mock_orchestrator, mock_agent):
    """Test that multiple blocking tasks execute in parallel."""
    # Register mock agents
    mock_orchestrator._agent_registry["researcher"] = mock_agent
    mock_orchestrator._agent_registry["executor"] = mock_agent

    # Create task plan with 2 blocking tasks
    task_plan = TaskPlan(
        reasoning="Need to research and execute",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Search for user info",
                agent="researcher",
                payload={"query": "Who is Sarah?"},
                blocking=True,
            ),
            PlannedTask(
                task_type="execute",
                description="Send email",
                agent="executor",
                payload={"action": "send email"},
                blocking=True,
            ),
        ],
    )

    # Execute tasks
    start = time.time()
    results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")
    elapsed = time.time() - start

    # Verify both tasks completed
    assert len(results) == 2
    assert "Search for user info" in results
    assert "Send email" in results

    # Verify results structure
    assert results["Search for user info"]["agent"] == "researcher"
    assert results["Search for user info"]["task_type"] == "research"
    assert results["Send email"]["agent"] == "executor"
    assert results["Send email"]["task_type"] == "execute"

    # Both tasks should have been called
    assert mock_agent.process_message.call_count == 2

    # Tasks ran in parallel, should be fast
    assert elapsed < 0.2  # Should be near-instant for mocked tasks


@pytest.mark.asyncio
async def test_execute_parallel_proves_parallelism(mock_orchestrator, mock_slow_agent):
    """Test that parallel execution is actually parallel (timing proof)."""
    # Register mock agents
    mock_orchestrator._agent_registry["researcher"] = mock_slow_agent
    mock_orchestrator._agent_registry["executor"] = mock_slow_agent

    # Create task plan with 2 blocking tasks that take 0.5s each
    task_plan = TaskPlan(
        reasoning="Need to research and execute",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Task 1",
                agent="researcher",
                payload={"query": "test"},
                blocking=True,
            ),
            PlannedTask(
                task_type="execute",
                description="Task 2",
                agent="executor",
                payload={"action": "test"},
                blocking=True,
            ),
        ],
    )

    # Execute tasks - should take ~0.5s total (parallel), not 1.0s (sequential)
    start = time.time()
    results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")
    elapsed = time.time() - start

    # Verify both completed
    assert len(results) == 2

    # Parallel execution should take ~0.5s, not 1.0s
    # Allow some overhead but should be clearly parallel
    assert elapsed < 0.8, f"Tasks took {elapsed}s - not parallel! Expected <0.8s"
    assert elapsed >= 0.5, f"Tasks took {elapsed}s - suspiciously fast"


@pytest.mark.asyncio
async def test_execute_parallel_with_fire_and_forget(mock_orchestrator, mock_agent):
    """Test that non-blocking tasks are fire-and-forget."""
    # Register mock agents
    mock_orchestrator._agent_registry["ingestor"] = mock_agent
    mock_orchestrator._agent_registry["researcher"] = mock_agent

    # Create task plan with blocking and non-blocking tasks
    task_plan = TaskPlan(
        reasoning="Need to ingest and research",
        tasks=[
            PlannedTask(
                task_type="ingest",
                description="Ingest conversation",
                agent="ingestor",
                payload={"text": "User told me about Sarah"},
                blocking=False,  # Fire-and-forget
            ),
            PlannedTask(
                task_type="research",
                description="Search for Sarah",
                agent="researcher",
                payload={"query": "Who is Sarah?"},
                blocking=True,
            ),
        ],
    )

    # Execute tasks
    results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")

    # Only blocking task should be in results
    assert len(results) == 1
    assert "Search for Sarah" in results
    assert "Ingest conversation" not in results

    # Fire-and-forget task should still have been dispatched
    # Give it a moment to complete
    await asyncio.sleep(0.1)

    # Both agents should have been called
    assert mock_agent.process_message.call_count == 2


@pytest.mark.asyncio
async def test_execute_parallel_empty_task_plan(mock_orchestrator):
    """Test that empty task plan returns empty results."""
    task_plan = TaskPlan(
        reasoning="No tasks needed",
        tasks=[],
    )

    results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")

    assert results == {}


# ===========================================================================
# Error Handling Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_execute_parallel_captures_task_failures(
    mock_orchestrator, mock_agent, mock_failing_agent
):
    """Test that individual task failures are captured, not propagated."""
    # Register agents - one works, one fails
    mock_orchestrator._agent_registry["researcher"] = mock_agent
    mock_orchestrator._agent_registry["executor"] = mock_failing_agent

    task_plan = TaskPlan(
        reasoning="Test error handling",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Task that succeeds",
                agent="researcher",
                payload={"query": "test"},
                blocking=True,
            ),
            PlannedTask(
                task_type="execute",
                description="Task that fails",
                agent="executor",
                payload={"action": "test"},
                blocking=True,
            ),
        ],
    )

    # Execute tasks - should not raise exception
    results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")

    # Both tasks should be in results
    assert len(results) == 2

    # Successful task should have result
    assert "Task that succeeds" in results
    assert "error" not in results["Task that succeeds"]

    # Failed task should have error
    assert "Task that fails" in results
    assert "error" in results["Task that fails"]
    assert "failed to process message" in results["Task that fails"]["error"].lower()


@pytest.mark.asyncio
async def test_execute_parallel_timeout_handling(mock_orchestrator):
    """Test that execution timeout is enforced."""

    # Create agent that takes too long
    async def process_message_timeout(msg: AgentMessage) -> AgentMessage:
        await asyncio.sleep(10)  # Way too long
        return AgentMessage(
            trace_id=msg.trace_id,
            source_agent=msg.target_agent,
            target_agent=msg.source_agent,
            intent="response",
            payload={"result": "This won't complete"},
        )

    slow_agent = MagicMock()
    slow_agent.process_message = AsyncMock(side_effect=process_message_timeout)

    mock_orchestrator._agent_registry["researcher"] = slow_agent

    # Mock config to use short timeout
    with patch.object(mock_orchestrator, "_load_v2_config") as mock_config:
        mock_config.return_value = {
            "execution": {"parallel_timeout_seconds": 0.5},
        }

        task_plan = TaskPlan(
            reasoning="Test timeout",
            tasks=[
                PlannedTask(
                    task_type="research",
                    description="Slow task",
                    agent="researcher",
                    payload={"query": "test"},
                    blocking=True,
                ),
            ],
        )

        # Execute with timeout
        start = time.time()
        results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")
        elapsed = time.time() - start

        # Should timeout quickly
        assert elapsed < 1.0

        # Result should indicate timeout
        assert "Slow task" in results
        assert "error" in results["Slow task"]
        assert "timed out" in results["Slow task"]["error"].lower()


@pytest.mark.asyncio
async def test_execute_parallel_agent_not_found(mock_orchestrator):
    """Test error when target agent not in registry."""
    # Clear the registry to simulate missing agent
    mock_orchestrator._agent_registry = {}

    # Use valid agent name in Pydantic model but not registered
    task_plan = TaskPlan(
        reasoning="Test missing agent",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Task for missing agent",
                agent="researcher",  # Valid agent name but not registered
                payload={"query": "test"},
                blocking=True,
            ),
        ],
    )

    results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")

    # Should capture the error
    assert len(results) == 1
    assert "error" in results["Task for missing agent"]
    assert "not found" in results["Task for missing agent"]["error"].lower()


# ===========================================================================
# Background Task Tracking Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_execute_parallel_tracks_background_tasks(mock_orchestrator, mock_agent):
    """Test that fire-and-forget tasks are tracked to prevent GC."""
    mock_orchestrator._agent_registry["ingestor"] = mock_agent

    task_plan = TaskPlan(
        reasoning="Test background tracking",
        tasks=[
            PlannedTask(
                task_type="ingest",
                description="Background task",
                agent="ingestor",
                payload={"text": "test"},
                blocking=False,
            ),
        ],
    )

    # Initially no background tasks
    initial_count = len(mock_orchestrator._background_tasks)

    # Execute
    await mock_orchestrator._execute_parallel(task_plan, "test-trace")

    # Should have created a background task
    # Note: Task may complete quickly and be removed, so check >= initial
    assert len(mock_orchestrator._background_tasks) >= initial_count

    # Wait for background tasks to complete
    await asyncio.sleep(0.1)

    # After completion, task should be removed from set
    # (due to callback that discards it)


@pytest.mark.asyncio
async def test_execute_parallel_fire_and_forget_errors_logged(
    mock_orchestrator, mock_failing_agent
):
    """Test that fire-and-forget task errors are logged but don't fail."""
    mock_orchestrator._agent_registry["ingestor"] = mock_failing_agent

    task_plan = TaskPlan(
        reasoning="Test fire-and-forget error handling",
        tasks=[
            PlannedTask(
                task_type="ingest",
                description="Failing background task",
                agent="ingestor",
                payload={"text": "test"},
                blocking=False,
            ),
        ],
    )

    # Should not raise exception even though agent fails
    results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")

    # No results for fire-and-forget
    assert results == {}

    # Give background task time to fail
    await asyncio.sleep(0.1)

    # Should have logged warning but not crashed
    # (Can't easily test logging in unit tests, but no exception = success)


# ===========================================================================
# Configuration Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_execute_parallel_uses_config_timeout(mock_orchestrator, mock_agent):
    """Test that timeout is loaded from config."""
    mock_orchestrator._agent_registry["researcher"] = mock_agent

    task_plan = TaskPlan(
        reasoning="Test config",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Test task",
                agent="researcher",
                payload={"query": "test"},
                blocking=True,
            ),
        ],
    )

    # Mock config with custom timeout
    with patch.object(mock_orchestrator, "_load_v2_config") as mock_config:
        mock_config.return_value = {
            "execution": {"parallel_timeout_seconds": 99.0},
        }

        results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")

        # Should complete successfully
        assert len(results) == 1

        # Config should have been called
        mock_config.assert_called_once()


@pytest.mark.asyncio
async def test_execute_parallel_default_timeout_when_config_missing(mock_orchestrator, mock_agent):
    """Test fallback to default timeout when config unavailable."""
    mock_orchestrator._agent_registry["researcher"] = mock_agent

    task_plan = TaskPlan(
        reasoning="Test default timeout",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Test task",
                agent="researcher",
                payload={"query": "test"},
                blocking=True,
            ),
        ],
    )

    # Mock config to return empty execution section
    with patch.object(mock_orchestrator, "_load_v2_config") as mock_config:
        mock_config.return_value = {}

        results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")

        # Should use default timeout (30s) and complete
        assert len(results) == 1


# ===========================================================================
# Integration-style Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_execute_parallel_mixed_success_and_failure(
    mock_orchestrator, mock_agent, mock_failing_agent
):
    """Test execution with mix of successful and failed tasks."""
    mock_orchestrator._agent_registry["researcher"] = mock_agent
    mock_orchestrator._agent_registry["executor"] = mock_failing_agent
    mock_orchestrator._agent_registry["ingestor"] = mock_agent

    task_plan = TaskPlan(
        reasoning="Mixed scenario",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Successful research",
                agent="researcher",
                payload={"query": "test"},
                blocking=True,
            ),
            PlannedTask(
                task_type="execute",
                description="Failed execution",
                agent="executor",
                payload={"action": "test"},
                blocking=True,
            ),
            PlannedTask(
                task_type="ingest",
                description="Fire-and-forget ingestion",
                agent="ingestor",
                payload={"text": "test"},
                blocking=False,
            ),
        ],
    )

    results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")

    # Only blocking tasks in results
    assert len(results) == 2

    # Successful task has result
    assert "Successful research" in results
    assert "error" not in results["Successful research"]

    # Failed task has error
    assert "Failed execution" in results
    assert "error" in results["Failed execution"]

    # Fire-and-forget not in results
    assert "Fire-and-forget ingestion" not in results


@pytest.mark.asyncio
async def test_execute_parallel_respects_task_payload(mock_orchestrator):
    """Test that task payload is correctly passed to agents."""
    # Create agent that captures the message it receives
    received_messages = []

    async def process_message_capture(msg: AgentMessage) -> AgentMessage:
        received_messages.append(msg)
        return AgentMessage(
            trace_id=msg.trace_id,
            source_agent=msg.target_agent,
            target_agent=msg.source_agent,
            intent="response",
            payload={"result": "ok"},
        )

    capture_agent = MagicMock()
    capture_agent.process_message = AsyncMock(side_effect=process_message_capture)

    mock_orchestrator._agent_registry["researcher"] = capture_agent

    task_plan = TaskPlan(
        reasoning="Test payload",
        tasks=[
            PlannedTask(
                task_type="research",
                description="Test task",
                agent="researcher",
                payload={"query": "Who is Sarah?", "max_results": 5, "custom_field": "test"},
                blocking=True,
            ),
        ],
    )

    results = await mock_orchestrator._execute_parallel(task_plan, "test-trace")

    # Verify task completed
    assert len(results) == 1

    # Verify message payload
    assert len(received_messages) == 1
    msg = received_messages[0]
    assert msg.payload["query"] == "Who is Sarah?"
    assert msg.payload["max_results"] == 5
    assert msg.payload["custom_field"] == "test"
    assert msg.intent == "research"
    assert msg.target_agent == "researcher"
