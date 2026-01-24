"""
Telegram driver for Klabautermann.

Provides Telegram bot interface for interacting with the assistant.
Supports text messages, commands, and voice message transcription.

Reference: specs/architecture/CHANNELS.md Section 3
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from klabautermann.channels.base_channel import BaseChannel
from klabautermann.channels.markdown_formatter import escape_markdown
from klabautermann.channels.sanitization import InputSanitizer
from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from telegram import Update

    from klabautermann.agents.orchestrator import Orchestrator


class TelegramDriver(BaseChannel):
    """
    Telegram bot driver using python-telegram-bot.

    Provides mobile access with support for:
    - Text messages
    - Bot commands (/start, /help, /status)
    - Voice message transcription (requires OpenAI Whisper)

    Thread isolation: Each chat_id maps to a unique thread UUID.
    """

    def __init__(
        self,
        orchestrator: Orchestrator | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize Telegram driver.

        Args:
            orchestrator: Orchestrator agent to forward messages to.
            config: Channel configuration with optional keys:
                - bot_token: Telegram bot token (or use TELEGRAM_BOT_TOKEN env)
                - allowed_user_ids: List of allowed user IDs (empty = allow all)
                - enable_voice: Whether to handle voice messages (default True)
        """
        super().__init__(orchestrator, config)
        self.bot_token = self.config.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
        self.allowed_user_ids: list[int] = self.config.get("allowed_user_ids", [])
        self.enable_voice: bool = self.config.get("enable_voice", True)
        self._app: Application | None = None
        self._running = False
        self._sanitizer = InputSanitizer()

    async def _safe_reply(
        self,
        message: Any,
        text: str,
        use_markdown: bool = True,
    ) -> None:
        """
        Send a reply with Markdown, falling back to plain text on error.

        Args:
            message: Telegram Message object to reply to.
            text: Response text.
            use_markdown: Whether to attempt Markdown formatting.

        Issue: #139
        """
        if not use_markdown:
            await message.reply_text(text)
            return

        formatted_text = escape_markdown(text)
        try:
            await message.reply_text(formatted_text, parse_mode="Markdown")
        except Exception as e:
            error_msg = str(e).lower()
            if "parse" in error_msg or "markdown" in error_msg or "can't" in error_msg:
                logger.warning(
                    f"[SWELL] Markdown parsing failed in reply, sending plain: {e}",
                    extra={"agent_name": "telegram"},
                )
                await message.reply_text(text)
            else:
                raise

    @property
    def channel_type(self) -> str:
        """Return channel identifier."""
        return "telegram"

    def get_thread_id(self, event: Any) -> str:
        """
        Extract thread ID from Telegram Update.

        Uses chat_id as the thread identifier, prefixed with 'telegram-'.

        Args:
            event: Telegram Update object.

        Returns:
            Thread identifier in format 'telegram-{chat_id}'.
        """
        # Check for message attribute (works with real Update and mocks)
        if (
            event is not None
            and hasattr(event, "message")
            and event.message is not None
            and hasattr(event.message, "chat_id")
        ):
            return f"telegram-{event.message.chat_id}"
        return f"telegram-unknown-{uuid.uuid4().hex[:8]}"

    async def start(self) -> None:
        """
        Initialize and start the Telegram bot.

        Starts polling for updates (no webhooks needed).

        Raises:
            ValueError: If TELEGRAM_BOT_TOKEN is not configured.
        """
        if not self.bot_token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN not configured. " "Set it in .env or pass bot_token in config."
            )

        logger.info(
            "[CHART] Starting Telegram driver...",
            extra={"agent_name": "telegram"},
        )

        # Build application
        self._app = Application.builder().token(self.bot_token).build()

        # Add command handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("status", self._cmd_status))

        # Add message handlers
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

        if self.enable_voice:
            self._app.add_handler(MessageHandler(filters.VOICE, self._on_voice))

        # Initialize and start polling
        await self._app.initialize()
        await self._app.start()
        if self._app.updater:
            await self._app.updater.start_polling(drop_pending_updates=True)

        self._running = True

        logger.info(
            "[BEACON] Telegram driver started successfully",
            extra={"agent_name": "telegram"},
        )

    async def stop(self) -> None:
        """Stop the Telegram bot gracefully."""
        self._running = False

        if self._app:
            if self._app.updater:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

        logger.info(
            "[CHART] Telegram driver stopped",
            extra={"agent_name": "telegram"},
        )

    async def send_message(
        self,
        thread_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> None:
        """
        Send a message to a Telegram chat.

        Args:
            thread_id: Thread ID in format 'telegram-{chat_id}'.
            content: Message content to send.
            metadata: Optional metadata (unused, for interface compatibility).
        """
        if not self._app:
            logger.error(
                "[STORM] Cannot send message: Telegram app not initialized",
                extra={"agent_name": "telegram"},
            )
            return

        # Extract chat_id from thread_id
        chat_id_str = thread_id.replace("telegram-", "")
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            logger.error(
                f"[STORM] Invalid thread_id format: {thread_id}",
                extra={"agent_name": "telegram"},
            )
            return

        # Format content for Telegram Markdown and send with fallback (#139)
        formatted_content = escape_markdown(content)
        try:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=formatted_content,
                parse_mode="Markdown",
            )
        except Exception as e:
            # Fallback to plain text if Markdown parsing fails
            error_msg = str(e).lower()
            if "parse" in error_msg or "markdown" in error_msg or "can't" in error_msg:
                logger.warning(
                    f"[SWELL] Markdown parsing failed, sending as plain text: {e}",
                    extra={"agent_name": "telegram", "chat_id": chat_id},
                )
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=content,  # Send original without parse_mode
                )
            else:
                raise

    async def receive_message(
        self,
        thread_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> str:
        """
        Process an incoming message from Telegram.

        Args:
            thread_id: Thread ID for the conversation.
            content: Message content.
            metadata: Optional channel-specific metadata (unused, for interface compatibility).

        Returns:
            Response content from the orchestrator.
        """
        if not self._orchestrator:
            return "I'm having trouble processing that right now. Please try again later."

        # Generate trace ID
        trace_id = f"tg-{uuid.uuid4().hex[:12]}"

        try:
            # Forward to orchestrator
            response = await self._orchestrator.handle_user_input_v2(
                text=content,
                thread_uuid=thread_id,
                trace_id=trace_id,
            )
            return response
        except Exception as e:
            logger.error(
                f"[STORM] Orchestrator error: {e}",
                extra={"agent_name": "telegram", "trace_id": trace_id},
            )
            return "Hit some rough waters processing that. Please try again."

    # =========================================================================
    # Command Handlers
    # =========================================================================

    async def _cmd_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,  # noqa: ARG002
    ) -> None:
        """Handle /start command - welcome message."""
        if not update.message:
            return

        welcome = (
            "*Ahoy, Captain!*\n\n"
            "I'm Klabautermann, your personal navigator through the information storm.\n\n"
            "Tell me about people you meet, projects you're working on, "
            "or ask me to find something in The Locker (your knowledge graph).\n\n"
            "Type /help for more information."
        )
        await self._safe_reply(update.message, welcome)

        logger.info(
            "[CHART] /start command received",
            extra={
                "agent_name": "telegram",
                "chat_id": update.message.chat_id,
                "user_id": update.message.from_user.id if update.message.from_user else None,
            },
        )

    async def _cmd_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,  # noqa: ARG002
    ) -> None:
        """Handle /help command - show available commands."""
        if not update.message:
            return

        help_text = (
            "*Available Commands:*\n\n"
            "/start - Welcome message\n"
            "/help - Show this help\n"
            "/status - System status\n\n"
            "*What I can do:*\n\n"
            "- Remember people, projects, and events you tell me about\n"
            "- Search your knowledge graph for information\n"
            "- Draft emails and create calendar events\n"
            "- Transcribe voice messages\n\n"
            "Just chat naturally - I'll figure out the rest!"
        )
        await self._safe_reply(update.message, help_text)

    async def _cmd_status(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,  # noqa: ARG002
    ) -> None:
        """Handle /status command - show system status."""
        if not update.message:
            return

        chat_id = update.message.chat_id
        user = update.message.from_user
        user_id = user.id if user else "unknown"
        username = user.username if user and user.username else "N/A"

        status = (
            "*System Status:*\n\n"
            f"- Channel: Telegram\n"
            f"- Chat ID: `{chat_id}`\n"
            f"- User ID: `{user_id}`\n"
            f"- Username: @{username}\n"
            f"- Status: Online\n"
            f"- Voice: {'Enabled' if self.enable_voice else 'Disabled'}"
        )
        await self._safe_reply(update.message, status)

    # =========================================================================
    # Message Handlers
    # =========================================================================

    async def _on_text(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,  # noqa: ARG002
    ) -> None:
        """Handle incoming text messages."""
        if not update.message or not update.message.text:
            return

        user = update.message.from_user
        user_id = user.id if user else 0

        # Check authorization if configured
        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            await update.message.reply_text("Sorry, I don't recognize you. This bot is private.")
            logger.warning(
                f"[SWELL] Unauthorized access attempt from user {user_id}",
                extra={"agent_name": "telegram", "user_id": user_id},
            )
            return

        # Show typing indicator
        await update.message.chat.send_action("typing")

        # Sanitize input
        sanitize_result = self._sanitizer.sanitize(update.message.text)
        content = sanitize_result.sanitized
        if not content:
            await update.message.reply_text("I couldn't understand that message. Please try again.")
            return

        # Get thread ID
        thread_id = self.get_thread_id(update)

        logger.info(
            f"[CHART] Text message received: {content[:50]}...",
            extra={
                "agent_name": "telegram",
                "chat_id": update.message.chat_id,
                "user_id": user_id,
                "thread_id": thread_id,
            },
        )

        # Process message
        try:
            response = await self.receive_message(
                thread_id=thread_id,
                content=content,
                metadata={
                    "chat_id": update.message.chat_id,
                    "user_id": user_id,
                    "timestamp": datetime.now(UTC).timestamp(),
                },
            )
            await self._safe_reply(update.message, response)
        except Exception as e:
            logger.error(
                f"[STORM] Error processing text message: {e}",
                extra={"agent_name": "telegram"},
            )
            await update.message.reply_text(
                "Hit some rough waters processing that. Please try again."
            )

    async def _on_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming voice messages."""
        if not update.message or not update.message.voice:
            return

        user = update.message.from_user
        user_id = user.id if user else 0

        # Check authorization
        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            await update.message.reply_text("Sorry, I don't recognize you. This bot is private.")
            return

        await update.message.chat.send_action("typing")

        # Download and transcribe voice
        try:
            voice = update.message.voice
            file = await context.bot.get_file(voice.file_id)

            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
                await file.download_to_drive(f.name)
                audio_path = f.name

            # Transcribe using Whisper
            transcription = await self._transcribe_audio(audio_path)

            # Clean up temp file
            Path(audio_path).unlink()

            if not transcription:
                await update.message.reply_text("Couldn't make out what you said. Try again?")
                return

            # Process as text message
            thread_id = self.get_thread_id(update)
            response = await self.receive_message(
                thread_id=thread_id,
                content=transcription,
                metadata={
                    "chat_id": update.message.chat_id,
                    "user_id": user_id,
                    "original_type": "voice",
                    "transcription": transcription,
                    "duration": voice.duration,
                },
            )
            voice_response = f"_Transcribed: {transcription}_\n\n{response}"
            await self._safe_reply(update.message, voice_response)

        except Exception as e:
            logger.error(
                f"[STORM] Voice processing error: {e}",
                extra={"agent_name": "telegram"},
            )
            await update.message.reply_text(
                "Had trouble with that voice message. Try typing instead?"
            )

    async def _transcribe_audio(self, audio_path: str) -> str | None:
        """
        Transcribe audio using OpenAI Whisper.

        Args:
            audio_path: Path to the audio file.

        Returns:
            Transcription text or None if failed.
        """
        try:
            import openai

            client = openai.AsyncOpenAI()
            with Path(audio_path).open("rb") as audio_file:
                transcript = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                )
            return str(transcript.text)
        except Exception as e:
            logger.error(
                f"[STORM] Whisper transcription failed: {e}",
                extra={"agent_name": "telegram"},
            )
            return None


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["TelegramDriver"]
