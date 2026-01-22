"""
Message queue for channel resilience.

Provides FIFO message queuing with backpressure handling when the
Orchestrator is busy processing requests.

Reference: specs/architecture/CHANNELS.md
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from klabautermann.core.logger import logger


# =============================================================================
# Queue Item
# =============================================================================


class QueueItemStatus(Enum):
    """Status of a queued message."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DROPPED = "dropped"


@dataclass
class QueueItem:
    """Represents a message in the queue."""

    id: str
    thread_id: str
    content: str
    metadata: dict[str, Any] | None
    created_at: datetime
    status: QueueItemStatus = QueueItemStatus.PENDING
    result: str | None = None
    error: str | None = None
    processed_at: datetime | None = None


# =============================================================================
# Queue Configuration
# =============================================================================


@dataclass
class MessageQueueConfig:
    """Configuration for the message queue."""

    max_size: int = 100  # Maximum queue size
    overflow_policy: str = "drop_oldest"  # drop_oldest, drop_newest, reject
    processing_timeout: float = 300.0  # 5 minute timeout per message
    enable_metrics: bool = True

    @classmethod
    def from_env(cls) -> MessageQueueConfig:
        """Load configuration from environment variables."""
        import os

        return cls(
            max_size=int(os.getenv("MESSAGE_QUEUE_MAX_SIZE", "100")),
            overflow_policy=os.getenv("MESSAGE_QUEUE_OVERFLOW", "drop_oldest"),
            processing_timeout=float(os.getenv("MESSAGE_QUEUE_TIMEOUT", "300.0")),
            enable_metrics=os.getenv("MESSAGE_QUEUE_METRICS", "true").lower()
            in (
                "true",
                "1",
                "yes",
            ),
        )


# =============================================================================
# Queue Stats
# =============================================================================


@dataclass
class QueueStats:
    """Statistics for the message queue."""

    current_size: int
    max_size: int
    total_enqueued: int
    total_processed: int
    total_failed: int
    total_dropped: int
    average_wait_ms: float
    is_processing: bool


# =============================================================================
# Overflow Result
# =============================================================================


class OverflowAction(Enum):
    """Action taken when queue overflows."""

    ACCEPTED = "accepted"
    DROPPED_OLDEST = "dropped_oldest"
    DROPPED_NEWEST = "dropped_newest"
    REJECTED = "rejected"


@dataclass
class EnqueueResult:
    """Result of enqueueing a message."""

    item_id: str
    accepted: bool
    action: OverflowAction
    dropped_item_id: str | None = None
    queue_position: int = 0


# =============================================================================
# Message Queue
# =============================================================================


# Type for message processor callback
MessageProcessor = Callable[[str, str, dict[str, Any] | None], Awaitable[str]]


class MessageQueue:
    """
    Async message queue for channel resilience.

    Provides FIFO message processing with:
    - Configurable max queue size
    - Overflow handling policies (drop oldest, drop newest, reject)
    - Backpressure signaling
    - Processing timeout
    - Statistics tracking

    Usage:
        queue = MessageQueue(processor=orchestrator.handle_user_input)
        await queue.start()

        # Enqueue message (returns immediately)
        result = await queue.enqueue(thread_id, content)

        # Wait for result
        response = await queue.wait_for_result(result.item_id)

        await queue.stop()
    """

    def __init__(
        self,
        processor: MessageProcessor,
        config: MessageQueueConfig | None = None,
    ) -> None:
        """
        Initialize the message queue.

        Args:
            processor: Async function to process messages.
                      Signature: (thread_id, content, metadata) -> response
            config: Queue configuration.
        """
        self._processor = processor
        self._config = config or MessageQueueConfig.from_env()

        # Queue storage
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=self._config.max_size)
        self._items: dict[str, QueueItem] = {}  # id -> item for result lookup
        self._pending_ids: list[str] = []  # Ordered list for FIFO tracking

        # Processing state
        self._running = False
        self._processing_task: asyncio.Task[None] | None = None
        self._current_item: QueueItem | None = None

        # Result notification
        self._result_events: dict[str, asyncio.Event] = {}

        # Statistics
        self._total_enqueued = 0
        self._total_processed = 0
        self._total_failed = 0
        self._total_dropped = 0
        self._wait_times_ms: list[float] = []

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start(self) -> None:
        """Start the queue processor."""
        if self._running:
            logger.warning("[SWELL] Message queue already running")
            return

        self._running = True
        self._processing_task = asyncio.create_task(self._process_loop())
        logger.info(
            "[CHART] Message queue started",
            extra={"max_size": self._config.max_size, "overflow": self._config.overflow_policy},
        )

    async def stop(self) -> None:
        """Stop the queue processor gracefully."""
        if not self._running:
            return

        self._running = False

        if self._processing_task:
            self._processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processing_task
            self._processing_task = None

        logger.info(
            "[BEACON] Message queue stopped",
            extra={"pending": len(self._pending_ids)},
        )

    # =========================================================================
    # Enqueue
    # =========================================================================

    async def enqueue(
        self,
        thread_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> EnqueueResult:
        """
        Add a message to the queue.

        Returns immediately - does not wait for processing.
        Use wait_for_result() to get the response.

        Args:
            thread_id: Thread/conversation identifier.
            content: Message content.
            metadata: Optional metadata.

        Returns:
            EnqueueResult with item ID and overflow action taken.
        """
        item = QueueItem(
            id=str(uuid4()),
            thread_id=thread_id,
            content=content,
            metadata=metadata,
            created_at=datetime.now(),
        )

        # Check queue capacity
        if len(self._pending_ids) >= self._config.max_size:
            return await self._handle_overflow(item)

        # Add to queue
        self._items[item.id] = item
        self._pending_ids.append(item.id)
        self._result_events[item.id] = asyncio.Event()
        await self._queue.put(item)

        self._total_enqueued += 1

        logger.debug(
            f"[WHISPER] Message enqueued: {item.id[:8]}",
            extra={
                "thread_id": thread_id,
                "queue_size": len(self._pending_ids),
            },
        )

        return EnqueueResult(
            item_id=item.id,
            accepted=True,
            action=OverflowAction.ACCEPTED,
            queue_position=len(self._pending_ids),
        )

    async def _handle_overflow(self, new_item: QueueItem) -> EnqueueResult:
        """Handle queue overflow according to policy."""
        policy = self._config.overflow_policy

        if policy == "drop_oldest" and self._pending_ids:
            # Remove oldest item
            oldest_id = self._pending_ids.pop(0)
            oldest = self._items.pop(oldest_id, None)
            if oldest:
                oldest.status = QueueItemStatus.DROPPED
                self._total_dropped += 1
                # Signal any waiters
                if oldest_id in self._result_events:
                    self._result_events[oldest_id].set()

                logger.warning(
                    f"[SWELL] Dropped oldest message: {oldest_id[:8]}",
                    extra={"thread_id": oldest.thread_id},
                )

            # Add new item
            self._items[new_item.id] = new_item
            self._pending_ids.append(new_item.id)
            self._result_events[new_item.id] = asyncio.Event()
            await self._queue.put(new_item)
            self._total_enqueued += 1

            return EnqueueResult(
                item_id=new_item.id,
                accepted=True,
                action=OverflowAction.DROPPED_OLDEST,
                dropped_item_id=oldest_id,
                queue_position=len(self._pending_ids),
            )

        if policy == "drop_newest":
            # Drop the new item
            new_item.status = QueueItemStatus.DROPPED
            self._total_dropped += 1

            logger.warning(
                f"[SWELL] Dropped newest message: {new_item.id[:8]}",
                extra={"thread_id": new_item.thread_id},
            )

            return EnqueueResult(
                item_id=new_item.id,
                accepted=False,
                action=OverflowAction.DROPPED_NEWEST,
            )

        # Default: reject (also handles drop_oldest with empty pending_ids)
        logger.warning(
            f"[SWELL] Rejected message - queue full: {new_item.id[:8]}",
            extra={"thread_id": new_item.thread_id},
        )

        return EnqueueResult(
            item_id=new_item.id,
            accepted=False,
            action=OverflowAction.REJECTED,
        )

    # =========================================================================
    # Result Retrieval
    # =========================================================================

    async def wait_for_result(
        self,
        item_id: str,
        timeout: float | None = None,
    ) -> str:
        """
        Wait for a queued message to be processed.

        Args:
            item_id: ID returned from enqueue().
            timeout: Optional timeout in seconds.

        Returns:
            Response from the processor.

        Raises:
            TimeoutError: If timeout exceeded.
            ValueError: If item not found or was dropped/failed.
        """
        if item_id not in self._items:
            raise ValueError(f"Item not found: {item_id}")

        event = self._result_events.get(item_id)
        if event is None:
            raise ValueError(f"No result event for: {item_id}")

        # Wait for processing
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            raise TimeoutError(f"Timeout waiting for result: {item_id}") from None

        item = self._items.get(item_id)
        if item is None:
            raise ValueError(f"Item no longer exists: {item_id}")

        if item.status == QueueItemStatus.DROPPED:
            raise ValueError(f"Item was dropped due to queue overflow: {item_id}")

        if item.status == QueueItemStatus.FAILED:
            raise ValueError(f"Processing failed: {item.error}")

        if item.result is None:
            raise ValueError(f"No result available: {item_id}")

        return item.result

    def get_item(self, item_id: str) -> QueueItem | None:
        """Get a queue item by ID."""
        return self._items.get(item_id)

    # =========================================================================
    # Processing Loop
    # =========================================================================

    async def _process_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            try:
                # Get next item (with timeout to allow shutdown checks)
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                # Skip if item was dropped during overflow
                if item.status == QueueItemStatus.DROPPED:
                    continue

                # Process the item
                await self._process_item(item)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[STORM] Queue processing error: {e}", exc_info=True)

    async def _process_item(self, item: QueueItem) -> None:
        """Process a single queue item."""
        self._current_item = item
        item.status = QueueItemStatus.PROCESSING

        # Calculate wait time
        wait_ms = (datetime.now() - item.created_at).total_seconds() * 1000
        self._wait_times_ms.append(wait_ms)
        # Keep only last 100 for average
        if len(self._wait_times_ms) > 100:
            self._wait_times_ms = self._wait_times_ms[-100:]

        logger.debug(
            f"[WHISPER] Processing message: {item.id[:8]}",
            extra={"thread_id": item.thread_id, "wait_ms": wait_ms},
        )

        try:
            # Process with timeout
            result = await asyncio.wait_for(
                self._processor(item.thread_id, item.content, item.metadata),
                timeout=self._config.processing_timeout,
            )

            item.result = result
            item.status = QueueItemStatus.COMPLETED
            item.processed_at = datetime.now()
            self._total_processed += 1

            logger.debug(
                f"[WHISPER] Message processed: {item.id[:8]}",
                extra={"thread_id": item.thread_id},
            )

        except TimeoutError:
            item.status = QueueItemStatus.FAILED
            item.error = "Processing timeout"
            item.processed_at = datetime.now()
            self._total_failed += 1

            logger.error(
                f"[STORM] Processing timeout: {item.id[:8]}",
                extra={"thread_id": item.thread_id},
            )

        except Exception as e:
            item.status = QueueItemStatus.FAILED
            item.error = str(e)
            item.processed_at = datetime.now()
            self._total_failed += 1

            logger.error(
                f"[STORM] Processing failed: {item.id[:8]} - {e}",
                extra={"thread_id": item.thread_id},
            )

        finally:
            # Remove from pending
            if item.id in self._pending_ids:
                self._pending_ids.remove(item.id)

            # Signal result available
            if item.id in self._result_events:
                self._result_events[item.id].set()

            self._current_item = None

    # =========================================================================
    # Status & Stats
    # =========================================================================

    @property
    def is_processing(self) -> bool:
        """Check if queue is currently processing a message."""
        return self._current_item is not None

    @property
    def queue_size(self) -> int:
        """Get current queue size."""
        return len(self._pending_ids)

    @property
    def is_full(self) -> bool:
        """Check if queue is at capacity."""
        return len(self._pending_ids) >= self._config.max_size

    def get_stats(self) -> QueueStats:
        """Get queue statistics."""
        avg_wait = 0.0
        if self._wait_times_ms:
            avg_wait = sum(self._wait_times_ms) / len(self._wait_times_ms)

        return QueueStats(
            current_size=len(self._pending_ids),
            max_size=self._config.max_size,
            total_enqueued=self._total_enqueued,
            total_processed=self._total_processed,
            total_failed=self._total_failed,
            total_dropped=self._total_dropped,
            average_wait_ms=avg_wait,
            is_processing=self.is_processing,
        )

    def clear(self) -> int:
        """
        Clear all pending messages.

        Returns:
            Number of messages cleared.
        """
        count = len(self._pending_ids)

        # Mark all as dropped and signal waiters
        for item_id in self._pending_ids:
            item = self._items.get(item_id)
            if item:
                item.status = QueueItemStatus.DROPPED
            if item_id in self._result_events:
                self._result_events[item_id].set()

        self._pending_ids.clear()
        self._total_dropped += count

        logger.info(f"[CHART] Cleared {count} pending messages")

        return count


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "EnqueueResult",
    "MessageQueue",
    "MessageQueueConfig",
    "OverflowAction",
    "QueueItem",
    "QueueItemStatus",
    "QueueStats",
]
