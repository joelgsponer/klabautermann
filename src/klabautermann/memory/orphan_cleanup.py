"""
Orphan message cleanup for Klabautermann.

Finds and removes messages not linked to any thread, which can occur
due to failed transactions or concurrent modifications.

Reference: specs/architecture/MEMORY.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class OrphanCleanupResult:
    """Result of an orphan cleanup operation."""

    orphan_count: int
    deleted_count: int
    failed_count: int
    execution_time_ms: float
    timestamp: datetime


@dataclass
class OrphanMessage:
    """An orphaned message node."""

    uuid: str
    content: str | None
    timestamp: float | None
    role: str | None


# =============================================================================
# Orphan Detection
# =============================================================================


async def find_orphan_messages(
    neo4j: Neo4jClient,
    limit: int = 100,
    trace_id: str | None = None,
) -> list[OrphanMessage]:
    """
    Find messages not linked to any thread.

    Args:
        neo4j: Connected Neo4jClient instance
        limit: Maximum number of orphans to return
        trace_id: Optional trace ID for logging

    Returns:
        List of OrphanMessage instances
    """
    logger.debug(
        f"[WHISPER] Searching for orphan messages (limit={limit})",
        extra={"trace_id": trace_id, "agent_name": "orphan_cleanup"},
    )

    query = """
    MATCH (m:Message)
    WHERE NOT EXISTS {
        MATCH (t:Thread)-[:CONTAINS]->(m)
    }
    RETURN m.uuid AS uuid, m.content AS content, m.timestamp AS timestamp, m.role AS role
    LIMIT $limit
    """

    result = await neo4j.execute_query(query, {"limit": limit}, trace_id=trace_id)

    orphans = [
        OrphanMessage(
            uuid=row["uuid"],
            content=row.get("content"),
            timestamp=row.get("timestamp"),
            role=row.get("role"),
        )
        for row in result
    ]

    logger.debug(
        f"[WHISPER] Found {len(orphans)} orphan messages",
        extra={"trace_id": trace_id, "agent_name": "orphan_cleanup"},
    )

    return orphans


async def count_orphan_messages(
    neo4j: Neo4jClient,
    trace_id: str | None = None,
) -> int:
    """
    Count total orphan messages in the graph.

    Args:
        neo4j: Connected Neo4jClient instance
        trace_id: Optional trace ID for logging

    Returns:
        Count of orphan messages
    """
    query = """
    MATCH (m:Message)
    WHERE NOT EXISTS {
        MATCH (t:Thread)-[:CONTAINS]->(m)
    }
    RETURN count(m) AS count
    """

    result = await neo4j.execute_query(query, {}, trace_id=trace_id)
    return int(result[0]["count"]) if result else 0


# =============================================================================
# Orphan Cleanup
# =============================================================================


async def delete_orphan_messages(
    neo4j: Neo4jClient,
    batch_size: int = 50,
    dry_run: bool = False,
    trace_id: str | None = None,
) -> OrphanCleanupResult:
    """
    Delete orphan messages from the graph.

    Args:
        neo4j: Connected Neo4jClient instance
        batch_size: Number of orphans to delete in one batch
        dry_run: If True, only count without deleting
        trace_id: Optional trace ID for logging

    Returns:
        OrphanCleanupResult with deletion statistics
    """
    import time

    start_time = time.time()

    logger.info(
        f"[CHART] Starting orphan cleanup (batch_size={batch_size}, dry_run={dry_run})",
        extra={"trace_id": trace_id, "agent_name": "orphan_cleanup"},
    )

    # Count orphans first
    orphan_count = await count_orphan_messages(neo4j, trace_id)

    if orphan_count == 0:
        logger.info(
            "[CHART] No orphan messages found",
            extra={"trace_id": trace_id, "agent_name": "orphan_cleanup"},
        )
        return OrphanCleanupResult(
            orphan_count=0,
            deleted_count=0,
            failed_count=0,
            execution_time_ms=(time.time() - start_time) * 1000,
            timestamp=datetime.now(),
        )

    if dry_run:
        logger.info(
            f"[CHART] Dry run: would delete {orphan_count} orphan messages",
            extra={"trace_id": trace_id, "agent_name": "orphan_cleanup"},
        )
        return OrphanCleanupResult(
            orphan_count=orphan_count,
            deleted_count=0,
            failed_count=0,
            execution_time_ms=(time.time() - start_time) * 1000,
            timestamp=datetime.now(),
        )

    # Delete orphans in batches
    deleted_count = 0
    failed_count = 0

    while True:
        delete_query = """
        MATCH (m:Message)
        WHERE NOT EXISTS {
            MATCH (t:Thread)-[:CONTAINS]->(m)
        }
        WITH m LIMIT $batch_size
        DETACH DELETE m
        RETURN count(*) AS deleted
        """

        try:
            result = await neo4j.execute_query(
                delete_query,
                {"batch_size": batch_size},
                trace_id=trace_id,
            )
            batch_deleted = int(result[0]["deleted"]) if result else 0

            if batch_deleted == 0:
                break

            deleted_count += batch_deleted
            logger.debug(
                f"[WHISPER] Deleted batch of {batch_deleted} orphans (total: {deleted_count})",
                extra={"trace_id": trace_id, "agent_name": "orphan_cleanup"},
            )

        except Exception as e:
            failed_count += 1
            logger.error(
                f"[STORM] Error deleting orphan batch: {e}",
                extra={"trace_id": trace_id, "agent_name": "orphan_cleanup"},
            )
            break

    execution_time_ms = (time.time() - start_time) * 1000

    logger.info(
        f"[CHART] Orphan cleanup complete: {deleted_count} deleted, {failed_count} failed "
        f"({execution_time_ms:.1f}ms)",
        extra={"trace_id": trace_id, "agent_name": "orphan_cleanup"},
    )

    return OrphanCleanupResult(
        orphan_count=orphan_count,
        deleted_count=deleted_count,
        failed_count=failed_count,
        execution_time_ms=execution_time_ms,
        timestamp=datetime.now(),
    )


def cleanup_result_to_dict(result: OrphanCleanupResult) -> dict:
    """
    Convert OrphanCleanupResult to a serializable dictionary.

    Args:
        result: OrphanCleanupResult instance

    Returns:
        Dictionary representation
    """
    return {
        "orphan_count": result.orphan_count,
        "deleted_count": result.deleted_count,
        "failed_count": result.failed_count,
        "execution_time_ms": result.execution_time_ms,
        "timestamp": result.timestamp.isoformat(),
    }


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "OrphanCleanupResult",
    "OrphanMessage",
    "cleanup_result_to_dict",
    "count_orphan_messages",
    "delete_orphan_messages",
    "find_orphan_messages",
]
