# Create Base Agent Abstract Class

## Metadata
- **ID**: T016
- **Priority**: P0
- **Category**: subagent
- **Effort**: M
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 2
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md)

## Dependencies
- [ ] T005 - Pydantic models (AgentMessage)
- [ ] T008 - Logging system

## Context
The base agent class defines the common interface and behavior for all agents in the multi-agent system. It implements the async inbox queue pattern for message passing and provides hooks for configuration, error handling, and metrics.

## Requirements
- [ ] Create `src/klabautermann/agents/base_agent.py` with:

### BaseAgent Abstract Class
- [ ] Async inbox queue for message receiving
- [ ] Abstract `process_message()` method
- [ ] `run()` method for main processing loop
- [ ] Error handling wrapper with logging
- [ ] Configuration loading from config manager

### Message Handling
- [ ] Accept `AgentMessage` objects
- [ ] Validate incoming messages
- [ ] Route responses to target agent
- [ ] Support priority queuing (optional for Sprint 1)

### Lifecycle
- [ ] `start()` - Begin processing loop
- [ ] `stop()` - Clean shutdown
- [ ] Health check method

### Observability
- [ ] Trace ID propagation
- [ ] Execution timing
- [ ] Success/failure counting (basic metrics)

## Acceptance Criteria
- [ ] `BaseAgent` is abstract (cannot be instantiated)
- [ ] Subclasses must implement `process_message()`
- [ ] Messages processed in order from queue
- [ ] Errors logged with trace ID
- [ ] Agent can be started and stopped cleanly

## Implementation Notes

```python
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import time

from klabautermann.core.models import AgentMessage
from klabautermann.core.logger import logger
from klabautermann.core.exceptions import AgentError


class BaseAgent(ABC):
    """
    Abstract base class for all Klabautermann agents.

    Implements the async inbox queue pattern for inter-agent communication.
    """

    def __init__(
        self,
        name: str,
        config: Optional[Dict[str, Any]] = None,
    ):
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
        self._agent_registry: Dict[str, "BaseAgent"] = {}

        # Basic metrics
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    @property
    def agent_registry(self) -> Dict[str, "BaseAgent"]:
        """Registry of all agents for message routing."""
        return self._agent_registry

    @agent_registry.setter
    def agent_registry(self, registry: Dict[str, "BaseAgent"]) -> None:
        self._agent_registry = registry

    @abstractmethod
    async def process_message(self, msg: AgentMessage) -> Optional[AgentMessage]:
        """
        Process an incoming message.

        Subclasses must implement this method.

        Args:
            msg: The incoming agent message.

        Returns:
            Optional response message, or None if no response needed.
        """
        pass

    async def run(self) -> None:
        """Main processing loop: consume messages from inbox."""
        self._running = True
        logger.info(f"[CHART] Agent '{self.name}' started")

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
                    exc_info=True,
                )

        logger.info(f"[CHART] Agent '{self.name}' stopped")

    async def _handle_message(self, msg: AgentMessage) -> None:
        """Handle a single message with timing and error handling."""
        start_time = time.time()
        self._request_count += 1

        try:
            logger.debug(
                f"[WHISPER] {self.name} processing message",
                extra={"trace_id": msg.trace_id, "intent": msg.intent}
            )

            response = await self.process_message(msg)

            if response:
                await self._route_response(response)

            self._success_count += 1
            logger.debug(
                f"[WHISPER] {self.name} completed",
                extra={"trace_id": msg.trace_id}
            )

        except Exception as e:
            self._error_count += 1
            logger.error(
                f"[STORM] {self.name} failed: {e}",
                extra={"trace_id": msg.trace_id}
            )
            # Don't re-raise - let the agent continue processing

        finally:
            elapsed_ms = (time.time() - start_time) * 1000
            self._total_latency_ms += elapsed_ms
            self.inbox.task_done()

    async def _route_response(self, response: AgentMessage) -> None:
        """Route response to target agent."""
        target = self._agent_registry.get(response.target_agent)
        if target:
            await target.inbox.put(response)
        else:
            logger.warning(
                f"[SWELL] Unknown target agent: {response.target_agent}",
                extra={"trace_id": response.trace_id}
            )

    async def stop(self) -> None:
        """Stop the agent gracefully."""
        self._running = False

    def get_metrics(self) -> Dict[str, Any]:
        """Return agent performance metrics."""
        avg_latency = (
            self._total_latency_ms / self._request_count
            if self._request_count > 0
            else 0
        )
        return {
            "agent": self.name,
            "requests": self._request_count,
            "successes": self._success_count,
            "errors": self._error_count,
            "avg_latency_ms": round(avg_latency, 2),
        }
```

This pattern is from AGENTS.md Section 2.2. In Sprint 1, only the Orchestrator will inherit from this. More agents follow in Sprint 2.
