"""
CLI driver for Klabautermann.

Provides command-line REPL interface for interacting with the assistant.
Primary development interface for Sprint 1.

Features:
- Rich markdown rendering for responses
- Progress spinners during LLM processing
- Command history with up/down arrow navigation
- Styled prompts and output
- Message export to neovim buffer for headless environments

Reference: specs/architecture/CHANNELS.md
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout

from klabautermann.channels.base_channel import BaseChannel
from klabautermann.channels.cli_renderer import CLIRenderer
from klabautermann.channels.sanitization import InputSanitizer
from klabautermann.core.logger import (
    logger,
    restore_console_logging,
    suppress_console_logging,
)


@dataclass
class ChatMessage:
    """Represents a chat message in the conversation history."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime


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
        self._message_count = 0
        self._sanitizer = InputSanitizer()
        self._message_history: list[ChatMessage] = []
        # Check for NO_SPINNER env var to disable animated spinner
        import os

        no_spinner = os.getenv("KLABAUTERMANN_NO_SPINNER", "").lower() in ("1", "true", "yes")
        self.renderer = CLIRenderer(no_spinner=no_spinner)
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

        # patch_stdout wraps ENTIRE REPL - logs always appear above prompt
        with patch_stdout():
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

                    # Check for clear command - resets session context
                    if user_input.lower() in ("/clear", "clear"):
                        old_session = self.session_id[:8]
                        self.session_id = str(uuid.uuid4())
                        self._message_count = 0
                        self.renderer.clear()
                        self.renderer.render_banner()
                        self.renderer.render_info(
                            f"Session reset. Old: {old_session}... → New: {self.session_id[:8]}..."
                        )
                        logger.info(
                            f"[CHART] Session reset: {old_session} -> {self.session_id[:8]}",
                            extra={"agent_name": "cli"},
                        )
                        continue

                    # Check for status command
                    if user_input.lower() in ("/status", "status"):
                        is_connected = self._orchestrator is not None
                        agent_status = "ready" if is_connected else "offline"
                        self.renderer.render_status(
                            session_id=self.session_id,
                            thread_id=self.get_thread_id(),
                            is_connected=is_connected,
                            agent_status=agent_status,
                            thread_count=1 if is_connected else 0,
                            message_count=self._message_count,
                        )
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

                    # Check for copy/export command
                    copy_match = re.match(
                        r"^/(?:copy|export)(?:\s+(\d+))?(?:\s+--format=(\w+))?$",
                        user_input.lower(),
                    )
                    if copy_match:
                        count = int(copy_match.group(1) or 1)
                        format_type = copy_match.group(2) or "markdown"
                        await self._handle_copy_command(count, format_type)
                        continue

                    # Echo user input with distinct styling
                    self.renderer.render_user_input(user_input)

                    # Track user message in history
                    self._message_history.append(
                        ChatMessage(role="user", content=user_input, timestamp=datetime.now())
                    )

                    # Process the message with spinner
                    response = await self.receive_message(
                        thread_id=self.get_thread_id(),
                        content=user_input,
                    )

                    # Track assistant response in history
                    self._message_history.append(
                        ChatMessage(role="assistant", content=response, timestamp=datetime.now())
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
        Sanitizes input before processing for security.

        Args:
            thread_id: Thread identifier.
            content: User's message content.
            metadata: Optional metadata.

        Returns:
            Response from orchestrator.
        """
        if not self._orchestrator:
            return "[Error] Orchestrator not initialized."

        # Sanitize input before processing
        trace_id = f"cli-{self.session_id[:8]}"
        sanitized_content = self._sanitizer.sanitize_message(content, trace_id=trace_id)
        sanitized_thread_id = self._sanitizer.sanitize_thread_id(thread_id, trace_id=trace_id)

        try:
            # Increment message count
            self._message_count += 1

            # Show spinner during processing
            with self.renderer.spinner("Charting course..."):
                response = await self._orchestrator.handle_user_input(
                    thread_id=sanitized_thread_id,
                    text=sanitized_content,
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
        Get user input asynchronously.

        Note: patch_stdout() is handled by the REPL loop in start().

        Args:
            prompt: Input prompt to display.

        Returns:
            User input string, stripped of whitespace.
        """
        if self._prompt_session is None:
            self._prompt_session = self._create_prompt_session()

        result: str = (await self._prompt_session.prompt_async(prompt)).strip()
        return result

    async def _handle_copy_command(
        self,
        count: int = 1,
        format_type: str = "markdown",
    ) -> None:
        """
        Handle the /copy command to export messages.

        Args:
            count: Number of recent messages to export
            format_type: Output format (markdown, plain, json)
        """
        if not self._message_history:
            self.renderer.render_info("No messages to copy.")
            return

        # Get the last N messages
        messages = self._message_history[-count:]

        if not messages:
            self.renderer.render_info("No messages to copy.")
            return

        # Format the messages
        content = self._format_messages(messages, format_type)

        # Try to export to neovim or fallback options
        if self._export_to_neovim(content, format_type):
            self.renderer.render_info(f"Exported {len(messages)} message(s) to neovim buffer")
        elif self._try_clipboard(content):
            self.renderer.render_info(f"Copied {len(messages)} message(s) to clipboard")
        else:
            # Fallback: write to temp file and display path
            temp_path = self._export_to_file(content, format_type)
            self.renderer.render_info(f"Exported {len(messages)} message(s) to {temp_path}")

    def _format_messages(
        self,
        messages: list[ChatMessage],
        format_type: str = "markdown",
    ) -> str:
        """
        Format messages for export.

        Args:
            messages: Messages to format
            format_type: Output format (markdown, plain, json)

        Returns:
            Formatted content string
        """
        if format_type == "json":
            import json

            return json.dumps(
                [
                    {
                        "role": m.role,
                        "content": m.content,
                        "timestamp": m.timestamp.isoformat(),
                    }
                    for m in messages
                ],
                indent=2,
            )

        if format_type == "plain":
            parts = []
            for msg in messages:
                role_label = "You" if msg.role == "user" else "Klabautermann"
                parts.append(f"[{role_label}] {msg.content}")
            return "\n\n".join(parts)

        # Default: markdown format
        parts = []
        for msg in messages:
            role_label = "User" if msg.role == "user" else "Assistant"
            timestamp_str = msg.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            parts.append(f"## {role_label} ({timestamp_str})\n\n{msg.content}")
        return "\n\n---\n\n".join(parts)

    def _export_to_neovim(self, content: str, format_type: str = "markdown") -> bool:
        """
        Export content to a neovim buffer.

        Args:
            content: Content to export
            format_type: Format type for file extension

        Returns:
            True if successful, False otherwise
        """
        # Check if neovim is available
        if not shutil.which("nvim"):
            return False

        # Determine file extension
        ext_map = {"markdown": ".md", "plain": ".txt", "json": ".json"}
        ext = ext_map.get(format_type, ".md")

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=ext, delete=False, prefix="klabautermann_export_"
        ) as f:
            f.write(content)
            temp_path = f.name

        try:
            # Open in neovim (works over SSH without X11)
            subprocess.run(["nvim", temp_path], check=False)
            return True
        except Exception as e:
            logger.debug(f"[WHISPER] Failed to open neovim: {e}")
            return False

    def _try_clipboard(self, content: str) -> bool:
        """
        Try to copy content to system clipboard.

        Args:
            content: Content to copy

        Returns:
            True if successful, False otherwise
        """
        # Try xclip (Linux with X11)
        if shutil.which("xclip"):
            try:
                process = subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=content.encode(),
                    check=True,
                    capture_output=True,
                )
                return process.returncode == 0
            except Exception:
                pass

        # Try pbcopy (macOS)
        if shutil.which("pbcopy"):
            try:
                process = subprocess.run(
                    ["pbcopy"],
                    input=content.encode(),
                    check=True,
                    capture_output=True,
                )
                return process.returncode == 0
            except Exception:
                pass

        # Try wl-copy (Wayland)
        if shutil.which("wl-copy"):
            try:
                process = subprocess.run(
                    ["wl-copy"],
                    input=content.encode(),
                    check=True,
                    capture_output=True,
                )
                return process.returncode == 0
            except Exception:
                pass

        return False

    def _export_to_file(self, content: str, format_type: str = "markdown") -> str:
        """
        Export content to a file (fallback option).

        Args:
            content: Content to export
            format_type: Format type for file extension

        Returns:
            Path to the exported file
        """
        ext_map = {"markdown": ".md", "plain": ".txt", "json": ".json"}
        ext = ext_map.get(format_type, ".md")

        # Create export directory if it doesn't exist
        export_dir = HISTORY_DIR / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = export_dir / f"conversation_{timestamp}{ext}"

        with filepath.open("w") as f:
            f.write(content)

        return str(filepath)


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["CLIDriver"]
