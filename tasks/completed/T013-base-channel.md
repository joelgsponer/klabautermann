# Create Base Channel Interface

## Metadata
- **ID**: T013
- **Priority**: P1
- **Category**: channel
- **Effort**: S
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [CHANNELS.md](../../specs/architecture/CHANNELS.md)
- Related: [PRD.md](../../specs/PRD.md) Section 5

## Dependencies
- [ ] T003 - Project directory structure

## Context
Klabautermann supports multiple communication channels (CLI, Telegram, Discord). The base channel interface defines the contract that all channel implementations must follow, enabling a pluggable architecture.

## Requirements
- [ ] Create `src/klabautermann/channels/base_channel.py` with:

### BaseChannel Abstract Class
- [ ] Abstract `start()` method - Begin listening for input
- [ ] Abstract `stop()` method - Clean shutdown
- [ ] Abstract `send_message()` method - Send response to user
- [ ] Abstract `receive_message()` method - Handle incoming message
- [ ] Property `channel_type` - Return channel identifier string

### Channel Configuration
- [ ] Accept orchestrator reference on init
- [ ] Accept optional configuration dict
- [ ] Store channel-specific metadata

### Thread Mapping
- [ ] Abstract `get_thread_id()` - Map channel event to thread ID
- [ ] This enables channel-specific thread identification (chat_id, session_id)

## Acceptance Criteria
- [ ] `BaseChannel` is abstract (cannot be instantiated directly)
- [ ] All abstract methods are defined with proper signatures
- [ ] Subclasses must implement all abstract methods
- [ ] Type hints on all methods

## Implementation Notes

```python
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from klabautermann.core.models import AgentMessage


class BaseChannel(ABC):
    """
    Abstract base class for communication channels.

    All channel implementations (CLI, Telegram, Discord) must inherit
    from this class and implement the abstract methods.
    """

    def __init__(
        self,
        orchestrator: Any,  # Type hint as Any to avoid circular import
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the channel.

        Args:
            orchestrator: The Orchestrator agent to send messages to.
            config: Channel-specific configuration.
        """
        self.orchestrator = orchestrator
        self.config = config or {}

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Return the channel type identifier (e.g., 'cli', 'telegram')."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """
        Start the channel and begin listening for input.

        This method should run until stop() is called or an error occurs.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the channel gracefully.

        Clean up resources and close connections.
        """
        pass

    @abstractmethod
    async def send_message(
        self,
        thread_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a message to the user.

        Args:
            thread_id: The thread/conversation identifier.
            content: The message content to send.
            metadata: Optional channel-specific metadata.
        """
        pass

    @abstractmethod
    async def receive_message(
        self,
        thread_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
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
        pass

    @abstractmethod
    def get_thread_id(self, event: Any) -> str:
        """
        Extract the thread ID from a channel-specific event.

        Args:
            event: Channel-specific event object.

        Returns:
            Thread identifier string.
        """
        pass
```

The CLI driver (T014) and future Telegram driver (Sprint 4) will both inherit from this class.
