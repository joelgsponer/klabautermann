"""
Custom exceptions for Klabautermann.

All exceptions inherit from KlabautermannError for consistent handling.
Each exception type maps to a specific failure mode for graceful degradation.
"""

from typing import Any


class KlabautermannError(Exception):
    """Base exception for all Klabautermann errors."""

    def __init__(
        self,
        message: str,
        trace_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.trace_id = trace_id
        self.context = context or {}

    def __str__(self) -> str:
        if self.trace_id:
            return f"[{self.trace_id[:8]}] {self.message}"
        return self.message


# ===========================================================================
# Connection Errors
# ===========================================================================


class GraphConnectionError(KlabautermannError):
    """Failed to connect to Neo4j or Graphiti."""

    def __init__(
        self,
        message: str = "Failed to connect to the graph database",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)


class ExternalServiceError(KlabautermannError):
    """External API call failed (Anthropic, OpenAI, etc.)."""

    def __init__(
        self,
        service: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        message = message or f"External service '{service}' failed"
        super().__init__(message, **kwargs)
        self.service = service


class MCPConnectionError(KlabautermannError):
    """MCP server connection failure."""

    def __init__(
        self,
        server: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        message = message or f"MCP server '{server}' connection failed"
        super().__init__(message, **kwargs)
        self.server = server


class MCPError(KlabautermannError):
    """MCP tool invocation failed."""

    def __init__(
        self,
        message: str,
        tool_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.tool_name = tool_name


class MCPTimeoutError(MCPError):
    """MCP tool invocation timed out."""

    def __init__(
        self,
        message: str,
        tool_name: str | None = None,
        timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, tool_name, **kwargs)
        self.timeout_seconds = timeout_seconds


# ===========================================================================
# Validation Errors
# ===========================================================================


class ValidationError(KlabautermannError):
    """Data validation failed."""

    def __init__(
        self,
        message: str = "Validation failed",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)


class LLMOutputValidationError(ValidationError):
    """LLM returned output that couldn't be parsed."""

    def __init__(
        self,
        raw_output: str,
        message: str = "Failed to parse LLM output",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.raw_output = raw_output


class SchemaValidationError(ValidationError):
    """Data doesn't match expected schema."""

    def __init__(
        self,
        schema_name: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        message = message or f"Data doesn't match schema '{schema_name}'"
        super().__init__(message, **kwargs)
        self.schema_name = schema_name


# ===========================================================================
# Operational Errors
# ===========================================================================


class CircuitOpenError(KlabautermannError):
    """Circuit breaker is open - service unavailable."""

    def __init__(
        self,
        service: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        message = message or f"Circuit breaker open for '{service}'"
        super().__init__(message, **kwargs)
        self.service = service


class OperationTimeoutError(KlabautermannError):
    """Operation exceeded timeout."""

    def __init__(
        self,
        operation: str,
        timeout_seconds: float,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        message = message or f"Operation '{operation}' timed out after {timeout_seconds}s"
        super().__init__(message, **kwargs)
        self.operation = operation
        self.timeout_seconds = timeout_seconds


class RateLimitError(KlabautermannError):
    """Rate limit exceeded."""

    def __init__(
        self,
        service: str,
        retry_after: float | None = None,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        message = message or f"Rate limit exceeded for '{service}'"
        if retry_after:
            message += f" (retry after {retry_after}s)"
        super().__init__(message, **kwargs)
        self.service = service
        self.retry_after = retry_after


# ===========================================================================
# Startup Errors
# ===========================================================================


class StartupError(KlabautermannError):
    """Application startup failed."""

    def __init__(
        self,
        message: str = "Application startup failed",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)


# ===========================================================================
# Agent Errors
# ===========================================================================


class AgentError(KlabautermannError):
    """Agent failed to process request."""

    def __init__(
        self,
        agent_name: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        message = message or f"Agent '{agent_name}' failed"
        super().__init__(message, **kwargs)
        self.agent_name = agent_name


class DelegationError(AgentError):
    """Failed to delegate to sub-agent."""

    def __init__(
        self,
        source_agent: str,
        target_agent: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        message = message or f"Failed to delegate from '{source_agent}' to '{target_agent}'"
        super().__init__(source_agent, message, **kwargs)
        self.target_agent = target_agent


# ===========================================================================
# Thread/Channel Errors
# ===========================================================================


class ThreadNotFoundError(KlabautermannError):
    """Thread not found in the graph."""

    def __init__(
        self,
        thread_id: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        message = message or f"Thread '{thread_id}' not found"
        super().__init__(message, **kwargs)
        self.thread_id = thread_id


class ChannelError(KlabautermannError):
    """Channel operation failed."""

    def __init__(
        self,
        channel_type: str,
        message: str | None = None,
        **kwargs: Any,
    ) -> None:
        message = message or f"Channel '{channel_type}' error"
        super().__init__(message, **kwargs)
        self.channel_type = channel_type


# ===========================================================================
# Export all exceptions
# ===========================================================================

__all__ = [
    # Agent
    "AgentError",
    "ChannelError",
    # Operational
    "CircuitOpenError",
    "DelegationError",
    "ExternalServiceError",
    # Connection
    "GraphConnectionError",
    # Base
    "KlabautermannError",
    "LLMOutputValidationError",
    "MCPConnectionError",
    "MCPError",
    "MCPTimeoutError",
    "OperationTimeoutError",
    "RateLimitError",
    "SchemaValidationError",
    # Startup
    "StartupError",
    # Thread/Channel
    "ThreadNotFoundError",
    # Validation
    "ValidationError",
]
