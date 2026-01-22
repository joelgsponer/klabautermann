"""
Prometheus metrics for Klabautermann.

Provides instrumentation for agent performance, API health, and system observability.
Metrics are exposed via /metrics endpoint in Prometheus text format.

Reference: specs/infrastructure/DEPLOYMENT.md
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.multiprocess import MultiProcessCollector


if TYPE_CHECKING:
    from collections.abc import Callable

# ===========================================================================
# Default Registry
# ===========================================================================

# Use a custom registry to avoid conflicts and support multiprocess mode
REGISTRY = CollectorRegistry()

# Check if running in multiprocess mode (e.g., gunicorn with multiple workers)
try:
    MultiProcessCollector(REGISTRY)
    _MULTIPROCESS_MODE = True
except ValueError:
    # Not in multiprocess mode, use default collector
    _MULTIPROCESS_MODE = False


# ===========================================================================
# Agent Metrics
# ===========================================================================

# Request counter per agent
AGENT_REQUESTS_TOTAL = Counter(
    "klabautermann_agent_requests_total",
    "Total number of requests processed by agents",
    ["agent_name"],
    registry=REGISTRY,
)

# Success counter per agent
AGENT_SUCCESSES_TOTAL = Counter(
    "klabautermann_agent_successes_total",
    "Total number of successful requests by agents",
    ["agent_name"],
    registry=REGISTRY,
)

# Error counter per agent
AGENT_ERRORS_TOTAL = Counter(
    "klabautermann_agent_errors_total",
    "Total number of errors by agents",
    ["agent_name"],
    registry=REGISTRY,
)

# Request latency histogram per agent (in milliseconds)
AGENT_REQUEST_LATENCY_MS = Histogram(
    "klabautermann_agent_request_latency_ms",
    "Request latency in milliseconds by agent",
    ["agent_name"],
    buckets=[10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
    registry=REGISTRY,
)

# Currently running agents gauge
AGENT_RUNNING = Gauge(
    "klabautermann_agent_running",
    "Whether an agent is currently running (1=running, 0=stopped)",
    ["agent_name"],
    registry=REGISTRY,
)

# Agent inbox queue size
AGENT_INBOX_SIZE = Gauge(
    "klabautermann_agent_inbox_size",
    "Number of messages in agent inbox queue",
    ["agent_name"],
    registry=REGISTRY,
)


# ===========================================================================
# API Metrics
# ===========================================================================

# HTTP request counter
API_REQUESTS_TOTAL = Counter(
    "klabautermann_api_requests_total",
    "Total number of API requests",
    ["method", "endpoint", "status_code"],
    registry=REGISTRY,
)

# HTTP request latency histogram (in seconds)
API_REQUEST_LATENCY_SECONDS = Histogram(
    "klabautermann_api_request_latency_seconds",
    "API request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=REGISTRY,
)

# Active WebSocket connections
API_WEBSOCKET_CONNECTIONS = Gauge(
    "klabautermann_api_websocket_connections",
    "Number of active WebSocket connections",
    registry=REGISTRY,
)


# ===========================================================================
# Memory/Graph Metrics
# ===========================================================================

# Graph operations counter
GRAPH_OPERATIONS_TOTAL = Counter(
    "klabautermann_graph_operations_total",
    "Total number of graph operations",
    ["operation_type"],  # search, add_episode, get_entity, etc.
    registry=REGISTRY,
)

# Graph operation latency
GRAPH_OPERATION_LATENCY_SECONDS = Histogram(
    "klabautermann_graph_operation_latency_seconds",
    "Graph operation latency in seconds",
    ["operation_type"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=REGISTRY,
)


# ===========================================================================
# LLM Metrics
# ===========================================================================

# LLM calls counter
LLM_CALLS_TOTAL = Counter(
    "klabautermann_llm_calls_total",
    "Total number of LLM API calls",
    ["model", "purpose"],  # model: haiku/sonnet/opus, purpose: extraction/search/reasoning
    registry=REGISTRY,
)

# LLM token usage
LLM_TOKENS_TOTAL = Counter(
    "klabautermann_llm_tokens_total",
    "Total tokens used in LLM calls",
    ["model", "token_type"],  # token_type: input/output
    registry=REGISTRY,
)

# LLM call latency
LLM_CALL_LATENCY_SECONDS = Histogram(
    "klabautermann_llm_call_latency_seconds",
    "LLM API call latency in seconds",
    ["model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
    registry=REGISTRY,
)


# ===========================================================================
# Helper Functions
# ===========================================================================


def get_metrics() -> bytes:
    """
    Generate metrics in Prometheus text format.

    Returns:
        Metrics as bytes in Prometheus exposition format.
    """
    return bytes(generate_latest(REGISTRY))


def record_agent_request(agent_name: str) -> None:
    """Record an agent request."""
    AGENT_REQUESTS_TOTAL.labels(agent_name=agent_name).inc()


def record_agent_success(agent_name: str) -> None:
    """Record an agent success."""
    AGENT_SUCCESSES_TOTAL.labels(agent_name=agent_name).inc()


def record_agent_error(agent_name: str) -> None:
    """Record an agent error."""
    AGENT_ERRORS_TOTAL.labels(agent_name=agent_name).inc()


def record_agent_latency(agent_name: str, latency_ms: float) -> None:
    """Record agent request latency in milliseconds."""
    AGENT_REQUEST_LATENCY_MS.labels(agent_name=agent_name).observe(latency_ms)


def set_agent_running(agent_name: str, running: bool) -> None:
    """Set agent running status."""
    AGENT_RUNNING.labels(agent_name=agent_name).set(1 if running else 0)


def set_agent_inbox_size(agent_name: str, size: int) -> None:
    """Set agent inbox queue size."""
    AGENT_INBOX_SIZE.labels(agent_name=agent_name).set(size)


def record_api_request(method: str, endpoint: str, status_code: int) -> None:
    """Record an API request."""
    API_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status_code=str(status_code)).inc()


def record_api_latency(method: str, endpoint: str, latency_seconds: float) -> None:
    """Record API request latency in seconds."""
    API_REQUEST_LATENCY_SECONDS.labels(method=method, endpoint=endpoint).observe(latency_seconds)


def set_websocket_connections(count: int) -> None:
    """Set the number of active WebSocket connections."""
    API_WEBSOCKET_CONNECTIONS.set(count)


def increment_websocket_connections() -> None:
    """Increment WebSocket connection count."""
    API_WEBSOCKET_CONNECTIONS.inc()


def decrement_websocket_connections() -> None:
    """Decrement WebSocket connection count."""
    API_WEBSOCKET_CONNECTIONS.dec()


def record_graph_operation(operation_type: str) -> None:
    """Record a graph operation."""
    GRAPH_OPERATIONS_TOTAL.labels(operation_type=operation_type).inc()


def record_graph_latency(operation_type: str, latency_seconds: float) -> None:
    """Record graph operation latency in seconds."""
    GRAPH_OPERATION_LATENCY_SECONDS.labels(operation_type=operation_type).observe(latency_seconds)


def record_llm_call(model: str, purpose: str) -> None:
    """Record an LLM API call."""
    LLM_CALLS_TOTAL.labels(model=model, purpose=purpose).inc()


def record_llm_tokens(model: str, input_tokens: int, output_tokens: int) -> None:
    """Record LLM token usage."""
    LLM_TOKENS_TOTAL.labels(model=model, token_type="input").inc(input_tokens)
    LLM_TOKENS_TOTAL.labels(model=model, token_type="output").inc(output_tokens)


def record_llm_latency(model: str, latency_seconds: float) -> None:
    """Record LLM API call latency in seconds."""
    LLM_CALL_LATENCY_SECONDS.labels(model=model).observe(latency_seconds)


def timed_operation(metric_func: Callable[[str, float], None], label: str) -> Callable:
    """
    Decorator for timing operations.

    Args:
        metric_func: Function to record latency (e.g., record_graph_latency).
        label: Label value for the metric.

    Returns:
        Decorator function.
    """
    import functools
    import time

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                metric_func(label, elapsed)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                metric_func(label, elapsed)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "AGENT_ERRORS_TOTAL",
    "AGENT_INBOX_SIZE",
    # Agent metrics
    "AGENT_REQUESTS_TOTAL",
    "AGENT_REQUEST_LATENCY_MS",
    "AGENT_RUNNING",
    "AGENT_SUCCESSES_TOTAL",
    # API metrics
    "API_REQUESTS_TOTAL",
    "API_REQUEST_LATENCY_SECONDS",
    "API_WEBSOCKET_CONNECTIONS",
    # Graph metrics
    "GRAPH_OPERATIONS_TOTAL",
    "GRAPH_OPERATION_LATENCY_SECONDS",
    # LLM metrics
    "LLM_CALLS_TOTAL",
    "LLM_CALL_LATENCY_SECONDS",
    "LLM_TOKENS_TOTAL",
    # Registry
    "REGISTRY",
    "decrement_websocket_connections",
    "get_metrics",
    "increment_websocket_connections",
    "record_agent_error",
    "record_agent_latency",
    # Agent helpers
    "record_agent_request",
    "record_agent_success",
    "record_api_latency",
    # API helpers
    "record_api_request",
    "record_graph_latency",
    "record_graph_operation",
    "record_llm_call",
    "record_llm_latency",
    "record_llm_tokens",
    "set_agent_inbox_size",
    "set_agent_running",
    "set_websocket_connections",
    # Utilities
    "timed_operation",
]
