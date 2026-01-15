# Create Retry Utility with Exponential Backoff

## Metadata
- **ID**: T022
- **Priority**: P1
- **Category**: core
- **Effort**: S
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md)
- Related: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 5

## Dependencies
- [x] T008 - Logging system
- [x] T012 - Custom exceptions

## Context
External API calls (LLM, MCP tools, Neo4j) can fail transiently. A retry utility with exponential backoff ensures resilience without manual retry logic in every function. This is a foundational utility used throughout Sprint 2.

## Requirements
- [ ] Create `src/klabautermann/utils/retry.py`:

### Retry Decorator
- [ ] `@with_retry` decorator for async functions
- [ ] Configurable max retries (default: 3)
- [ ] Exponential backoff with jitter
- [ ] Exception filtering (only retry specific exceptions)

### Backoff Calculation
- [ ] Base delay configurable (default: 1.0s)
- [ ] Multiplier configurable (default: 2.0)
- [ ] Max delay cap configurable (default: 30s)
- [ ] Jitter: random 0-25% of delay

### Logging
- [ ] Log each retry attempt with remaining count
- [ ] Log final failure
- [ ] Include trace_id if available in context

### Exception Handling
- [ ] Allow specifying which exceptions to retry
- [ ] Default: retry on `TimeoutError`, `ConnectionError`
- [ ] Never retry on `ValidationError`, `AuthenticationError`

## Acceptance Criteria
- [ ] Decorator works with async functions
- [ ] Backoff increases exponentially with each retry
- [ ] Jitter prevents thundering herd
- [ ] Only specified exceptions trigger retry
- [ ] All retries logged appropriately

## Implementation Notes

```python
import asyncio
import random
from functools import wraps
from typing import Type, Tuple, Callable, Any, Optional
import time

from klabautermann.core.logger import logger

def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    multiplier: float = 2.0,
    max_delay: float = 30.0,
    jitter: float = 0.25,
    retry_on: Tuple[Type[Exception], ...] = (TimeoutError, ConnectionError),
    no_retry_on: Tuple[Type[Exception], ...] = (),
) -> Callable:
    """
    Decorator for async functions with exponential backoff retry.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay between retries in seconds.
        multiplier: Factor to multiply delay by after each retry.
        max_delay: Maximum delay between retries.
        jitter: Random jitter factor (0.0 to 1.0).
        retry_on: Tuple of exception types to retry on.
        no_retry_on: Tuple of exception types to never retry on.

    Example:
        @with_retry(max_retries=3, retry_on=(ConnectionError,))
        async def call_external_api():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Optional[Exception] = None
            delay = base_delay

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)

                except no_retry_on as e:
                    # Never retry these
                    raise

                except retry_on as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.warning(
                            f"[SWELL] {func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )
                        raise

                    # Calculate delay with jitter
                    jittered_delay = delay * (1 + random.uniform(-jitter, jitter))
                    jittered_delay = min(jittered_delay, max_delay)

                    logger.debug(
                        f"[WHISPER] {func.__name__} attempt {attempt + 1} failed, "
                        f"retrying in {jittered_delay:.2f}s: {e}"
                    )

                    await asyncio.sleep(jittered_delay)
                    delay = min(delay * multiplier, max_delay)

                except Exception as e:
                    # Unexpected exception - don't retry
                    logger.error(f"[STORM] {func.__name__} unexpected error: {e}")
                    raise

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


# Convenience shortcuts for common patterns
def retry_on_timeout(max_retries: int = 3) -> Callable:
    """Retry only on timeout errors."""
    return with_retry(max_retries=max_retries, retry_on=(asyncio.TimeoutError, TimeoutError))


def retry_on_connection(max_retries: int = 3) -> Callable:
    """Retry on connection errors."""
    return with_retry(max_retries=max_retries, retry_on=(ConnectionError, OSError))


def retry_on_llm_errors(max_retries: int = 2) -> Callable:
    """Retry on common LLM API errors."""
    # Import here to avoid circular dependency
    from anthropic import RateLimitError, APIStatusError
    return with_retry(
        max_retries=max_retries,
        base_delay=2.0,
        retry_on=(RateLimitError, APIStatusError, TimeoutError),
    )
```

Usage example:
```python
from klabautermann.utils.retry import with_retry, retry_on_llm_errors

@retry_on_llm_errors(max_retries=2)
async def call_claude(prompt: str) -> str:
    return await anthropic_client.messages.create(...)
```
