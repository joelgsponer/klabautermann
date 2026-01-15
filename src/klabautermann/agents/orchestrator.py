"""
Orchestrator agent for Klabautermann.

The central navigator that receives all user input and generates responses.
Sprint 1 version: Simple implementation without sub-agent delegation.

Reference: specs/architecture/AGENTS.md Section 1.1
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import TYPE_CHECKING, Any

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.exceptions import ExternalServiceError
from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage, ThreadContext


if TYPE_CHECKING:
    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.thread_manager import ThreadManager


class Orchestrator(BaseAgent):
    """
    The central navigator - receives all user input and generates responses.

    Sprint 1 version: Simple implementation without sub-agent delegation.
    Full multi-agent delegation (Researcher, Executor, etc.) comes in Sprint 2.

    Responsibilities:
    - Receive user messages from channels
    - Load conversation context from ThreadManager
    - Generate responses via Claude
    - Fire background ingestion for entity extraction
    """

    # System prompt with Klabautermann personality
    SYSTEM_PROMPT = """You are Klabautermann, a helpful ship spirit who manages your captain's personal knowledge.

Your personality:
- Witty and dry, with subtle nautical undertones
- Efficiency first: answer the question clearly, then add personality
- Use nautical metaphors naturally when appropriate: "The Locker" (your memory), "charting a course" (planning)
- Be warm and helpful, never annoying or over-the-top

Your capabilities (Sprint 1):
- Conversational responses with memory of our current conversation
- Learning about the user's life (you note what they tell you about people, projects, etc.)

Current limitations (coming in future sprints):
- You cannot yet search your full memory (The Locker)
- You cannot yet send emails or create calendar events
- You cannot yet set reminders

When the user tells you about people, places, projects, or tasks:
- Acknowledge that you're making note of it
- Confirm the key details you understood
- Be conversational, not robotic

Example responses:
- "Noted! I'll remember that Sarah works at Acme as a PM. Anything else I should know about her?"
- "Got it, adding that to The Locker. Sounds like an interesting project!"
"""

    def __init__(
        self,
        graphiti: GraphitiClient | None = None,
        thread_manager: ThreadManager | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the Orchestrator.

        Args:
            graphiti: GraphitiClient for knowledge graph operations.
            thread_manager: ThreadManager for conversation persistence.
            config: Agent configuration.
        """
        super().__init__(name="orchestrator", config=config)
        self.graphiti = graphiti
        self.thread_manager = thread_manager

        # Anthropic client (lazy initialization)
        self._anthropic = None
        self.model = (config or {}).get("model", "claude-sonnet-4-20250514")

    @property
    def anthropic(self) -> Any:
        """Lazy-load Anthropic client."""
        if self._anthropic is None:
            import anthropic

            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ExternalServiceError("anthropic", "ANTHROPIC_API_KEY not set")
            self._anthropic = anthropic.Anthropic(api_key=api_key)
        return self._anthropic

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process agent-to-agent message.

        In Sprint 1, this is not used since handle_user_input is the main entry point.
        Full agent-to-agent communication comes in Sprint 2.
        """
        logger.debug(
            f"[WHISPER] Received agent message: {msg.intent}",
            extra={"trace_id": msg.trace_id, "agent_name": self.name},
        )
        # For Sprint 1, just log and ignore agent messages
        return None

    async def handle_user_input(
        self,
        thread_id: str,
        text: str,
        context: ThreadContext | None = None,
        trace_id: str | None = None,
    ) -> str:
        """
        Main entry point: process user input and return response.

        This is the primary interface for channels to interact with the Orchestrator.

        Args:
            thread_id: Thread identifier from channel.
            text: User's message content.
            context: Optional pre-loaded context window.
            trace_id: Request trace ID for logging.

        Returns:
            Response text to send back to user.
        """
        # Generate trace ID if not provided
        trace_id = trace_id or f"orch-{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        logger.info(
            "[CHART] Processing user input",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "thread_id": thread_id[:16],
                "text_preview": text[:50],
            },
        )

        try:
            # Parse thread_id to extract channel_type and external_id
            # Format: "channel-uuid" (e.g., "cli-abc123", "telegram-12345")
            thread_uuid = thread_id  # Default to using as-is
            if "-" in thread_id:
                parts = thread_id.split("-", 1)
                channel_type = parts[0]
                external_id = parts[1] if len(parts) > 1 else thread_id
            else:
                channel_type = "cli"
                external_id = thread_id

            # Get or create thread (if thread_manager available)
            if self.thread_manager:
                try:
                    thread = await self.thread_manager.get_or_create_thread(
                        external_id=external_id,
                        channel_type=channel_type,
                        trace_id=trace_id,
                    )
                    thread_uuid = thread.uuid
                except Exception as e:
                    logger.warning(
                        f"[SWELL] Could not get/create thread: {e}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )

            # Load context if not provided and thread_manager is available
            if context is None and self.thread_manager:
                try:
                    context = await self.thread_manager.get_context_window(
                        thread_uuid=thread_uuid,
                        trace_id=trace_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"[SWELL] Could not load context: {e}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )
                    context = None

            # Store user message in thread (if thread_manager available)
            if self.thread_manager:
                try:
                    await self.thread_manager.add_message(
                        thread_uuid=thread_uuid,
                        role="user",
                        content=text,
                        trace_id=trace_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"[SWELL] Could not store user message: {e}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )

            # Build messages for Claude
            messages = self._build_messages(text, context)

            # Call Claude with timeout
            response_text = await asyncio.wait_for(
                self._call_claude(messages, trace_id),
                timeout=30.0,
            )

            # Store assistant response in thread
            if self.thread_manager:
                try:
                    await self.thread_manager.add_message(
                        thread_uuid=thread_uuid,
                        role="assistant",
                        content=response_text,
                        trace_id=trace_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"[SWELL] Could not store assistant message: {e}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )

            # Fire-and-forget ingestion (non-blocking)
            if self.graphiti:
                asyncio.create_task(
                    self._ingest_conversation(text, response_text, trace_id)
                )

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                "[BEACON] Response generated",
                extra={
                    "trace_id": trace_id,
                    "agent_name": self.name,
                    "latency_ms": round(elapsed_ms, 2),
                },
            )

            return response_text

        except asyncio.TimeoutError:
            logger.error(
                "[STORM] Claude call timed out",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return "I'm taking longer than usual to respond. The seas are rough today - please try again."

        except Exception as e:
            logger.error(
                f"[STORM] Orchestrator error: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return f"I've hit some rough waters. Error: {type(e).__name__}"

    def _build_messages(
        self,
        text: str,
        context: ThreadContext | None,
    ) -> list[dict[str, str]]:
        """
        Build message list for Claude API.

        Args:
            text: Current user message.
            context: Optional conversation context.

        Returns:
            List of message dicts with role and content.
        """
        messages: list[dict[str, str]] = []

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

    async def _call_claude(self, messages: list[dict[str, str]], trace_id: str) -> str:
        """
        Call Claude API and return response text.

        Uses run_in_executor since the Anthropic SDK is synchronous.

        Args:
            messages: Message list for the API.
            trace_id: Request trace ID.

        Returns:
            Response text from Claude.
        """
        loop = asyncio.get_event_loop()

        def _sync_call() -> str:
            response = self.anthropic.messages.create(
                model=self.model,
                max_tokens=1024,
                system=self.SYSTEM_PROMPT,
                messages=messages,
            )
            return response.content[0].text

        logger.debug(
            f"[WHISPER] Calling Claude ({self.model})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return await loop.run_in_executor(None, _sync_call)

    async def _ingest_conversation(
        self,
        user_text: str,
        assistant_text: str,
        trace_id: str,
    ) -> None:
        """
        Fire-and-forget: ingest conversation into knowledge graph.

        This runs in the background and doesn't block the response.
        Graphiti will extract entities and update the graph.

        Args:
            user_text: User's message.
            assistant_text: Assistant's response.
            trace_id: Request trace ID.
        """
        if not self.graphiti:
            return

        try:
            # Combine into episode for Graphiti
            episode_content = f"User: {user_text}\nAssistant: {assistant_text}"

            await self.graphiti.add_episode(
                content=episode_content,
                source="conversation",
                trace_id=trace_id,
            )

            logger.debug(
                "[WHISPER] Conversation ingested to Graphiti",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

        except Exception as e:
            # Don't fail the response if ingestion fails
            logger.warning(
                f"[SWELL] Ingestion failed (non-blocking): {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Orchestrator"]
