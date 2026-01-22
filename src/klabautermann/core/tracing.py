"""
Distributed tracing for Klabautermann.

Provides trace context propagation for tracking requests across agents.
Compatible with W3C Trace Context standard for interoperability.

Features:
- W3C Trace Context compatible trace IDs (128-bit) and span IDs (64-bit)
- Context propagation via contextvars
- Span tracking for nested operations
- Export to stdout (development) or OpenTelemetry collector (production)

Environment Variables:
- TRACING_ENABLED: Enable distributed tracing (default: true)
- TRACING_EXPORT: Export destination (none, stdout, otlp). Default: none
- OTEL_EXPORTER_OTLP_ENDPOINT: OpenTelemetry collector endpoint
- OTEL_SERVICE_NAME: Service name for traces (default: klabautermann)

Reference: W3C Trace Context https://www.w3.org/TR/trace-context/
"""

from __future__ import annotations

import contextvars
import os
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from collections.abc import Iterator


# =============================================================================
# Context Variables
# =============================================================================

# Current trace context
_trace_context: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "trace_context", default=None
)

# Current span
_current_span: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "current_span", default=None
)


# =============================================================================
# Trace ID Generation (W3C Trace Context compatible)
# =============================================================================


def generate_trace_id() -> str:
    """
    Generate a W3C Trace Context compatible trace ID.

    Format: 32 lowercase hex characters (128 bits)
    Example: "4bf92f3577b34da6a3ce929d0e0e4736"
    """
    return secrets.token_hex(16)


def generate_span_id() -> str:
    """
    Generate a W3C Trace Context compatible span ID.

    Format: 16 lowercase hex characters (64 bits)
    Example: "00f067aa0ba902b7"
    """
    return secrets.token_hex(8)


def generate_short_trace_id() -> str:
    """
    Generate a short trace ID for display/logging.

    Format: 8 lowercase hex characters (32 bits)
    Example: "4bf92f35"

    Note: Use full trace_id for actual tracing, this is just for display.
    """
    return secrets.token_hex(4)


# =============================================================================
# Span Status
# =============================================================================


class SpanStatus(Enum):
    """Status of a span."""

    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


# =============================================================================
# Span
# =============================================================================


@dataclass
class Span:
    """
    Represents a unit of work within a trace.

    A span tracks a single operation with timing, status, and metadata.
    Spans can be nested to represent operation hierarchy.
    """

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    status: SpanStatus = SpanStatus.UNSET
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_ms(self) -> float | None:
        """Duration in milliseconds, or None if not ended."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def set_attribute(self, key: str, value: Any) -> None:
        """Set a span attribute."""
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add an event to the span."""
        self.events.append(
            {
                "name": name,
                "timestamp": datetime.now(UTC).isoformat(),
                "attributes": attributes or {},
            }
        )

    def end(self, status: SpanStatus = SpanStatus.OK) -> None:
        """End the span."""
        self.end_time = time.time()
        if self.status == SpanStatus.UNSET:
            self.status = status

    def set_error(self, error: Exception) -> None:
        """Record an error on the span."""
        self.status = SpanStatus.ERROR
        self.set_attribute("error.type", type(error).__name__)
        self.set_attribute("error.message", str(error))

    def to_dict(self) -> dict[str, Any]:
        """Convert span to dictionary for export."""
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time": datetime.fromtimestamp(self.start_time, tz=UTC).isoformat(),
            "end_time": (
                datetime.fromtimestamp(self.end_time, tz=UTC).isoformat() if self.end_time else None
            ),
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "attributes": self.attributes,
            "events": self.events,
        }


# =============================================================================
# Trace Context
# =============================================================================


@dataclass
class TraceContext:
    """
    W3C Trace Context for distributed tracing.

    Contains the trace ID and optional parent span ID for propagation.
    """

    trace_id: str
    parent_span_id: str | None = None

    @classmethod
    def new(cls) -> TraceContext:
        """Create a new trace context with fresh trace ID."""
        return cls(trace_id=generate_trace_id())

    @classmethod
    def from_traceparent(cls, traceparent: str) -> TraceContext | None:
        """
        Parse W3C traceparent header.

        Format: version-trace_id-parent_id-trace_flags
        Example: "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        """
        try:
            parts = traceparent.split("-")
            if len(parts) != 4:
                return None

            version, trace_id, parent_id, flags = parts

            if version != "00":
                return None  # Only version 00 supported

            if len(trace_id) != 32 or len(parent_id) != 16:
                return None

            return cls(trace_id=trace_id, parent_span_id=parent_id)

        except Exception:
            return None

    def to_traceparent(self, span_id: str) -> str:
        """
        Generate W3C traceparent header.

        Args:
            span_id: Current span ID to include.

        Returns:
            Traceparent header value.
        """
        return f"00-{self.trace_id}-{span_id}-01"


# =============================================================================
# Tracer
# =============================================================================


class Tracer:
    """
    Main tracer interface for creating and managing spans.

    The tracer provides the API for starting spans, propagating context,
    and exporting trace data.
    """

    def __init__(self, service_name: str | None = None) -> None:
        """
        Initialize the tracer.

        Args:
            service_name: Service name for traces. Defaults to OTEL_SERVICE_NAME
                         or "klabautermann".
        """
        self.service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "klabautermann")
        self.enabled = os.getenv("TRACING_ENABLED", "true").lower() in ("true", "1", "yes")
        self.export_mode = os.getenv("TRACING_EXPORT", "none").lower()
        self._spans: list[Span] = []  # Completed spans for export

    def start_trace(self, name: str = "request") -> TraceContext:  # noqa: ARG002
        """
        Start a new trace.

        Args:
            name: Name for the root span.

        Returns:
            New trace context.
        """
        ctx = TraceContext.new()
        _trace_context.set(ctx)
        return ctx

    def get_current_context(self) -> TraceContext | None:
        """Get the current trace context."""
        return _trace_context.get()

    def get_current_span(self) -> Span | None:
        """Get the current span."""
        return _current_span.get()

    @contextmanager
    def span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[Span]:
        """
        Create a span for tracking an operation.

        Usage:
            with tracer.span("database.query", {"db.system": "neo4j"}) as span:
                result = await db.query(...)
                span.set_attribute("db.rows", len(result))

        Args:
            name: Span name (e.g., "agent.process", "llm.call").
            attributes: Initial span attributes.

        Yields:
            The span instance.
        """
        if not self.enabled:
            # Return a dummy span when tracing is disabled
            yield Span(
                name=name,
                trace_id="00000000000000000000000000000000",
                span_id="0000000000000000",
            )
            return

        # Get or create trace context
        ctx = _trace_context.get()
        if ctx is None:
            ctx = TraceContext.new()
            _trace_context.set(ctx)

        # Get parent span
        parent = _current_span.get()
        parent_span_id = parent.span_id if parent else ctx.parent_span_id

        # Create new span
        span = Span(
            name=name,
            trace_id=ctx.trace_id,
            span_id=generate_span_id(),
            parent_span_id=parent_span_id,
            attributes=attributes or {},
        )

        # Set as current span
        token = _current_span.set(span)

        try:
            yield span
            if span.status == SpanStatus.UNSET:
                span.status = SpanStatus.OK

        except Exception as e:
            span.set_error(e)
            raise

        finally:
            span.end()
            _current_span.reset(token)

            # Export span
            self._export_span(span)

    def _export_span(self, span: Span) -> None:
        """Export a completed span."""
        if self.export_mode == "none":
            return

        if self.export_mode == "stdout":
            self._export_stdout(span)
        elif self.export_mode == "otlp":
            self._export_otlp(span)

    def _export_stdout(self, span: Span) -> None:
        """Export span to stdout (for development)."""
        import json

        data = span.to_dict()
        data["service"] = self.service_name
        logger.debug(
            f"[TRACE] {span.name}",
            extra={
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "duration_ms": span.duration_ms,
            },
        )
        if os.getenv("TRACE_VERBOSE", "").lower() in ("true", "1", "yes"):
            print(f"SPAN: {json.dumps(data, indent=2)}")

    def _export_otlp(self, span: Span) -> None:
        """Export span to OpenTelemetry collector."""
        # For now, just log - full OTLP integration would require
        # opentelemetry-sdk dependency
        logger.debug(
            f"[TRACE-OTLP] {span.name}",
            extra={
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "duration_ms": span.duration_ms,
            },
        )


# =============================================================================
# Global Tracer Instance
# =============================================================================

_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    """Get the global tracer instance."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def reset_tracer() -> None:
    """Reset the global tracer (for testing)."""
    global _tracer
    _tracer = None
    _trace_context.set(None)
    _current_span.set(None)


# =============================================================================
# Convenience Functions
# =============================================================================


def start_trace(name: str = "request") -> TraceContext:
    """Start a new trace and return the context."""
    return get_tracer().start_trace(name)


def current_trace_id() -> str | None:
    """Get the current trace ID, or None if no trace active."""
    ctx = _trace_context.get()
    return ctx.trace_id if ctx else None


def current_span_id() -> str | None:
    """Get the current span ID, or None if no span active."""
    span = _current_span.get()
    return span.span_id if span else None


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """
    Create a traced span (convenience wrapper).

    Usage:
        with trace_span("orchestrator.process") as span:
            span.set_attribute("intent", "search")
            result = await process()
    """
    with get_tracer().span(name, attributes) as span:
        yield span


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "Span",
    "SpanStatus",
    "TraceContext",
    "Tracer",
    "current_span_id",
    "current_trace_id",
    "generate_short_trace_id",
    "generate_span_id",
    "generate_trace_id",
    "get_tracer",
    "reset_tracer",
    "start_trace",
    "trace_span",
]
