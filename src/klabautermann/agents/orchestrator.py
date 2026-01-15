"""
Orchestrator agent for Klabautermann.

The "CEO" that receives all user input, classifies intent, delegates to
sub-agents, and synthesizes the final response.

Sprint 2 version: Full agent delegation with dispatch-and-wait and
fire-and-forget patterns for inter-agent communication.

Reference: specs/architecture/AGENTS.md Section 1.1, 2.3
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.agents.ingestor import Ingestor
from klabautermann.core.exceptions import ExternalServiceError
from klabautermann.core.logger import logger
from klabautermann.core.models import (
    AgentMessage,
    IntentClassification,
    IntentClassificationResponse,
    IntentType,
    ThreadContext,
)


if TYPE_CHECKING:
    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.thread_manager import ThreadManager


class Orchestrator(BaseAgent):
    """
    The "CEO" - routes intents, delegates to sub-agents, synthesizes responses.

    Implements dispatch-and-wait and fire-and-forget patterns for agent delegation:
    - dispatch_and_wait: Synchronous call, waits for sub-agent response
    - dispatch_fire_and_forget: Async background task, no response expected

    Responsibilities:
    - Parse incoming user messages
    - Load thread context (rolling window of recent messages)
    - Classify intent (search, action, ingestion, conversation)
    - Dispatch to appropriate sub-agent(s)
    - Synthesize responses from sub-agents
    - Apply Klabautermann personality formatting
    - Fire-and-forget ingestion (non-blocking)
    """

    # LLM-based intent classification prompt (replaces hardcoded keyword lists)
    CLASSIFICATION_PROMPT: ClassVar[
        str
    ] = """Classify this user message into one of these intent types:

SEARCH - User wants to retrieve information from the knowledge graph (things they told you before)
  Examples: "Who is Sarah?", "What do you know about Project Alpha?", "What did John tell me last week?"

ACTION - User wants to interact with external services (Gmail, Calendar) or perform tasks
  Examples: "Send an email to John", "Schedule a meeting tomorrow", "Check my email", "Any unread emails?", "What's on my calendar today?"

INGESTION - User is sharing new information to remember
  Examples: "I met John today, he works at Acme", "Sarah's email is sarah@example.com", "I'm working on Project Beta"

CONVERSATION - General chat, greetings, acknowledgments, or unclear intent
  Examples: "Hello!", "Thanks for the help", "How are you?", "Ok sounds good"

User message: {message}

Respond with ONLY valid JSON (no markdown, no explanation):
{{"intent_type": "search", "confidence": 0.95, "reasoning": "User asking about a person", "extracted_query": "Who is Sarah?", "extracted_action": null}}
"""

    # Default model for classification (Haiku for speed)
    CLASSIFICATION_MODEL: ClassVar[str] = "claude-3-5-haiku-20241022"

    # System prompt with Klabautermann personality and intent classification rules
    SYSTEM_PROMPT = """You are the Klabautermann Orchestrator - the central navigator of a personal knowledge system.

CORE RULES:
1. SEARCH FIRST: Before answering factual questions, delegate to the Researcher to query The Locker (graph database).
2. NEVER HALLUCINATE: If the Researcher returns no results, say "I don't have that in The Locker" rather than guessing.
3. INGEST IN BACKGROUND: When the user mentions new information (people, events, projects), dispatch to the Ingestor asynchronously - don't make the user wait.
4. ACTION REQUIRES CONTEXT: Before the Executor sends an email or creates an event, ensure the Researcher has verified the recipient's email or the calendar availability.

INTENT CLASSIFICATION:
- Search intents: "who", "what", "when", "where", "find", "tell me about", "remind me"
- Action intents: "send", "email", "schedule", "create", "draft", "remind"
- Ingestion triggers: "I met", "I talked to", "I'm working on", "I learned", mentions of new people/projects

PERSONALITY:
- You are a salty, efficient helper - witty but never annoying
- Efficiency first: answer the question, then add nautical color
- Use "The Locker" for database, "Scouting the horizon" for search, "The Manifest" for tasks
- Be warm and helpful, never over-the-top with pirate speak

When the user tells you about people, places, projects, or tasks:
- Acknowledge that you're making note of it
- Confirm the key details you understood
- Be conversational, not robotic

Example responses:
- "Noted! I'll remember that Sarah works at Acme as a PM. Anything else I should know about her?"
- "Got it, adding that to The Locker. Sounds like an interesting project!"
- "Scouting the horizon for Sarah... Found her in The Locker: PM at Acme, met her last Tuesday."
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
        model_config = (config or {}).get("model", {})
        if isinstance(model_config, dict):
            self.model = model_config.get("primary", "claude-sonnet-4-20250514")
        else:
            self.model = model_config or "claude-sonnet-4-20250514"

        # Background tasks set to prevent garbage collection of fire-and-forget tasks
        self._background_tasks: set[asyncio.Task[Any]] = set()

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

            # Classify user intent
            intent = await self._classify_intent(text, context, trace_id)
            logger.info(
                "[CHART] Intent classified",
                extra={
                    "trace_id": trace_id,
                    "agent_name": self.name,
                    "intent": intent.type.value,
                    "confidence": intent.confidence,
                },
            )

            # Dispatch based on intent
            if intent.type == IntentType.SEARCH:
                # Will delegate to Researcher in T021
                response_text = await self._handle_search(intent, context, trace_id)
            elif intent.type == IntentType.ACTION:
                # Will delegate to Executor in T021
                response_text = await self._handle_action(intent, context, trace_id)
            elif intent.type == IntentType.INGESTION:
                # Fire-and-forget to Ingestor, respond conversationally
                response_text = await self._handle_conversation(text, context, trace_id)
            else:
                # Default conversation handling
                response_text = await self._handle_conversation(text, context, trace_id)

            # Apply personality formatting
            response_text = await self._apply_personality(response_text, trace_id)

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

            # Fire-and-forget ingestion only for INGESTION intent (don't pollute graph with queries)
            if self.graphiti and intent.type == IntentType.INGESTION:
                task = asyncio.create_task(self._ingest_conversation(text, response_text, trace_id))
                # Store reference to prevent garbage collection
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

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

        except TimeoutError:
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
                messages.append(
                    {
                        "role": msg["role"],
                        "content": msg["content"],
                    }
                )

        # Add current user message
        messages.append(
            {
                "role": "user",
                "content": text,
            }
        )

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
            text: str = response.content[0].text
            return text

        logger.debug(
            f"[WHISPER] Calling Claude ({self.model})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return await loop.run_in_executor(None, _sync_call)

    async def _call_classification_model(
        self,
        prompt: str,
        trace_id: str,
    ) -> str:
        """
        Call Claude Haiku for intent classification.

        Uses Haiku for fast, cheap classification. Returns raw text response.

        Args:
            prompt: Classification prompt with user message.
            trace_id: Request trace ID.

        Returns:
            Raw response text (expected to be JSON).
        """
        loop = asyncio.get_event_loop()

        def _sync_call() -> str:
            response = self.anthropic.messages.create(
                model=self.CLASSIFICATION_MODEL,
                max_tokens=256,  # Classification responses are small
                messages=[{"role": "user", "content": prompt}],
            )
            text: str = response.content[0].text
            return text

        logger.debug(
            f"[WHISPER] Calling classification model ({self.CLASSIFICATION_MODEL})",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return await loop.run_in_executor(None, _sync_call)

    async def _ingest_conversation(
        self,
        user_text: str,
        _assistant_text: str,  # Reserved - not ingested to avoid meta-garbage
        trace_id: str,
    ) -> None:
        """
        Fire-and-forget: ingest user message into knowledge graph.

        This runs in the background and doesn't block the response.
        Graphiti will extract entities and update the graph.

        IMPORTANT: Only ingests user messages, NOT assistant responses.
        Ingesting assistant responses creates meta-garbage like "Assistant
        is searching for X" which pollutes search results.

        Input is cleaned before ingestion to remove:
        - Role prefixes (User:, Assistant:, etc.)
        - Roleplay markers (*actions*, **Researcher**: etc.)
        - System mentions (The Locker, etc.)

        Args:
            user_text: User's message to ingest.
            _assistant_text: Reserved for future use (currently ignored).
            trace_id: Request trace ID.
        """
        if not self.graphiti:
            return

        try:
            # Clean input before ingestion (removes role prefixes, roleplay, etc.)
            cleaned_text = Ingestor.clean_input(user_text)

            if not cleaned_text:
                logger.debug(
                    "[WHISPER] Text cleaned to empty - skipping ingestion",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                return

            logger.debug(
                f"[WHISPER] Ingesting: {len(user_text)} -> {len(cleaned_text)} chars",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

            # Ingest cleaned user message - Graphiti handles entity extraction
            await self.graphiti.add_episode(
                content=cleaned_text,
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

    # =========================================================================
    # Agent Delegation (T021)
    # =========================================================================

    async def _dispatch_and_wait(
        self,
        target_agent: str,
        payload: dict[str, Any],
        trace_id: str,
        timeout: float = 30.0,
    ) -> AgentMessage | None:
        """
        Dispatch message to agent and wait for response.

        Uses asyncio.Queue for synchronous request-response pattern.
        The response_queue field in AgentMessage allows the target agent
        to route its response directly back instead of through the inbox.

        Args:
            target_agent: Name of the target agent.
            payload: Message payload.
            trace_id: Request trace ID.
            timeout: Maximum time to wait for response.

        Returns:
            Response AgentMessage or None if timeout/error.
        """
        # Create response queue for this request
        response_queue: asyncio.Queue[AgentMessage] = asyncio.Queue()

        # Create message with response queue
        msg = AgentMessage(
            trace_id=trace_id,
            source_agent=self.name,
            target_agent=target_agent,
            intent=payload.get("intent", "request"),
            payload=payload,
            response_queue=response_queue,
        )

        # Get target agent from registry
        target = self._agent_registry.get(target_agent)
        if not target:
            logger.error(
                f"[STORM] Unknown agent: {target_agent}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return None

        # Send message to target agent's inbox
        logger.debug(
            f"[WHISPER] Dispatching to {target_agent}",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "payload_keys": list(payload.keys()),
            },
        )
        await target.inbox.put(msg)

        # Wait for response with timeout
        try:
            response = await asyncio.wait_for(response_queue.get(), timeout=timeout)
            logger.debug(
                f"[WHISPER] Received response from {target_agent}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return response
        except TimeoutError:
            logger.warning(
                f"[SWELL] Timeout waiting for {target_agent}",
                extra={"trace_id": trace_id, "agent_name": self.name, "timeout": timeout},
            )
            return None

    async def _dispatch_fire_and_forget(
        self,
        target_agent: str,
        payload: dict[str, Any],
        trace_id: str,
    ) -> None:
        """
        Dispatch message to agent without waiting for response.

        Used for non-blocking operations like ingestion where we don't
        need to wait for the result.

        Args:
            target_agent: Name of the target agent.
            payload: Message payload.
            trace_id: Request trace ID.
        """
        msg = AgentMessage(
            trace_id=trace_id,
            source_agent=self.name,
            target_agent=target_agent,
            intent=payload.get("intent", "request"),
            payload=payload,
            # No response_queue - fire and forget
        )

        target = self._agent_registry.get(target_agent)
        if target:
            logger.debug(
                f"[WHISPER] Fire-and-forget to {target_agent}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            await target.inbox.put(msg)
        else:
            logger.warning(
                f"[SWELL] Fire-and-forget target not found: {target_agent}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

    def _has_agent(self, agent_name: str) -> bool:
        """Check if an agent is registered."""
        has = agent_name in self._agent_registry
        if not has:
            logger.warning(
                f"[SWELL] Agent '{agent_name}' not in registry. Available: {list(self._agent_registry.keys())}",
                extra={"agent_name": self.name},
            )
        return has

    # =========================================================================
    # Intent Classification (T020) - LLM-based with structured output
    # =========================================================================

    async def _classify_intent(
        self,
        text: str,
        context: ThreadContext | None,
        trace_id: str,
    ) -> IntentClassification:
        """
        Classify user intent using LLM with structured JSON output.

        Uses Claude Haiku for fast, semantic intent classification. Falls back
        to simple heuristics if LLM call fails.

        Args:
            text: User's message text.
            context: Conversation context for better classification.
            trace_id: Request trace ID for logging.

        Returns:
            IntentClassification with type and confidence score.
        """
        try:
            # Build prompt with user message
            prompt = self.CLASSIFICATION_PROMPT.format(message=text)

            # Add conversation context if available (last 2 messages)
            if context and context.messages:
                recent = context.messages[-2:]
                if recent:
                    context_str = "\n".join(
                        f"{m.get('role', 'user')}: {m.get('content', '')[:100]}" for m in recent
                    )
                    prompt = f"Recent conversation:\n{context_str}\n\n{prompt}"

            # Call classification model (Haiku)
            response_text = await self._call_classification_model(prompt, trace_id)

            # Parse JSON response (handle potential markdown code blocks)
            json_str = response_text.strip()
            if json_str.startswith("```"):
                # Extract JSON from markdown code block
                lines = json_str.split("\n")
                json_lines = [line for line in lines if not line.startswith("```")]
                json_str = "\n".join(json_lines)

            # Normalize intent_type to lowercase (LLM sometimes returns uppercase)
            import json as json_module

            parsed = json_module.loads(json_str)
            if "intent_type" in parsed and isinstance(parsed["intent_type"], str):
                parsed["intent_type"] = parsed["intent_type"].lower()
            json_str = json_module.dumps(parsed)

            result = IntentClassificationResponse.model_validate_json(json_str)

            logger.debug(
                f"[WHISPER] LLM classified as {result.intent_type.value}: {result.reasoning}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

            return IntentClassification(
                type=result.intent_type,
                confidence=result.confidence,
                query=result.extracted_query,
                action=result.extracted_action,
            )

        except Exception as e:
            # Fallback to simple heuristics if LLM fails
            logger.warning(
                f"[SWELL] LLM classification failed, using fallback: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return self._classify_intent_fallback(text, trace_id)

    def _classify_intent_fallback(self, text: str, trace_id: str) -> IntentClassification:
        """
        Simple fallback classification when LLM is unavailable.

        Uses basic heuristics - much less accurate than LLM but works offline.
        """
        text_lower = text.lower().strip()

        # Question mark -> SEARCH
        if "?" in text:
            logger.debug(
                "[WHISPER] Fallback: question mark -> SEARCH",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return IntentClassification(
                type=IntentType.SEARCH,
                confidence=0.6,
                query=text,
            )

        # Action keywords
        action_starts = ("send", "email", "schedule", "create", "draft", "book")
        if any(text_lower.startswith(kw) for kw in action_starts):
            logger.debug(
                "[WHISPER] Fallback: action keyword -> ACTION",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return IntentClassification(
                type=IntentType.ACTION,
                confidence=0.6,
                action=text,
            )

        # Ingestion keywords
        ingest_starts = ("i met", "i talked", "i spoke", "i learned", "i just")
        if any(text_lower.startswith(kw) for kw in ingest_starts):
            logger.debug(
                "[WHISPER] Fallback: ingestion keyword -> INGESTION",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return IntentClassification(
                type=IntentType.INGESTION,
                confidence=0.6,
            )

        # Default to conversation
        logger.debug(
            "[WHISPER] Fallback: default -> CONVERSATION",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )
        return IntentClassification(
            type=IntentType.CONVERSATION,
            confidence=0.5,
        )

    # =========================================================================
    # Intent Handlers (T021 - Full Delegation)
    # =========================================================================

    async def _handle_search(
        self,
        intent: IntentClassification,
        context: ThreadContext | None,
        trace_id: str,
    ) -> str:
        """
        Handle search intent by delegating to Researcher.

        Delegates to the Researcher agent for knowledge graph queries.
        Falls back to direct Claude call if Researcher not available.

        Args:
            intent: Classified search intent with query.
            context: Conversation context.
            trace_id: Request trace ID.

        Returns:
            Response text from Researcher or fallback.
        """
        logger.info(
            "[CHART] Handling search intent",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "query": intent.query,
            },
        )

        query = intent.query or "your question"

        # Try to delegate to Researcher agent
        if self._has_agent("researcher"):
            response = await self._dispatch_and_wait(
                "researcher",
                {"query": query, "intent": "search", "context": context},
                trace_id,
            )
            if response:
                result: str = response.payload.get("result", "")
                if result:
                    # Process through Claude for human-readable response
                    messages = [
                        {
                            "role": "user",
                            "content": f"""Based on these search results from the knowledge graph, provide a helpful natural language response to the question: "{query}"

Search results:
{result}

If the results are relevant, summarize them conversationally. If not helpful, say you couldn't find anything relevant.""",
                        }
                    ]
                    return await self._call_claude(messages, trace_id)
                # Empty result from Researcher
                return "I checked The Locker but couldn't find anything on that."

            # Timeout or error - fall back to conversation
            logger.warning(
                "[SWELL] Researcher unavailable, falling back to conversation",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

        # Fallback: use conversation handler
        messages = self._build_messages(query, context)
        claude_response: str = await asyncio.wait_for(
            self._call_claude(messages, trace_id),
            timeout=30.0,
        )

        return claude_response

    async def _handle_action(
        self,
        intent: IntentClassification,
        _context: ThreadContext | None,
        trace_id: str,
    ) -> str:
        """
        Handle action intent by delegating to Executor.

        First queries Researcher for context (e.g., recipient email),
        then delegates to Executor with that context.

        Args:
            intent: Classified action intent with action description.
            _context: Conversation context for Researcher lookup.
            trace_id: Request trace ID.

        Returns:
            Response text from Executor or fallback.
        """
        logger.info(
            "[CHART] Handling action intent",
            extra={
                "trace_id": trace_id,
                "agent_name": self.name,
                "action": intent.action,
            },
        )

        action = intent.action or "that action"
        action_context: dict[str, Any] = {}

        # First, get context from Researcher if available
        if self._has_agent("researcher") and intent.context_query:
            context_response = await self._dispatch_and_wait(
                "researcher",
                {"query": intent.context_query, "intent": "context_lookup"},
                trace_id,
                timeout=15.0,  # Shorter timeout for context lookup
            )
            if context_response:
                action_context = context_response.payload

        # Now delegate to Executor
        if self._has_agent("executor"):
            response = await self._dispatch_and_wait(
                "executor",
                {"action": action, "intent": "execute", "context": action_context},
                trace_id,
            )
            if response:
                action_result: str = response.payload.get("result", "")
                if action_result:
                    return action_result
                # Check for specific errors
                if not response.payload.get("success", True):
                    error_msg: str = response.payload.get(
                        "message", "I couldn't complete that action."
                    )
                    return error_msg

            # Timeout or error
            logger.warning(
                "[SWELL] Executor unavailable, action cannot be completed",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

        # Fallback: acknowledge but explain limitation
        return (
            f'I\'ve noted your request: "{action}". '
            "Action execution (email, calendar) is coming in the next update. "
            "For now, I've logged this in The Manifest."
        )

    async def _handle_conversation(
        self,
        text: str,
        context: ThreadContext | None,
        trace_id: str,
    ) -> str:
        """
        Handle general conversation using Claude.

        This is the default handler for conversational messages
        that don't require search or action delegation.

        Args:
            text: User's message text.
            context: Conversation context.
            trace_id: Request trace ID.

        Returns:
            Response text from Claude.
        """
        logger.debug(
            "[WHISPER] Handling conversation",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        messages = self._build_messages(text, context)

        response = await asyncio.wait_for(
            self._call_claude(messages, trace_id),
            timeout=30.0,
        )

        return response

    async def _apply_personality(
        self,
        response: str,
        trace_id: str,
    ) -> str:
        """
        Apply Klabautermann personality formatting to response.

        Currently a pass-through. In future sprints, this could invoke
        The Bard for response "salting" with nautical flair.

        Args:
            response: Raw response text.
            trace_id: Request trace ID.

        Returns:
            Response with personality applied.
        """
        # Future: Invoke The Bard for response salting via self.bard.salt_response()

        logger.debug(
            "[WHISPER] Personality applied (pass-through)",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return response


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Orchestrator"]
