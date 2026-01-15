# Implement Async Agent Delegation Pattern

## Metadata
- **ID**: T021
- **Priority**: P0
- **Category**: subagent
- **Effort**: M
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 2.3
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md)

## Dependencies
- [ ] T020 - Orchestrator intent classification

## Context
The Orchestrator needs to delegate work to sub-agents (Researcher, Executor, Ingestor). This task implements the dispatch/wait and fire-and-forget patterns for inter-agent communication using asyncio queues.

## Requirements
- [ ] Extend `src/klabautermann/agents/orchestrator.py`:

### Dispatch and Wait Pattern
- [ ] Implement `_dispatch_and_wait()` for synchronous agent calls
- [ ] Create response queue for waiting on sub-agent replies
- [ ] Add timeout handling (default 30s)
- [ ] Propagate trace ID through all calls

### Fire and Forget Pattern
- [ ] Implement `_dispatch_fire_and_forget()` for async background tasks
- [ ] Use `asyncio.create_task()` for non-blocking dispatch
- [ ] No response expected - used for Ingestor

### Response Aggregation
- [ ] Support waiting on multiple agents in parallel
- [ ] Combine results from Researcher + graph context for Executor

### Integration with Intent Handlers
- [ ] Update `_handle_search()` to use `_dispatch_and_wait("researcher", ...)`
- [ ] Update `_handle_action()` to:
  1. First dispatch to Researcher for context
  2. Then dispatch to Executor with context
- [ ] Add fire-and-forget Ingestor call after all responses

## Acceptance Criteria
- [ ] Search intent delegates to Researcher and waits for response
- [ ] Action intent queries Researcher then delegates to Executor
- [ ] Ingestion happens in background (non-blocking)
- [ ] Timeout triggers graceful error response
- [ ] All delegations logged with trace ID

## Implementation Notes

```python
from typing import Optional
import asyncio

class Orchestrator(BaseAgent):
    async def _dispatch_and_wait(
        self,
        target_agent: str,
        payload: dict,
        trace_id: str,
        timeout: float = 30.0,
    ) -> Optional[AgentMessage]:
        """Dispatch message to agent and wait for response."""
        # Create response queue for this request
        response_queue: asyncio.Queue[AgentMessage] = asyncio.Queue()

        # Create message
        msg = AgentMessage(
            trace_id=trace_id,
            source_agent="orchestrator",
            target_agent=target_agent,
            intent=payload.get("intent", "request"),
            payload=payload,
            timestamp=time.time(),
            response_queue=response_queue,  # For response routing
        )

        # Get target agent
        target = self.agent_registry.get(target_agent)
        if not target:
            logger.error(f"[STORM] Unknown agent: {target_agent}", extra={"trace_id": trace_id})
            return None

        # Send message
        logger.debug(
            f"[WHISPER] Dispatching to {target_agent}",
            extra={"trace_id": trace_id, "payload": payload}
        )
        await target.inbox.put(msg)

        # Wait for response with timeout
        try:
            response = await asyncio.wait_for(response_queue.get(), timeout=timeout)
            logger.debug(
                f"[WHISPER] Received response from {target_agent}",
                extra={"trace_id": trace_id}
            )
            return response
        except asyncio.TimeoutError:
            logger.warning(
                f"[SWELL] Timeout waiting for {target_agent}",
                extra={"trace_id": trace_id}
            )
            return None

    async def _dispatch_fire_and_forget(
        self,
        target_agent: str,
        payload: dict,
        trace_id: str,
    ) -> None:
        """Dispatch message to agent without waiting for response."""
        msg = AgentMessage(
            trace_id=trace_id,
            source_agent="orchestrator",
            target_agent=target_agent,
            intent=payload.get("intent", "request"),
            payload=payload,
            timestamp=time.time(),
        )

        target = self.agent_registry.get(target_agent)
        if target:
            logger.debug(
                f"[WHISPER] Fire-and-forget to {target_agent}",
                extra={"trace_id": trace_id}
            )
            await target.inbox.put(msg)

    async def handle_user_input(self, thread_id: str, text: str) -> str:
        """Main entry point - now with delegation."""
        trace_id = str(uuid.uuid4())
        context = await self.memory.get_thread_context(thread_id, limit=15)
        intent = await self._classify_intent(text, context, trace_id)

        response_text = ""

        if intent.type == IntentType.SEARCH:
            # Delegate to Researcher
            response = await self._dispatch_and_wait(
                "researcher",
                {"query": intent.query, "context": context},
                trace_id,
            )
            if response:
                response_text = response.payload.get("result", "No results found.")
            else:
                response_text = "I'm having trouble searching The Locker right now."

        elif intent.type == IntentType.ACTION:
            # First get context from Researcher
            context_response = await self._dispatch_and_wait(
                "researcher",
                {"query": intent.context_query or intent.action, "context": context},
                trace_id,
            )
            # Then execute with context
            action_response = await self._dispatch_and_wait(
                "executor",
                {
                    "action": intent.action,
                    "context": context_response.payload if context_response else {},
                },
                trace_id,
            )
            if action_response:
                response_text = action_response.payload.get("result", "Action completed.")
            else:
                response_text = "I'm having trouble with that action right now."

        else:
            # Conversation - handle directly
            response_text = await self._generate_response(text, context, trace_id)

        # Fire-and-forget ingestion for all messages
        asyncio.create_task(
            self._dispatch_fire_and_forget(
                "ingestor",
                {"text": text, "thread_id": thread_id},
                trace_id,
            )
        )

        return await self._apply_personality(response_text, trace_id)
```

Note: The `response_queue` field will need to be added to `AgentMessage` model, or we can use a separate response routing mechanism.
