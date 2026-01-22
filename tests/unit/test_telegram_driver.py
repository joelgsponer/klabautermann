"""
Unit tests for TelegramDriver.

Tests the Telegram channel implementation without real API calls.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.channels.telegram_driver import TelegramDriver


@pytest.fixture
def mock_orchestrator() -> MagicMock:
    """Create a mock orchestrator."""
    orchestrator = MagicMock()
    orchestrator.handle_user_input_v2 = AsyncMock(return_value="Test response")
    return orchestrator


@pytest.fixture
def telegram_driver(mock_orchestrator: MagicMock) -> TelegramDriver:
    """Create a TelegramDriver with mock orchestrator."""
    return TelegramDriver(
        orchestrator=mock_orchestrator,
        config={
            "bot_token": "test-token-12345",
            "allowed_user_ids": [],
            "enable_voice": True,
        },
    )


@pytest.fixture
def mock_update() -> MagicMock:
    """Create a mock Telegram Update."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.chat_id = 123456789
    update.message.from_user = MagicMock()
    update.message.from_user.id = 987654321
    update.message.from_user.username = "testuser"
    update.message.text = "Hello, Klabautermann!"
    update.message.reply_text = AsyncMock()
    update.message.chat = MagicMock()
    update.message.chat.send_action = AsyncMock()
    return update


def test_init_with_config_token() -> None:
    """TelegramDriver uses bot_token from config."""
    driver = TelegramDriver(
        orchestrator=None,
        config={"bot_token": "config-token"},
    )
    assert driver.bot_token == "config-token"


def test_init_with_env_token() -> None:
    """TelegramDriver falls back to TELEGRAM_BOT_TOKEN env var."""
    with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "env-token"}):
        driver = TelegramDriver(
            orchestrator=None,
            config={},
        )
        assert driver.bot_token == "env-token"


def test_init_allowed_user_ids() -> None:
    """TelegramDriver respects allowed_user_ids config."""
    driver = TelegramDriver(
        orchestrator=None,
        config={"allowed_user_ids": [123, 456, 789]},
    )
    assert driver.allowed_user_ids == [123, 456, 789]


def test_init_voice_disabled() -> None:
    """TelegramDriver can disable voice handling."""
    driver = TelegramDriver(
        orchestrator=None,
        config={"enable_voice": False},
    )
    assert driver.enable_voice is False


def test_channel_type(telegram_driver: TelegramDriver) -> None:
    """TelegramDriver returns correct channel type."""
    assert telegram_driver.channel_type == "telegram"


def test_get_thread_id_from_update(telegram_driver: TelegramDriver, mock_update: MagicMock) -> None:
    """TelegramDriver extracts thread ID from Update."""
    thread_id = telegram_driver.get_thread_id(mock_update)
    assert thread_id == "telegram-123456789"


def test_get_thread_id_invalid_event(telegram_driver: TelegramDriver) -> None:
    """TelegramDriver handles invalid event gracefully."""
    thread_id = telegram_driver.get_thread_id(None)
    assert thread_id.startswith("telegram-unknown-")


def test_get_thread_id_no_message(telegram_driver: TelegramDriver) -> None:
    """TelegramDriver handles Update with no message."""
    update = MagicMock()
    update.message = None
    thread_id = telegram_driver.get_thread_id(update)
    assert thread_id.startswith("telegram-unknown-")


@pytest.mark.asyncio
async def test_start_without_token() -> None:
    """TelegramDriver raises error if no token configured."""
    driver = TelegramDriver(orchestrator=None, config={})
    driver.bot_token = None

    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN not configured"):
        await driver.start()


@pytest.mark.asyncio
async def test_stop_without_start(telegram_driver: TelegramDriver) -> None:
    """TelegramDriver handles stop when not started."""
    # Should not raise
    await telegram_driver.stop()
    assert telegram_driver._running is False


@pytest.mark.asyncio
async def test_receive_message(
    telegram_driver: TelegramDriver, mock_orchestrator: MagicMock
) -> None:
    """TelegramDriver forwards messages to orchestrator."""
    response = await telegram_driver.receive_message(
        thread_id="telegram-123",
        content="Test message",
        metadata={"chat_id": 123},
    )

    assert response == "Test response"
    mock_orchestrator.handle_user_input_v2.assert_called_once()
    call_kwargs = mock_orchestrator.handle_user_input_v2.call_args.kwargs
    assert call_kwargs["text"] == "Test message"
    assert call_kwargs["thread_uuid"] == "telegram-123"


@pytest.mark.asyncio
async def test_receive_message_no_orchestrator() -> None:
    """TelegramDriver returns error when no orchestrator."""
    driver = TelegramDriver(orchestrator=None, config={})
    response = await driver.receive_message(
        thread_id="telegram-123",
        content="Test message",
    )
    assert "trouble processing" in response.lower()


@pytest.mark.asyncio
async def test_receive_message_orchestrator_error(
    telegram_driver: TelegramDriver, mock_orchestrator: MagicMock
) -> None:
    """TelegramDriver handles orchestrator errors gracefully."""
    mock_orchestrator.handle_user_input_v2.side_effect = Exception("API error")

    response = await telegram_driver.receive_message(
        thread_id="telegram-123",
        content="Test message",
    )

    assert "rough waters" in response.lower()


@pytest.mark.asyncio
async def test_cmd_start(telegram_driver: TelegramDriver, mock_update: MagicMock) -> None:
    """TelegramDriver /start command sends welcome message."""
    context = MagicMock()

    await telegram_driver._cmd_start(mock_update, context)

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert "Ahoy" in call_args[0][0]
    assert "Klabautermann" in call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_help(telegram_driver: TelegramDriver, mock_update: MagicMock) -> None:
    """TelegramDriver /help command shows available commands."""
    context = MagicMock()

    await telegram_driver._cmd_help(mock_update, context)

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert "/start" in call_args[0][0]
    assert "/help" in call_args[0][0]
    assert "/status" in call_args[0][0]


@pytest.mark.asyncio
async def test_cmd_status(telegram_driver: TelegramDriver, mock_update: MagicMock) -> None:
    """TelegramDriver /status command shows system status."""
    context = MagicMock()

    await telegram_driver._cmd_status(mock_update, context)

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert "System Status" in call_args[0][0]
    assert "Telegram" in call_args[0][0]
    assert "123456789" in call_args[0][0]  # chat_id


@pytest.mark.asyncio
async def test_on_text_authorized(
    telegram_driver: TelegramDriver,
    mock_update: MagicMock,
    mock_orchestrator: MagicMock,
) -> None:
    """TelegramDriver processes messages from authorized users."""
    telegram_driver.allowed_user_ids = []  # Empty = allow all
    context = MagicMock()

    await telegram_driver._on_text(mock_update, context)

    # Should have sent typing action and reply
    mock_update.message.chat.send_action.assert_called_once_with("typing")
    mock_update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_on_text_unauthorized(
    telegram_driver: TelegramDriver, mock_update: MagicMock
) -> None:
    """TelegramDriver rejects messages from unauthorized users."""
    telegram_driver.allowed_user_ids = [111111]  # Different user
    mock_update.message.from_user.id = 999999  # Not in allowed list
    context = MagicMock()

    await telegram_driver._on_text(mock_update, context)

    # Should have sent rejection message
    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert "don't recognize you" in call_args[0][0].lower()


@pytest.mark.asyncio
async def test_send_message_not_initialized(
    telegram_driver: TelegramDriver,
) -> None:
    """TelegramDriver handles send when app not initialized."""
    # _app is None
    await telegram_driver.send_message(
        thread_id="telegram-123",
        content="Test",
    )
    # Should not raise, just log error


@pytest.mark.asyncio
async def test_send_message_invalid_thread_id(
    telegram_driver: TelegramDriver,
) -> None:
    """TelegramDriver handles invalid thread_id format."""
    telegram_driver._app = MagicMock()

    # Should not raise
    await telegram_driver.send_message(
        thread_id="invalid-format",
        content="Test",
    )


@pytest.mark.asyncio
async def test_on_text_empty_after_sanitization(
    telegram_driver: TelegramDriver, mock_update: MagicMock
) -> None:
    """TelegramDriver rejects empty messages after sanitization."""
    from klabautermann.channels.sanitization import SanitizationResult

    mock_update.message.text = "   "  # Whitespace only
    context = MagicMock()

    # Mock sanitize to return empty result
    empty_result = SanitizationResult(
        original="   ",
        sanitized="",
        modifications=["stripped whitespace"],
        original_length=3,
        sanitized_length=0,
    )

    with patch.object(telegram_driver._sanitizer, "sanitize", return_value=empty_result):
        await telegram_driver._on_text(mock_update, context)

    # Should have sent error message
    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    assert "couldn't understand" in call_args[0][0].lower()
