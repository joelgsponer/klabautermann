"""
Core module - Foundation components for Klabautermann.

Contains:
- models: Pydantic data models
- ontology: Graph schema constants
- logger: Nautical logging system
- exceptions: Custom exception types
"""

from klabautermann.core.exceptions import (
    CircuitOpenError,
    ExternalServiceError,
    GraphConnectionError,
    KlabautermannError,
    ValidationError,
)


__all__ = [
    "CircuitOpenError",
    "ExternalServiceError",
    "GraphConnectionError",
    "KlabautermannError",
    "ValidationError",
]
