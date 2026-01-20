"""
Unit tests for Channel Manager.

Tests channel lifecycle management, health monitoring, and status reporting.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.channels.manager import (
    ChannelConfig,
    ChannelManager,
    ChannelStatus,
    ChannelStatusReport,
    get_channel_manager,
    reset_channel_manager,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_channel() -> MagicMock:
    """Create a mock channel."""
    channel = MagicMock()
    channel.channel_type = "test"
    channel.start = AsyncMock()
    channel.stop = AsyncMock()
    channel.is_healthy = AsyncMock(return_value=True)
    return channel


@pytest.fixture
def manager() -> ChannelManager:
    """Create a fresh channel manager."""
    return ChannelManager(ChannelConfig())


@pytest.fixture(autouse=True)
def reset_global_manager() -> None:
    """Reset global manager before each test."""
    reset_channel_manager()


# =============================================================================
# Test ChannelConfig
# =============================================================================


class TestChannelConfig:
    """Tests for ChannelConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = ChannelConfig()

        assert config.enable_cli is True
        assert config.enable_telegram is False
        assert config.enable_discord is False
        assert config.health_check_interval == 30.0
        assert config.stale_threshold == 300.0

    def test_from_env_cli_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading CLI enabled from environment."""
        monkeypatch.setenv("ENABLE_CLI", "true")
        config = ChannelConfig.from_env()
        assert config.enable_cli is True

    def test_from_env_cli_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading CLI disabled from environment."""
        monkeypatch.setenv("ENABLE_CLI", "false")
        config = ChannelConfig.from_env()
        assert config.enable_cli is False

    def test_from_env_telegram_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading Telegram enabled from environment."""
        monkeypatch.setenv("ENABLE_TELEGRAM", "true")
        config = ChannelConfig.from_env()
        assert config.enable_telegram is True

    def test_from_env_health_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading health check interval from environment."""
        monkeypatch.setenv("HEALTH_CHECK_INTERVAL", "60.0")
        config = ChannelConfig.from_env()
        assert config.health_check_interval == 60.0


# =============================================================================
# Test Registration
# =============================================================================


class TestChannelRegistration:
    """Tests for channel registration."""

    def test_register_channel(self, manager: ChannelManager, mock_channel: MagicMock) -> None:
        """Test registering a channel."""
        manager.register("test", mock_channel)

        assert "test" in manager.registered_channels
        assert manager.get_channel("test") is mock_channel
        assert manager.get_status("test") == ChannelStatus.STOPPED

    def test_register_duplicate_raises(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test that registering duplicate name raises."""
        manager.register("test", mock_channel)

        with pytest.raises(ValueError, match="already registered"):
            manager.register("test", mock_channel)

    def test_unregister_channel(self, manager: ChannelManager, mock_channel: MagicMock) -> None:
        """Test unregistering a channel."""
        manager.register("test", mock_channel)
        manager.unregister("test")

        assert "test" not in manager.registered_channels
        assert manager.get_channel("test") is None

    def test_unregister_nonexistent_raises(self, manager: ChannelManager) -> None:
        """Test that unregistering nonexistent channel raises."""
        with pytest.raises(ValueError, match="not registered"):
            manager.unregister("nonexistent")

    @pytest.mark.asyncio
    async def test_unregister_running_raises(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test that unregistering running channel raises."""
        manager.register("test", mock_channel)
        await manager.start_all()

        with pytest.raises(ValueError, match="Cannot unregister running"):
            manager.unregister("test")

        await manager.stop_all()

    def test_get_channel_nonexistent(self, manager: ChannelManager) -> None:
        """Test getting nonexistent channel returns None."""
        assert manager.get_channel("nonexistent") is None

    def test_get_status_nonexistent(self, manager: ChannelManager) -> None:
        """Test getting status of nonexistent channel."""
        assert manager.get_status("nonexistent") == ChannelStatus.STOPPED


# =============================================================================
# Test Lifecycle
# =============================================================================


class TestChannelLifecycle:
    """Tests for channel lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_all_empty(self, manager: ChannelManager) -> None:
        """Test starting with no channels."""
        results = await manager.start_all()
        assert results == {}

    @pytest.mark.asyncio
    async def test_start_single_channel(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test starting a single channel."""
        manager.register("test", mock_channel)
        results = await manager.start_all()

        assert results == {"test": True}
        assert manager.get_status("test") == ChannelStatus.RUNNING
        mock_channel.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_multiple_channels(self, manager: ChannelManager) -> None:
        """Test starting multiple channels concurrently."""
        channels = {}
        for name in ["ch1", "ch2", "ch3"]:
            ch = MagicMock()
            ch.channel_type = name
            ch.start = AsyncMock()
            ch.stop = AsyncMock()
            channels[name] = ch
            manager.register(name, ch)

        results = await manager.start_all()

        assert all(results.values())
        for name, ch in channels.items():
            assert manager.get_status(name) == ChannelStatus.RUNNING
            ch.start.assert_called_once()

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_start_with_failure(self, manager: ChannelManager) -> None:
        """Test starting when one channel fails."""
        good_channel = MagicMock()
        good_channel.channel_type = "good"
        good_channel.start = AsyncMock()
        good_channel.stop = AsyncMock()

        bad_channel = MagicMock()
        bad_channel.channel_type = "bad"
        bad_channel.start = AsyncMock(side_effect=RuntimeError("Failed"))
        bad_channel.stop = AsyncMock()

        manager.register("good", good_channel)
        manager.register("bad", bad_channel)

        results = await manager.start_all()

        assert results["good"] is True
        assert results["bad"] is False
        assert manager.get_status("good") == ChannelStatus.RUNNING
        assert manager.get_status("bad") == ChannelStatus.ERROR

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_stop_all_empty(self, manager: ChannelManager) -> None:
        """Test stopping with no channels."""
        results = await manager.stop_all()
        assert results == {}

    @pytest.mark.asyncio
    async def test_stop_single_channel(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test stopping a single channel."""
        manager.register("test", mock_channel)
        await manager.start_all()

        results = await manager.stop_all()

        assert results == {"test": True}
        assert manager.get_status("test") == ChannelStatus.STOPPED
        mock_channel.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_reverse_order(self, manager: ChannelManager) -> None:
        """Test that channels stop in reverse registration order."""
        stop_order: list[str] = []

        def make_stop_fn(name: str) -> AsyncMock:
            """Create a stop function that records when it's called."""

            async def _stop() -> None:
                stop_order.append(name)

            return AsyncMock(side_effect=_stop)

        for name in ["first", "second", "third"]:
            ch = MagicMock()
            ch.channel_type = name
            ch.start = AsyncMock()
            ch.stop = make_stop_fn(name)
            manager.register(name, ch)

        await manager.start_all()
        await manager.stop_all()

        assert stop_order == ["third", "second", "first"]

    @pytest.mark.asyncio
    async def test_stop_with_failure(self, manager: ChannelManager) -> None:
        """Test stopping when one channel fails."""
        good_channel = MagicMock()
        good_channel.channel_type = "good"
        good_channel.start = AsyncMock()
        good_channel.stop = AsyncMock()

        bad_channel = MagicMock()
        bad_channel.channel_type = "bad"
        bad_channel.start = AsyncMock()
        bad_channel.stop = AsyncMock(side_effect=RuntimeError("Stop failed"))

        manager.register("good", good_channel)
        manager.register("bad", bad_channel)

        await manager.start_all()
        results = await manager.stop_all()

        assert results["good"] is True
        assert results["bad"] is False

    @pytest.mark.asyncio
    async def test_restart_channel(self, manager: ChannelManager, mock_channel: MagicMock) -> None:
        """Test restarting a channel."""
        manager.register("test", mock_channel)
        await manager.start_all()

        # Reset mocks
        mock_channel.start.reset_mock()
        mock_channel.stop.reset_mock()

        result = await manager.restart_channel("test")

        assert result is True
        mock_channel.stop.assert_called_once()
        mock_channel.start.assert_called_once()
        assert manager.get_status("test") == ChannelStatus.RUNNING

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_restart_nonexistent(self, manager: ChannelManager) -> None:
        """Test restarting nonexistent channel."""
        result = await manager.restart_channel("nonexistent")
        assert result is False


# =============================================================================
# Test Active Channels
# =============================================================================


class TestActiveChannels:
    """Tests for active channel tracking."""

    def test_active_channels_empty(self, manager: ChannelManager) -> None:
        """Test active channels when none registered."""
        assert manager.active_channels == []

    @pytest.mark.asyncio
    async def test_active_channels_after_start(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test active channels after starting."""
        manager.register("test", mock_channel)
        await manager.start_all()

        assert "test" in manager.active_channels

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_active_channels_after_stop(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test active channels after stopping."""
        manager.register("test", mock_channel)
        await manager.start_all()
        await manager.stop_all()

        assert manager.active_channels == []


# =============================================================================
# Test Health Monitoring
# =============================================================================


class TestHealthMonitoring:
    """Tests for health monitoring."""

    @pytest.mark.asyncio
    async def test_start_health_monitoring(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test starting health monitoring."""
        manager.register("test", mock_channel)
        await manager.start_all()
        await manager.start_health_monitoring(interval_seconds=0.1)

        # Let it run briefly
        await asyncio.sleep(0.2)

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_health_check_records_status(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test that health checks record status."""
        manager.register("test", mock_channel)
        await manager.start_all()

        # Manually trigger health check
        await manager._perform_health_checks(300.0)

        health = manager.get_health("test")
        assert health is not None
        assert health.is_healthy is True
        assert health.channel_name == "test"

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_health_check_detects_unhealthy(self, manager: ChannelManager) -> None:
        """Test that health checks detect unhealthy channels."""
        channel = MagicMock()
        channel.channel_type = "test"
        channel.start = AsyncMock()
        channel.stop = AsyncMock()
        channel.is_healthy = AsyncMock(return_value=False)

        manager.register("test", channel)
        await manager.start_all()

        await manager._perform_health_checks(300.0)

        health = manager.get_health("test")
        assert health is not None
        assert health.is_healthy is False

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_stale_detection(self, manager: ChannelManager, mock_channel: MagicMock) -> None:
        """Test stale channel detection."""
        manager.register("test", mock_channel)
        await manager.start_all()

        # Record a message
        manager.record_message("test")

        # Set last message to old time
        from datetime import timedelta

        manager._last_message_at["test"] = datetime.now() - timedelta(seconds=400)

        # Check with 300s threshold
        await manager._perform_health_checks(300.0)

        health = manager.get_health("test")
        assert health is not None
        assert health.is_healthy is False
        assert "No messages for" in (health.error or "")

        await manager.stop_all()

    def test_all_healthy_no_channels(self, manager: ChannelManager) -> None:
        """Test all_healthy with no channels."""
        assert manager.all_healthy is True

    @pytest.mark.asyncio
    async def test_all_healthy_with_healthy_channels(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test all_healthy with healthy channels."""
        manager.register("test", mock_channel)
        await manager.start_all()
        await manager._perform_health_checks(300.0)

        assert manager.all_healthy is True

        await manager.stop_all()


# =============================================================================
# Test Message Tracking
# =============================================================================


class TestMessageTracking:
    """Tests for message tracking."""

    def test_record_message(self, manager: ChannelManager, mock_channel: MagicMock) -> None:
        """Test recording a message."""
        manager.register("test", mock_channel)
        manager.record_message("test")

        assert manager._message_counts["test"] == 1
        assert manager._last_message_at["test"] is not None

    def test_record_multiple_messages(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test recording multiple messages."""
        manager.register("test", mock_channel)

        for _ in range(5):
            manager.record_message("test")

        assert manager._message_counts["test"] == 5

    def test_record_message_unregistered(self, manager: ChannelManager) -> None:
        """Test recording message for unregistered channel."""
        # Should not raise, just ignore
        manager.record_message("nonexistent")


# =============================================================================
# Test Status Reporting
# =============================================================================


class TestStatusReporting:
    """Tests for status reporting."""

    def test_get_status_report_empty(self, manager: ChannelManager) -> None:
        """Test status report with no channels."""
        report = manager.get_status_report()

        assert isinstance(report, ChannelStatusReport)
        assert report.channels == {}
        assert report.total_messages == 0
        assert report.healthy_count == 0
        assert report.unhealthy_count == 0

    @pytest.mark.asyncio
    async def test_get_status_report_with_channels(
        self, manager: ChannelManager, mock_channel: MagicMock
    ) -> None:
        """Test status report with channels."""
        manager.register("test", mock_channel)
        await manager.start_all()
        manager.record_message("test")

        report = manager.get_status_report()

        assert "test" in report.channels
        assert report.total_messages == 1
        assert report.channels["test"].message_count == 1
        assert report.channels["test"].status == ChannelStatus.RUNNING

        await manager.stop_all()

    def test_get_channel_info(self, manager: ChannelManager, mock_channel: MagicMock) -> None:
        """Test getting channel info."""
        manager.register("test", mock_channel)

        info = manager.get_channel_info("test")

        assert info is not None
        assert info.name == "test"
        assert info.channel_type == "test"
        assert info.status == ChannelStatus.STOPPED

    def test_get_channel_info_nonexistent(self, manager: ChannelManager) -> None:
        """Test getting info for nonexistent channel."""
        info = manager.get_channel_info("nonexistent")
        assert info is None


# =============================================================================
# Test Global Instance
# =============================================================================


class TestGlobalInstance:
    """Tests for global channel manager instance."""

    def test_get_channel_manager_creates_instance(self) -> None:
        """Test that get_channel_manager creates instance."""
        manager = get_channel_manager()
        assert isinstance(manager, ChannelManager)

    def test_get_channel_manager_returns_same_instance(self) -> None:
        """Test that get_channel_manager returns same instance."""
        manager1 = get_channel_manager()
        manager2 = get_channel_manager()
        assert manager1 is manager2

    def test_reset_channel_manager(self) -> None:
        """Test resetting global manager."""
        manager1 = get_channel_manager()
        reset_channel_manager()
        manager2 = get_channel_manager()
        assert manager1 is not manager2
