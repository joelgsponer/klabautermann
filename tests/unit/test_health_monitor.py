"""
Unit tests for memory health monitor module.

Tests connection checking, latency tracking, and error rate calculation.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.health_monitor import (
    ErrorRecord,
    MemoryHealthMonitor,
    MemoryHealthStatus,
    QueryLatency,
    get_health_monitor,
    health_status_to_dict,
    reset_health_monitor,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Create a mock Neo4jClient."""
    client = MagicMock()
    client.execute_query = AsyncMock()
    return client


@pytest.fixture
def monitor() -> MemoryHealthMonitor:
    """Create a fresh health monitor."""
    return MemoryHealthMonitor()


@pytest.fixture(autouse=True)
def reset_global_monitor() -> None:
    """Reset global monitor before each test."""
    reset_health_monitor()


# =============================================================================
# Test Data Classes
# =============================================================================


class TestQueryLatency:
    """Tests for QueryLatency dataclass."""

    def test_creation(self) -> None:
        """Test creating QueryLatency."""
        latency = QueryLatency(
            query_type="read",
            latency_ms=45.5,
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
            success=True,
        )
        assert latency.query_type == "read"
        assert latency.latency_ms == 45.5
        assert latency.success is True


class TestErrorRecord:
    """Tests for ErrorRecord dataclass."""

    def test_creation(self) -> None:
        """Test creating ErrorRecord."""
        error = ErrorRecord(
            query_type="write",
            error_message="Connection refused",
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
        )
        assert error.query_type == "write"
        assert error.error_message == "Connection refused"


class TestMemoryHealthStatus:
    """Tests for MemoryHealthStatus dataclass."""

    def test_creation(self) -> None:
        """Test creating MemoryHealthStatus."""
        status = MemoryHealthStatus(
            is_connected=True,
            connection_latency_ms=15.0,
            total_queries=100,
            successful_queries=95,
            failed_queries=5,
            avg_latency_ms=25.5,
            min_latency_ms=5.0,
            max_latency_ms=150.0,
            p95_latency_ms=75.0,
            error_rate=0.05,
            recent_errors=["Error 1"],
            last_successful_query_at=datetime(2024, 1, 15, 10, 0, 0),
            last_error_at=datetime(2024, 1, 15, 9, 55, 0),
            status_computed_at=datetime(2024, 1, 15, 10, 0, 0),
        )
        assert status.is_connected is True
        assert status.error_rate == 0.05


# =============================================================================
# Test Health Monitor
# =============================================================================


class TestMemoryHealthMonitor:
    """Tests for MemoryHealthMonitor class."""

    def test_initial_state(self, monitor: MemoryHealthMonitor) -> None:
        """Test initial monitor state."""
        assert monitor._total_queries == 0
        assert monitor._successful_queries == 0
        assert monitor._failed_queries == 0

    def test_record_successful_query(self, monitor: MemoryHealthMonitor) -> None:
        """Test recording successful query."""
        monitor.record_query("read", 25.0, success=True)

        assert monitor._total_queries == 1
        assert monitor._successful_queries == 1
        assert monitor._failed_queries == 0
        assert monitor._last_successful_at is not None

    def test_record_failed_query(self, monitor: MemoryHealthMonitor) -> None:
        """Test recording failed query."""
        monitor.record_query("write", 50.0, success=False, error_message="Error")

        assert monitor._total_queries == 1
        assert monitor._successful_queries == 0
        assert monitor._failed_queries == 1
        assert monitor._last_error_at is not None

    def test_multiple_queries(self, monitor: MemoryHealthMonitor) -> None:
        """Test recording multiple queries."""
        for i in range(10):
            success = i < 8  # 80% success rate
            monitor.record_query("read", float(i * 10), success=success)

        assert monitor._total_queries == 10
        assert monitor._successful_queries == 8
        assert monitor._failed_queries == 2

    @pytest.mark.asyncio
    async def test_check_connection_success(
        self, monitor: MemoryHealthMonitor, mock_neo4j: MagicMock
    ) -> None:
        """Test successful connection check."""
        mock_neo4j.execute_query.return_value = [{"ping": 1}]

        is_connected, latency = await monitor.check_connection(mock_neo4j)

        assert is_connected is True
        assert latency is not None
        assert latency >= 0

    @pytest.mark.asyncio
    async def test_check_connection_failure(
        self, monitor: MemoryHealthMonitor, mock_neo4j: MagicMock
    ) -> None:
        """Test failed connection check."""
        mock_neo4j.execute_query.side_effect = Exception("Connection refused")

        is_connected, latency = await monitor.check_connection(mock_neo4j)

        assert is_connected is False
        assert latency is not None

    @pytest.mark.asyncio
    async def test_get_health_status(
        self, monitor: MemoryHealthMonitor, mock_neo4j: MagicMock
    ) -> None:
        """Test getting health status."""
        # Record some queries
        monitor.record_query("read", 20.0, success=True)
        monitor.record_query("read", 30.0, success=True)
        monitor.record_query("write", 100.0, success=False, error_message="Failed")

        mock_neo4j.execute_query.return_value = [{"ping": 1}]

        status = await monitor.get_health_status(mock_neo4j)

        assert status.is_connected is True
        assert status.total_queries == 3
        assert status.successful_queries == 2
        assert status.failed_queries == 1
        assert status.error_rate == pytest.approx(1 / 3)

    def test_reset(self, monitor: MemoryHealthMonitor) -> None:
        """Test resetting monitor."""
        monitor.record_query("read", 25.0, success=True)
        monitor.reset()

        assert monitor._total_queries == 0
        assert monitor._successful_queries == 0
        assert len(monitor._latencies) == 0

    def test_latency_stats_calculation(self, monitor: MemoryHealthMonitor) -> None:
        """Test latency statistics calculation."""
        # Add latency samples
        for latency in [10.0, 20.0, 30.0, 40.0, 50.0]:
            monitor.record_query("read", latency, success=True)

        stats = monitor._calculate_latency_stats()

        assert stats["avg"] == pytest.approx(30.0)
        assert stats["min"] == 10.0
        assert stats["max"] == 50.0
        assert stats["p95"] is not None

    def test_latency_stats_empty(self, monitor: MemoryHealthMonitor) -> None:
        """Test latency stats with no samples."""
        stats = monitor._calculate_latency_stats()

        assert stats["avg"] is None
        assert stats["min"] is None
        assert stats["max"] is None
        assert stats["p95"] is None


# =============================================================================
# Test Global Instance
# =============================================================================


class TestGlobalInstance:
    """Tests for global monitor instance."""

    def test_get_health_monitor(self) -> None:
        """Test getting global monitor."""
        monitor1 = get_health_monitor()
        monitor2 = get_health_monitor()

        assert monitor1 is monitor2

    def test_reset_health_monitor(self) -> None:
        """Test resetting global monitor."""
        monitor1 = get_health_monitor()
        reset_health_monitor()
        monitor2 = get_health_monitor()

        assert monitor1 is not monitor2


# =============================================================================
# Test Serialization
# =============================================================================


class TestHealthStatusToDict:
    """Tests for health_status_to_dict function."""

    def test_converts_to_dict(self) -> None:
        """Test converting status to dictionary."""
        status = MemoryHealthStatus(
            is_connected=True,
            connection_latency_ms=15.0,
            total_queries=100,
            successful_queries=95,
            failed_queries=5,
            avg_latency_ms=25.5,
            min_latency_ms=5.0,
            max_latency_ms=150.0,
            p95_latency_ms=75.0,
            error_rate=0.05,
            recent_errors=["Error 1"],
            last_successful_query_at=datetime(2024, 1, 15, 10, 0, 0),
            last_error_at=None,
            status_computed_at=datetime(2024, 1, 15, 10, 0, 0),
        )

        d = health_status_to_dict(status)

        assert d["is_connected"] is True
        assert d["total_queries"] == 100
        assert d["error_rate"] == 0.05
        assert d["last_error_at"] is None
        assert "status_computed_at" in d
