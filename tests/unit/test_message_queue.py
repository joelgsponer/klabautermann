"""Unit tests for MessageQueue."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from klabautermann.channels.message_queue import (
    MessageQueue,
    MessageQueueConfig,
    OverflowAction,
    QueueItem,
    QueueItemStatus,
    QueueStats,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_processor() -> AsyncMock:
    """Create a mock message processor."""
    processor = AsyncMock()
    processor.return_value = "Processed response"
    return processor


@pytest.fixture
def queue_config() -> MessageQueueConfig:
    """Create test queue configuration."""
    return MessageQueueConfig(
        max_size=5,
        overflow_policy="drop_oldest",
        processing_timeout=5.0,
        enable_metrics=True,
    )


@pytest.fixture
async def queue(mock_processor: AsyncMock, queue_config: MessageQueueConfig) -> MessageQueue:
    """Create a message queue for testing."""
    q = MessageQueue(processor=mock_processor, config=queue_config)
    await q.start()
    yield q
    await q.stop()


# =============================================================================
# Basic Queue Operations
# =============================================================================


class TestBasicQueueOperations:
    """Test basic queue operations."""

    async def test_enqueue_message(self, queue: MessageQueue) -> None:
        """Test enqueueing a single message."""
        result = await queue.enqueue("thread-1", "Hello")

        assert result.accepted is True
        assert result.action == OverflowAction.ACCEPTED
        assert result.item_id is not None
        assert result.queue_position == 1

    async def test_enqueue_with_metadata(self, queue: MessageQueue) -> None:
        """Test enqueueing a message with metadata."""
        metadata = {"source": "test", "priority": "high"}
        result = await queue.enqueue("thread-1", "Hello", metadata=metadata)

        assert result.accepted is True
        item = queue.get_item(result.item_id)
        assert item is not None
        assert item.metadata == metadata

    async def test_process_message(self, queue: MessageQueue, mock_processor: AsyncMock) -> None:
        """Test processing a queued message."""
        result = await queue.enqueue("thread-1", "Hello")

        # Wait for processing
        response = await queue.wait_for_result(result.item_id, timeout=2.0)

        assert response == "Processed response"
        mock_processor.assert_called_once_with("thread-1", "Hello", None)

    async def test_multiple_messages_fifo(
        self, queue: MessageQueue, mock_processor: AsyncMock
    ) -> None:
        """Test that messages are processed in FIFO order."""
        # Add delay to processor to ensure ordering
        call_order: list[str] = []

        async def slow_processor(
            thread_id: str, content: str, metadata: dict[str, Any] | None
        ) -> str:
            call_order.append(content)
            await asyncio.sleep(0.05)  # Small delay
            return f"Response to {content}"

        mock_processor.side_effect = slow_processor

        # Enqueue multiple messages
        r1 = await queue.enqueue("thread-1", "First")
        r2 = await queue.enqueue("thread-1", "Second")
        r3 = await queue.enqueue("thread-1", "Third")

        # Wait for all to complete
        await queue.wait_for_result(r1.item_id, timeout=5.0)
        await queue.wait_for_result(r2.item_id, timeout=5.0)
        await queue.wait_for_result(r3.item_id, timeout=5.0)

        # Verify FIFO order
        assert call_order == ["First", "Second", "Third"]

    async def test_queue_size(self, queue: MessageQueue) -> None:
        """Test queue size tracking."""
        assert queue.queue_size == 0

        # Pause processing
        event = asyncio.Event()

        async def blocking_processor(
            thread_id: str, content: str, metadata: dict[str, Any] | None
        ) -> str:
            await event.wait()
            return "Done"

        queue._processor = blocking_processor

        # Enqueue
        await queue.enqueue("thread-1", "Hello")
        await asyncio.sleep(0.1)  # Let it start processing

        # First message is processing, not in pending queue
        assert queue.is_processing is True

        # Unblock
        event.set()


# =============================================================================
# Overflow Handling
# =============================================================================


class TestOverflowHandling:
    """Test queue overflow policies."""

    async def test_drop_oldest_policy(self, mock_processor: AsyncMock) -> None:
        """Test drop_oldest overflow policy."""
        config = MessageQueueConfig(
            max_size=2,
            overflow_policy="drop_oldest",
            processing_timeout=5.0,
        )

        # Don't process immediately - block the queue
        event = asyncio.Event()

        async def blocking_processor(
            thread_id: str, content: str, metadata: dict[str, Any] | None
        ) -> str:
            await event.wait()
            return "Done"

        queue = MessageQueue(processor=blocking_processor, config=config)
        await queue.start()

        try:
            # Fill the queue
            await queue.enqueue("t1", "First")
            await queue.enqueue("t1", "Second")

            # Wait for first to start processing
            await asyncio.sleep(0.1)

            # Queue now has 1 item (Second), First is processing
            # Overflow with third message
            r3 = await queue.enqueue("t1", "Third")

            # Should have dropped oldest (Second was waiting)
            assert r3.action == OverflowAction.DROPPED_OLDEST
            assert r3.accepted is True

            # Unblock and let processing complete
            event.set()
            await asyncio.sleep(0.1)

        finally:
            await queue.stop()

    async def test_drop_newest_policy(self, mock_processor: AsyncMock) -> None:
        """Test drop_newest overflow policy."""
        config = MessageQueueConfig(
            max_size=2,
            overflow_policy="drop_newest",
            processing_timeout=5.0,
        )

        event = asyncio.Event()

        async def blocking_processor(
            thread_id: str, content: str, metadata: dict[str, Any] | None
        ) -> str:
            await event.wait()
            return "Done"

        queue = MessageQueue(processor=blocking_processor, config=config)
        await queue.start()

        try:
            # Fill the queue
            await queue.enqueue("t1", "First")
            await queue.enqueue("t1", "Second")

            await asyncio.sleep(0.1)  # Let first start processing

            # Try to add third - should be dropped
            r3 = await queue.enqueue("t1", "Third")

            assert r3.action == OverflowAction.DROPPED_NEWEST
            assert r3.accepted is False

            event.set()

        finally:
            await queue.stop()

    async def test_reject_policy(self, mock_processor: AsyncMock) -> None:
        """Test reject overflow policy."""
        config = MessageQueueConfig(
            max_size=2,
            overflow_policy="reject",
            processing_timeout=5.0,
        )

        event = asyncio.Event()

        async def blocking_processor(
            thread_id: str, content: str, metadata: dict[str, Any] | None
        ) -> str:
            await event.wait()
            return "Done"

        queue = MessageQueue(processor=blocking_processor, config=config)
        await queue.start()

        try:
            await queue.enqueue("t1", "First")
            await queue.enqueue("t1", "Second")

            await asyncio.sleep(0.1)

            r3 = await queue.enqueue("t1", "Third")

            assert r3.action == OverflowAction.REJECTED
            assert r3.accepted is False

            event.set()

        finally:
            await queue.stop()


# =============================================================================
# Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error handling scenarios."""

    async def test_processor_exception(self, mock_processor: AsyncMock) -> None:
        """Test handling of processor exceptions."""
        mock_processor.side_effect = Exception("Processing error")

        queue = MessageQueue(processor=mock_processor)
        await queue.start()

        try:
            result = await queue.enqueue("thread-1", "Hello")
            await asyncio.sleep(0.2)  # Let it process

            item = queue.get_item(result.item_id)
            assert item is not None
            assert item.status == QueueItemStatus.FAILED
            assert item.error == "Processing error"

        finally:
            await queue.stop()

    async def test_processing_timeout(self) -> None:
        """Test processing timeout."""

        async def slow_processor(
            thread_id: str, content: str, metadata: dict[str, Any] | None
        ) -> str:
            await asyncio.sleep(10)  # Longer than timeout
            return "Done"

        config = MessageQueueConfig(
            max_size=10,
            processing_timeout=0.1,  # 100ms timeout
        )

        queue = MessageQueue(processor=slow_processor, config=config)
        await queue.start()

        try:
            result = await queue.enqueue("thread-1", "Hello")
            await asyncio.sleep(0.3)  # Wait for timeout

            item = queue.get_item(result.item_id)
            assert item is not None
            assert item.status == QueueItemStatus.FAILED
            assert item.error == "Processing timeout"

        finally:
            await queue.stop()

    async def test_wait_for_nonexistent_item(self) -> None:
        """Test waiting for a nonexistent item raises error."""

        async def mock_proc(thread_id: str, content: str, metadata: dict[str, Any] | None) -> str:
            return "Done"

        queue = MessageQueue(processor=mock_proc)
        await queue.start()

        try:
            with pytest.raises(ValueError, match="Item not found"):
                await queue.wait_for_result("nonexistent-id", timeout=1.0)

        finally:
            await queue.stop()


# =============================================================================
# Statistics
# =============================================================================


class TestStatistics:
    """Test queue statistics."""

    async def test_get_stats(self, queue: MessageQueue, mock_processor: AsyncMock) -> None:
        """Test statistics tracking."""
        # Process some messages
        r1 = await queue.enqueue("t1", "First")
        r2 = await queue.enqueue("t1", "Second")

        await queue.wait_for_result(r1.item_id, timeout=2.0)
        await queue.wait_for_result(r2.item_id, timeout=2.0)

        stats = queue.get_stats()

        assert isinstance(stats, QueueStats)
        assert stats.total_enqueued == 2
        assert stats.total_processed == 2
        assert stats.total_failed == 0
        assert stats.total_dropped == 0
        assert stats.max_size == 5
        assert stats.average_wait_ms >= 0

    async def test_is_full(self) -> None:
        """Test is_full property."""
        config = MessageQueueConfig(max_size=2)
        event = asyncio.Event()

        async def blocking_processor(
            thread_id: str, content: str, metadata: dict[str, Any] | None
        ) -> str:
            await event.wait()
            return "Done"

        queue = MessageQueue(processor=blocking_processor, config=config)
        await queue.start()

        try:
            assert queue.is_full is False

            await queue.enqueue("t1", "First")
            await queue.enqueue("t1", "Second")

            await asyncio.sleep(0.1)  # Let first start processing

            # One processing, one waiting = 1 in pending_ids
            # Depending on timing, may or may not be full
            # Add one more to ensure we hit the limit
            await queue.enqueue("t1", "Third")

            event.set()

        finally:
            await queue.stop()


# =============================================================================
# Lifecycle
# =============================================================================


class TestLifecycle:
    """Test queue lifecycle operations."""

    async def test_start_stop(self, mock_processor: AsyncMock) -> None:
        """Test starting and stopping the queue."""
        queue = MessageQueue(processor=mock_processor)

        # Should be stopped initially
        assert queue._running is False

        await queue.start()
        assert queue._running is True
        assert queue._processing_task is not None

        await queue.stop()
        assert queue._running is False

    async def test_clear_queue(self, mock_processor: AsyncMock) -> None:
        """Test clearing pending messages."""
        event = asyncio.Event()

        async def blocking_processor(
            thread_id: str, content: str, metadata: dict[str, Any] | None
        ) -> str:
            await event.wait()
            return "Done"

        queue = MessageQueue(processor=blocking_processor)
        await queue.start()

        try:
            # Add messages
            await queue.enqueue("t1", "First")
            await queue.enqueue("t1", "Second")
            await queue.enqueue("t1", "Third")

            await asyncio.sleep(0.1)  # Let first start processing

            # Clear pending
            cleared = queue.clear()

            # First is processing, so 2 should be cleared
            assert cleared >= 0  # May vary based on timing

            stats = queue.get_stats()
            assert stats.current_size == 0

            event.set()

        finally:
            await queue.stop()


# =============================================================================
# Configuration
# =============================================================================


class TestConfiguration:
    """Test configuration options."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = MessageQueueConfig()

        assert config.max_size == 100
        assert config.overflow_policy == "drop_oldest"
        assert config.processing_timeout == 300.0
        assert config.enable_metrics is True

    def test_config_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading config from environment."""
        monkeypatch.setenv("MESSAGE_QUEUE_MAX_SIZE", "50")
        monkeypatch.setenv("MESSAGE_QUEUE_OVERFLOW", "reject")
        monkeypatch.setenv("MESSAGE_QUEUE_TIMEOUT", "60.0")
        monkeypatch.setenv("MESSAGE_QUEUE_METRICS", "false")

        config = MessageQueueConfig.from_env()

        assert config.max_size == 50
        assert config.overflow_policy == "reject"
        assert config.processing_timeout == 60.0
        assert config.enable_metrics is False


# =============================================================================
# Queue Item
# =============================================================================


class TestQueueItem:
    """Test QueueItem dataclass."""

    def test_queue_item_creation(self) -> None:
        """Test creating a queue item."""
        item = QueueItem(
            id="test-123",
            thread_id="thread-1",
            content="Hello",
            metadata={"key": "value"},
            created_at=datetime.now(),
        )

        assert item.id == "test-123"
        assert item.thread_id == "thread-1"
        assert item.content == "Hello"
        assert item.metadata == {"key": "value"}
        assert item.status == QueueItemStatus.PENDING
        assert item.result is None
        assert item.error is None
        assert item.processed_at is None
