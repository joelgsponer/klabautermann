# Implement CLI Driver

## Metadata
- **ID**: T014
- **Priority**: P1
- **Category**: channel
- **Effort**: M
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [CHANNELS.md](../../specs/architecture/CHANNELS.md)
- Related: [PERSONALITY.md](../../specs/branding/PERSONALITY.md)

## Dependencies
- [ ] T013 - Base channel interface

## Context
The CLI driver is the primary development interface for Sprint 1. It provides an async REPL (Read-Eval-Print Loop) for interacting with Klabautermann from the command line.

## Requirements
- [ ] Create `src/klabautermann/channels/cli_driver.py` with:

### CLIDriver Class (extends BaseChannel)
- [ ] Implement `start()` - Begin REPL loop
- [ ] Implement `stop()` - Clean shutdown with message
- [ ] Implement `send_message()` - Print to stdout
- [ ] Implement `receive_message()` - Forward to orchestrator
- [ ] Implement `get_thread_id()` - Return session identifier

### REPL Features
- [ ] Async input handling
- [ ] Graceful exit on Ctrl+C / "exit" / "quit"
- [ ] Welcome message on start
- [ ] Prompt with nautical theme (e.g., "> ")
- [ ] Input history (optional for Sprint 1)

### Session Management
- [ ] Generate unique session ID on start
- [ ] Use session ID as thread external_id
- [ ] Support session persistence (via thread manager)

## Acceptance Criteria
- [ ] `python main.py` starts CLI with welcome message
- [ ] User can type messages and receive responses
- [ ] "exit" or "quit" cleanly stops the CLI
- [ ] Ctrl+C triggers graceful shutdown
- [ ] Each CLI session has a consistent thread ID

## Implementation Notes

```python
import asyncio
import sys
import uuid
from typing import Optional, Dict, Any

from klabautermann.channels.base_channel import BaseChannel
from klabautermann.core.logger import logger


class CLIDriver(BaseChannel):
    """Command-line interface for Klabautermann."""

    def __init__(self, orchestrator: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(orchestrator, config)
        self.session_id = str(uuid.uuid4())
        self._running = False

    @property
    def channel_type(self) -> str:
        return "cli"

    def get_thread_id(self, event: Any = None) -> str:
        """CLI uses session ID as thread identifier."""
        return f"cli-{self.session_id}"

    async def start(self) -> None:
        """Start the CLI REPL loop."""
        self._running = True
        self._print_welcome()

        while self._running:
            try:
                # Async input handling
                user_input = await self._async_input("> ")

                if not user_input:
                    continue

                # Check for exit commands
                if user_input.lower() in ("exit", "quit", "/quit", "/exit"):
                    await self.stop()
                    break

                # Process the message
                response = await self.receive_message(
                    thread_id=self.get_thread_id(),
                    content=user_input,
                )

                # Send the response
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
                logger.error(f"[STORM] CLI error: {e}")
                print(f"\nError: {e}\n")

    async def stop(self) -> None:
        """Stop the CLI gracefully."""
        self._running = False
        print("\nFair winds and following seas, Captain.\n")
        logger.info("[CHART] CLI session ended")

    async def send_message(
        self,
        thread_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Print message to stdout."""
        print(f"\n{content}\n")

    async def receive_message(
        self,
        thread_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Forward message to orchestrator and return response."""
        response = await self.orchestrator.handle_user_input(
            thread_id=thread_id,
            text=content,
        )
        return response

    def _print_welcome(self) -> None:
        """Print welcome message."""
        welcome = """
=====================================
     KLABAUTERMANN v0.1
     Your Personal Navigator
=====================================

Type your message, or 'exit' to quit.
"""
        print(welcome)

    async def _async_input(self, prompt: str) -> str:
        """Async wrapper for input()."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: input(prompt).strip())
```

Note: For Sprint 1, input history is optional. Consider adding `readline` support in a future enhancement.
