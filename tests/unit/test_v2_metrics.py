"""
Unit tests for V2WorkflowMetrics.

Tests the metrics tracking model for Orchestrator v2 workflow including
request counting, latency tracking, and computed properties.
"""

from klabautermann.core.models import V2WorkflowMetrics


class TestV2WorkflowMetricsInit:
    """Test V2WorkflowMetrics initialization."""

    def test_default_initialization(self) -> None:
        """Test metrics start at zero."""
        metrics = V2WorkflowMetrics()

        assert metrics.request_count == 0
        assert metrics.success_count == 0
        assert metrics.error_count == 0
        assert metrics.direct_response_count == 0
        assert metrics.total_latency_sum == 0.0
        assert metrics.task_count_sum == 0

    def test_custom_initialization(self) -> None:
        """Test metrics can be initialized with values."""
        metrics = V2WorkflowMetrics(
            request_count=10,
            success_count=8,
            error_count=2,
        )

        assert metrics.request_count == 10
        assert metrics.success_count == 8
        assert metrics.error_count == 2


class TestV2WorkflowMetricsRecording:
    """Test V2WorkflowMetrics recording functionality."""

    def test_record_successful_request(self) -> None:
        """Test recording a successful request."""
        metrics = V2WorkflowMetrics()

        metrics.record_request(
            success=True,
            direct_response=False,
            latencies={"total": 1500.0, "context": 200.0, "planning": 300.0},
            task_counts={"ingest": 1, "research": 2, "execute": 0},
        )

        assert metrics.request_count == 1
        assert metrics.success_count == 1
        assert metrics.error_count == 0
        assert metrics.total_latency_sum == 1500.0
        assert metrics.context_latency_sum == 200.0
        assert metrics.planning_latency_sum == 300.0
        assert metrics.task_count_sum == 3
        assert metrics.ingest_task_count == 1
        assert metrics.research_task_count == 2

    def test_record_failed_request(self) -> None:
        """Test recording a failed request."""
        metrics = V2WorkflowMetrics()

        metrics.record_request(
            success=False,
            direct_response=False,
            latencies={"total": 500.0},
            task_counts={},
        )

        assert metrics.request_count == 1
        assert metrics.success_count == 0
        assert metrics.error_count == 1

    def test_record_direct_response(self) -> None:
        """Test recording a direct response (no tasks)."""
        metrics = V2WorkflowMetrics()

        metrics.record_request(
            success=True,
            direct_response=True,
            latencies={"total": 100.0},
            task_counts={},
        )

        assert metrics.request_count == 1
        assert metrics.direct_response_count == 1
        assert metrics.task_count_sum == 0

    def test_record_multiple_requests(self) -> None:
        """Test recording multiple requests."""
        metrics = V2WorkflowMetrics()

        # First request - success
        metrics.record_request(
            success=True,
            direct_response=False,
            latencies={"total": 1000.0},
            task_counts={"research": 2},
        )

        # Second request - failure
        metrics.record_request(
            success=False,
            direct_response=False,
            latencies={"total": 500.0},
            task_counts={"execute": 1},
        )

        # Third request - direct response
        metrics.record_request(
            success=True,
            direct_response=True,
            latencies={"total": 50.0},
            task_counts={},
        )

        assert metrics.request_count == 3
        assert metrics.success_count == 2
        assert metrics.error_count == 1
        assert metrics.direct_response_count == 1
        assert metrics.total_latency_sum == 1550.0
        assert metrics.task_count_sum == 3


class TestV2WorkflowMetricsComputedProperties:
    """Test V2WorkflowMetrics computed properties."""

    def test_avg_latency_ms_empty(self) -> None:
        """Test average latency with no requests."""
        metrics = V2WorkflowMetrics()
        assert metrics.avg_latency_ms == 0.0

    def test_avg_latency_ms(self) -> None:
        """Test average latency calculation."""
        metrics = V2WorkflowMetrics()
        metrics.record_request(True, False, {"total": 1000.0}, {})
        metrics.record_request(True, False, {"total": 2000.0}, {})

        assert metrics.avg_latency_ms == 1500.0

    def test_success_rate_empty(self) -> None:
        """Test success rate with no requests."""
        metrics = V2WorkflowMetrics()
        assert metrics.success_rate == 0.0

    def test_success_rate(self) -> None:
        """Test success rate calculation."""
        metrics = V2WorkflowMetrics()
        metrics.record_request(True, False, {"total": 100.0}, {})
        metrics.record_request(True, False, {"total": 100.0}, {})
        metrics.record_request(False, False, {"total": 100.0}, {})
        metrics.record_request(True, False, {"total": 100.0}, {})

        assert metrics.success_rate == 0.75

    def test_direct_response_rate_empty(self) -> None:
        """Test direct response rate with no requests."""
        metrics = V2WorkflowMetrics()
        assert metrics.direct_response_rate == 0.0

    def test_direct_response_rate(self) -> None:
        """Test direct response rate calculation."""
        metrics = V2WorkflowMetrics()
        metrics.record_request(True, True, {"total": 50.0}, {})
        metrics.record_request(True, False, {"total": 1000.0}, {"research": 2})
        metrics.record_request(True, True, {"total": 75.0}, {})
        metrics.record_request(True, False, {"total": 1500.0}, {"execute": 1})

        assert metrics.direct_response_rate == 0.5

    def test_avg_tasks_per_request_empty(self) -> None:
        """Test average tasks with no requests."""
        metrics = V2WorkflowMetrics()
        assert metrics.avg_tasks_per_request == 0.0

    def test_avg_tasks_per_request(self) -> None:
        """Test average tasks calculation."""
        metrics = V2WorkflowMetrics()
        metrics.record_request(True, False, {"total": 100.0}, {"ingest": 1, "research": 2})
        metrics.record_request(True, False, {"total": 100.0}, {"execute": 1})

        assert metrics.avg_tasks_per_request == 2.0


class TestV2WorkflowMetricsToDict:
    """Test V2WorkflowMetrics export functionality."""

    def test_to_dict_empty(self) -> None:
        """Test to_dict with no data."""
        metrics = V2WorkflowMetrics()
        result = metrics.to_dict()

        assert result["requests"]["total"] == 0
        assert result["rates"]["success_rate"] == 0.0
        assert result["tasks"]["total"] == 0

    def test_to_dict_with_data(self) -> None:
        """Test to_dict with recorded data."""
        metrics = V2WorkflowMetrics()
        metrics.record_request(
            success=True,
            direct_response=False,
            latencies={
                "total": 1500.0,
                "context": 200.0,
                "planning": 300.0,
                "execution": 800.0,
                "synthesis": 200.0,
            },
            task_counts={"ingest": 1, "research": 2, "execute": 1},
        )

        result = metrics.to_dict()

        assert result["requests"]["total"] == 1
        assert result["requests"]["success"] == 1
        assert result["rates"]["success_rate"] == 1.0
        assert result["latency_ms"]["avg_total"] == 1500.0
        assert result["tasks"]["total"] == 4
        assert result["tasks"]["by_type"]["research"] == 2
