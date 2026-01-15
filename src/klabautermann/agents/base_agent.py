"""
Base agent abstract class for Klabautermann.

Defines the common interface and behavior for all agents in the multi-agent system.
Implements the async inbox queue pattern for message passing.

Reference: specs/architecture/AGENTS.md Section 2
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage


class BaseAgent(ABC):
    """
    Abstract base class for all Klabautermann agents.

    Implements the async inbox queue pattern for inter-agent communication.
    All agents (Orchestrator, Ingestor, Researcher, etc.) inherit from this.
    """

    def __init__(
        self,
        name: str,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the agent.

        Args:
            name: Agent identifier (e.g., 'orchestrator', 'ingestor').
            config: Agent-specific configuration.
        """
        self.name = name
        self.config = config or {}
        self.inbox: asyncio.Queue[AgentMessage] = asyncio.Queue()
        self._running = False
        self._agent_registry: dict[str, BaseAgent] = {}

        # Basic metrics
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    @property
    def agent_registry(self) -> dict[str, BaseAgent]:
        """Registry of all agents for message routing."""
        return self._agent_registry

    @agent_registry.setter
    def agent_registry(self, registry: dict[str, BaseAgent]) -> None:
        """Set the agent registry for message routing."""
        self._agent_registry = registry

    @property
    def is_running(self) -> bool:
        """Check if agent is currently running."""
        return self._running

    @abstractmethod
    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process an incoming message.

        Subclasses must implement this method to handle their specific logic.

        Args:
            msg: The incoming agent message.

        Returns:
            Optional response message, or None if no response needed.
        """
        ...

    async def run(self) -> None:
        """
        Main processing loop: consume messages from inbox.

        Runs until stop() is called. Handles message processing
        with timing, error handling, and metrics collection.
        """
        self._running = True
        logger.info(
            f"[CHART] Agent '{self.name}' started",
            extra={"agent_name": self.name},
        )

        while self._running:
            try:
                # Wait for message with timeout (allows clean shutdown)
                try:
                    msg = await asyncio.wait_for(
                        self.inbox.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                # Process the message
                await self._handle_message(msg)

            except Exception as e:
                logger.error(
                    f"[STORM] Agent '{self.name}' loop error: {e}",
                    extra={"agent_name": self.name},
                    exc_info=True,
                )

        logger.info(
            f"[CHART] Agent '{self.name}' stopped",
            extra={"agent_name": self.name},
        )

    async def _handle_message(self, msg: AgentMessage) -> None:
        """
        Handle a single message with timing and error handling.

        Args:
            msg: Message to process.
        """
        start_time = time.time()
        self._request_count += 1

        try:
            logger.debug(
                f"[WHISPER] {self.name} processing message",
                extra={
                    "trace_id": msg.trace_id,
                    "agent_name": self.name,
                    "intent": msg.intent,
                },
            )

            response = await self.process_message(msg)

            if response:
                await self._route_response(response, original_msg=msg)

            self._success_count += 1
            logger.debug(
                f"[WHISPER] {self.name} completed",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
            )

        except Exception as e:
            self._error_count += 1
            logger.error(
                f"[STORM] {self.name} failed: {e}",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
                exc_info=True,
            )
            # Don't re-raise - let the agent continue processing other messages

        finally:
            elapsed_ms = (time.time() - start_time) * 1000
            self._total_latency_ms += elapsed_ms
            self.inbox.task_done()

    async def _route_response(
        self, response: AgentMessage, original_msg: AgentMessage | None = None
    ) -> None:
        """
        Route response to target agent or response queue.

        If the original message has a response_queue, send there instead
        of the target agent's inbox (dispatch-and-wait pattern).

        Args:
            response: Response message to route.
            original_msg: Original message that triggered this response.
        """
        # Check if original message has a response queue (dispatch-and-wait pattern)
        if original_msg and original_msg.response_queue is not None:
            await original_msg.response_queue.put(response)
            logger.debug(
                f"[WHISPER] Response sent to queue for {response.target_agent}",
                extra={"trace_id": response.trace_id, "agent_name": self.name},
            )
            return

        # Normal routing to target agent's inbox
        target = self._agent_registry.get(response.target_agent)
        if target:
            await target.inbox.put(response)
        else:
            logger.warning(
                f"[SWELL] Unknown target agent: {response.target_agent}",
                extra={
                    "trace_id": response.trace_id,
                    "agent_name": self.name,
                },
            )

    async def send_message(
        self,
        target_agent: str,
        intent: str,
        payload: dict[str, Any],
        trace_id: str,
        priority: str = "normal",
    ) -> None:
        """
        Send a message to another agent.

        Args:
            target_agent: Name of the target agent.
            intent: Intent/action for the message.
            payload: Message payload data.
            trace_id: Request trace ID.
            priority: Message priority (normal, high).
        """
        msg = AgentMessage(
            trace_id=trace_id,
            source_agent=self.name,
            target_agent=target_agent,
            intent=intent,
            payload=payload,
            priority=priority,
        )
        await self._route_response(msg)

    async def start(self) -> None:
        """
        Start the agent.

        Convenience method that calls run() in a task.
        """
        asyncio.create_task(self.run())

    async def stop(self) -> None:
        """Stop the agent gracefully."""
        self._running = False
        logger.info(
            f"[CHART] Agent '{self.name}' stopping...",
            extra={"agent_name": self.name},
        )

    def get_metrics(self) -> dict[str, Any]:
        """
        Return agent performance metrics.

        Returns:
            Dictionary with request counts, error counts, and latency stats.
        """
        avg_latency = (
            self._total_latency_ms / self._request_count if self._request_count > 0 else 0
        )
        success_rate = (
            self._success_count / self._request_count if self._request_count > 0 else 1.0
        )

        return {
            "agent": self.name,
            "requests": self._request_count,
            "successes": self._success_count,
            "errors": self._error_count,
            "success_rate": round(success_rate, 3),
            "avg_latency_ms": round(avg_latency, 2),
            "total_latency_ms": round(self._total_latency_ms, 2),
        }

    async def health_check(self) -> bool:
        """
        Check if agent is healthy.

        Override in subclasses for specific health checks.

        Returns:
            True if healthy, False otherwise.
        """
        return self._running


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["BaseAgent"]
