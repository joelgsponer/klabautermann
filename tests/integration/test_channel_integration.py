"""
Integration Tests: Comprehensive Channel Test Suite (#161)

Tests verifying channel integration with the orchestrator, thread isolation,
and multi-channel scenarios.

Reference:
- specs/architecture/CHANNELS.md Section 7
- Issue #161: Add channel integration test suite

Test Coverage:
1. CLI integration with orchestrator
2. Telegram integration with orchestrator
3. Thread isolation (no context bleed between channels)
4. Multi-channel concurrent operation
5. Channel manager integration
6. Message routing and response formatting
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.channels.cli_driver import CLIDriver
from klabautermann.channels.manager import (
    ChannelConfig,
    ChannelManager,
    ChannelStatus,
)
from klabautermann.channels.telegram_driver import TelegramDriver


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_orchestrator() -> MagicMock:
    """Create a mock orchestrator with v2 workflow."""
    orchestrator = MagicMock(spec=Orchestrator)
    orchestrator.handle_user_input = AsyncMock(return_value="Test response")
    orchestrator.handle_user_input_v2 = AsyncMock(return_value="Test response")
    return orchestrator


@pytest.fixture
def cli_driver(mock_orchestrator: MagicMock) -> CLIDriver:
    """Create CLI driver with mock orchestrator."""
    return CLIDriver(orchestrator=mock_orchestrator)


@pytest.fixture
def telegram_driver(mock_orchestrator: MagicMock) -> TelegramDriver:
    """Create Telegram driver with mock orchestrator."""
    return TelegramDriver(
        orchestrator=mock_orchestrator,
        config={
            "bot_token": "test-token-12345",
            "allowed_user_ids": [],
            "enable_voice": False,
        },
    )


@pytest.fixture
def channel_manager() -> ChannelManager:
    """Create a fresh channel manager."""
    return ChannelManager(
        ChannelConfig(
            auto_restart=False,  # Disable for testing
        )
    )


# =============================================================================
# TEST 1: CLI Integration Tests
# =============================================================================


class TestCLIIntegration:
    """Tests for CLI driver integration with orchestrator."""

    @pytest.mark.asyncio
    async def test_cli_receive_message_calls_orchestrator(
        self, cli_driver: CLIDriver, mock_orchestrator: MagicMock
    ) -> None:
        """CLI driver should call orchestrator for message processing."""
        response = await cli_driver.receive_message(
            thread_id="cli-test-123",
            content="Hello world",
        )

        mock_orchestrator.handle_user_input.assert_called_once()
        assert response == "Test response"

    @pytest.mark.asyncio
    async def test_cli_thread_id_format(self, cli_driver: CLIDriver) -> None:
        """CLI driver should generate thread IDs in correct format."""
        thread_id = cli_driver.get_thread_id()

        assert thread_id.startswith("cli-")
        assert len(thread_id) > 4

    def test_cli_channel_type(self, cli_driver: CLIDriver) -> None:
        """CLI driver should report correct channel type."""
        assert cli_driver.channel_type == "cli"

    @pytest.mark.asyncio
    async def test_cli_passes_thread_id_to_orchestrator(
        self, cli_driver: CLIDriver, mock_orchestrator: MagicMock
    ) -> None:
        """CLI driver should pass thread_id to orchestrator."""
        await cli_driver.receive_message(
            thread_id="cli-specific-thread",
            content="Test message",
        )

        call_kwargs = mock_orchestrator.handle_user_input.call_args.kwargs
        assert call_kwargs["thread_id"] == "cli-specific-thread"

    @pytest.mark.asyncio
    async def test_cli_error_handling(
        self, cli_driver: CLIDriver, mock_orchestrator: MagicMock
    ) -> None:
        """CLI driver should handle orchestrator errors gracefully."""
        mock_orchestrator.handle_user_input.side_effect = Exception("Connection error")

        response = await cli_driver.receive_message(
            thread_id="cli-test",
            content="Test",
        )

        # Should return user-friendly error message
        assert "rough waters" in response.lower()


# =============================================================================
# TEST 2: Telegram Integration Tests
# =============================================================================


class TestTelegramIntegration:
    """Tests for Telegram driver integration with orchestrator."""

    @pytest.mark.asyncio
    async def test_telegram_receive_message_calls_orchestrator(
        self, telegram_driver: TelegramDriver, mock_orchestrator: MagicMock
    ) -> None:
        """Telegram driver should call orchestrator for message processing."""
        response = await telegram_driver.receive_message(
            thread_id="telegram-123456789",
            content="Hello from Telegram",
        )

        mock_orchestrator.handle_user_input_v2.assert_called_once()
        assert response == "Test response"

    def test_telegram_channel_type(self, telegram_driver: TelegramDriver) -> None:
        """Telegram driver should report correct channel type."""
        assert telegram_driver.channel_type == "telegram"

    @pytest.mark.asyncio
    async def test_telegram_thread_id_from_update(self, telegram_driver: TelegramDriver) -> None:
        """Telegram driver should extract thread ID from Update object."""
        mock_update = MagicMock()
        mock_update.message = MagicMock()
        mock_update.message.chat_id = 987654321

        thread_id = telegram_driver.get_thread_id(mock_update)

        assert thread_id == "telegram-987654321"

    @pytest.mark.asyncio
    async def test_telegram_passes_thread_id_to_orchestrator(
        self, telegram_driver: TelegramDriver, mock_orchestrator: MagicMock
    ) -> None:
        """Telegram driver should pass thread_id to orchestrator."""
        await telegram_driver.receive_message(
            thread_id="telegram-123456789",
            content="Test message",
        )

        call_kwargs = mock_orchestrator.handle_user_input_v2.call_args.kwargs
        assert call_kwargs["thread_uuid"] == "telegram-123456789"


# =============================================================================
# TEST 3: Thread Isolation Tests
# =============================================================================


class TestThreadIsolation:
    """Tests verifying thread isolation between channels."""

    @pytest.mark.asyncio
    async def test_cli_threads_isolated(
        self, cli_driver: CLIDriver, mock_orchestrator: MagicMock
    ) -> None:
        """Different CLI sessions should use different thread IDs."""
        # Create two CLI drivers (simulating two sessions)
        cli1 = CLIDriver(orchestrator=mock_orchestrator)
        cli2 = CLIDriver(orchestrator=mock_orchestrator)

        thread_id1 = cli1.get_thread_id()
        thread_id2 = cli2.get_thread_id()

        # Thread IDs should be different
        assert thread_id1 != thread_id2
        assert thread_id1.startswith("cli-")
        assert thread_id2.startswith("cli-")

    @pytest.mark.asyncio
    async def test_telegram_chats_isolated(self, telegram_driver: TelegramDriver) -> None:
        """Different Telegram chats should map to different thread IDs."""
        update1 = MagicMock()
        update1.message = MagicMock()
        update1.message.chat_id = 111111111

        update2 = MagicMock()
        update2.message = MagicMock()
        update2.message.chat_id = 222222222

        thread_id1 = telegram_driver.get_thread_id(update1)
        thread_id2 = telegram_driver.get_thread_id(update2)

        # Thread IDs should be different
        assert thread_id1 != thread_id2
        assert thread_id1 == "telegram-111111111"
        assert thread_id2 == "telegram-222222222"

    @pytest.mark.asyncio
    async def test_cross_channel_isolation(
        self,
        cli_driver: CLIDriver,
        telegram_driver: TelegramDriver,
        mock_orchestrator: MagicMock,
    ) -> None:
        """Messages from different channels should use different thread prefixes."""
        cli_thread = cli_driver.get_thread_id()

        telegram_update = MagicMock()
        telegram_update.message = MagicMock()
        telegram_update.message.chat_id = 123456789
        telegram_thread = telegram_driver.get_thread_id(telegram_update)

        # Thread IDs should have different prefixes
        assert cli_thread.startswith("cli-")
        assert telegram_thread.startswith("telegram-")
        assert cli_thread != telegram_thread

    @pytest.mark.asyncio
    async def test_same_user_different_channels_isolated(
        self, mock_orchestrator: MagicMock
    ) -> None:
        """Same user on different channels should have isolated contexts."""
        cli_driver = CLIDriver(orchestrator=mock_orchestrator)
        telegram_driver = TelegramDriver(
            orchestrator=mock_orchestrator,
            config={"bot_token": "test-token"},
        )

        # Send message from CLI
        await cli_driver.receive_message(
            thread_id="cli-user123",
            content="Remember: my name is Alice",
        )

        # Send message from Telegram
        await telegram_driver.receive_message(
            thread_id="telegram-user123",
            content="What's my name?",
        )

        # Verify different thread IDs used
        calls = mock_orchestrator.handle_user_input.call_args_list
        telegram_calls = mock_orchestrator.handle_user_input_v2.call_args_list

        # CLI uses handle_user_input, Telegram uses handle_user_input_v2
        assert len(calls) == 1
        assert len(telegram_calls) == 1

        cli_thread = calls[0].kwargs["thread_id"]
        telegram_thread = telegram_calls[0].kwargs["thread_uuid"]

        assert cli_thread != telegram_thread


# =============================================================================
# TEST 4: Multi-Channel Concurrent Operation
# =============================================================================


class TestMultiChannelOperation:
    """Tests for concurrent multi-channel operation."""

    @pytest.mark.asyncio
    async def test_channel_manager_registers_multiple_channels(
        self,
        channel_manager: ChannelManager,
        cli_driver: CLIDriver,
        telegram_driver: TelegramDriver,
    ) -> None:
        """Channel manager should handle multiple channel registrations."""
        channel_manager.register("cli", cli_driver)
        channel_manager.register("telegram", telegram_driver)

        assert "cli" in channel_manager.registered_channels
        assert "telegram" in channel_manager.registered_channels
        assert len(channel_manager.registered_channels) == 2

    @pytest.mark.asyncio
    async def test_channel_manager_starts_multiple_channels(
        self,
        channel_manager: ChannelManager,
    ) -> None:
        """Channel manager should start multiple channels concurrently."""
        # Create mock channels
        cli_mock = MagicMock()
        cli_mock.channel_type = "cli"
        cli_mock.start = AsyncMock()
        cli_mock.stop = AsyncMock()

        telegram_mock = MagicMock()
        telegram_mock.channel_type = "telegram"
        telegram_mock.start = AsyncMock()
        telegram_mock.stop = AsyncMock()

        channel_manager.register("cli", cli_mock)
        channel_manager.register("telegram", telegram_mock)

        results = await channel_manager.start_all()

        assert results["cli"] is True
        assert results["telegram"] is True
        cli_mock.start.assert_called_once()
        telegram_mock.start.assert_called_once()

        await channel_manager.stop_all()

    @pytest.mark.asyncio
    async def test_channel_manager_tracks_active_channels(
        self,
        channel_manager: ChannelManager,
    ) -> None:
        """Channel manager should track which channels are active."""
        cli_mock = MagicMock()
        cli_mock.channel_type = "cli"
        cli_mock.start = AsyncMock()
        cli_mock.stop = AsyncMock()

        channel_manager.register("cli", cli_mock)

        # Before start
        assert channel_manager.active_channels == []

        await channel_manager.start_all()

        # After start
        assert "cli" in channel_manager.active_channels
        assert channel_manager.get_status("cli") == ChannelStatus.RUNNING

        await channel_manager.stop_all()

        # After stop
        assert channel_manager.active_channels == []

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_channels(
        self,
        channel_manager: ChannelManager,
    ) -> None:
        """Channel manager should broadcast to all active channels."""
        cli_mock = MagicMock()
        cli_mock.channel_type = "cli"
        cli_mock.start = AsyncMock()
        cli_mock.stop = AsyncMock()
        cli_mock.send_message = AsyncMock()

        telegram_mock = MagicMock()
        telegram_mock.channel_type = "telegram"
        telegram_mock.start = AsyncMock()
        telegram_mock.stop = AsyncMock()
        telegram_mock.send_message = AsyncMock()

        channel_manager.register("cli", cli_mock)
        channel_manager.register("telegram", telegram_mock)

        await channel_manager.start_all()

        result = await channel_manager.broadcast("System announcement")

        assert result.delivered_count == 2
        assert result.all_delivered
        cli_mock.send_message.assert_called_once()
        telegram_mock.send_message.assert_called_once()

        await channel_manager.stop_all()


# =============================================================================
# TEST 5: Message Routing Tests
# =============================================================================


class TestMessageRouting:
    """Tests for message routing and formatting."""

    @pytest.mark.asyncio
    async def test_cli_message_includes_content(
        self, cli_driver: CLIDriver, mock_orchestrator: MagicMock
    ) -> None:
        """CLI should pass message content to orchestrator."""
        await cli_driver.receive_message(
            thread_id="cli-test",
            content="What's the weather?",
        )

        call_kwargs = mock_orchestrator.handle_user_input.call_args.kwargs
        assert call_kwargs["text"] == "What's the weather?"

    @pytest.mark.asyncio
    async def test_telegram_message_includes_content(
        self, telegram_driver: TelegramDriver, mock_orchestrator: MagicMock
    ) -> None:
        """Telegram should pass message content to orchestrator."""
        await telegram_driver.receive_message(
            thread_id="telegram-123",
            content="What's the weather?",
        )

        call_kwargs = mock_orchestrator.handle_user_input_v2.call_args.kwargs
        assert call_kwargs["text"] == "What's the weather?"

    @pytest.mark.asyncio
    async def test_cli_returns_orchestrator_response(
        self, cli_driver: CLIDriver, mock_orchestrator: MagicMock
    ) -> None:
        """CLI should return orchestrator's response."""
        mock_orchestrator.handle_user_input.return_value = "It's sunny today!"

        response = await cli_driver.receive_message(
            thread_id="cli-test",
            content="What's the weather?",
        )

        assert response == "It's sunny today!"

    @pytest.mark.asyncio
    async def test_telegram_returns_orchestrator_response(
        self, telegram_driver: TelegramDriver, mock_orchestrator: MagicMock
    ) -> None:
        """Telegram should return orchestrator's response."""
        mock_orchestrator.handle_user_input_v2.return_value = "It's sunny today!"

        response = await telegram_driver.receive_message(
            thread_id="telegram-123",
            content="What's the weather?",
        )

        assert response == "It's sunny today!"


# =============================================================================
# TEST 6: Channel Status and Health
# =============================================================================


class TestChannelStatus:
    """Tests for channel status reporting."""

    @pytest.mark.asyncio
    async def test_channel_status_report(
        self,
        channel_manager: ChannelManager,
    ) -> None:
        """Channel manager should provide comprehensive status reports."""
        cli_mock = MagicMock()
        cli_mock.channel_type = "cli"
        cli_mock.start = AsyncMock()
        cli_mock.stop = AsyncMock()

        channel_manager.register("cli", cli_mock)
        await channel_manager.start_all()

        # Record some messages
        channel_manager.record_message("cli")
        channel_manager.record_message("cli")

        report = channel_manager.get_status_report()

        assert "cli" in report.channels
        assert report.channels["cli"].status == ChannelStatus.RUNNING
        assert report.channels["cli"].message_count == 2
        assert report.total_messages == 2

        await channel_manager.stop_all()

    def test_channel_info(
        self,
        channel_manager: ChannelManager,
        cli_driver: CLIDriver,
    ) -> None:
        """Channel manager should provide detailed channel info."""
        channel_manager.register("cli", cli_driver)

        info = channel_manager.get_channel_info("cli")

        assert info is not None
        assert info.name == "cli"
        assert info.channel_type == "cli"
        assert info.status == ChannelStatus.STOPPED
