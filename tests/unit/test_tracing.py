"""Unit tests for distributed tracing."""

from __future__ import annotations

import pytest

from klabautermann.core.tracing import (
    Span,
    SpanStatus,
    TraceContext,
    Tracer,
    current_span_id,
    current_trace_id,
    generate_short_trace_id,
    generate_span_id,
    generate_trace_id,
    get_tracer,
    reset_tracer,
    start_trace,
    trace_span,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def reset_tracing() -> None:
    """Reset tracing state before each test."""
    reset_tracer()


@pytest.fixture
def tracer() -> Tracer:
    """Create a tracer instance."""
    return Tracer(service_name="test-service")


# =============================================================================
# Trace ID Generation
# =============================================================================


class TestTraceIdGeneration:
    """Test trace ID generation functions."""

    def test_generate_trace_id_format(self) -> None:
        """Test trace ID is 32 hex characters."""
        trace_id = generate_trace_id()

        assert len(trace_id) == 32
        assert all(c in "0123456789abcdef" for c in trace_id)

    def test_generate_trace_id_uniqueness(self) -> None:
        """Test trace IDs are unique."""
        ids = {generate_trace_id() for _ in range(100)}
        assert len(ids) == 100  # All unique

    def test_generate_span_id_format(self) -> None:
        """Test span ID is 16 hex characters."""
        span_id = generate_span_id()

        assert len(span_id) == 16
        assert all(c in "0123456789abcdef" for c in span_id)

    def test_generate_span_id_uniqueness(self) -> None:
        """Test span IDs are unique."""
        ids = {generate_span_id() for _ in range(100)}
        assert len(ids) == 100

    def test_generate_short_trace_id_format(self) -> None:
        """Test short trace ID is 8 hex characters."""
        short_id = generate_short_trace_id()

        assert len(short_id) == 8
        assert all(c in "0123456789abcdef" for c in short_id)


# =============================================================================
# TraceContext
# =============================================================================


class TestTraceContext:
    """Test TraceContext class."""

    def test_new_creates_trace_id(self) -> None:
        """Test TraceContext.new() creates a trace ID."""
        ctx = TraceContext.new()

        assert len(ctx.trace_id) == 32
        assert ctx.parent_span_id is None

    def test_from_traceparent_valid(self) -> None:
        """Test parsing valid traceparent header."""
        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

        ctx = TraceContext.from_traceparent(traceparent)

        assert ctx is not None
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert ctx.parent_span_id == "00f067aa0ba902b7"

    def test_from_traceparent_invalid_version(self) -> None:
        """Test parsing traceparent with unsupported version."""
        traceparent = "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

        ctx = TraceContext.from_traceparent(traceparent)

        assert ctx is None

    def test_from_traceparent_invalid_format(self) -> None:
        """Test parsing invalid traceparent format."""
        ctx = TraceContext.from_traceparent("invalid")
        assert ctx is None

        ctx = TraceContext.from_traceparent("00-abc-def-01")
        assert ctx is None

    def test_to_traceparent(self) -> None:
        """Test generating traceparent header."""
        ctx = TraceContext(trace_id="4bf92f3577b34da6a3ce929d0e0e4736")
        span_id = "00f067aa0ba902b7"

        traceparent = ctx.to_traceparent(span_id)

        assert traceparent == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


# =============================================================================
# Span
# =============================================================================


class TestSpan:
    """Test Span class."""

    def test_span_creation(self) -> None:
        """Test creating a span."""
        span = Span(
            name="test.operation",
            trace_id=generate_trace_id(),
            span_id=generate_span_id(),
        )

        assert span.name == "test.operation"
        assert span.status == SpanStatus.UNSET
        assert span.end_time is None
        assert span.duration_ms is None

    def test_span_end(self) -> None:
        """Test ending a span."""
        span = Span(
            name="test.operation",
            trace_id=generate_trace_id(),
            span_id=generate_span_id(),
        )

        span.end()

        assert span.end_time is not None
        assert span.status == SpanStatus.OK
        assert span.duration_ms is not None
        assert span.duration_ms >= 0

    def test_span_end_with_status(self) -> None:
        """Test ending a span with specific status."""
        span = Span(
            name="test.operation",
            trace_id=generate_trace_id(),
            span_id=generate_span_id(),
        )

        span.end(SpanStatus.ERROR)

        assert span.status == SpanStatus.ERROR

    def test_span_set_attribute(self) -> None:
        """Test setting span attributes."""
        span = Span(
            name="test.operation",
            trace_id=generate_trace_id(),
            span_id=generate_span_id(),
        )

        span.set_attribute("key1", "value1")
        span.set_attribute("key2", 42)

        assert span.attributes["key1"] == "value1"
        assert span.attributes["key2"] == 42

    def test_span_add_event(self) -> None:
        """Test adding events to a span."""
        span = Span(
            name="test.operation",
            trace_id=generate_trace_id(),
            span_id=generate_span_id(),
        )

        span.add_event("cache.hit", {"cache_key": "user:123"})

        assert len(span.events) == 1
        assert span.events[0]["name"] == "cache.hit"
        assert span.events[0]["attributes"]["cache_key"] == "user:123"
        assert "timestamp" in span.events[0]

    def test_span_set_error(self) -> None:
        """Test recording an error on a span."""
        span = Span(
            name="test.operation",
            trace_id=generate_trace_id(),
            span_id=generate_span_id(),
        )

        span.set_error(ValueError("Test error"))

        assert span.status == SpanStatus.ERROR
        assert span.attributes["error.type"] == "ValueError"
        assert span.attributes["error.message"] == "Test error"

    def test_span_to_dict(self) -> None:
        """Test converting span to dictionary."""
        span = Span(
            name="test.operation",
            trace_id="abc123",
            span_id="def456",
            parent_span_id="parent789",
        )
        span.set_attribute("key", "value")
        span.end()

        data = span.to_dict()

        assert data["name"] == "test.operation"
        assert data["trace_id"] == "abc123"
        assert data["span_id"] == "def456"
        assert data["parent_span_id"] == "parent789"
        assert data["status"] == "ok"
        assert data["attributes"]["key"] == "value"
        assert data["duration_ms"] is not None


# =============================================================================
# Tracer
# =============================================================================


class TestTracer:
    """Test Tracer class."""

    def test_tracer_service_name(self, tracer: Tracer) -> None:
        """Test tracer has service name."""
        assert tracer.service_name == "test-service"

    def test_tracer_enabled_by_default(self, tracer: Tracer) -> None:
        """Test tracing is enabled by default."""
        assert tracer.enabled is True

    def test_tracer_start_trace(self, tracer: Tracer) -> None:
        """Test starting a new trace."""
        ctx = tracer.start_trace()

        assert ctx is not None
        assert len(ctx.trace_id) == 32
        assert tracer.get_current_context() == ctx

    def test_tracer_span_context_manager(self, tracer: Tracer) -> None:
        """Test span as context manager."""
        tracer.start_trace()

        with tracer.span("test.operation") as span:
            assert span.name == "test.operation"
            assert tracer.get_current_span() == span
            span.set_attribute("key", "value")

        # Span should be ended after context manager
        assert span.end_time is not None
        assert span.status == SpanStatus.OK

    def test_tracer_span_error_handling(self, tracer: Tracer) -> None:
        """Test span handles exceptions."""
        tracer.start_trace()

        with pytest.raises(ValueError), tracer.span("failing.operation") as span:
            raise ValueError("Test error")

        assert span.status == SpanStatus.ERROR
        assert span.attributes["error.type"] == "ValueError"

    def test_tracer_nested_spans(self, tracer: Tracer) -> None:
        """Test nested spans have correct parent relationships."""
        tracer.start_trace()

        with (
            tracer.span("parent.operation") as parent_span,
            tracer.span("child.operation") as child_span,
        ):
            assert child_span.parent_span_id == parent_span.span_id

    def test_tracer_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test tracing when disabled."""
        monkeypatch.setenv("TRACING_ENABLED", "false")
        tracer = Tracer()

        assert tracer.enabled is False

        with tracer.span("test.operation") as span:
            # Should get a dummy span
            assert span.trace_id == "00000000000000000000000000000000"


# =============================================================================
# Convenience Functions
# =============================================================================


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_start_trace_function(self) -> None:
        """Test start_trace convenience function."""
        ctx = start_trace()

        assert ctx is not None
        assert len(ctx.trace_id) == 32

    def test_current_trace_id_none_when_no_trace(self) -> None:
        """Test current_trace_id returns None when no trace."""
        assert current_trace_id() is None

    def test_current_trace_id_returns_id(self) -> None:
        """Test current_trace_id returns trace ID."""
        ctx = start_trace()

        assert current_trace_id() == ctx.trace_id

    def test_current_span_id_none_when_no_span(self) -> None:
        """Test current_span_id returns None when no span."""
        start_trace()

        assert current_span_id() is None

    def test_current_span_id_returns_id(self) -> None:
        """Test current_span_id returns span ID."""
        start_trace()

        with trace_span("test.operation") as span:
            assert current_span_id() == span.span_id

    def test_trace_span_function(self) -> None:
        """Test trace_span convenience function."""
        start_trace()

        with trace_span("test.operation", {"key": "value"}) as span:
            assert span.name == "test.operation"
            assert span.attributes["key"] == "value"

    def test_get_tracer_singleton(self) -> None:
        """Test get_tracer returns singleton."""
        tracer1 = get_tracer()
        tracer2 = get_tracer()

        assert tracer1 is tracer2

    def test_reset_tracer(self) -> None:
        """Test reset_tracer clears state."""
        start_trace()
        assert current_trace_id() is not None

        reset_tracer()

        assert current_trace_id() is None
        # New tracer instance
        tracer = get_tracer()
        assert tracer.get_current_context() is None
