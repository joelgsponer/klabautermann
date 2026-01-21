"""
Context window statistics for Klabautermann.

Tracks context usage including token counts, compression ratios,
and overflow events for conversation threads.

Reference: specs/architecture/MEMORY.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Constants
# =============================================================================

# Approximate characters per token for rough estimation
# More accurate counting would require tiktoken or similar
CHARS_PER_TOKEN_ESTIMATE = 4

# Default max messages in context window
DEFAULT_MAX_MESSAGES = 20


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ContextWindowMetrics:
    """Metrics for a single thread's context window."""

    thread_uuid: str
    message_count: int
    max_messages: int

    # Token estimates
    estimated_tokens: int
    estimated_token_limit: int | None = None

    # Compression tracking
    compression_ratio: float = 1.0  # 1.0 = no compression
    original_content_size: int = 0
    compressed_content_size: int = 0

    # Overflow tracking
    overflow_events: int = 0
    messages_dropped: int = 0

    # Timestamps
    last_message_at: datetime | None = None
    computed_at: datetime = field(default_factory=datetime.now)

    @property
    def is_at_capacity(self) -> bool:
        """Check if context window is at maximum capacity."""
        return self.message_count >= self.max_messages

    @property
    def utilization_percent(self) -> float:
        """Calculate context window utilization percentage."""
        if self.max_messages <= 0:
            return 0.0
        return (self.message_count / self.max_messages) * 100.0


@dataclass
class GlobalContextMetrics:
    """Aggregated context metrics across all threads."""

    total_threads: int
    active_threads: int

    # Token statistics
    total_estimated_tokens: int
    avg_tokens_per_thread: float

    # Overflow statistics
    total_overflow_events: int
    total_messages_dropped: int
    threads_at_capacity: int

    # Compression statistics
    avg_compression_ratio: float

    # Metadata
    computed_at: datetime = field(default_factory=datetime.now)


@dataclass
class OverflowEvent:
    """Record of a context window overflow event."""

    thread_uuid: str
    timestamp: datetime
    messages_before: int
    messages_after: int
    messages_dropped: int
    reason: str = "capacity_exceeded"


# =============================================================================
# Token Estimation
# =============================================================================


def estimate_tokens(text: str | None) -> int:
    """
    Estimate token count from text using character-based approximation.

    For more accurate counting, integrate tiktoken or similar library.

    Args:
        text: Text content to estimate tokens for

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)


def estimate_message_tokens(role: str, content: str) -> int:
    """
    Estimate tokens for a message including role overhead.

    Args:
        role: Message role (user, assistant, system)
        content: Message content

    Returns:
        Estimated token count including overhead
    """
    # Role tokens (approximately 4 tokens for role formatting)
    role_overhead = 4
    content_tokens = estimate_tokens(content)
    return role_overhead + content_tokens


# =============================================================================
# Context Statistics Functions
# =============================================================================


async def get_thread_context_metrics(
    neo4j: Neo4jClient,
    thread_uuid: str,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    trace_id: str | None = None,
) -> ContextWindowMetrics:
    """
    Get context window metrics for a specific thread.

    Args:
        neo4j: Connected Neo4jClient instance
        thread_uuid: UUID of the thread
        max_messages: Maximum messages allowed in context window
        trace_id: Optional trace ID for logging

    Returns:
        ContextWindowMetrics for the thread
    """
    logger.debug(
        f"[WHISPER] Computing context metrics for thread {thread_uuid[:8]}...",
        extra={"trace_id": trace_id, "agent_name": "context_stats"},
    )

    # Query thread messages
    query = """
    MATCH (t:Thread {uuid: $thread_uuid})-[:CONTAINS]->(m:Message)
    RETURN m.content AS content, m.role AS role, m.timestamp AS timestamp
    ORDER BY m.timestamp DESC
    LIMIT $max_messages
    """

    result = await neo4j.execute_query(
        query,
        {
            "thread_uuid": thread_uuid,
            "max_messages": max_messages * 2,
        },  # Get extra for overflow calc
        trace_id=trace_id,
    )

    # Calculate metrics
    total_messages = len(result)
    messages_in_window = min(total_messages, max_messages)
    overflow_events = 1 if total_messages > max_messages else 0
    messages_dropped = max(0, total_messages - max_messages)

    # Estimate tokens for messages in window
    total_tokens = 0
    original_size = 0

    for i, row in enumerate(result):
        content = row.get("content") or ""
        role = row.get("role") or "user"
        original_size += len(content)

        if i < max_messages:
            total_tokens += estimate_message_tokens(role, content)

    # Calculate compression ratio (1.0 if no summarization applied)
    compressed_size = original_size  # Would be different if summarization was applied
    compression_ratio = original_size / compressed_size if compressed_size > 0 else 1.0

    # Get last message timestamp
    last_message_at = None
    if result:
        timestamp = result[0].get("timestamp")
        if timestamp:
            last_message_at = datetime.fromtimestamp(timestamp)

    return ContextWindowMetrics(
        thread_uuid=thread_uuid,
        message_count=messages_in_window,
        max_messages=max_messages,
        estimated_tokens=total_tokens,
        compression_ratio=compression_ratio,
        original_content_size=original_size,
        compressed_content_size=compressed_size,
        overflow_events=overflow_events,
        messages_dropped=messages_dropped,
        last_message_at=last_message_at,
    )


async def get_global_context_metrics(
    neo4j: Neo4jClient,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    trace_id: str | None = None,
) -> GlobalContextMetrics:
    """
    Get aggregated context metrics across all threads.

    Args:
        neo4j: Connected Neo4jClient instance
        max_messages: Maximum messages allowed per context window
        trace_id: Optional trace ID for logging

    Returns:
        GlobalContextMetrics with aggregated statistics
    """
    logger.info(
        "[CHART] Computing global context metrics",
        extra={"trace_id": trace_id, "agent_name": "context_stats"},
    )

    # Query all threads with message counts
    query = """
    MATCH (t:Thread)
    OPTIONAL MATCH (t)-[:CONTAINS]->(m:Message)
    WITH t, count(m) AS message_count,
         collect(m.content) AS contents,
         max(m.timestamp) AS last_msg
    RETURN t.uuid AS thread_uuid,
           t.status AS status,
           message_count,
           contents,
           last_msg
    """

    result = await neo4j.execute_query(query, {}, trace_id=trace_id)

    total_threads = len(result)
    active_threads = 0
    total_tokens = 0
    total_overflow_events = 0
    total_messages_dropped = 0
    threads_at_capacity = 0
    compression_ratios: list[float] = []

    for row in result:
        status = row.get("status")
        message_count = int(row.get("message_count", 0))
        contents = row.get("contents") or []

        if status == "active":
            active_threads += 1

        # Count tokens for messages in window
        for content in contents[:max_messages]:
            if content:
                total_tokens += estimate_tokens(content)

        # Track overflow
        if message_count > max_messages:
            total_overflow_events += 1
            total_messages_dropped += message_count - max_messages

        # Track capacity
        if message_count >= max_messages:
            threads_at_capacity += 1

        # Compression ratio (1.0 for now, would track actual if summarization applied)
        compression_ratios.append(1.0)

    avg_tokens = total_tokens / total_threads if total_threads > 0 else 0.0
    avg_compression = (
        sum(compression_ratios) / len(compression_ratios) if compression_ratios else 1.0
    )

    metrics = GlobalContextMetrics(
        total_threads=total_threads,
        active_threads=active_threads,
        total_estimated_tokens=total_tokens,
        avg_tokens_per_thread=avg_tokens,
        total_overflow_events=total_overflow_events,
        total_messages_dropped=total_messages_dropped,
        threads_at_capacity=threads_at_capacity,
        avg_compression_ratio=avg_compression,
    )

    logger.info(
        f"[CHART] Global context: {total_threads} threads, {total_tokens} tokens, "
        f"{threads_at_capacity} at capacity",
        extra={"trace_id": trace_id, "agent_name": "context_stats"},
    )

    return metrics


def metrics_to_dict(metrics: ContextWindowMetrics | GlobalContextMetrics) -> dict:
    """
    Convert metrics to a serializable dictionary.

    Args:
        metrics: ContextWindowMetrics or GlobalContextMetrics instance

    Returns:
        Dictionary representation of metrics
    """
    if isinstance(metrics, ContextWindowMetrics):
        return {
            "thread_uuid": metrics.thread_uuid,
            "message_count": metrics.message_count,
            "max_messages": metrics.max_messages,
            "estimated_tokens": metrics.estimated_tokens,
            "compression_ratio": metrics.compression_ratio,
            "overflow_events": metrics.overflow_events,
            "messages_dropped": metrics.messages_dropped,
            "is_at_capacity": metrics.is_at_capacity,
            "utilization_percent": metrics.utilization_percent,
            "last_message_at": metrics.last_message_at.isoformat()
            if metrics.last_message_at
            else None,
            "computed_at": metrics.computed_at.isoformat(),
        }
    else:
        return {
            "total_threads": metrics.total_threads,
            "active_threads": metrics.active_threads,
            "total_estimated_tokens": metrics.total_estimated_tokens,
            "avg_tokens_per_thread": metrics.avg_tokens_per_thread,
            "total_overflow_events": metrics.total_overflow_events,
            "total_messages_dropped": metrics.total_messages_dropped,
            "threads_at_capacity": metrics.threads_at_capacity,
            "avg_compression_ratio": metrics.avg_compression_ratio,
            "computed_at": metrics.computed_at.isoformat(),
        }


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "CHARS_PER_TOKEN_ESTIMATE",
    "DEFAULT_MAX_MESSAGES",
    "ContextWindowMetrics",
    "GlobalContextMetrics",
    "OverflowEvent",
    "estimate_message_tokens",
    "estimate_tokens",
    "get_global_context_metrics",
    "get_thread_context_metrics",
    "metrics_to_dict",
]
