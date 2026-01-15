"""
CLI driver for Klabautermann.

Provides command-line REPL interface for interacting with the assistant.
Primary development interface for Sprint 1.

Reference: specs/architecture/CHANNELS.md
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

from klabautermann.channels.base_channel import BaseChannel
from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.agents.orchestrator import Orchestrator


class CLIDriver(BaseChannel):
    """
    Command-line interface for Klabautermann.

    Provides an async REPL (Read-Eval-Print Loop) for development
    and direct interaction with the assistant.
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

    @property
    def channel_type(self) -> str:
        """Return channel identifier."""
        return "cli"

    def get_thread_id(self, event: Any = None) -> str:
        """
        Get thread ID for CLI session.

        CLI uses a persistent session ID as the thread identifier,
        allowing conversation persistence across app restarts.
        """
        return f"cli-{self.session_id}"

    async def start(self) -> None:
        """
        Start the CLI REPL loop.

        Runs until user exits or Ctrl+C is pressed.
        """
        self._running = True
        self._print_welcome()

        logger.info(
            "[CHART] CLI session started",
            extra={"agent_name": "cli", "session_id": self.session_id[:8]},
        )

        while self._running:
            try:
                # Get user input asynchronously
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
                    self._print_help()
                    continue

                # Process the message
                response = await self.receive_message(
                    thread_id=self.get_thread_id(),
                    content=user_input,
                )

                # Display the response
                await self.send_message(
                    thread_id=self.get_thread_id(),
                    content=response,
                )

            except KeyboardInterrupt:
                print()  # New line after ^C
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
                print(f"\n[Error] {e}\n")

    async def stop(self) -> None:
        """Stop the CLI gracefully."""
        self._running = False
        print("\nFair winds and following seas, Captain.\n")
        logger.info(
            "[CHART] CLI session ended",
            extra={"agent_name": "cli", "session_id": self.session_id[:8]},
        )

    async def send_message(
        self,
        thread_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Display message to user.

        Args:
            thread_id: Thread identifier (not used in CLI display).
            content: Message content to display.
            metadata: Optional metadata (not used in CLI).
        """
        print(f"\n{content}\n")

    async def receive_message(
        self,
        thread_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Process incoming message from user.

        Forwards to orchestrator and returns response.

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

    def _print_welcome(self) -> None:
        """Display welcome message."""
        welcome = """
================================================================================
                         KLABAUTERMANN v0.1.0
                        Your Personal Navigator
================================================================================

  Ahoy, Captain! Your ship spirit is ready to assist.

  Commands:
    Type your message and press Enter to chat
    'help'  - Show available commands
    'exit'  - Leave the ship

================================================================================
"""
        print(welcome)

    def _print_help(self) -> None:
        """Display help message."""
        help_text = """
  Available Commands:
  -------------------
  [message]  - Chat with Klabautermann
  help       - Show this help
  exit/quit  - End the session

  Tips:
  -----
  - Tell me about people you meet: "I met Sarah from Acme Corp"
  - Share your projects: "I'm working on Project Lighthouse"
  - Ask questions: "What do I know about Sarah?"

  Note: Full memory search and action execution coming in Sprint 2!
"""
        print(help_text)

    async def _async_input(self, prompt: str) -> str:
        """
        Async wrapper for blocking input().

        Uses run_in_executor to avoid blocking the event loop.

        Args:
            prompt: Input prompt to display.

        Returns:
            User input string, stripped of whitespace.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: input(prompt).strip())


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["CLIDriver"]
