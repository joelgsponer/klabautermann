"""
Core module - Foundation components for Klabautermann.

Contains:
- models: Pydantic data models
- ontology: Graph schema constants
- logger: Nautical logging system
- exceptions: Custom exception types
- workflow_inspector: Agent workflow inspection for debugging
- tracing: Distributed tracing with W3C Trace Context support
"""

from klabautermann.core.exceptions import (
    CircuitOpenError,
    ExternalServiceError,
    GraphConnectionError,
    KlabautermannError,
    ValidationError,
)
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
from klabautermann.core.workflow_inspector import (
    WorkflowEntry,
    WorkflowInspector,
    WorkflowPhase,
    get_inspector,
    log_output,
    log_request,
    log_thinking,
)


__all__ = [
    "CircuitOpenError",
    "ExternalServiceError",
    "GraphConnectionError",
    "KlabautermannError",
    "ValidationError",
    # Tracing
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
    # Workflow Inspector
    "WorkflowEntry",
    "WorkflowInspector",
    "WorkflowPhase",
    "get_inspector",
    "log_output",
    "log_request",
    "log_thinking",
]
