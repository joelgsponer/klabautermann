"""
Core module - Foundation components for Klabautermann.

Contains:
- models: Pydantic data models
- ontology: Graph schema constants
- validation: Ontology validation for entity/relationship extraction
- model_selector: Multi-model orchestration for task-appropriate model selection
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
from klabautermann.core.model_selector import (
    COMPLEXITY_TO_TIER,
    DEFAULT_MODELS,
    PURPOSE_TO_TIER,
    ModelCallResult,
    ModelSelectionConfig,
    ModelSelector,
    ModelTier,
    TaskComplexity,
    TaskPurpose,
    get_model_for_agent,
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
from klabautermann.core.validation import (
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionResult,
    OntologyValidator,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
    is_valid_entity_type,
    is_valid_relationship_type,
    validate_extraction,
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
    # Model Selection
    "COMPLEXITY_TO_TIER",
    "DEFAULT_MODELS",
    "PURPOSE_TO_TIER",
    "CircuitOpenError",
    "ExternalServiceError",
    "ExtractedEntity",
    "ExtractedRelationship",
    # Ontology Validation
    "ExtractionResult",
    "GraphConnectionError",
    "KlabautermannError",
    "ModelCallResult",
    "ModelSelectionConfig",
    "ModelSelector",
    "ModelTier",
    "OntologyValidator",
    # Tracing
    "Span",
    "SpanStatus",
    "TaskComplexity",
    "TaskPurpose",
    "TraceContext",
    "Tracer",
    "ValidationError",
    "ValidationIssue",
    "ValidationResult",
    "ValidationSeverity",
    # Workflow Inspector
    "WorkflowEntry",
    "WorkflowInspector",
    "WorkflowPhase",
    "current_span_id",
    "current_trace_id",
    "generate_short_trace_id",
    "generate_span_id",
    "generate_trace_id",
    "get_inspector",
    "get_model_for_agent",
    "get_tracer",
    "is_valid_entity_type",
    "is_valid_relationship_type",
    "log_output",
    "log_request",
    "log_thinking",
    "reset_tracer",
    "start_trace",
    "trace_span",
    "validate_extraction",
]
