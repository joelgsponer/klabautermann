"""
Tests for Prometheus metrics module.

Tests cover:
- Metric registration and generation
- Agent metrics recording
- API metrics recording
- Graph operation metrics
- LLM metrics
- Timed operation decorator
"""

import asyncio

import pytest

from klabautermann.core.metrics import (
    AGENT_ERRORS_TOTAL,
    AGENT_INBOX_SIZE,
    AGENT_REQUESTS_TOTAL,
    AGENT_RUNNING,
    AGENT_SUCCESSES_TOTAL,
    API_REQUESTS_TOTAL,
    API_WEBSOCKET_CONNECTIONS,
    CHANNEL_ACTIVE_COUNT,
    CHANNEL_BROADCAST_DELIVERIES_TOTAL,
    CHANNEL_BROADCASTS_TOTAL,
    CHANNEL_ERRORS_TOTAL,
    CHANNEL_HEALTHY,
    CHANNEL_MESSAGES_TOTAL,
    CHANNEL_STATUS,
    GRAPH_OPERATIONS_TOTAL,
    LLM_CALLS_TOTAL,
    LLM_TOKENS_TOTAL,
    REGISTRY,
    decrement_websocket_connections,
    get_metrics,
    increment_websocket_connections,
    record_agent_error,
    record_agent_latency,
    record_agent_request,
    record_agent_success,
    record_api_latency,
    record_api_request,
    record_channel_broadcast,
    record_channel_broadcast_delivery,
    record_channel_error,
    record_channel_latency,
    record_channel_message,
    record_graph_latency,
    record_graph_operation,
    record_llm_call,
    record_llm_latency,
    record_llm_tokens,
    set_agent_inbox_size,
    set_agent_running,
    set_channel_active_count,
    set_channel_healthy,
    set_channel_status,
    set_websocket_connections,
    timed_operation,
)


# ===========================================================================
# Registry and Generation Tests
# ===========================================================================


class TestRegistry:
    """Tests for the Prometheus registry."""

    def test_registry_exists(self):
        """Registry should be initialized."""
        assert REGISTRY is not None

    def test_get_metrics_returns_bytes(self):
        """get_metrics should return bytes in Prometheus format."""
        metrics = get_metrics()
        assert isinstance(metrics, bytes)

    def test_get_metrics_contains_metric_names(self):
        """Metrics output should contain expected metric names."""
        metrics = get_metrics().decode("utf-8")

        # Check for agent metrics
        assert "klabautermann_agent_requests_total" in metrics
        assert "klabautermann_agent_successes_total" in metrics
        assert "klabautermann_agent_errors_total" in metrics
        assert "klabautermann_agent_request_latency_ms" in metrics

        # Check for API metrics
        assert "klabautermann_api_requests_total" in metrics
        assert "klabautermann_api_request_latency_seconds" in metrics

        # Check for graph metrics
        assert "klabautermann_graph_operations_total" in metrics
        assert "klabautermann_graph_operation_latency_seconds" in metrics

        # Check for LLM metrics
        assert "klabautermann_llm_calls_total" in metrics
        assert "klabautermann_llm_tokens_total" in metrics


# ===========================================================================
# Agent Metrics Tests
# ===========================================================================


class TestAgentMetrics:
    """Tests for agent metrics recording."""

    def test_record_agent_request(self):
        """Should increment agent request counter."""
        initial = AGENT_REQUESTS_TOTAL.labels(agent_name="test_agent")._value.get()
        record_agent_request("test_agent")
        after = AGENT_REQUESTS_TOTAL.labels(agent_name="test_agent")._value.get()
        assert after == initial + 1

    def test_record_agent_success(self):
        """Should increment agent success counter."""
        initial = AGENT_SUCCESSES_TOTAL.labels(agent_name="test_agent")._value.get()
        record_agent_success("test_agent")
        after = AGENT_SUCCESSES_TOTAL.labels(agent_name="test_agent")._value.get()
        assert after == initial + 1

    def test_record_agent_error(self):
        """Should increment agent error counter."""
        initial = AGENT_ERRORS_TOTAL.labels(agent_name="test_agent")._value.get()
        record_agent_error("test_agent")
        after = AGENT_ERRORS_TOTAL.labels(agent_name="test_agent")._value.get()
        assert after == initial + 1

    def test_record_agent_latency(self):
        """Should record latency in histogram."""
        record_agent_latency("latency_test_agent", 100.5)
        # Verify the metric was recorded by checking it appears in output
        metrics = get_metrics().decode("utf-8")
        assert 'agent_name="latency_test_agent"' in metrics
        assert "klabautermann_agent_request_latency_ms" in metrics

    def test_set_agent_running_true(self):
        """Should set running gauge to 1."""
        set_agent_running("test_agent", running=True)
        value = AGENT_RUNNING.labels(agent_name="test_agent")._value.get()
        assert value == 1

    def test_set_agent_running_false(self):
        """Should set running gauge to 0."""
        set_agent_running("test_agent", running=False)
        value = AGENT_RUNNING.labels(agent_name="test_agent")._value.get()
        assert value == 0

    def test_set_agent_inbox_size(self):
        """Should set inbox size gauge."""
        set_agent_inbox_size("test_agent", 5)
        value = AGENT_INBOX_SIZE.labels(agent_name="test_agent")._value.get()
        assert value == 5


# ===========================================================================
# API Metrics Tests
# ===========================================================================


class TestAPIMetrics:
    """Tests for API metrics recording."""

    def test_record_api_request(self):
        """Should increment API request counter with labels."""
        initial = API_REQUESTS_TOTAL.labels(
            method="GET", endpoint="/test", status_code="200"
        )._value.get()
        record_api_request("GET", "/test", 200)
        after = API_REQUESTS_TOTAL.labels(
            method="GET", endpoint="/test", status_code="200"
        )._value.get()
        assert after == initial + 1

    def test_record_api_request_different_status(self):
        """Should track different status codes separately."""
        initial_200 = API_REQUESTS_TOTAL.labels(
            method="POST", endpoint="/api", status_code="200"
        )._value.get()
        initial_500 = API_REQUESTS_TOTAL.labels(
            method="POST", endpoint="/api", status_code="500"
        )._value.get()

        record_api_request("POST", "/api", 200)
        record_api_request("POST", "/api", 500)

        after_200 = API_REQUESTS_TOTAL.labels(
            method="POST", endpoint="/api", status_code="200"
        )._value.get()
        after_500 = API_REQUESTS_TOTAL.labels(
            method="POST", endpoint="/api", status_code="500"
        )._value.get()

        assert after_200 == initial_200 + 1
        assert after_500 == initial_500 + 1

    def test_record_api_latency(self):
        """Should record API latency in histogram."""
        record_api_latency("GET", "/api_latency_test", 0.05)
        # Verify the metric was recorded by checking it appears in output
        metrics = get_metrics().decode("utf-8")
        assert 'endpoint="/api_latency_test"' in metrics
        assert "klabautermann_api_request_latency_seconds" in metrics

    def test_websocket_connections_increment(self):
        """Should increment WebSocket connection count."""
        initial = API_WEBSOCKET_CONNECTIONS._value.get()
        increment_websocket_connections()
        after = API_WEBSOCKET_CONNECTIONS._value.get()
        assert after == initial + 1

    def test_websocket_connections_decrement(self):
        """Should decrement WebSocket connection count."""
        # Ensure we have at least 1 connection
        set_websocket_connections(5)
        initial = API_WEBSOCKET_CONNECTIONS._value.get()
        decrement_websocket_connections()
        after = API_WEBSOCKET_CONNECTIONS._value.get()
        assert after == initial - 1

    def test_set_websocket_connections(self):
        """Should set WebSocket connection count directly."""
        set_websocket_connections(10)
        value = API_WEBSOCKET_CONNECTIONS._value.get()
        assert value == 10


# ===========================================================================
# Graph Metrics Tests
# ===========================================================================


class TestGraphMetrics:
    """Tests for graph operation metrics."""

    def test_record_graph_operation(self):
        """Should increment graph operation counter."""
        initial = GRAPH_OPERATIONS_TOTAL.labels(operation_type="search")._value.get()
        record_graph_operation("search")
        after = GRAPH_OPERATIONS_TOTAL.labels(operation_type="search")._value.get()
        assert after == initial + 1

    def test_record_graph_latency(self):
        """Should record graph operation latency."""
        record_graph_latency("add_episode_test", 0.25)
        # Verify the metric was recorded by checking it appears in output
        metrics = get_metrics().decode("utf-8")
        assert 'operation_type="add_episode_test"' in metrics
        assert "klabautermann_graph_operation_latency_seconds" in metrics


# ===========================================================================
# LLM Metrics Tests
# ===========================================================================


class TestLLMMetrics:
    """Tests for LLM metrics recording."""

    def test_record_llm_call(self):
        """Should increment LLM call counter with labels."""
        initial = LLM_CALLS_TOTAL.labels(model="haiku", purpose="extraction")._value.get()
        record_llm_call("haiku", "extraction")
        after = LLM_CALLS_TOTAL.labels(model="haiku", purpose="extraction")._value.get()
        assert after == initial + 1

    def test_record_llm_tokens(self):
        """Should increment token counters."""
        initial_input = LLM_TOKENS_TOTAL.labels(model="sonnet", token_type="input")._value.get()
        initial_output = LLM_TOKENS_TOTAL.labels(model="sonnet", token_type="output")._value.get()

        record_llm_tokens("sonnet", input_tokens=500, output_tokens=200)

        after_input = LLM_TOKENS_TOTAL.labels(model="sonnet", token_type="input")._value.get()
        after_output = LLM_TOKENS_TOTAL.labels(model="sonnet", token_type="output")._value.get()

        assert after_input == initial_input + 500
        assert after_output == initial_output + 200

    def test_record_llm_latency(self):
        """Should record LLM call latency."""
        record_llm_latency("opus_test", 2.5)
        # Verify the metric was recorded by checking it appears in output
        metrics = get_metrics().decode("utf-8")
        assert 'model="opus_test"' in metrics
        assert "klabautermann_llm_call_latency_seconds" in metrics


# ===========================================================================
# Timed Operation Decorator Tests
# ===========================================================================


class TestTimedOperation:
    """Tests for the timed_operation decorator."""

    def test_timed_operation_sync(self):
        """Should time synchronous functions."""
        recorded_latencies = []

        def mock_record(label: str, latency: float) -> None:
            recorded_latencies.append((label, latency))

        @timed_operation(mock_record, "sync_op")
        def sync_function():
            return "result"

        result = sync_function()
        assert result == "result"
        assert len(recorded_latencies) == 1
        assert recorded_latencies[0][0] == "sync_op"
        assert recorded_latencies[0][1] >= 0

    @pytest.mark.asyncio
    async def test_timed_operation_async(self):
        """Should time asynchronous functions."""
        recorded_latencies = []

        def mock_record(label: str, latency: float) -> None:
            recorded_latencies.append((label, latency))

        @timed_operation(mock_record, "async_op")
        async def async_function():
            await asyncio.sleep(0.01)
            return "async_result"

        result = await async_function()
        assert result == "async_result"
        assert len(recorded_latencies) == 1
        assert recorded_latencies[0][0] == "async_op"
        assert recorded_latencies[0][1] >= 0.01

    def test_timed_operation_with_exception(self):
        """Should record timing even when exception occurs."""
        recorded_latencies = []

        def mock_record(label: str, latency: float) -> None:
            recorded_latencies.append((label, latency))

        @timed_operation(mock_record, "error_op")
        def failing_function():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing_function()

        # Should still have recorded the latency
        assert len(recorded_latencies) == 1
        assert recorded_latencies[0][0] == "error_op"


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestIntegration:
    """Integration tests for metrics system."""

    def test_metrics_output_format(self):
        """Metrics should be in valid Prometheus format."""
        # Record some metrics
        record_agent_request("integration_test")
        record_agent_latency("integration_test", 50.0)
        record_api_request("GET", "/test", 200)

        metrics = get_metrics().decode("utf-8")

        # Check format (should have HELP and TYPE lines)
        assert "# HELP klabautermann_agent_requests_total" in metrics
        assert "# TYPE klabautermann_agent_requests_total counter" in metrics

        # Check that our labels appear
        assert 'agent_name="integration_test"' in metrics

    def test_histogram_buckets_in_output(self):
        """Histogram metrics should include bucket information."""
        record_agent_latency("histogram_test", 100.0)

        metrics = get_metrics().decode("utf-8")

        # Histograms should have _bucket, _count, _sum
        assert "klabautermann_agent_request_latency_ms_bucket" in metrics
        assert "klabautermann_agent_request_latency_ms_count" in metrics
        assert "klabautermann_agent_request_latency_ms_sum" in metrics

    def test_multiple_labels_work_correctly(self):
        """Different label combinations should be tracked separately."""
        # Record for different agents
        for _ in range(3):
            record_agent_request("agent_a")
        for _ in range(5):
            record_agent_request("agent_b")

        metrics = get_metrics().decode("utf-8")

        # Both should appear in output
        assert 'agent_name="agent_a"' in metrics
        assert 'agent_name="agent_b"' in metrics


# ===========================================================================
# Channel Metrics Tests
# ===========================================================================


class TestChannelMetrics:
    """Tests for channel metrics recording."""

    def test_record_channel_message(self):
        """Should increment channel message counter."""
        initial = CHANNEL_MESSAGES_TOTAL.labels(channel_name="test_channel")._value.get()
        record_channel_message("test_channel")
        after = CHANNEL_MESSAGES_TOTAL.labels(channel_name="test_channel")._value.get()
        assert after == initial + 1

    def test_record_channel_latency(self):
        """Should record channel response latency."""
        record_channel_latency("latency_channel", 150.0)
        metrics = get_metrics().decode("utf-8")
        assert 'channel_name="latency_channel"' in metrics
        assert "klabautermann_channel_response_latency_ms" in metrics

    def test_record_channel_error(self):
        """Should increment channel error counter with error type."""
        initial = CHANNEL_ERRORS_TOTAL.labels(
            channel_name="error_channel", error_type="connection"
        )._value.get()
        record_channel_error("error_channel", "connection")
        after = CHANNEL_ERRORS_TOTAL.labels(
            channel_name="error_channel", error_type="connection"
        )._value.get()
        assert after == initial + 1

    def test_record_channel_error_different_types(self):
        """Should track different error types separately."""
        initial_conn = CHANNEL_ERRORS_TOTAL.labels(
            channel_name="multi_error_channel", error_type="connection"
        )._value.get()
        initial_timeout = CHANNEL_ERRORS_TOTAL.labels(
            channel_name="multi_error_channel", error_type="timeout"
        )._value.get()

        record_channel_error("multi_error_channel", "connection")
        record_channel_error("multi_error_channel", "timeout")

        after_conn = CHANNEL_ERRORS_TOTAL.labels(
            channel_name="multi_error_channel", error_type="connection"
        )._value.get()
        after_timeout = CHANNEL_ERRORS_TOTAL.labels(
            channel_name="multi_error_channel", error_type="timeout"
        )._value.get()

        assert after_conn == initial_conn + 1
        assert after_timeout == initial_timeout + 1

    def test_set_channel_status_running(self):
        """Should set channel status gauge to 1 when running."""
        set_channel_status("status_channel", running=True)
        value = CHANNEL_STATUS.labels(channel_name="status_channel")._value.get()
        assert value == 1

    def test_set_channel_status_stopped(self):
        """Should set channel status gauge to 0 when stopped."""
        set_channel_status("status_channel", running=False)
        value = CHANNEL_STATUS.labels(channel_name="status_channel")._value.get()
        assert value == 0

    def test_set_channel_healthy_true(self):
        """Should set channel health gauge to 1 when healthy."""
        set_channel_healthy("health_channel", healthy=True)
        value = CHANNEL_HEALTHY.labels(channel_name="health_channel")._value.get()
        assert value == 1

    def test_set_channel_healthy_false(self):
        """Should set channel health gauge to 0 when unhealthy."""
        set_channel_healthy("health_channel", healthy=False)
        value = CHANNEL_HEALTHY.labels(channel_name="health_channel")._value.get()
        assert value == 0

    def test_record_channel_broadcast(self):
        """Should increment broadcast counter."""
        initial = CHANNEL_BROADCASTS_TOTAL._value.get()
        record_channel_broadcast()
        after = CHANNEL_BROADCASTS_TOTAL._value.get()
        assert after == initial + 1

    def test_record_channel_broadcast_delivery_success(self):
        """Should track successful broadcast deliveries."""
        initial = CHANNEL_BROADCAST_DELIVERIES_TOTAL.labels(
            channel_name="delivery_channel", status="success"
        )._value.get()
        record_channel_broadcast_delivery("delivery_channel", success=True)
        after = CHANNEL_BROADCAST_DELIVERIES_TOTAL.labels(
            channel_name="delivery_channel", status="success"
        )._value.get()
        assert after == initial + 1

    def test_record_channel_broadcast_delivery_failure(self):
        """Should track failed broadcast deliveries."""
        initial = CHANNEL_BROADCAST_DELIVERIES_TOTAL.labels(
            channel_name="delivery_channel", status="failure"
        )._value.get()
        record_channel_broadcast_delivery("delivery_channel", success=False)
        after = CHANNEL_BROADCAST_DELIVERIES_TOTAL.labels(
            channel_name="delivery_channel", status="failure"
        )._value.get()
        assert after == initial + 1

    def test_set_channel_active_count(self):
        """Should set active channel count gauge."""
        set_channel_active_count(3)
        value = CHANNEL_ACTIVE_COUNT._value.get()
        assert value == 3

    def test_channel_metrics_in_output(self):
        """Channel metrics should appear in Prometheus output."""
        # Record some channel metrics
        record_channel_message("output_test_channel")
        record_channel_error("output_test_channel", "test_error")
        set_channel_status("output_test_channel", running=True)

        metrics = get_metrics().decode("utf-8")

        # Verify channel metrics are present
        assert "klabautermann_channel_messages_total" in metrics
        assert "klabautermann_channel_errors_total" in metrics
        assert "klabautermann_channel_status" in metrics
        assert "klabautermann_channel_healthy" in metrics
        assert "klabautermann_channel_broadcasts_total" in metrics
        assert "klabautermann_channel_active_count" in metrics
