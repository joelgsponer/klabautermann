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
- message_queue: Message queuing for resilience

Future channels (Sprint 4+):
- discord_driver: Discord bot interface
"""

from klabautermann.channels.base_channel import BaseChannel
from klabautermann.channels.cli_driver import CLIDriver
from klabautermann.channels.cli_renderer import CLIRenderer
from klabautermann.channels.manager import (
    BroadcastResult,
    ChannelConfig,
    ChannelInfo,
    ChannelManager,
    ChannelStatus,
    ChannelStatusReport,
    HealthStatus,
    get_channel_manager,
    reset_channel_manager,
)
from klabautermann.channels.message_queue import (
    EnqueueResult,
    MessageQueue,
    MessageQueueConfig,
    OverflowAction,
    QueueItem,
    QueueItemStatus,
    QueueStats,
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
    "BroadcastResult",
    "ChannelConfig",
    "ChannelInfo",
    "ChannelManager",
    "ChannelStatus",
    "ChannelStatusReport",
    "HealthStatus",
    # Message Queue
    "EnqueueResult",
    "MessageQueue",
    "MessageQueueConfig",
    "OverflowAction",
    "QueueItem",
    "QueueItemStatus",
    "QueueStats",
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
