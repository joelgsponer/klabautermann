"""
Graceful shutdown management for Klabautermann.

Coordinates orderly shutdown of all system components with:
- Reverse-order component shutdown
- Pending message draining
- Timeout handling
- Detailed status logging

Reference: Issue #152, specs/architecture/CHANNELS.md Section 5.2
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from klabautermann.agents.base_agent import BaseAgent
    from klabautermann.channels.base_channel import BaseChannel


class ShutdownPhase(Enum):
    """Phases of the shutdown process."""

    INITIATED = "initiated"
    CHANNELS_STOPPING = "channels_stopping"
    DRAINING_QUEUES = "draining_queues"
    AGENTS_STOPPING = "agents_stopping"
    CLIENTS_DISCONNECTING = "clients_disconnecting"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ShutdownStatus:
    """Status of a component during shutdown."""

    component_name: str
    component_type: str  # "channel", "agent", "client"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    success: bool = False
    error: str | None = None
    pending_items: int = 0

    @property
    def duration_ms(self) -> float | None:
        """Get duration in milliseconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None


@dataclass
class ShutdownResult:
    """Result of the shutdown process."""

    success: bool
    phase: ShutdownPhase
    started_at: datetime
    completed_at: datetime | None = None
    component_statuses: list[ShutdownStatus] = field(default_factory=list)
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        """Get total duration in milliseconds."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None

    def summary(self) -> str:
        """Get a summary of the shutdown result."""
        status = "SUCCESS" if self.success else "FAILED"
        duration = f" in {self.duration_ms:.0f}ms" if self.duration_ms else ""
        failed = [s for s in self.component_statuses if not s.success]
        if failed:
            failures = ", ".join(s.component_name for s in failed)
            return f"Shutdown {status}{duration}. Failed: {failures}"
        return (
            f"Shutdown {status}{duration}. All {len(self.component_statuses)} components stopped."
        )


class ShutdownManager:
    """
    Manages graceful shutdown of all system components.

    Ensures orderly shutdown by:
    1. Stopping channels first (stops accepting new requests)
    2. Draining pending messages from agent queues
    3. Stopping agents in reverse registration order
    4. Disconnecting clients (Neo4j, Graphiti, etc.)

    Usage:
        manager = ShutdownManager(timeout_seconds=30)
        manager.register_channel(cli_driver)
        manager.register_agent(orchestrator)
        manager.register_client("neo4j", neo4j.disconnect)

        result = await manager.shutdown()
    """

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        drain_timeout_seconds: float = 10.0,
    ) -> None:
        """
        Initialize shutdown manager.

        Args:
            timeout_seconds: Maximum time to wait for shutdown.
            drain_timeout_seconds: Maximum time to wait for queue draining.
        """
        self.timeout_seconds = timeout_seconds
        self.drain_timeout_seconds = drain_timeout_seconds

        # Components in registration order
        self._channels: list[tuple[str, BaseChannel]] = []
        self._agents: list[tuple[str, BaseAgent]] = []
        self._clients: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]] = []

        # Shutdown state
        self._shutdown_requested = False
        self._current_phase = ShutdownPhase.INITIATED
        self._shutdown_event = asyncio.Event()

    @property
    def shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested

    @property
    def current_phase(self) -> ShutdownPhase:
        """Get current shutdown phase."""
        return self._current_phase

    def register_channel(self, name: str, channel: BaseChannel) -> None:
        """
        Register a channel for shutdown tracking.

        Args:
            name: Channel identifier.
            channel: Channel instance.
        """
        self._channels.append((name, channel))
        logger.debug(
            f"[WHISPER] Registered channel for shutdown: {name}",
            extra={"component": name, "type": "channel"},
        )

    def register_agent(self, name: str, agent: BaseAgent) -> None:
        """
        Register an agent for shutdown tracking.

        Args:
            name: Agent identifier.
            agent: Agent instance.
        """
        self._agents.append((name, agent))
        logger.debug(
            f"[WHISPER] Registered agent for shutdown: {name}",
            extra={"component": name, "type": "agent"},
        )

    def register_client(
        self,
        name: str,
        disconnect_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """
        Register a client for shutdown.

        Args:
            name: Client identifier (e.g., "neo4j", "graphiti").
            disconnect_fn: Async function to disconnect the client.
        """
        self._clients.append((name, disconnect_fn))
        logger.debug(
            f"[WHISPER] Registered client for shutdown: {name}",
            extra={"component": name, "type": "client"},
        )

    def request_shutdown(self) -> None:
        """Request graceful shutdown (non-blocking)."""
        self._shutdown_requested = True
        self._shutdown_event.set()
        logger.info("[CHART] Shutdown requested")

    async def wait_for_shutdown(self) -> None:
        """Wait until shutdown is requested."""
        await self._shutdown_event.wait()

    async def shutdown(self) -> ShutdownResult:
        """
        Execute graceful shutdown of all components.

        Returns:
            ShutdownResult with status of each component.
        """
        result = ShutdownResult(
            success=True,
            phase=ShutdownPhase.INITIATED,
            started_at=datetime.now(),
        )

        self._shutdown_requested = True
        logger.info(
            "[CHART] Beginning graceful shutdown...",
            extra={"timeout_seconds": self.timeout_seconds},
        )

        try:
            # Phase 1: Stop channels (stops accepting new requests)
            await self._stop_channels(result)

            # Phase 2: Drain agent queues
            await self._drain_queues()

            # Phase 3: Stop agents (reverse order)
            await self._stop_agents(result)

            # Phase 4: Disconnect clients
            await self._disconnect_clients(result)

            result.phase = ShutdownPhase.COMPLETE
            result.success = all(s.success for s in result.component_statuses)

        except TimeoutError:
            result.phase = ShutdownPhase.FAILED
            result.success = False
            result.error = f"Shutdown timed out after {self.timeout_seconds}s"
            logger.error(
                f"[STORM] {result.error}",
                extra={"phase": self._current_phase.value},
            )

        except Exception as e:
            result.phase = ShutdownPhase.FAILED
            result.success = False
            result.error = str(e)
            logger.error(
                f"[STORM] Shutdown failed: {e}",
                extra={"phase": self._current_phase.value},
                exc_info=True,
            )

        result.completed_at = datetime.now()

        # Log final summary
        if result.success:
            logger.info(
                f"[BEACON] {result.summary()}",
                extra={"duration_ms": result.duration_ms},
            )
        else:
            logger.error(
                f"[SHIPWRECK] {result.summary()}",
                extra={"duration_ms": result.duration_ms},
            )

        return result

    async def _stop_channels(self, result: ShutdownResult) -> None:
        """Stop all channels."""
        if not self._channels:
            return

        self._current_phase = ShutdownPhase.CHANNELS_STOPPING
        logger.info(
            f"[CHART] Stopping {len(self._channels)} channel(s)...",
            extra={"phase": "channels_stopping"},
        )

        # Stop channels in reverse order
        for name, channel in reversed(self._channels):
            status = await self._stop_component(
                name=name,
                component_type="channel",
                stop_fn=channel.stop,
            )
            result.component_statuses.append(status)

    async def _drain_queues(self) -> None:
        """Wait for agent queues to drain."""
        if not self._agents:
            return

        self._current_phase = ShutdownPhase.DRAINING_QUEUES
        logger.info(
            f"[CHART] Draining {len(self._agents)} agent queue(s)...",
            extra={"phase": "draining_queues", "timeout": self.drain_timeout_seconds},
        )

        try:
            await asyncio.wait_for(
                self._wait_for_queues_empty(),
                timeout=self.drain_timeout_seconds,
            )
            logger.info("[CHART] All queues drained")
        except TimeoutError:
            # Log warning but continue - agents will be stopped anyway
            pending_counts = self._get_pending_counts()
            logger.warning(
                f"[SWELL] Queue drain timed out. Remaining: {pending_counts}",
                extra={"phase": "draining_queues"},
            )

    async def _wait_for_queues_empty(self) -> None:
        """Wait until all agent queues are empty."""
        while True:
            all_empty = True
            for _name, agent in self._agents:
                if hasattr(agent, "inbox") and not agent.inbox.empty():
                    all_empty = False
                    break

            if all_empty:
                return

            await asyncio.sleep(0.1)

    def _get_pending_counts(self) -> dict[str, int]:
        """Get pending message counts for each agent."""
        counts = {}
        for name, agent in self._agents:
            if hasattr(agent, "inbox"):
                counts[name] = agent.inbox.qsize()
        return counts

    async def _stop_agents(self, result: ShutdownResult) -> None:
        """Stop all agents in reverse registration order."""
        if not self._agents:
            return

        self._current_phase = ShutdownPhase.AGENTS_STOPPING
        logger.info(
            f"[CHART] Stopping {len(self._agents)} agent(s)...",
            extra={"phase": "agents_stopping"},
        )

        # Stop agents in reverse order (last started = first stopped)
        for name, agent in reversed(self._agents):
            # Get pending count before stopping
            pending = agent.inbox.qsize() if hasattr(agent, "inbox") else 0

            status = await self._stop_component(
                name=name,
                component_type="agent",
                stop_fn=agent.stop,
            )
            status.pending_items = pending
            result.component_statuses.append(status)

    async def _disconnect_clients(self, result: ShutdownResult) -> None:
        """Disconnect all clients."""
        if not self._clients:
            return

        self._current_phase = ShutdownPhase.CLIENTS_DISCONNECTING
        logger.info(
            f"[CHART] Disconnecting {len(self._clients)} client(s)...",
            extra={"phase": "clients_disconnecting"},
        )

        # Disconnect in reverse order
        for name, disconnect_fn in reversed(self._clients):
            status = await self._stop_component(
                name=name,
                component_type="client",
                stop_fn=disconnect_fn,
            )
            result.component_statuses.append(status)

    async def _stop_component(
        self,
        name: str,
        component_type: str,
        stop_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> ShutdownStatus:
        """
        Stop a single component with timeout and error handling.

        Args:
            name: Component identifier.
            component_type: Type of component.
            stop_fn: Async function to stop the component.

        Returns:
            ShutdownStatus for the component.
        """
        status = ShutdownStatus(
            component_name=name,
            component_type=component_type,
            started_at=datetime.now(),
        )

        try:
            # Per-component timeout (fraction of total)
            component_timeout = self.timeout_seconds / max(
                len(self._channels) + len(self._agents) + len(self._clients), 1
            )

            await asyncio.wait_for(stop_fn(), timeout=component_timeout)

            status.success = True
            status.completed_at = datetime.now()

            logger.debug(
                f"[WHISPER] Stopped {component_type}: {name}",
                extra={
                    "component": name,
                    "type": component_type,
                    "duration_ms": status.duration_ms,
                },
            )

        except TimeoutError:
            status.success = False
            status.completed_at = datetime.now()
            status.error = "Timeout"
            logger.warning(
                f"[SWELL] {component_type.title()} {name} stop timed out",
                extra={"component": name, "type": component_type},
            )

        except Exception as e:
            status.success = False
            status.completed_at = datetime.now()
            status.error = str(e)
            logger.error(
                f"[STORM] Error stopping {component_type} {name}: {e}",
                extra={"component": name, "type": component_type},
                exc_info=True,
            )

        return status


# Module-level instance for application-wide shutdown coordination
_shutdown_manager: ShutdownManager | None = None


def get_shutdown_manager() -> ShutdownManager:
    """Get or create the global shutdown manager."""
    global _shutdown_manager
    if _shutdown_manager is None:
        _shutdown_manager = ShutdownManager()
    return _shutdown_manager


def reset_shutdown_manager() -> None:
    """Reset the global shutdown manager (for testing)."""
    global _shutdown_manager
    _shutdown_manager = None


__all__ = [
    "ShutdownManager",
    "ShutdownPhase",
    "ShutdownResult",
    "ShutdownStatus",
    "get_shutdown_manager",
    "reset_shutdown_manager",
]
