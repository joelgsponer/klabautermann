"""
Unit tests for the CLI driver.

Tests the command-line interface including message history tracking
and the /copy command for message export.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from klabautermann.channels.cli_driver import ChatMessage, CLIDriver


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_orchestrator() -> MagicMock:
    """Create a mock orchestrator."""
    orchestrator = MagicMock()
    orchestrator.handle_user_input = MagicMock(return_value="Test response")
    return orchestrator


@pytest.fixture
def cli_driver(mock_orchestrator: MagicMock) -> CLIDriver:
    """Create a CLIDriver instance with mocked orchestrator."""
    driver = CLIDriver(orchestrator=mock_orchestrator)
    return driver


# ===========================================================================
# Test ChatMessage
# ===========================================================================


class TestChatMessage:
    """Tests for the ChatMessage dataclass."""

    def test_create_user_message(self) -> None:
        """Should create a user message with all fields."""
        msg = ChatMessage(
            role="user",
            content="Hello, Klabautermann!",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
        )
        assert msg.role == "user"
        assert msg.content == "Hello, Klabautermann!"
        assert msg.timestamp == datetime(2024, 1, 15, 10, 30, 0)

    def test_create_assistant_message(self) -> None:
        """Should create an assistant message."""
        msg = ChatMessage(
            role="assistant",
            content="Ahoy, Captain!",
            timestamp=datetime(2024, 1, 15, 10, 30, 5),
        )
        assert msg.role == "assistant"
        assert msg.content == "Ahoy, Captain!"


# ===========================================================================
# Test Message Formatting
# ===========================================================================


class TestMessageFormatting:
    """Tests for message formatting methods."""

    def test_format_markdown(self, cli_driver: CLIDriver) -> None:
        """Should format messages as markdown with headers and timestamps."""
        messages = [
            ChatMessage(
                role="user",
                content="What's on my schedule?",
                timestamp=datetime(2024, 1, 15, 10, 30, 0),
            ),
            ChatMessage(
                role="assistant",
                content="You have a meeting at 2pm.",
                timestamp=datetime(2024, 1, 15, 10, 30, 5),
            ),
        ]

        result = cli_driver._format_messages(messages, "markdown")

        assert "## User" in result
        assert "## Assistant" in result
        assert "2024-01-15 10:30:00" in result
        assert "What's on my schedule?" in result
        assert "You have a meeting at 2pm." in result
        assert "---" in result  # Separator between messages

    def test_format_plain(self, cli_driver: CLIDriver) -> None:
        """Should format messages as plain text."""
        messages = [
            ChatMessage(
                role="user",
                content="Hello",
                timestamp=datetime(2024, 1, 15, 10, 30, 0),
            ),
            ChatMessage(
                role="assistant",
                content="Hi there!",
                timestamp=datetime(2024, 1, 15, 10, 30, 5),
            ),
        ]

        result = cli_driver._format_messages(messages, "plain")

        assert "[You] Hello" in result
        assert "[Klabautermann] Hi there!" in result
        assert "##" not in result  # No markdown headers

    def test_format_json(self, cli_driver: CLIDriver) -> None:
        """Should format messages as JSON."""
        messages = [
            ChatMessage(
                role="user",
                content="Test message",
                timestamp=datetime(2024, 1, 15, 10, 30, 0),
            ),
        ]

        result = cli_driver._format_messages(messages, "json")

        # Should be valid JSON
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["role"] == "user"
        assert parsed[0]["content"] == "Test message"
        assert "timestamp" in parsed[0]


# ===========================================================================
# Test Copy Command Handling
# ===========================================================================


class TestCopyCommand:
    """Tests for the /copy command functionality."""

    @pytest.mark.asyncio
    async def test_copy_no_messages(self, cli_driver: CLIDriver) -> None:
        """Should handle /copy with no messages in history."""
        cli_driver._message_history = []

        with patch.object(cli_driver.renderer, "render_info") as mock_render:
            await cli_driver._handle_copy_command(count=5)
            mock_render.assert_called_once_with("No messages to copy.")

    @pytest.mark.asyncio
    async def test_copy_exports_to_file_fallback(self, cli_driver: CLIDriver) -> None:
        """Should fallback to file export when neovim and clipboard unavailable."""
        cli_driver._message_history = [
            ChatMessage(
                role="user",
                content="Test",
                timestamp=datetime(2024, 1, 15, 10, 30, 0),
            ),
        ]

        with (
            patch.object(cli_driver, "_export_to_neovim", return_value=False),
            patch.object(cli_driver, "_try_clipboard", return_value=False),
            patch.object(cli_driver, "_export_to_file", return_value="/tmp/test.md") as mock_export,
            patch.object(cli_driver.renderer, "render_info") as mock_render,
        ):
            await cli_driver._handle_copy_command(count=1)

            mock_export.assert_called_once()
            mock_render.assert_called_once()
            assert "Exported 1 message(s)" in mock_render.call_args[0][0]

    @pytest.mark.asyncio
    async def test_copy_last_n_messages(self, cli_driver: CLIDriver) -> None:
        """Should copy only the last N messages."""
        cli_driver._message_history = [
            ChatMessage(role="user", content="First", timestamp=datetime.now()),
            ChatMessage(role="assistant", content="Second", timestamp=datetime.now()),
            ChatMessage(role="user", content="Third", timestamp=datetime.now()),
            ChatMessage(role="assistant", content="Fourth", timestamp=datetime.now()),
        ]

        with (
            patch.object(cli_driver, "_export_to_neovim", return_value=False),
            patch.object(cli_driver, "_try_clipboard", return_value=True),
            patch.object(cli_driver.renderer, "render_info"),
            patch.object(cli_driver, "_format_messages", return_value="") as mock_format,
        ):
            await cli_driver._handle_copy_command(count=2)

            # Should only format the last 2 messages
            formatted_messages = mock_format.call_args[0][0]
            assert len(formatted_messages) == 2
            assert formatted_messages[0].content == "Third"
            assert formatted_messages[1].content == "Fourth"


# ===========================================================================
# Test Export Methods
# ===========================================================================


class TestExportMethods:
    """Tests for the various export methods."""

    def test_try_clipboard_no_tools(self, cli_driver: CLIDriver) -> None:
        """Should return False when no clipboard tools available."""
        with patch("shutil.which", return_value=None):
            result = cli_driver._try_clipboard("test content")
            assert result is False

    def test_export_to_neovim_not_installed(self, cli_driver: CLIDriver) -> None:
        """Should return False when neovim is not installed."""
        with patch("shutil.which", return_value=None):
            result = cli_driver._export_to_neovim("test content")
            assert result is False

    def test_export_to_file_creates_directory(self, cli_driver: CLIDriver, tmp_path) -> None:
        """Should create export directory if it doesn't exist."""
        from klabautermann.channels import cli_driver as cli_module

        # Temporarily change the history dir
        original_dir = cli_module.HISTORY_DIR
        cli_module.HISTORY_DIR = tmp_path / "test_klabautermann"

        try:
            result = cli_driver._export_to_file("test content", "markdown")

            assert result.endswith(".md")
            assert "conversation_" in result
            # Verify file exists and contains content
            with Path(result).open() as f:
                assert f.read() == "test content"
        finally:
            cli_module.HISTORY_DIR = original_dir
