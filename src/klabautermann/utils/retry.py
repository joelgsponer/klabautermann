"""
Retry utility with exponential backoff for Klabautermann.

Provides decorators for async functions that need resilience against transient failures.
Used throughout Sprint 2 for external API calls (LLM, MCP tools, Neo4j).

Reference: specs/quality/CODING_STANDARDS.md
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from klabautermann.core.logger import logger


# Type variable for decorated function return type
T = TypeVar("T")


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    multiplier: float = 2.0,
    max_delay: float = 30.0,
    jitter: float = 0.25,
    retry_on: tuple[type[Exception], ...] = (TimeoutError, ConnectionError),
    no_retry_on: tuple[type[Exception], ...] = (),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator for async functions with exponential backoff retry.

    Implements exponential backoff with jitter to prevent thundering herd.
    Only retries on specified exception types.

    Args:
        max_retries: Maximum number of retry attempts (not including initial attempt).
        base_delay: Initial delay between retries in seconds.
        multiplier: Factor to multiply delay by after each retry.
        max_delay: Maximum delay between retries.
        jitter: Random jitter factor (0.0 to 1.0) applied to delay.
        retry_on: Tuple of exception types to retry on.
        no_retry_on: Tuple of exception types to never retry on (takes precedence).

    Returns:
        Decorated async function with retry behavior.

    Example:
        @with_retry(max_retries=3, retry_on=(ConnectionError,))
        async def call_external_api():
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            delay = base_delay

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)

                except no_retry_on:
                    # Never retry these exceptions - raise immediately
                    raise

                except retry_on as e:
                    last_exception = e

                    if attempt == max_retries:
                        # Final attempt failed
                        logger.warning(
                            f"[SWELL] {func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )
                        raise

                    # Calculate delay with jitter to prevent thundering herd
                    jittered_delay = delay * (1 + random.uniform(-jitter, jitter))
                    jittered_delay = min(jittered_delay, max_delay)

                    logger.debug(
                        f"[WHISPER] {func.__name__} attempt {attempt + 1} failed, "
                        f"retrying in {jittered_delay:.2f}s: {e}"
                    )

                    await asyncio.sleep(jittered_delay)
                    delay = min(delay * multiplier, max_delay)

                except Exception as e:
                    # Unexpected exception - don't retry, log and raise
                    logger.error(f"[STORM] {func.__name__} unexpected error: {e}")
                    raise

            # Should not reach here, but handle edge case
            if last_exception:
                raise last_exception

            # If somehow we get here without exception, return None
            # This shouldn't happen in normal flow
            return None

        return wrapper

    return decorator


# ===========================================================================
# Convenience Shortcuts for Common Patterns
# ===========================================================================


def retry_on_timeout(max_retries: int = 3) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Retry decorator for timeout-prone operations.

    Retries on both asyncio.TimeoutError and built-in TimeoutError.

    Args:
        max_retries: Maximum retry attempts.

    Returns:
        Configured retry decorator.
    """
    return with_retry(
        max_retries=max_retries,
        retry_on=(asyncio.TimeoutError, TimeoutError),
    )


def retry_on_connection(max_retries: int = 3) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Retry decorator for connection-prone operations.

    Retries on connection errors and OS errors (network issues).

    Args:
        max_retries: Maximum retry attempts.

    Returns:
        Configured retry decorator.
    """
    return with_retry(
        max_retries=max_retries,
        retry_on=(ConnectionError, OSError),
    )


def retry_on_llm_errors(max_retries: int = 2) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Retry decorator for LLM API calls.

    Uses longer base delay since LLM rate limits often require waiting.
    Imports Anthropic exceptions dynamically to avoid hard dependency.

    Args:
        max_retries: Maximum retry attempts (default 2 for LLM calls).

    Returns:
        Configured retry decorator.
    """
    # Build retry_on tuple dynamically based on available libraries
    retry_exceptions: list[type[Exception]] = [TimeoutError, ConnectionError]

    try:
        from anthropic import APIStatusError, RateLimitError

        retry_exceptions.extend([RateLimitError, APIStatusError])
    except ImportError:
        pass

    return with_retry(
        max_retries=max_retries,
        base_delay=2.0,
        multiplier=2.0,
        max_delay=60.0,
        retry_on=tuple(retry_exceptions),
    )


def retry_on_graph_errors(
    max_retries: int = 3,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Retry decorator for Neo4j/Graphiti operations.

    Handles transient graph database errors.

    Args:
        max_retries: Maximum retry attempts.

    Returns:
        Configured retry decorator.
    """
    # Build retry_on tuple dynamically based on available libraries
    retry_exceptions: list[type[Exception]] = [TimeoutError, ConnectionError, OSError]

    try:
        from neo4j.exceptions import ServiceUnavailable, TransientError

        retry_exceptions.extend([TransientError, ServiceUnavailable])
    except ImportError:
        pass

    return with_retry(
        max_retries=max_retries,
        base_delay=1.0,
        retry_on=tuple(retry_exceptions),
    )


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "with_retry",
    "retry_on_timeout",
    "retry_on_connection",
    "retry_on_llm_errors",
    "retry_on_graph_errors",
]
