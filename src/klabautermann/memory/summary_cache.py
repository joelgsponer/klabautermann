"""
Thread summary caching for Klabautermann.

Caches thread summaries to avoid re-computing summaries for threads
that haven't changed. Summaries are invalidated when new messages
are added to a thread.

Reference: specs/architecture/MEMORY.md
Issue: #200 - Add thread summary caching
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from klabautermann.core.logger import logger
from klabautermann.core.models import ThreadSummary


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# Type alias for summary compute function
SummaryComputeFn = Callable[[str | None], Awaitable[ThreadSummary]]


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class CachedSummary:
    """A cached thread summary with metadata."""

    thread_uuid: str
    summary: ThreadSummary
    cached_at: float
    message_count_at_cache: int
    last_message_at_cache: float


# =============================================================================
# Cache Operations
# =============================================================================


async def get_cached_summary(
    neo4j: Neo4jClient,
    thread_uuid: str,
    trace_id: str | None = None,
) -> CachedSummary | None:
    """
    Get cached summary for a thread if available and still valid.

    Returns None if:
    - No cached summary exists
    - New messages have been added since caching
    - The thread has been modified since caching

    Args:
        neo4j: Connected Neo4jClient instance
        thread_uuid: UUID of the thread
        trace_id: Optional trace ID for logging

    Returns:
        CachedSummary if valid cache exists, None otherwise
    """
    logger.debug(
        f"[WHISPER] Checking summary cache for thread {thread_uuid[:8]}...",
        extra={"trace_id": trace_id, "agent_name": "summary_cache"},
    )

    query = """
    MATCH (t:Thread {uuid: $thread_uuid})
    WHERE t.cached_summary IS NOT NULL
      AND t.cached_summary_at IS NOT NULL
      AND t.cached_message_count IS NOT NULL

    // Count current messages to check if new ones were added
    OPTIONAL MATCH (t)-[:CONTAINS]->(m:Message)
    WITH t, count(m) as current_count

    // Check if cache is still valid (message count matches)
    WHERE current_count = t.cached_message_count
      AND t.last_message_at = t.cached_last_message_at

    RETURN t.cached_summary as summary,
           t.cached_summary_at as cached_at,
           t.cached_message_count as message_count,
           t.cached_last_message_at as last_message_at,
           t.cached_topics as topics,
           t.cached_participants as participants,
           t.cached_sentiment as sentiment
    """

    result = await neo4j.execute_query(
        query,
        {"thread_uuid": thread_uuid},
        trace_id=trace_id,
    )

    if not result:
        logger.debug(
            f"[WHISPER] No valid cached summary for thread {thread_uuid[:8]}...",
            extra={"trace_id": trace_id, "agent_name": "summary_cache"},
        )
        return None

    row = result[0]

    # Reconstruct ThreadSummary from cached fields
    summary = ThreadSummary(
        summary=row.get("summary") or "",
        topics=row.get("topics") or [],
        participants=row.get("participants") or [],
        action_items=[],  # Not cached for simplicity
        new_facts=[],  # Not cached for simplicity
        conflicts=[],  # Not cached for simplicity
        sentiment=row.get("sentiment") or "neutral",
    )

    cached = CachedSummary(
        thread_uuid=thread_uuid,
        summary=summary,
        cached_at=row.get("cached_at") or 0.0,
        message_count_at_cache=row.get("message_count") or 0,
        last_message_at_cache=row.get("last_message_at") or 0.0,
    )

    logger.info(
        f"[BEACON] Cache hit for thread {thread_uuid[:8]}... "
        f"(cached {int(time.time() - cached.cached_at)}s ago)",
        extra={"trace_id": trace_id, "agent_name": "summary_cache"},
    )

    return cached


async def set_cached_summary(
    neo4j: Neo4jClient,
    thread_uuid: str,
    summary: ThreadSummary,
    trace_id: str | None = None,
) -> bool:
    """
    Cache a summary for a thread.

    Stores the summary text and metadata on the Thread node.
    Also captures the current message count and last_message_at
    for cache invalidation checks.

    Args:
        neo4j: Connected Neo4jClient instance
        thread_uuid: UUID of the thread
        summary: ThreadSummary to cache
        trace_id: Optional trace ID for logging

    Returns:
        True if successfully cached, False otherwise
    """
    now = time.time()

    logger.debug(
        f"[WHISPER] Caching summary for thread {thread_uuid[:8]}...",
        extra={"trace_id": trace_id, "agent_name": "summary_cache"},
    )

    query = """
    MATCH (t:Thread {uuid: $thread_uuid})
    OPTIONAL MATCH (t)-[:CONTAINS]->(m:Message)
    WITH t, count(m) as message_count
    SET t.cached_summary = $summary,
        t.cached_summary_at = $cached_at,
        t.cached_message_count = message_count,
        t.cached_last_message_at = t.last_message_at,
        t.cached_topics = $topics,
        t.cached_participants = $participants,
        t.cached_sentiment = $sentiment
    RETURN t.uuid
    """

    result = await neo4j.execute_query(
        query,
        {
            "thread_uuid": thread_uuid,
            "summary": summary.summary,
            "cached_at": now,
            "topics": summary.topics,
            "participants": summary.participants,
            "sentiment": summary.sentiment,
        },
        trace_id=trace_id,
    )

    success = len(result) > 0

    if success:
        logger.info(
            f"[BEACON] Cached summary for thread {thread_uuid[:8]}...",
            extra={"trace_id": trace_id, "agent_name": "summary_cache"},
        )
    else:
        logger.warning(
            f"[SWELL] Failed to cache summary for thread {thread_uuid[:8]}...",
            extra={"trace_id": trace_id, "agent_name": "summary_cache"},
        )

    return success


async def invalidate_summary_cache(
    neo4j: Neo4jClient,
    thread_uuid: str,
    trace_id: str | None = None,
) -> bool:
    """
    Invalidate (clear) the cached summary for a thread.

    This should be called when a new message is added to the thread.

    Args:
        neo4j: Connected Neo4jClient instance
        thread_uuid: UUID of the thread
        trace_id: Optional trace ID for logging

    Returns:
        True if cache was invalidated, False if no cache existed
    """
    logger.debug(
        f"[WHISPER] Invalidating summary cache for thread {thread_uuid[:8]}...",
        extra={"trace_id": trace_id, "agent_name": "summary_cache"},
    )

    query = """
    MATCH (t:Thread {uuid: $thread_uuid})
    WHERE t.cached_summary IS NOT NULL
    REMOVE t.cached_summary,
           t.cached_summary_at,
           t.cached_message_count,
           t.cached_last_message_at,
           t.cached_topics,
           t.cached_participants,
           t.cached_sentiment
    RETURN t.uuid
    """

    result = await neo4j.execute_query(
        query,
        {"thread_uuid": thread_uuid},
        trace_id=trace_id,
    )

    invalidated = len(result) > 0

    if invalidated:
        logger.debug(
            f"[WHISPER] Invalidated summary cache for thread {thread_uuid[:8]}...",
            extra={"trace_id": trace_id, "agent_name": "summary_cache"},
        )

    return invalidated


async def get_or_compute_summary(
    neo4j: Neo4jClient,
    thread_uuid: str,
    compute_fn: SummaryComputeFn,
    trace_id: str | None = None,
) -> ThreadSummary:
    """
    Get cached summary or compute a new one.

    This is the main entry point for summary caching. It:
    1. Checks for a valid cached summary
    2. If found, returns it immediately
    3. If not found, calls compute_fn to generate a new summary
    4. Caches the new summary before returning

    Args:
        neo4j: Connected Neo4jClient instance
        thread_uuid: UUID of the thread
        compute_fn: Async function that takes trace_id and returns ThreadSummary
        trace_id: Optional trace ID for logging

    Returns:
        ThreadSummary (either from cache or newly computed)
    """
    # Try to get cached summary
    cached = await get_cached_summary(neo4j, thread_uuid, trace_id)

    if cached is not None:
        return cached.summary

    # Compute new summary
    logger.info(
        f"[CHART] Computing summary for thread {thread_uuid[:8]}... (cache miss)",
        extra={"trace_id": trace_id, "agent_name": "summary_cache"},
    )

    summary = await compute_fn(trace_id)

    # Cache the computed summary
    await set_cached_summary(neo4j, thread_uuid, summary, trace_id)

    return summary


async def get_cache_statistics(
    neo4j: Neo4jClient,
    trace_id: str | None = None,
) -> dict:
    """
    Get summary cache statistics.

    Returns counts of cached vs uncached threads for monitoring.

    Args:
        neo4j: Connected Neo4jClient instance
        trace_id: Optional trace ID for logging

    Returns:
        Dictionary with cache statistics
    """
    query = """
    MATCH (t:Thread)
    WHERE t.status = 'active'
    RETURN
        count(t) as total_threads,
        sum(CASE WHEN t.cached_summary IS NOT NULL THEN 1 ELSE 0 END) as cached_threads,
        sum(CASE WHEN t.cached_summary IS NULL THEN 1 ELSE 0 END) as uncached_threads
    """

    result = await neo4j.execute_query(query, {}, trace_id=trace_id)

    if not result:
        return {
            "total_threads": 0,
            "cached_threads": 0,
            "uncached_threads": 0,
            "cache_hit_rate": 0.0,
        }

    row = result[0]
    total = row.get("total_threads") or 0
    cached = row.get("cached_threads") or 0

    return {
        "total_threads": total,
        "cached_threads": cached,
        "uncached_threads": row.get("uncached_threads") or 0,
        "cache_hit_rate": cached / total if total > 0 else 0.0,
    }


# =============================================================================
# Export
# =============================================================================

__all__ = [
    # Data Classes
    "CachedSummary",
    # Operations
    "get_cache_statistics",
    "get_cached_summary",
    "get_or_compute_summary",
    "invalidate_summary_cache",
    "set_cached_summary",
]
