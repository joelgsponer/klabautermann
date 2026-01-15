"""
CLI driver for Klabautermann.

Provides command-line REPL interface for interacting with the assistant.
Primary development interface for Sprint 1.

Features:
- Rich markdown rendering for responses
- Progress spinners during LLM processing
- Command history with up/down arrow navigation
- Styled prompts and output

Reference: specs/architecture/CHANNELS.md
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from klabautermann.channels.base_channel import BaseChannel
from klabautermann.channels.cli_renderer import CLIRenderer
from klabautermann.core.logger import (
    logger,
    restore_console_logging,
    suppress_console_logging,
)


# Track log visibility state
_logs_visible = True


if TYPE_CHECKING:
    from klabautermann.agents.orchestrator import Orchestrator


# History file location
HISTORY_DIR = Path.home() / ".klabautermann"
HISTORY_FILE = HISTORY_DIR / "cli_history"


class CLIDriver(BaseChannel):
    """
    Command-line interface for Klabautermann.

    Provides an async REPL (Read-Eval-Print Loop) for development
    and direct interaction with the assistant.

    Features:
    - Rich markdown rendering for AI responses
    - Progress spinners during processing
    - Command history (up/down arrows)
    - Styled nautical-themed output
    """

    def __init__(
        self,
        orchestrator: Orchestrator | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize CLI driver.

        Args:
            orchestrator: Orchestrator agent to forward messages to.
            config: Channel configuration.
        """
        super().__init__(orchestrator, config)
        self.session_id = str(uuid.uuid4())
        self._running = False
        self.renderer = CLIRenderer()
        self._prompt_session: PromptSession[str] | None = None

    @property
    def channel_type(self) -> str:
        """Return channel identifier."""
        return "cli"

    def get_thread_id(self, _event: Any = None) -> str:
        """
        Get thread ID for CLI session.

        CLI uses a persistent session ID as the thread identifier,
        allowing conversation persistence across app restarts.
        """
        return f"cli-{self.session_id}"

    def _ensure_history_dir(self) -> None:
        """Ensure history directory exists."""
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    def _create_prompt_session(self) -> PromptSession[str]:
        """Create prompt session with history support."""
        self._ensure_history_dir()
        return PromptSession(
            history=FileHistory(str(HISTORY_FILE)),
        )

    async def start(self) -> None:
        """
        Start the CLI REPL loop.

        Runs until user exits or Ctrl+C is pressed.
        """
        self._running = True
        self._prompt_session = self._create_prompt_session()

        # Display welcome banner
        self.renderer.render_banner()

        logger.info(
            "[CHART] CLI session started",
            extra={"agent_name": "cli", "session_id": self.session_id[:8]},
        )

        while self._running:
            try:
                # Get user input with history support
                user_input = await self._async_input("> ")

                # Skip empty input
                if not user_input:
                    continue

                # Check for exit commands
                if user_input.lower() in ("exit", "quit", "/quit", "/exit", "q"):
                    await self.stop()
                    break

                # Check for help command
                if user_input.lower() in ("help", "/help", "?"):
                    self.renderer.render_help()
                    continue

                # Check for clear command
                if user_input.lower() in ("/clear", "clear"):
                    self.renderer.clear()
                    self.renderer.render_banner()
                    continue

                # Check for logs toggle command
                if user_input.lower() in ("/logs", "/log"):
                    global _logs_visible
                    _logs_visible = not _logs_visible
                    if _logs_visible:
                        restore_console_logging()
                        self.renderer.render_info("Logs enabled")
                    else:
                        suppress_console_logging()
                        self.renderer.render_info("Logs disabled")
                    continue

                # Process the message with spinner
                response = await self.receive_message(
                    thread_id=self.get_thread_id(),
                    content=user_input,
                )

                # Display the response with markdown rendering
                await self.send_message(
                    thread_id=self.get_thread_id(),
                    content=response,
                )

            except KeyboardInterrupt:
                await self.stop()
                break
            except EOFError:
                await self.stop()
                break
            except Exception as e:
                logger.error(
                    f"[STORM] CLI error: {e}",
                    extra={"agent_name": "cli"},
                    exc_info=True,
                )
                self.renderer.render_error(str(e))

    async def stop(self) -> None:
        """Stop the CLI gracefully."""
        self._running = False
        self.renderer.render_farewell()
        logger.info(
            "[CHART] CLI session ended",
            extra={"agent_name": "cli", "session_id": self.session_id[:8]},
        )

    async def send_message(
        self,
        thread_id: str,  # noqa: ARG002
        content: str,
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> None:
        """
        Display message to user with markdown rendering.

        Args:
            thread_id: Thread identifier (not used in CLI display).
            content: Message content to display (may contain markdown).
            metadata: Optional metadata (not used in CLI).
        """
        self.renderer.render_response(content)

    async def receive_message(
        self,
        thread_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> str:
        """
        Process incoming message from user.

        Forwards to orchestrator with progress spinner and returns response.

        Args:
            thread_id: Thread identifier.
            content: User's message content.
            metadata: Optional metadata.

        Returns:
            Response from orchestrator.
        """
        if not self._orchestrator:
            return "[Error] Orchestrator not initialized."

        try:
            # Show spinner during processing
            with self.renderer.spinner("Charting course..."):
                response = await self._orchestrator.handle_user_input(
                    thread_id=thread_id,
                    text=content,
                )
            return response
        except Exception as e:
            logger.error(
                f"[STORM] Error processing message: {e}",
                extra={"agent_name": "cli"},
            )
            return f"I've hit some rough waters: {e}"

    async def _async_input(self, prompt: str) -> str:
        """
        Async wrapper for prompt_toolkit input with history support.

        Uses run_in_executor to avoid blocking the event loop.

        Args:
            prompt: Input prompt to display.

        Returns:
            User input string, stripped of whitespace.
        """
        if self._prompt_session is None:
            self._prompt_session = self._create_prompt_session()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._prompt_session.prompt(prompt).strip(),  # type: ignore[union-attr]
        )


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["CLIDriver"]
