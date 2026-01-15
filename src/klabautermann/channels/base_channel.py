"""
Base channel interface for Klabautermann.

Defines the contract that all communication channels must follow.
Supports pluggable architecture for CLI, Telegram, Discord, etc.

Reference: specs/architecture/CHANNELS.md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from klabautermann.agents.orchestrator import Orchestrator


class BaseChannel(ABC):
    """
    Abstract base class for communication channels.

    All channel implementations (CLI, Telegram, Discord) must inherit
    from this class and implement the abstract methods.
    """

    def __init__(
        self,
        orchestrator: Orchestrator | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the channel.

        Args:
            orchestrator: The Orchestrator agent to send messages to.
            config: Channel-specific configuration.
        """
        self._orchestrator = orchestrator
        self.config = config or {}

    @property
    def orchestrator(self) -> Orchestrator | None:
        """Get the orchestrator."""
        return self._orchestrator

    @orchestrator.setter
    def orchestrator(self, value: Orchestrator) -> None:
        """Set the orchestrator (for deferred initialization)."""
        self._orchestrator = value

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """
        Return the channel type identifier.

        Examples: 'cli', 'telegram', 'discord'
        """
        ...

    @abstractmethod
    async def start(self) -> None:
        """
        Start the channel and begin listening for input.

        This method should run until stop() is called or an error occurs.
        Implementations should handle their own event loops.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the channel gracefully.

        Clean up resources, close connections, and notify the user.
        """
        ...

    @abstractmethod
    async def send_message(
        self,
        thread_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Send a message to the user.

        Args:
            thread_id: The thread/conversation identifier.
            content: The message content to send.
            metadata: Optional channel-specific metadata.
        """
        ...

    @abstractmethod
    async def receive_message(
        self,
        thread_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Process an incoming message from the user.

        This method should:
        1. Forward the message to the orchestrator
        2. Wait for the response
        3. Return the response content

        Args:
            thread_id: The thread/conversation identifier.
            content: The incoming message content.
            metadata: Optional channel-specific metadata.

        Returns:
            The response content from the orchestrator.
        """
        ...

    @abstractmethod
    def get_thread_id(self, event: Any) -> str:
        """
        Extract the thread ID from a channel-specific event.

        Each channel has its own way of identifying conversations:
        - CLI: session ID
        - Telegram: chat_id
        - Discord: channel_id

        Args:
            event: Channel-specific event object.

        Returns:
            Thread identifier string.
        """
        ...


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["BaseChannel"]
