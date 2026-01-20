"""
Unit tests for Rate Limiter.

Tests sliding window rate limiting and per-channel configuration.
"""

from __future__ import annotations

import time

import pytest

from klabautermann.channels.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    RateLimiterRegistry,
    RateLimitExceeded,
    RateLimitResult,
    get_rate_limiter_registry,
    reset_rate_limiter_registry,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def config() -> RateLimitConfig:
    """Create test config."""
    return RateLimitConfig(
        max_requests=5,
        window_seconds=10,
        burst_allowance=2,
        enabled=True,
    )


@pytest.fixture
def limiter(config: RateLimitConfig) -> RateLimiter:
    """Create a rate limiter with test config."""
    return RateLimiter(config)


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Reset global registry before each test."""
    reset_rate_limiter_registry()


# =============================================================================
# Test RateLimitConfig
# =============================================================================


class TestRateLimitConfig:
    """Tests for RateLimitConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = RateLimitConfig()

        assert config.max_requests == 10
        assert config.window_seconds == 60
        assert config.burst_allowance == 5
        assert config.enabled is True

    def test_from_dict(self) -> None:
        """Test creating config from dictionary."""
        data = {
            "max_requests": 20,
            "window_seconds": 30,
            "burst_allowance": 3,
            "enabled": False,
        }
        config = RateLimitConfig.from_dict(data)

        assert config.max_requests == 20
        assert config.window_seconds == 30
        assert config.burst_allowance == 3
        assert config.enabled is False

    def test_from_dict_partial(self) -> None:
        """Test creating config from partial dictionary."""
        data = {"max_requests": 15}
        config = RateLimitConfig.from_dict(data)

        assert config.max_requests == 15
        assert config.window_seconds == 60  # default
        assert config.burst_allowance == 5  # default

    def test_default_cli(self) -> None:
        """Test CLI default config."""
        config = RateLimitConfig.default_cli()

        assert config.max_requests == 30
        assert config.window_seconds == 60
        assert config.burst_allowance == 10

    def test_default_telegram(self) -> None:
        """Test Telegram default config."""
        config = RateLimitConfig.default_telegram()

        assert config.max_requests == 10
        assert config.window_seconds == 60
        assert config.burst_allowance == 5

    def test_default_discord(self) -> None:
        """Test Discord default config."""
        config = RateLimitConfig.default_discord()

        assert config.max_requests == 15
        assert config.window_seconds == 60
        assert config.burst_allowance == 5


# =============================================================================
# Test RateLimitExceeded
# =============================================================================


class TestRateLimitExceeded:
    """Tests for RateLimitExceeded exception."""

    def test_exception_attributes(self) -> None:
        """Test exception has correct attributes."""
        exc = RateLimitExceeded("user123", 5.5)

        assert exc.user_id == "user123"
        assert exc.retry_after == 5.5
        assert "user123" in str(exc)
        assert "5.5" in str(exc)


# =============================================================================
# Test RateLimiter - Basic Functionality
# =============================================================================


class TestRateLimiterBasic:
    """Tests for basic rate limiter functionality."""

    def test_first_request_allowed(self, limiter: RateLimiter) -> None:
        """Test that first request is always allowed."""
        assert limiter.is_allowed("user1") is True

    def test_requests_within_limit_allowed(self, limiter: RateLimiter) -> None:
        """Test that requests within limit are allowed."""
        for _ in range(5):
            assert limiter.is_allowed("user1") is True

    def test_requests_in_burst_zone_allowed(self, limiter: RateLimiter) -> None:
        """Test that burst zone requests are allowed."""
        # max_requests=5, burst_allowance=2 -> total 7 allowed
        for i in range(7):
            assert limiter.is_allowed("user1") is True, f"Request {i+1} should be allowed"

    def test_requests_exceed_total_limit(self, limiter: RateLimiter) -> None:
        """Test that requests exceeding total limit are denied."""
        # max_requests=5, burst_allowance=2 -> total 7 allowed
        for _ in range(7):
            limiter.is_allowed("user1")

        # 8th request should be denied
        assert limiter.is_allowed("user1") is False

    def test_different_users_independent(self, limiter: RateLimiter) -> None:
        """Test that different users have independent limits."""
        # Exhaust user1's limit
        for _ in range(7):
            limiter.is_allowed("user1")

        # user2 should still be allowed
        assert limiter.is_allowed("user2") is True


# =============================================================================
# Test RateLimiter - Check Method
# =============================================================================


class TestRateLimiterCheck:
    """Tests for the check() method."""

    def test_check_returns_result(self, limiter: RateLimiter) -> None:
        """Test that check returns RateLimitResult."""
        result = limiter.check("user1")

        assert isinstance(result, RateLimitResult)
        assert result.allowed is True
        assert result.remaining >= 0

    def test_check_remaining_decreases(self, limiter: RateLimiter) -> None:
        """Test that remaining count decreases."""
        result1 = limiter.check("user1")
        result2 = limiter.check("user1")

        assert result2.remaining < result1.remaining

    def test_check_warning_in_burst_zone(self, limiter: RateLimiter) -> None:
        """Test that warning flag is set in burst zone."""
        # First 5 requests (within max_requests)
        for _ in range(5):
            result = limiter.check("user1")
            assert result.is_warning is False

        # 6th and 7th requests (in burst zone)
        for _ in range(2):
            result = limiter.check("user1")
            assert result.is_warning is True

    def test_check_denied_after_limit(self, limiter: RateLimiter) -> None:
        """Test that check returns denied after limit."""
        for _ in range(7):
            limiter.check("user1")

        result = limiter.check("user1")
        assert result.allowed is False
        assert result.remaining == 0


# =============================================================================
# Test RateLimiter - Window Expiration
# =============================================================================


class TestRateLimiterWindow:
    """Tests for sliding window behavior."""

    def test_requests_expire_after_window(self) -> None:
        """Test that old requests expire."""
        config = RateLimitConfig(
            max_requests=3,
            window_seconds=1,  # 1 second window
            burst_allowance=0,
        )
        limiter = RateLimiter(config)

        # Use up all requests
        for _ in range(3):
            assert limiter.is_allowed("user1") is True

        # Should be denied
        assert limiter.is_allowed("user1") is False

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again
        assert limiter.is_allowed("user1") is True

    def test_get_reset_time(self, limiter: RateLimiter) -> None:
        """Test getting reset time."""
        # No requests yet
        assert limiter.get_reset_time("user1") == 0.0

        # Make a request
        limiter.is_allowed("user1")

        # Reset time should be positive
        reset_time = limiter.get_reset_time("user1")
        assert reset_time > 0
        assert reset_time <= 10  # window_seconds


# =============================================================================
# Test RateLimiter - Remaining Requests
# =============================================================================


class TestRateLimiterRemaining:
    """Tests for remaining requests calculation."""

    def test_get_remaining_full(self, limiter: RateLimiter) -> None:
        """Test remaining is full initially."""
        remaining = limiter.get_remaining("user1")
        assert remaining == 5  # max_requests

    def test_get_remaining_after_requests(self, limiter: RateLimiter) -> None:
        """Test remaining decreases after requests."""
        limiter.is_allowed("user1")
        limiter.is_allowed("user1")

        remaining = limiter.get_remaining("user1")
        assert remaining == 3

    def test_get_remaining_zero_after_limit(self, limiter: RateLimiter) -> None:
        """Test remaining is zero after limit."""
        for _ in range(7):
            limiter.is_allowed("user1")

        remaining = limiter.get_remaining("user1")
        assert remaining == 0


# =============================================================================
# Test RateLimiter - Clear
# =============================================================================


class TestRateLimiterClear:
    """Tests for clearing rate limits."""

    def test_clear_user(self, limiter: RateLimiter) -> None:
        """Test clearing a user's rate limit."""
        # Use up limit
        for _ in range(7):
            limiter.is_allowed("user1")

        assert limiter.is_allowed("user1") is False

        # Clear
        limiter.clear("user1")

        # Should be allowed again
        assert limiter.is_allowed("user1") is True

    def test_clear_all(self, limiter: RateLimiter) -> None:
        """Test clearing all rate limits."""
        # Use up limits for multiple users
        for _ in range(7):
            limiter.is_allowed("user1")
            limiter.is_allowed("user2")

        limiter.clear_all()

        assert limiter.is_allowed("user1") is True
        assert limiter.is_allowed("user2") is True


# =============================================================================
# Test RateLimiter - Disabled
# =============================================================================


class TestRateLimiterDisabled:
    """Tests for disabled rate limiter."""

    def test_disabled_always_allows(self) -> None:
        """Test that disabled limiter always allows."""
        config = RateLimitConfig(enabled=False)
        limiter = RateLimiter(config)

        for _ in range(100):
            assert limiter.is_allowed("user1") is True

    def test_disabled_remaining_full(self) -> None:
        """Test that disabled limiter shows full remaining."""
        config = RateLimitConfig(enabled=False)
        limiter = RateLimiter(config)

        limiter.is_allowed("user1")
        limiter.is_allowed("user1")

        assert limiter.get_remaining("user1") == config.max_requests


# =============================================================================
# Test RateLimiter - Stats
# =============================================================================


class TestRateLimiterStats:
    """Tests for rate limiter statistics."""

    def test_get_stats_empty(self, limiter: RateLimiter) -> None:
        """Test stats with no requests."""
        stats = limiter.get_stats()

        assert stats["active_users"] == 0
        assert stats["total_requests"] == 0

    def test_get_stats_with_requests(self, limiter: RateLimiter) -> None:
        """Test stats with requests."""
        limiter.is_allowed("user1")
        limiter.is_allowed("user1")
        limiter.is_allowed("user2")

        stats = limiter.get_stats()

        assert stats["active_users"] == 2
        assert stats["total_requests"] == 3

    def test_get_stats_includes_config(self, limiter: RateLimiter) -> None:
        """Test stats includes config."""
        stats = limiter.get_stats()

        assert "config" in stats
        assert stats["config"]["max_requests"] == 5
        assert stats["config"]["window_seconds"] == 10


# =============================================================================
# Test RateLimiterRegistry
# =============================================================================


class TestRateLimiterRegistry:
    """Tests for RateLimiterRegistry."""

    def test_register_limiter(self) -> None:
        """Test registering a limiter."""
        registry = RateLimiterRegistry()
        config = RateLimitConfig(max_requests=20)

        limiter = registry.register("test", config)

        assert isinstance(limiter, RateLimiter)
        assert limiter.config.max_requests == 20

    def test_register_with_defaults(self) -> None:
        """Test registering with channel-specific defaults."""
        registry = RateLimiterRegistry()

        cli_limiter = registry.register("cli")
        telegram_limiter = registry.register("telegram")
        discord_limiter = registry.register("discord")

        assert cli_limiter.config.max_requests == 30
        assert telegram_limiter.config.max_requests == 10
        assert discord_limiter.config.max_requests == 15

    def test_get_limiter(self) -> None:
        """Test getting a registered limiter."""
        registry = RateLimiterRegistry()
        registered = registry.register("test")

        retrieved = registry.get("test")

        assert retrieved is registered

    def test_get_nonexistent(self) -> None:
        """Test getting nonexistent limiter."""
        registry = RateLimiterRegistry()

        assert registry.get("nonexistent") is None

    def test_get_or_create(self) -> None:
        """Test get_or_create creates if needed."""
        registry = RateLimiterRegistry()

        limiter = registry.get_or_create("test")

        assert isinstance(limiter, RateLimiter)
        assert registry.get("test") is limiter

    def test_get_or_create_returns_existing(self) -> None:
        """Test get_or_create returns existing."""
        registry = RateLimiterRegistry()
        registered = registry.register("test")

        retrieved = registry.get_or_create("test")

        assert retrieved is registered

    def test_unregister(self) -> None:
        """Test unregistering a limiter."""
        registry = RateLimiterRegistry()
        registry.register("test")

        registry.unregister("test")

        assert registry.get("test") is None

    def test_clear_all(self) -> None:
        """Test clearing all limiters."""
        registry = RateLimiterRegistry()
        limiter = registry.register("test")

        # Use up limit
        for _ in range(15):
            limiter.is_allowed("user1")

        registry.clear_all()

        # Should be reset
        assert limiter.is_allowed("user1") is True


# =============================================================================
# Test Global Registry
# =============================================================================


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def test_get_registry_creates_instance(self) -> None:
        """Test that get_rate_limiter_registry creates instance."""
        registry = get_rate_limiter_registry()
        assert isinstance(registry, RateLimiterRegistry)

    def test_get_registry_returns_same_instance(self) -> None:
        """Test that get_rate_limiter_registry returns same instance."""
        registry1 = get_rate_limiter_registry()
        registry2 = get_rate_limiter_registry()
        assert registry1 is registry2

    def test_reset_registry(self) -> None:
        """Test resetting global registry."""
        registry1 = get_rate_limiter_registry()
        reset_rate_limiter_registry()
        registry2 = get_rate_limiter_registry()
        assert registry1 is not registry2
