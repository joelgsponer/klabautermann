"""
Channel Manager for Klabautermann.

Orchestrates multiple communication channels (CLI, Telegram, Discord) with:
- Unified lifecycle management (start/stop)
- Health monitoring with periodic checks
- Status reporting and metrics
- Graceful shutdown coordination

Reference: specs/architecture/CHANNELS.md Section 5.2
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.channels.base_channel import BaseChannel


# =============================================================================
# Channel Status
# =============================================================================


class ChannelStatus(Enum):
    """Status of a channel in its lifecycle."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


# =============================================================================
# Health Status
# =============================================================================


@dataclass
class HealthStatus:
    """Health status for a channel."""

    channel_name: str
    is_healthy: bool
    last_message_at: datetime | None
    last_check_at: datetime
    error: str | None = None
    message_count: int = 0


# =============================================================================
# Channel Info
# =============================================================================


@dataclass
class ChannelInfo:
    """Detailed information about a channel."""

    name: str
    channel_type: str
    status: ChannelStatus
    is_healthy: bool
    message_count: int
    last_message_at: datetime | None
    started_at: datetime | None
    error: str | None = None


# =============================================================================
# Status Report
# =============================================================================


@dataclass
class ChannelStatusReport:
    """Complete status report for all channels."""

    timestamp: datetime
    channels: dict[str, ChannelInfo]
    total_messages: int
    uptime_seconds: float
    healthy_count: int
    unhealthy_count: int


# =============================================================================
# Channel Configuration
# =============================================================================


@dataclass
class ChannelConfig:
    """Configuration for channel manager."""

    enable_cli: bool = True
    enable_telegram: bool = False
    enable_discord: bool = False
    cli_config: dict[str, Any] = field(default_factory=dict)
    telegram_config: dict[str, Any] = field(default_factory=dict)
    discord_config: dict[str, Any] = field(default_factory=dict)
    health_check_interval: float = 30.0
    stale_threshold: float = 300.0  # 5 minutes

    @classmethod
    def from_env(cls) -> ChannelConfig:
        """Load configuration from environment variables."""
        import os

        def str_to_bool(value: str | None) -> bool:
            if not value:
                return False
            return value.lower() in ("true", "1", "yes")

        return cls(
            enable_cli=str_to_bool(os.getenv("ENABLE_CLI", "true")),
            enable_telegram=str_to_bool(os.getenv("ENABLE_TELEGRAM")),
            enable_discord=str_to_bool(os.getenv("ENABLE_DISCORD")),
            health_check_interval=float(os.getenv("HEALTH_CHECK_INTERVAL", "30.0")),
            stale_threshold=float(os.getenv("CHANNEL_STALE_THRESHOLD", "300.0")),
        )


# =============================================================================
# Channel Manager
# =============================================================================


class ChannelManager:
    """
    Manages multiple communication channels with unified lifecycle.

    Responsibilities:
    - Channel registration and tracking
    - Concurrent startup of enabled channels
    - Graceful shutdown in reverse order
    - Health monitoring with periodic checks
    - Status reporting and metrics

    Usage:
        manager = ChannelManager(config)
        manager.register("cli", cli_driver)
        await manager.start_all()
        await manager.start_health_monitoring()
        # ... run ...
        await manager.stop_all()
    """

    def __init__(self, config: ChannelConfig | None = None) -> None:
        """
        Initialize the channel manager.

        Args:
            config: Channel configuration. Defaults to environment-based config.
        """
        self._config = config or ChannelConfig.from_env()
        self._channels: dict[str, BaseChannel] = {}
        self._status: dict[str, ChannelStatus] = {}
        self._started_at: dict[str, datetime] = {}
        self._message_counts: dict[str, int] = {}
        self._last_message_at: dict[str, datetime | None] = {}
        self._health_status: dict[str, HealthStatus] = {}
        self._health_task: asyncio.Task[None] | None = None
        self._manager_started_at: datetime | None = None
        self._registration_order: list[str] = []

    # =========================================================================
    # Registration
    # =========================================================================

    def register(self, name: str, channel: BaseChannel) -> None:
        """
        Register a channel for management.

        Args:
            name: Unique channel identifier.
            channel: Channel instance.

        Raises:
            ValueError: If channel name is already registered.
        """
        if name in self._channels:
            raise ValueError(f"Channel '{name}' is already registered")

        self._channels[name] = channel
        self._status[name] = ChannelStatus.STOPPED
        self._message_counts[name] = 0
        self._last_message_at[name] = None
        self._registration_order.append(name)

        logger.debug(
            f"[WHISPER] Registered channel: {name}",
            extra={"channel": name, "type": channel.channel_type},
        )

    def unregister(self, name: str) -> None:
        """
        Unregister a channel.

        Args:
            name: Channel identifier to unregister.

        Raises:
            ValueError: If channel is not registered or still running.
        """
        if name not in self._channels:
            raise ValueError(f"Channel '{name}' is not registered")

        if self._status[name] == ChannelStatus.RUNNING:
            raise ValueError(f"Cannot unregister running channel '{name}'")

        del self._channels[name]
        del self._status[name]
        del self._message_counts[name]
        del self._last_message_at[name]
        self._started_at.pop(name, None)
        self._health_status.pop(name, None)
        self._registration_order.remove(name)

        logger.debug(f"[WHISPER] Unregistered channel: {name}")

    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self._channels.get(name)

    def get_status(self, name: str) -> ChannelStatus:
        """Get channel status."""
        return self._status.get(name, ChannelStatus.STOPPED)

    @property
    def active_channels(self) -> list[str]:
        """List of running channel names."""
        return [name for name, status in self._status.items() if status == ChannelStatus.RUNNING]

    @property
    def registered_channels(self) -> list[str]:
        """List of all registered channel names."""
        return list(self._channels.keys())

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def start_all(self) -> dict[str, bool]:
        """
        Start all registered channels concurrently.

        Returns:
            Dict mapping channel names to success status.
        """
        if not self._channels:
            logger.warning("[SWELL] No channels registered to start")
            return {}

        self._manager_started_at = datetime.now()
        results: dict[str, bool] = {}
        tasks: list[tuple[str, asyncio.Task[None]]] = []

        logger.info(
            f"[CHART] Starting {len(self._channels)} channel(s)...",
            extra={"channels": list(self._channels.keys())},
        )

        # Create start tasks for each channel
        for name, channel in self._channels.items():
            self._status[name] = ChannelStatus.STARTING
            task = asyncio.create_task(self._start_channel(name, channel))
            tasks.append((name, task))

        # Wait for all tasks with exception handling
        for name, task in tasks:
            try:
                await task
                results[name] = True
            except Exception as e:
                results[name] = False
                self._status[name] = ChannelStatus.ERROR
                logger.error(
                    f"[STORM] Failed to start channel {name}: {e}",
                    extra={"channel": name},
                    exc_info=True,
                )

        success_count = sum(results.values())
        logger.info(
            f"[CHART] Started {success_count}/{len(results)} channel(s)",
            extra={"results": results},
        )

        return results

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a single channel."""
        logger.debug(f"[WHISPER] Starting channel: {name}")
        await channel.start()
        self._status[name] = ChannelStatus.RUNNING
        self._started_at[name] = datetime.now()
        logger.info(f"[CHART] Channel started: {name}")

    async def stop_all(self) -> dict[str, bool]:
        """
        Stop all channels in reverse registration order.

        Returns:
            Dict mapping channel names to success status.
        """
        if not self._channels:
            return {}

        # Stop health monitoring first
        await self.stop_health_monitoring()

        results: dict[str, bool] = {}

        logger.info(
            f"[CHART] Stopping {len(self._channels)} channel(s)...",
            extra={"channels": list(reversed(self._registration_order))},
        )

        # Stop in reverse registration order
        for name in reversed(self._registration_order):
            channel = self._channels.get(name)
            if channel is None:
                continue

            if self._status[name] != ChannelStatus.RUNNING:
                results[name] = True
                continue

            self._status[name] = ChannelStatus.STOPPING

            try:
                await channel.stop()
                self._status[name] = ChannelStatus.STOPPED
                results[name] = True
                logger.debug(f"[WHISPER] Stopped channel: {name}")
            except Exception as e:
                self._status[name] = ChannelStatus.ERROR
                results[name] = False
                logger.error(
                    f"[STORM] Failed to stop channel {name}: {e}",
                    extra={"channel": name},
                    exc_info=True,
                )

        success_count = sum(results.values())
        logger.info(
            f"[BEACON] Stopped {success_count}/{len(results)} channel(s)",
            extra={"results": results},
        )

        return results

    async def restart_channel(self, name: str) -> bool:
        """
        Restart a specific channel.

        Args:
            name: Channel name to restart.

        Returns:
            True if restart succeeded.
        """
        if name not in self._channels:
            logger.error(f"[STORM] Channel not found: {name}")
            return False

        channel = self._channels[name]

        logger.info(f"[CHART] Restarting channel: {name}")

        # Stop if running
        if self._status[name] == ChannelStatus.RUNNING:
            self._status[name] = ChannelStatus.STOPPING
            try:
                await channel.stop()
            except Exception as e:
                logger.error(f"[STORM] Error stopping channel {name}: {e}")

        # Start
        self._status[name] = ChannelStatus.STARTING
        try:
            await channel.start()
            self._status[name] = ChannelStatus.RUNNING
            self._started_at[name] = datetime.now()
            logger.info(f"[BEACON] Channel restarted: {name}")
            return True
        except Exception as e:
            self._status[name] = ChannelStatus.ERROR
            logger.error(f"[STORM] Failed to restart channel {name}: {e}")
            return False

    # =========================================================================
    # Health Monitoring
    # =========================================================================

    async def start_health_monitoring(
        self,
        interval_seconds: float | None = None,
        stale_threshold_seconds: float | None = None,
    ) -> None:
        """
        Start periodic health checks.

        Args:
            interval_seconds: Check interval. Defaults to config value.
            stale_threshold_seconds: Threshold for stale detection.
        """
        if self._health_task is not None:
            logger.warning("[SWELL] Health monitoring already running")
            return

        interval = interval_seconds or self._config.health_check_interval
        threshold = stale_threshold_seconds or self._config.stale_threshold

        logger.info(
            f"[CHART] Starting health monitoring (interval={interval}s, stale={threshold}s)"
        )

        self._health_task = asyncio.create_task(self._health_check_loop(interval, threshold))

    async def stop_health_monitoring(self) -> None:
        """Stop health check task."""
        if self._health_task is None:
            return

        self._health_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._health_task
        self._health_task = None

        logger.debug("[WHISPER] Health monitoring stopped")

    async def _health_check_loop(self, interval: float, stale_threshold: float) -> None:
        """Periodically check channel health."""
        while True:
            try:
                await asyncio.sleep(interval)
                await self._perform_health_checks(stale_threshold)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[STORM] Health check error: {e}", exc_info=True)

    async def _perform_health_checks(self, stale_threshold: float) -> None:
        """Perform health checks on all channels."""
        now = datetime.now()

        for name, channel in self._channels.items():
            if self._status[name] != ChannelStatus.RUNNING:
                continue

            # Check if channel has is_healthy method
            is_healthy = True
            error = None

            if hasattr(channel, "is_healthy"):
                try:
                    is_healthy = await channel.is_healthy()
                except Exception as e:
                    is_healthy = False
                    error = str(e)

            # Check for stale channel (no messages for too long)
            last_msg = self._last_message_at.get(name)
            if last_msg is not None:
                seconds_since = (now - last_msg).total_seconds()
                if seconds_since > stale_threshold:
                    is_healthy = False
                    error = f"No messages for {seconds_since:.0f}s"

            # Update health status
            self._health_status[name] = HealthStatus(
                channel_name=name,
                is_healthy=is_healthy,
                last_message_at=last_msg,
                last_check_at=now,
                error=error,
                message_count=self._message_counts.get(name, 0),
            )

            if not is_healthy:
                logger.warning(
                    f"[SWELL] Channel unhealthy: {name}",
                    extra={"channel": name, "error": error},
                )

    def get_health(self, name: str) -> HealthStatus | None:
        """Get health status for a channel."""
        return self._health_status.get(name)

    @property
    def all_healthy(self) -> bool:
        """Check if all running channels are healthy."""
        for name in self.active_channels:
            health = self._health_status.get(name)
            if health is None or not health.is_healthy:
                return False
        return True

    # =========================================================================
    # Message Tracking
    # =========================================================================

    def record_message(self, channel_name: str) -> None:
        """
        Record that a message was processed.

        Args:
            channel_name: Name of the channel that processed the message.
        """
        if channel_name in self._message_counts:
            self._message_counts[channel_name] += 1
            self._last_message_at[channel_name] = datetime.now()

    # =========================================================================
    # Status Reporting
    # =========================================================================

    def get_status_report(self) -> ChannelStatusReport:
        """
        Get comprehensive status report for all channels.

        Returns:
            ChannelStatusReport with health and message stats.
        """
        now = datetime.now()
        channels: dict[str, ChannelInfo] = {}

        for name, channel in self._channels.items():
            health = self._health_status.get(name)
            channels[name] = ChannelInfo(
                name=name,
                channel_type=channel.channel_type,
                status=self._status[name],
                is_healthy=health.is_healthy if health else True,
                message_count=self._message_counts.get(name, 0),
                last_message_at=self._last_message_at.get(name),
                started_at=self._started_at.get(name),
                error=health.error if health else None,
            )

        total_messages = sum(self._message_counts.values())
        uptime = 0.0
        if self._manager_started_at:
            uptime = (now - self._manager_started_at).total_seconds()

        healthy_count = sum(1 for c in channels.values() if c.is_healthy)
        unhealthy_count = len(channels) - healthy_count

        return ChannelStatusReport(
            timestamp=now,
            channels=channels,
            total_messages=total_messages,
            uptime_seconds=uptime,
            healthy_count=healthy_count,
            unhealthy_count=unhealthy_count,
        )

    def get_channel_info(self, name: str) -> ChannelInfo | None:
        """Get detailed info for a specific channel."""
        if name not in self._channels:
            return None

        channel = self._channels[name]
        health = self._health_status.get(name)

        return ChannelInfo(
            name=name,
            channel_type=channel.channel_type,
            status=self._status[name],
            is_healthy=health.is_healthy if health else True,
            message_count=self._message_counts.get(name, 0),
            last_message_at=self._last_message_at.get(name),
            started_at=self._started_at.get(name),
            error=health.error if health else None,
        )


# =============================================================================
# Module-level instance
# =============================================================================

_channel_manager: ChannelManager | None = None


def get_channel_manager() -> ChannelManager:
    """Get or create the global channel manager."""
    global _channel_manager
    if _channel_manager is None:
        _channel_manager = ChannelManager()
    return _channel_manager


def reset_channel_manager() -> None:
    """Reset the global channel manager (for testing)."""
    global _channel_manager
    _channel_manager = None


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "ChannelConfig",
    "ChannelInfo",
    "ChannelManager",
    "ChannelStatus",
    "ChannelStatusReport",
    "HealthStatus",
    "get_channel_manager",
    "reset_channel_manager",
]
