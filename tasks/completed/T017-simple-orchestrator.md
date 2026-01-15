# Implement Simple Orchestrator

## Metadata
- **ID**: T017
- **Priority**: P0
- **Category**: subagent
- **Effort**: L
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.1
- Related: [PERSONALITY.md](../../specs/branding/PERSONALITY.md)

## Dependencies
- [ ] T009 - Graphiti client (for ingestion)
- [ ] T011 - Thread manager (for context)
- [ ] T016 - Base agent class

## Context
The Orchestrator is the "CEO" agent that receives all user input and generates responses. In Sprint 1, this is a **simplified version** without sub-agent delegation - it handles everything directly. Full multi-agent delegation comes in Sprint 2.

## Requirements
- [ ] Create `src/klabautermann/agents/orchestrator.py` with:

### Orchestrator Class (extends BaseAgent)
- [ ] `handle_user_input()` - Main entry point from channels
- [ ] Load thread context before processing
- [ ] Call Claude for response generation
- [ ] Fire background ingestion task (non-blocking)
- [ ] Apply basic personality formatting

### LLM Integration
- [ ] Use Anthropic SDK for Claude calls
- [ ] System prompt with Klabautermann personality
- [ ] Include thread context in conversation
- [ ] Timeout handling for LLM calls

### Ingestion (Fire-and-Forget)
- [ ] After generating response, queue ingestion
- [ ] Use `asyncio.create_task()` for non-blocking
- [ ] Call Graphiti's `add_episode()` with conversation

### Error Handling
- [ ] Graceful fallback on LLM failure
- [ ] Log errors with trace ID
- [ ] User-friendly error messages

## Acceptance Criteria
- [ ] `orchestrator.handle_user_input(thread_id, "Hello")` returns response
- [ ] Response has Klabautermann personality
- [ ] Context window included in Claude call
- [ ] Ingestion happens in background (doesn't block response)
- [ ] LLM timeout doesn't crash system

## Implementation Notes

```python
import asyncio
import os
import time
from typing import Optional

import anthropic

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.models import AgentMessage, ThreadContext
from klabautermann.core.logger import logger
from klabautermann.memory.graphiti_client import GraphitiClient
from klabautermann.memory.thread_manager import ThreadManager


class Orchestrator(BaseAgent):
    """
    The central navigator - receives all user input and generates responses.

    Sprint 1 version: Simple implementation without sub-agent delegation.
    """

    SYSTEM_PROMPT = """You are Klabautermann, a salty but efficient personal assistant.

Your personality:
- Witty and dry, with nautical undertones
- Efficiency first: answer the question, then add color
- Use nautical terms naturally: "The Locker" (your memory), "Scouting the horizon" (searching)
- Never be annoying or over-the-top pirate parody

Your capabilities (Sprint 1):
- Conversational responses
- Memory of our conversation (context provided)
- Learning about the user's life (I'm noting what you tell me)

Current limitations (coming soon):
- You cannot yet search your full memory (The Locker)
- You cannot yet send emails or create calendar events

When the user tells you about people, places, or projects, acknowledge that you're making note of it.
"""

    def __init__(
        self,
        graphiti: GraphitiClient,
        thread_manager: ThreadManager,
        config: Optional[dict] = None,
    ):
        super().__init__(name="orchestrator", config=config)
        self.graphiti = graphiti
        self.thread_manager = thread_manager
        self.anthropic = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
        self.model = config.get("model", "claude-3-5-sonnet-20241022") if config else "claude-3-5-sonnet-20241022"

    async def process_message(self, msg: AgentMessage) -> Optional[AgentMessage]:
        """Process agent-to-agent message (for future delegation)."""
        # In Sprint 1, not used - handle_user_input is the entry point
        pass

    async def handle_user_input(
        self,
        thread_id: str,
        text: str,
        context: Optional[ThreadContext] = None,
        trace_id: Optional[str] = None,
    ) -> str:
        """
        Main entry point: process user input and return response.

        Args:
            thread_id: Thread identifier from channel.
            text: User's message.
            context: Optional pre-loaded context window.
            trace_id: Request trace ID.

        Returns:
            Response text to send back to user.
        """
        trace_id = trace_id or f"orch-{time.time()}"

        logger.info(
            f"[CHART] Processing user input",
            extra={"trace_id": trace_id, "text_preview": text[:50]}
        )

        try:
            # Build messages for Claude
            messages = self._build_messages(text, context)

            # Call Claude with timeout
            response_text = await asyncio.wait_for(
                self._call_claude(messages, trace_id),
                timeout=30.0,
            )

            # Fire-and-forget ingestion
            asyncio.create_task(
                self._ingest_conversation(text, response_text, trace_id)
            )

            logger.info(
                "[BEACON] Response generated",
                extra={"trace_id": trace_id}
            )

            return response_text

        except asyncio.TimeoutError:
            logger.error("[STORM] Claude call timed out", extra={"trace_id": trace_id})
            return "I'm taking longer than usual to respond. Please try again."

        except Exception as e:
            logger.error(f"[STORM] Orchestrator error: {e}", extra={"trace_id": trace_id})
            return "I've hit some rough waters. Let's try that again."

    def _build_messages(
        self,
        text: str,
        context: Optional[ThreadContext],
    ) -> list:
        """Build message list for Claude API."""
        messages = []

        # Add context window if available
        if context and context.messages:
            for msg in context.messages:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        # Add current user message
        messages.append({
            "role": "user",
            "content": text,
        })

        return messages

    async def _call_claude(self, messages: list, trace_id: str) -> str:
        """Call Claude API and return response text."""
        # Use run_in_executor since anthropic SDK is sync
        loop = asyncio.get_event_loop()

        def _sync_call():
            response = self.anthropic.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self.SYSTEM_PROMPT,
                messages=messages,
            )
            return response.content[0].text

        return await loop.run_in_executor(None, _sync_call)

    async def _ingest_conversation(
        self,
        user_text: str,
        assistant_text: str,
        trace_id: str,
    ) -> None:
        """Fire-and-forget: ingest conversation into knowledge graph."""
        try:
            # Combine into episode
            episode_content = f"User: {user_text}\nAssistant: {assistant_text}"

            await self.graphiti.add_episode(
                content=episode_content,
                source="conversation",
                trace_id=trace_id,
            )

            logger.debug(
                "[WHISPER] Conversation ingested",
                extra={"trace_id": trace_id}
            )

        except Exception as e:
            # Don't fail the response if ingestion fails
            logger.warning(
                f"[SWELL] Ingestion failed (non-blocking): {e}",
                extra={"trace_id": trace_id}
            )
```

**Sprint 1 Limitations**: This orchestrator doesn't delegate to sub-agents. It calls Claude directly and fires ingestion in the background. Full delegation (Researcher, Executor, Ingestor as separate agents) comes in Sprint 2.
