"""
Memory health monitoring for Klabautermann.

Tracks database connection status, query latencies, and error rates
for the Neo4j knowledge graph.

Reference: specs/architecture/MEMORY.md
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Constants
# =============================================================================

# Maximum number of latency samples to keep
MAX_LATENCY_SAMPLES = 100

# Maximum number of error records to keep
MAX_ERROR_RECORDS = 50


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class QueryLatency:
    """Record of a query's execution time."""

    query_type: str
    latency_ms: float
    timestamp: datetime
    success: bool


@dataclass
class ErrorRecord:
    """Record of a query error."""

    query_type: str
    error_message: str
    timestamp: datetime


@dataclass
class MemoryHealthStatus:
    """Current health status of the memory system."""

    is_connected: bool
    connection_latency_ms: float | None

    # Query statistics
    total_queries: int
    successful_queries: int
    failed_queries: int

    # Latency statistics
    avg_latency_ms: float | None
    min_latency_ms: float | None
    max_latency_ms: float | None
    p95_latency_ms: float | None

    # Error rate
    error_rate: float  # 0.0 to 1.0

    # Recent errors
    recent_errors: list[str]

    # Timestamps
    last_successful_query_at: datetime | None
    last_error_at: datetime | None
    status_computed_at: datetime


# =============================================================================
# Health Monitor
# =============================================================================


class MemoryHealthMonitor:
    """
    Monitor for memory system health.

    Tracks connection status, query latencies, and error rates.
    Provides health snapshots for monitoring and alerting.

    Usage:
        monitor = MemoryHealthMonitor()
        monitor.record_query("read", 45.2, success=True)
        status = monitor.get_health_status(neo4j)
    """

    def __init__(self) -> None:
        """Initialize health monitor."""
        self._latencies: deque[QueryLatency] = deque(maxlen=MAX_LATENCY_SAMPLES)
        self._errors: deque[ErrorRecord] = deque(maxlen=MAX_ERROR_RECORDS)
        self._total_queries = 0
        self._successful_queries = 0
        self._failed_queries = 0
        self._last_successful_at: datetime | None = None
        self._last_error_at: datetime | None = None

    def record_query(
        self,
        query_type: str,
        latency_ms: float,
        success: bool = True,
        error_message: str | None = None,
    ) -> None:
        """
        Record a query execution.

        Args:
            query_type: Type of query (read, write, etc.)
            latency_ms: Execution time in milliseconds
            success: Whether query succeeded
            error_message: Error message if failed
        """
        now = datetime.now()

        # Record latency
        self._latencies.append(
            QueryLatency(
                query_type=query_type,
                latency_ms=latency_ms,
                timestamp=now,
                success=success,
            )
        )

        # Update counters
        self._total_queries += 1
        if success:
            self._successful_queries += 1
            self._last_successful_at = now
        else:
            self._failed_queries += 1
            self._last_error_at = now
            if error_message:
                self._errors.append(
                    ErrorRecord(
                        query_type=query_type,
                        error_message=error_message,
                        timestamp=now,
                    )
                )

    async def check_connection(
        self,
        neo4j: Neo4jClient,
        trace_id: str | None = None,
    ) -> tuple[bool, float | None]:
        """
        Check database connection and measure latency.

        Args:
            neo4j: Neo4jClient instance
            trace_id: Optional trace ID for logging

        Returns:
            Tuple of (is_connected, latency_ms)
        """
        start = time.time()
        try:
            # Simple query to test connection
            await neo4j.execute_query("RETURN 1 AS ping", {}, trace_id=trace_id)
            latency_ms = (time.time() - start) * 1000
            return True, latency_ms
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            logger.warning(
                f"[SWELL] Connection check failed: {e}",
                extra={"trace_id": trace_id, "agent_name": "health_monitor"},
            )
            return False, latency_ms

    def _calculate_latency_stats(self) -> dict[str, float | None]:
        """Calculate latency statistics from samples."""
        if not self._latencies:
            return {
                "avg": None,
                "min": None,
                "max": None,
                "p95": None,
            }

        latency_values = [q.latency_ms for q in self._latencies if q.success]
        if not latency_values:
            return {
                "avg": None,
                "min": None,
                "max": None,
                "p95": None,
            }

        sorted_latencies = sorted(latency_values)
        n = len(sorted_latencies)

        avg = sum(latency_values) / n
        min_val = sorted_latencies[0]
        max_val = sorted_latencies[-1]

        # P95 calculation
        p95_index = int(0.95 * n)
        p95 = sorted_latencies[min(p95_index, n - 1)]

        return {
            "avg": avg,
            "min": min_val,
            "max": max_val,
            "p95": p95,
        }

    async def get_health_status(
        self,
        neo4j: Neo4jClient,
        trace_id: str | None = None,
    ) -> MemoryHealthStatus:
        """
        Get current health status.

        Args:
            neo4j: Neo4jClient instance
            trace_id: Optional trace ID for logging

        Returns:
            MemoryHealthStatus with current metrics
        """
        logger.debug(
            "[WHISPER] Computing memory health status",
            extra={"trace_id": trace_id, "agent_name": "health_monitor"},
        )

        # Check connection
        is_connected, conn_latency = await self.check_connection(neo4j, trace_id)

        # Calculate latency stats
        latency_stats = self._calculate_latency_stats()

        # Calculate error rate
        error_rate = 0.0
        if self._total_queries > 0:
            error_rate = self._failed_queries / self._total_queries

        # Get recent error messages
        recent_errors = [e.error_message for e in list(self._errors)[-5:]]

        return MemoryHealthStatus(
            is_connected=is_connected,
            connection_latency_ms=conn_latency,
            total_queries=self._total_queries,
            successful_queries=self._successful_queries,
            failed_queries=self._failed_queries,
            avg_latency_ms=latency_stats["avg"],
            min_latency_ms=latency_stats["min"],
            max_latency_ms=latency_stats["max"],
            p95_latency_ms=latency_stats["p95"],
            error_rate=error_rate,
            recent_errors=recent_errors,
            last_successful_query_at=self._last_successful_at,
            last_error_at=self._last_error_at,
            status_computed_at=datetime.now(),
        )

    def reset(self) -> None:
        """Reset all statistics."""
        self._latencies.clear()
        self._errors.clear()
        self._total_queries = 0
        self._successful_queries = 0
        self._failed_queries = 0
        self._last_successful_at = None
        self._last_error_at = None
        logger.info(
            "[CHART] Health monitor reset",
            extra={"agent_name": "health_monitor"},
        )


def health_status_to_dict(status: MemoryHealthStatus) -> dict:
    """
    Convert MemoryHealthStatus to a serializable dictionary.

    Args:
        status: MemoryHealthStatus instance

    Returns:
        Dictionary representation
    """
    return {
        "is_connected": status.is_connected,
        "connection_latency_ms": status.connection_latency_ms,
        "total_queries": status.total_queries,
        "successful_queries": status.successful_queries,
        "failed_queries": status.failed_queries,
        "avg_latency_ms": status.avg_latency_ms,
        "min_latency_ms": status.min_latency_ms,
        "max_latency_ms": status.max_latency_ms,
        "p95_latency_ms": status.p95_latency_ms,
        "error_rate": status.error_rate,
        "recent_errors": status.recent_errors,
        "last_successful_query_at": status.last_successful_query_at.isoformat()
        if status.last_successful_query_at
        else None,
        "last_error_at": status.last_error_at.isoformat() if status.last_error_at else None,
        "status_computed_at": status.status_computed_at.isoformat(),
    }


# =============================================================================
# Module-level monitor instance
# =============================================================================

_monitor: MemoryHealthMonitor | None = None


def get_health_monitor() -> MemoryHealthMonitor:
    """Get or create the global health monitor."""
    global _monitor
    if _monitor is None:
        _monitor = MemoryHealthMonitor()
    return _monitor


def reset_health_monitor() -> None:
    """Reset the global health monitor."""
    global _monitor
    _monitor = None


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "ErrorRecord",
    "MemoryHealthMonitor",
    "MemoryHealthStatus",
    "QueryLatency",
    "get_health_monitor",
    "health_status_to_dict",
    "reset_health_monitor",
]
