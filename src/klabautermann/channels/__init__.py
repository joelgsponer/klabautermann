"""
Channels module - Communication interfaces for Klabautermann.

Contains:
- base_channel: Abstract base class for all channels
- cli_driver: Command-line interface with Rich rendering
- cli_renderer: Rich-based terminal output formatting
- telegram_driver: Telegram bot interface
- sanitization: Input sanitization for security
- manager: Channel lifecycle management
- rate_limiter: Per-channel rate limiting

Future channels (Sprint 4+):
- discord_driver: Discord bot interface
"""

from klabautermann.channels.base_channel import BaseChannel
from klabautermann.channels.cli_driver import CLIDriver
from klabautermann.channels.cli_renderer import CLIRenderer
from klabautermann.channels.manager import (
    ChannelConfig,
    ChannelInfo,
    ChannelManager,
    ChannelStatus,
    ChannelStatusReport,
    HealthStatus,
    get_channel_manager,
    reset_channel_manager,
)
from klabautermann.channels.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    RateLimiterRegistry,
    RateLimitExceeded,
    RateLimitResult,
    get_rate_limiter_registry,
    reset_rate_limiter_registry,
)
from klabautermann.channels.sanitization import (
    InputSanitizer,
    SanitizationConfig,
    SanitizationResult,
    get_sanitizer,
    sanitize_input,
)
from klabautermann.channels.telegram_driver import TelegramDriver


__all__ = [
    # Base
    "BaseChannel",
    "CLIDriver",
    "CLIRenderer",
    "TelegramDriver",
    # Manager
    "ChannelConfig",
    "ChannelInfo",
    "ChannelManager",
    "ChannelStatus",
    "ChannelStatusReport",
    "HealthStatus",
    # Sanitization
    "InputSanitizer",
    # Rate Limiting
    "RateLimitConfig",
    "RateLimitExceeded",
    "RateLimitResult",
    "RateLimiter",
    "RateLimiterRegistry",
    "SanitizationConfig",
    "SanitizationResult",
    "get_channel_manager",
    "get_rate_limiter_registry",
    "get_sanitizer",
    "reset_channel_manager",
    "reset_rate_limiter_registry",
    "sanitize_input",
]
