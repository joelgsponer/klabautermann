# Create Custom Exceptions Module

## Metadata
- **ID**: T012
- **Priority**: P0
- **Category**: core
- **Effort**: S
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md) Section 5
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md)

## Dependencies
- [ ] T005 - Pydantic models

## Context
Custom exceptions enable precise error handling and graceful degradation. Each exception type maps to a specific failure mode, allowing the system to respond appropriately rather than crashing.

## Requirements
- [ ] Create `src/klabautermann/core/exceptions.py` with:

### Base Exception
- [ ] `KlabautermannError` - Base class for all custom exceptions

### Connection Errors
- [ ] `GraphConnectionError` - Neo4j/Graphiti connection failure
- [ ] `ExternalServiceError` - External API failure (Anthropic, OpenAI)
- [ ] `MCPConnectionError` - MCP server connection failure

### Validation Errors
- [ ] `LLMOutputValidationError` - LLM returned unparseable output
- [ ] `SchemaValidationError` - Data doesn't match expected schema

### Operational Errors
- [ ] `CircuitOpenError` - Circuit breaker is open
- [ ] `TimeoutError` - Operation exceeded timeout
- [ ] `RateLimitError` - Rate limit exceeded

### Agent Errors
- [ ] `AgentError` - Generic agent failure
- [ ] `DelegationError` - Failed to delegate to sub-agent

## Acceptance Criteria
- [ ] All exceptions inherit from `KlabautermannError`
- [ ] Each exception has a meaningful default message
- [ ] Exceptions can carry additional context (trace_id, agent_name)
- [ ] `from klabautermann.core.exceptions import GraphConnectionError` works

## Implementation Notes

```python
from typing import Optional, Dict, Any


class KlabautermannError(Exception):
    """Base exception for all Klabautermann errors."""

    def __init__(
        self,
        message: str,
        trace_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.trace_id = trace_id
        self.context = context or {}

    def __str__(self) -> str:
        if self.trace_id:
            return f"[{self.trace_id[:8]}] {self.message}"
        return self.message


class GraphConnectionError(KlabautermannError):
    """Failed to connect to Neo4j or Graphiti."""

    def __init__(
        self,
        message: str = "Failed to connect to the graph database",
        **kwargs,
    ):
        super().__init__(message, **kwargs)


class ExternalServiceError(KlabautermannError):
    """External API call failed."""

    def __init__(
        self,
        service: str,
        message: Optional[str] = None,
        **kwargs,
    ):
        message = message or f"External service '{service}' failed"
        super().__init__(message, **kwargs)
        self.service = service


class LLMOutputValidationError(KlabautermannError):
    """LLM returned output that couldn't be parsed."""

    def __init__(
        self,
        raw_output: str,
        message: str = "Failed to parse LLM output",
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.raw_output = raw_output


class CircuitOpenError(KlabautermannError):
    """Circuit breaker is open - service unavailable."""

    def __init__(
        self,
        service: str,
        message: Optional[str] = None,
        **kwargs,
    ):
        message = message or f"Circuit breaker open for '{service}'"
        super().__init__(message, **kwargs)
        self.service = service


class AgentError(KlabautermannError):
    """Agent failed to process request."""

    def __init__(
        self,
        agent_name: str,
        message: Optional[str] = None,
        **kwargs,
    ):
        message = message or f"Agent '{agent_name}' failed"
        super().__init__(message, **kwargs)
        self.agent_name = agent_name


class DelegationError(AgentError):
    """Failed to delegate to sub-agent."""

    def __init__(
        self,
        source_agent: str,
        target_agent: str,
        message: Optional[str] = None,
        **kwargs,
    ):
        message = message or f"Failed to delegate from '{source_agent}' to '{target_agent}'"
        super().__init__(source_agent, message, **kwargs)
        self.target_agent = target_agent


# Re-export for convenience
__all__ = [
    "KlabautermannError",
    "GraphConnectionError",
    "ExternalServiceError",
    "LLMOutputValidationError",
    "CircuitOpenError",
    "AgentError",
    "DelegationError",
]
```

Usage in error handling:
```python
from klabautermann.core.exceptions import GraphConnectionError

try:
    await neo4j.connect()
except Exception as e:
    raise GraphConnectionError(
        message=f"Neo4j connection failed: {e}",
        trace_id=trace_id,
        context={"uri": neo4j_uri}
    )
```
