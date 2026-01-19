"""
Unit tests for background task tracking in Orchestrator.

Tests verify that fire-and-forget tasks are properly tracked to prevent
garbage collection, and that task lifecycle (completion, failure, shutdown)
is correctly handled.

Reference: T074 - Background Task Tracking
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from klabautermann.agents.orchestrator import Orchestrator


@pytest.fixture
def orchestrator():
    """Create orchestrator with mocked dependencies."""
    graphiti = MagicMock()
    thread_manager = MagicMock()
    neo4j_client = MagicMock()
    config = {"model": {"primary": "claude-sonnet-4-20250514"}}

    return Orchestrator(
        graphiti=graphiti,
        thread_manager=thread_manager,
        neo4j_client=neo4j_client,
        config=config,
    )


@pytest.mark.asyncio
async def test_track_background_task_adds_to_set(orchestrator):
    """Test that _track_background_task adds task to the background set."""

    async def dummy_coro():
        await asyncio.sleep(0.1)
        return "done"

    task = orchestrator._track_background_task(
        dummy_coro(),
        trace_id="test-123",
        task_name="test-task",
    )

    assert task in orchestrator._background_tasks
    assert orchestrator._get_background_task_count() == 1

    await task


@pytest.mark.asyncio
async def test_track_background_task_removed_on_completion(orchestrator):
    """Test that completed tasks are automatically removed from the set."""

    async def dummy_coro():
        await asyncio.sleep(0.01)
        return "done"

    task = orchestrator._track_background_task(
        dummy_coro(),
        trace_id="test-123",
        task_name="test-task",
    )
    assert orchestrator._get_background_task_count() == 1

    await task
    await asyncio.sleep(0.01)

    assert orchestrator._get_background_task_count() == 0
    assert task not in orchestrator._background_tasks


@pytest.mark.asyncio
async def test_track_background_task_removed_on_failure(orchestrator):
    """Test that failed tasks are removed from set and exception is logged."""

    async def failing_coro():
        await asyncio.sleep(0.01)
        raise ValueError("Test error")

    task = orchestrator._track_background_task(
        failing_coro(),
        trace_id="test-123",
        task_name="failing-task",
    )
    assert orchestrator._get_background_task_count() == 1

    with pytest.raises(ValueError):
        await task

    await asyncio.sleep(0.01)

    assert orchestrator._get_background_task_count() == 0
    assert task not in orchestrator._background_tasks


@pytest.mark.asyncio
async def test_track_background_task_logs_completion(orchestrator):
    """Test that task completion is logged with [WHISPER] level."""

    async def dummy_coro():
        await asyncio.sleep(0.01)
        return "done"

    with patch("klabautermann.agents.orchestrator._orchestrator.logger") as mock_logger:
        task = orchestrator._track_background_task(
            dummy_coro(),
            trace_id="test-123",
            task_name="test-task",
        )
        await task
        await asyncio.sleep(0.01)

        mock_logger.debug.assert_called()
        call_args = mock_logger.debug.call_args
        assert "[WHISPER]" in call_args[0][0]
        assert "completed" in call_args[0][0].lower()


@pytest.mark.asyncio
async def test_track_background_task_logs_failure(orchestrator):
    """Test that task failure is logged with [SWELL] level."""

    async def failing_coro():
        await asyncio.sleep(0.01)
        raise ValueError("Test error")

    with patch("klabautermann.agents.orchestrator._orchestrator.logger") as mock_logger:
        task = orchestrator._track_background_task(
            failing_coro(),
            trace_id="test-123",
            task_name="failing-task",
        )
        with pytest.raises(ValueError):
            await task
        await asyncio.sleep(0.01)

        mock_logger.warning.assert_called()
        call_args = mock_logger.warning.call_args
        assert "[SWELL]" in call_args[0][0]
        assert "failed" in call_args[0][0].lower()


@pytest.mark.asyncio
async def test_get_background_task_count_accurate(orchestrator):
    """Test that _get_background_task_count returns accurate count."""

    async def slow_coro(delay: float):
        await asyncio.sleep(delay)
        return "done"

    task1 = orchestrator._track_background_task(
        slow_coro(0.1),
        trace_id="test-1",
        task_name="task-1",
    )
    assert orchestrator._get_background_task_count() == 1

    task2 = orchestrator._track_background_task(
        slow_coro(0.1),
        trace_id="test-2",
        task_name="task-2",
    )
    assert orchestrator._get_background_task_count() == 2

    task3 = orchestrator._track_background_task(
        slow_coro(0.1),
        trace_id="test-3",
        task_name="task-3",
    )
    assert orchestrator._get_background_task_count() == 3

    await asyncio.gather(task1, task2, task3)
    await asyncio.sleep(0.01)

    assert orchestrator._get_background_task_count() == 0


@pytest.mark.asyncio
async def test_shutdown_cancels_all_tasks(orchestrator):
    """Test that shutdown cancels all pending background tasks."""

    async def long_running_coro():
        await asyncio.sleep(10)
        return "done"

    task1 = orchestrator._track_background_task(
        long_running_coro(),
        trace_id="test-1",
        task_name="task-1",
    )
    task2 = orchestrator._track_background_task(
        long_running_coro(),
        trace_id="test-2",
        task_name="task-2",
    )
    assert orchestrator._get_background_task_count() == 2

    await orchestrator.shutdown()

    assert task1.cancelled()
    assert task2.cancelled()
    await asyncio.sleep(0.01)
    assert orchestrator._get_background_task_count() == 0


@pytest.mark.asyncio
async def test_shutdown_with_no_tasks(orchestrator):
    """Test that shutdown gracefully handles case with no tasks."""

    assert orchestrator._get_background_task_count() == 0

    with patch("klabautermann.agents.orchestrator._orchestrator.logger") as mock_logger:
        await orchestrator.shutdown()

        mock_logger.info.assert_called()
        call_args = mock_logger.info.call_args_list[0]
        assert "No background tasks" in call_args[0][0]


@pytest.mark.asyncio
async def test_shutdown_waits_for_cancellation(orchestrator):
    """Test that shutdown waits for all tasks to be cancelled."""

    cancellation_started = asyncio.Event()
    cancellation_detected = asyncio.Event()

    async def cancellable_coro():
        try:
            cancellation_started.set()
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancellation_detected.set()
            raise

    task = orchestrator._track_background_task(
        cancellable_coro(),
        trace_id="test-1",
        task_name="cancellable-task",
    )

    await cancellation_started.wait()

    await orchestrator.shutdown()

    assert cancellation_detected.is_set()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_multiple_tasks_independent_lifecycle(orchestrator):
    """Test that multiple tasks have independent lifecycles."""

    async def fast_coro():
        await asyncio.sleep(0.01)
        return "fast"

    async def slow_coro():
        await asyncio.sleep(0.1)
        return "slow"

    fast_task = orchestrator._track_background_task(
        fast_coro(),
        trace_id="fast",
        task_name="fast-task",
    )
    slow_task = orchestrator._track_background_task(
        slow_coro(),
        trace_id="slow",
        task_name="slow-task",
    )
    assert orchestrator._get_background_task_count() == 2

    await fast_task
    await asyncio.sleep(0.02)

    assert orchestrator._get_background_task_count() == 1
    assert slow_task in orchestrator._background_tasks
    assert fast_task not in orchestrator._background_tasks

    await slow_task
    await asyncio.sleep(0.01)

    assert orchestrator._get_background_task_count() == 0


@pytest.mark.asyncio
async def test_track_background_task_with_descriptive_name(orchestrator):
    """Test that task names are preserved for debugging."""

    async def dummy_coro():
        await asyncio.sleep(0.01)

    task = orchestrator._track_background_task(
        dummy_coro(),
        trace_id="test-123",
        task_name="ingest-v1-abc123",
    )

    assert task.get_name() == "ingest-v1-abc123"

    await task


@pytest.mark.asyncio
async def test_no_garbage_collection_of_fire_and_forget(orchestrator):
    """Test that fire-and-forget tasks aren't garbage collected prematurely."""

    completed = asyncio.Event()

    async def background_work():
        await asyncio.sleep(0.05)
        completed.set()
        return "done"

    orchestrator._track_background_task(
        background_work(),
        trace_id="test-gc",
        task_name="gc-test",
    )
    assert orchestrator._get_background_task_count() == 1

    import gc

    gc.collect()

    await completed.wait()
    await asyncio.sleep(0.01)

    assert completed.is_set()
    assert orchestrator._get_background_task_count() == 0
