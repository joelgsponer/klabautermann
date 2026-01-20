"""
Rate Limiter for Klabautermann channels.

Implements sliding window rate limiting to prevent abuse and ensure fair usage.
Configurable per-channel with per-user tracking.

Reference: specs/architecture/CHANNELS.md Section 8.2
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from klabautermann.core.logger import logger


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    # Maximum requests allowed in the window
    max_requests: int = 10

    # Time window in seconds
    window_seconds: int = 60

    # Extra requests before hard limit (soft warning threshold)
    burst_allowance: int = 5

    # Whether to enable rate limiting
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RateLimitConfig:
        """Create config from dictionary."""
        return cls(
            max_requests=data.get("max_requests", 10),
            window_seconds=data.get("window_seconds", 60),
            burst_allowance=data.get("burst_allowance", 5),
            enabled=data.get("enabled", True),
        )

    @classmethod
    def default_cli(cls) -> RateLimitConfig:
        """Default config for CLI (more permissive)."""
        return cls(max_requests=30, window_seconds=60, burst_allowance=10)

    @classmethod
    def default_telegram(cls) -> RateLimitConfig:
        """Default config for Telegram."""
        return cls(max_requests=10, window_seconds=60, burst_allowance=5)

    @classmethod
    def default_discord(cls) -> RateLimitConfig:
        """Default config for Discord."""
        return cls(max_requests=15, window_seconds=60, burst_allowance=5)


# =============================================================================
# Exceptions
# =============================================================================


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, user_id: str, retry_after: float) -> None:
        self.user_id = user_id
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded for user {user_id}. Retry after {retry_after:.1f}s")


# =============================================================================
# Rate Limit Result
# =============================================================================


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    reset_after: float
    is_warning: bool = False  # True if in burst zone


# =============================================================================
# Rate Limiter
# =============================================================================


class RateLimiter:
    """
    Sliding window rate limiter.

    Tracks requests per user with a sliding time window.
    Supports burst allowance for temporary spikes.

    Usage:
        limiter = RateLimiter(RateLimitConfig(max_requests=10, window_seconds=60))

        if limiter.is_allowed(user_id):
            # Process request
        else:
            retry_after = limiter.get_reset_time(user_id)
            # Send rate limit response
    """

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        """
        Initialize rate limiter.

        Args:
            config: Rate limit configuration.
        """
        self._config = config or RateLimitConfig()
        self._requests: dict[str, list[float]] = {}

    @property
    def config(self) -> RateLimitConfig:
        """Get rate limit configuration."""
        return self._config

    def is_allowed(self, user_id: str) -> bool:
        """
        Check if a request is allowed for the user.

        Args:
            user_id: User identifier.

        Returns:
            True if request is allowed.
        """
        if not self._config.enabled:
            return True

        result = self.check(user_id)
        return result.allowed

    def check(self, user_id: str) -> RateLimitResult:
        """
        Check rate limit status for a user.

        Args:
            user_id: User identifier.

        Returns:
            RateLimitResult with detailed status.
        """
        if not self._config.enabled:
            return RateLimitResult(
                allowed=True,
                remaining=self._config.max_requests,
                reset_after=0.0,
            )

        now = time.time()
        cutoff = now - self._config.window_seconds

        # Clean old requests
        if user_id in self._requests:
            self._requests[user_id] = [t for t in self._requests[user_id] if t > cutoff]
        else:
            self._requests[user_id] = []

        request_count = len(self._requests[user_id])
        total_limit = self._config.max_requests + self._config.burst_allowance

        # Calculate remaining and reset time
        if self._requests[user_id]:
            oldest = min(self._requests[user_id])
            reset_after = oldest + self._config.window_seconds - now
        else:
            reset_after = 0.0

        remaining = max(0, self._config.max_requests - request_count)

        # Check if allowed
        if request_count >= total_limit:
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_after=max(0, reset_after),
            )

        # Record the request
        self._requests[user_id].append(now)

        # Check if in warning zone (using burst allowance)
        is_warning = request_count >= self._config.max_requests

        if is_warning:
            logger.debug(
                f"[WHISPER] User {user_id} in rate limit burst zone",
                extra={"user_id": user_id, "count": request_count + 1},
            )

        return RateLimitResult(
            allowed=True,
            remaining=max(0, remaining - 1),
            reset_after=max(0, reset_after),
            is_warning=is_warning,
        )

    def get_remaining(self, user_id: str) -> int:
        """
        Get remaining requests in current window.

        Args:
            user_id: User identifier.

        Returns:
            Number of remaining requests.
        """
        if not self._config.enabled:
            return self._config.max_requests

        now = time.time()
        cutoff = now - self._config.window_seconds

        if user_id not in self._requests:
            return self._config.max_requests

        # Count recent requests
        recent = [t for t in self._requests[user_id] if t > cutoff]
        return max(0, self._config.max_requests - len(recent))

    def get_reset_time(self, user_id: str) -> float:
        """
        Get seconds until rate limit resets.

        Args:
            user_id: User identifier.

        Returns:
            Seconds until reset, or 0 if no active limit.
        """
        if not self._config.enabled:
            return 0.0

        if user_id not in self._requests or not self._requests[user_id]:
            return 0.0

        now = time.time()
        cutoff = now - self._config.window_seconds

        # Find oldest recent request
        recent = [t for t in self._requests[user_id] if t > cutoff]
        if not recent:
            return 0.0

        oldest = min(recent)
        return max(0, oldest + self._config.window_seconds - now)

    def clear(self, user_id: str) -> None:
        """
        Clear rate limit for user (admin action).

        Args:
            user_id: User identifier.
        """
        if user_id in self._requests:
            del self._requests[user_id]
            logger.info(
                f"[CHART] Rate limit cleared for user {user_id}",
                extra={"user_id": user_id},
            )

    def clear_all(self) -> None:
        """Clear all rate limits (admin action)."""
        self._requests.clear()
        logger.info("[CHART] All rate limits cleared")

    def get_stats(self) -> dict[str, Any]:
        """
        Get rate limiter statistics.

        Returns:
            Dict with tracked user count and request counts.
        """
        now = time.time()
        cutoff = now - self._config.window_seconds

        active_users = 0
        total_requests = 0

        for _user_id, timestamps in self._requests.items():
            recent = [t for t in timestamps if t > cutoff]
            if recent:
                active_users += 1
                total_requests += len(recent)

        return {
            "active_users": active_users,
            "total_requests": total_requests,
            "config": {
                "max_requests": self._config.max_requests,
                "window_seconds": self._config.window_seconds,
                "burst_allowance": self._config.burst_allowance,
                "enabled": self._config.enabled,
            },
        }


# =============================================================================
# Rate Limiter Registry
# =============================================================================


class RateLimiterRegistry:
    """
    Registry for per-channel rate limiters.

    Allows different rate limit configurations for different channels.
    """

    def __init__(self) -> None:
        self._limiters: dict[str, RateLimiter] = {}

    def register(
        self,
        channel_name: str,
        config: RateLimitConfig | None = None,
    ) -> RateLimiter:
        """
        Register a rate limiter for a channel.

        Args:
            channel_name: Channel identifier.
            config: Rate limit config. Defaults to channel-specific defaults.

        Returns:
            The registered RateLimiter.
        """
        if config is None:
            # Use channel-specific defaults
            if channel_name == "cli":
                config = RateLimitConfig.default_cli()
            elif channel_name == "telegram":
                config = RateLimitConfig.default_telegram()
            elif channel_name == "discord":
                config = RateLimitConfig.default_discord()
            else:
                config = RateLimitConfig()

        limiter = RateLimiter(config)
        self._limiters[channel_name] = limiter
        return limiter

    def get(self, channel_name: str) -> RateLimiter | None:
        """Get rate limiter for a channel."""
        return self._limiters.get(channel_name)

    def get_or_create(
        self,
        channel_name: str,
        config: RateLimitConfig | None = None,
    ) -> RateLimiter:
        """Get or create a rate limiter for a channel."""
        if channel_name not in self._limiters:
            return self.register(channel_name, config)
        return self._limiters[channel_name]

    def unregister(self, channel_name: str) -> None:
        """Remove a rate limiter."""
        self._limiters.pop(channel_name, None)

    def clear_all(self) -> None:
        """Clear all rate limiters."""
        for limiter in self._limiters.values():
            limiter.clear_all()


# =============================================================================
# Module-level registry
# =============================================================================

_registry: RateLimiterRegistry | None = None


def get_rate_limiter_registry() -> RateLimiterRegistry:
    """Get or create the global rate limiter registry."""
    global _registry
    if _registry is None:
        _registry = RateLimiterRegistry()
    return _registry


def reset_rate_limiter_registry() -> None:
    """Reset the global registry (for testing)."""
    global _registry
    _registry = None


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "RateLimitConfig",
    "RateLimitExceeded",
    "RateLimitResult",
    "RateLimiter",
    "RateLimiterRegistry",
    "get_rate_limiter_registry",
    "reset_rate_limiter_registry",
]
