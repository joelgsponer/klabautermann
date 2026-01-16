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
from klabautermann.agents.executor import Executor
from klabautermann.agents.ingestor import Ingestor
from klabautermann.agents.researcher import Researcher
from klabautermann.core.exceptions import ExternalServiceError
from klabautermann.core.logger import logger
from klabautermann.core.models import (
    AgentMessage,
    ChannelType,
    EnrichedContext,
    IntentClassification,
    IntentClassificationResponse,
    IntentType,
    PlannedTask,
    TaskPlan,
    ThreadContext,
)
from klabautermann.mcp.google_workspace import GoogleWorkspaceBridge
from klabautermann.memory.context_queries import (
    get_pending_tasks,
    get_recent_entities,
    get_recent_summaries,
    get_relevant_islands,
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

    # Synthesis prompt for Orchestrator v2 (combines results into coherent response)
    SYNTHESIS_PROMPT: ClassVar[
        str
    ] = """You are synthesizing a response for the user based on gathered information.

Original message: {original_text}

Context:
{formatted_context}

Results from subagents:
{formatted_results}

Instructions:
1. Answer the user's questions using the gathered information
2. If information is missing or uncertain, say so honestly
3. Be proactive - suggest follow-up actions if appropriate
4. If new information was ingested, briefly acknowledge it
5. Keep the response concise but complete

Proactive suggestions (when appropriate):
- "Should I add this to your calendar?"
- "Would you like me to send a follow-up email?"
- "I can set a reminder for this."

Write a natural, helpful response. Do NOT include any JSON or structured formatting.
"""

    # Task planning prompt for Orchestrator v2 (Think-Dispatch-Synthesize pattern)
    TASK_PLANNING_PROMPT: ClassVar[
        str
    ] = """You are the Klabautermann Orchestrator analyzing a user message.

Given the user's message and context, identify ALL tasks that would help provide a complete answer.

For each piece of information the user provides or requests:
1. INGEST: New facts to store ("I learned X", "Sarah works at Y", "Met someone named...")
2. RESEARCH: Information to retrieve from the knowledge graph (questions about known entities)
3. EXECUTE: Actions requiring calendar/email access (scheduling, sending emails, checking events)

Think step by step:
- What is the user telling me? (potential ingestion)
- What is the user asking? (potential research/execution)
- What related information might be useful? (proactive research)

IMPORTANT RULES:
- Ingest tasks should have blocking=false (fire-and-forget)
- Research and Execute tasks should have blocking=true (need results)
- If the message is a simple greeting or doesn't need tasks, set direct_response
- Be thorough - it's better to gather more context than to miss something

Return a JSON task plan following this exact schema:
{
  "reasoning": "Your step-by-step thinking about what tasks are needed",
  "tasks": [
    {
      "task_type": "ingest|research|execute",
      "description": "What this task will do",
      "agent": "ingestor|researcher|executor",
      "payload": {"key": "value pairs for the agent"},
      "blocking": true|false
    }
  ],
  "direct_response": "Response if no tasks needed, or null"
}
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
        neo4j_client: Any | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the Orchestrator.

        Args:
            graphiti: GraphitiClient for knowledge graph operations.
            thread_manager: ThreadManager for conversation persistence.
            neo4j_client: Neo4jClient for direct graph queries (context building).
            config: Agent configuration.
        """
        super().__init__(name="orchestrator", config=config)
        self.graphiti = graphiti
        self.thread_manager = thread_manager
        self.neo4j_client = neo4j_client

        # Anthropic client (lazy initialization)
        self._anthropic = None
        model_config = (config or {}).get("model", {})
        if isinstance(model_config, dict):
            self.model = model_config.get("primary", "claude-sonnet-4-20250514")
        else:
            self.model = model_config or "claude-sonnet-4-20250514"

        # Background tasks set to prevent garbage collection of fire-and-forget tasks
        self._background_tasks: set[asyncio.Task[Any]] = set()

        # Initialize Google Workspace bridge for calendar/email
        self._google_bridge = GoogleWorkspaceBridge()

        # Create and register Executor agent for action handling
        executor = Executor(
            name="executor",
            config=config,
            google_bridge=self._google_bridge,
        )
        self._agent_registry["executor"] = executor

        # Create and register Researcher agent for search queries
        researcher = Researcher(
            name="researcher",
            config=config,
            graphiti=graphiti,
        )
        self._agent_registry["researcher"] = researcher

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
                timeout=60.0,  # Longer timeout for Opus-based Researcher
            )
            if response:
                # New format: ResearcherResponse with GraphIntelligenceReport
                report = response.payload.get("report", {})
                direct_answer = report.get("direct_answer", "")

                if direct_answer:
                    # Build a rich response from the intelligence report
                    confidence = report.get("confidence", 0)
                    confidence_level = report.get("confidence_level", "uncertain")
                    evidence = report.get("evidence", [])

                    # Format response with evidence if confidence is medium or higher
                    if confidence >= 0.5 and evidence:
                        evidence_text = "\n".join(f"  - {e.get('fact', '')}" for e in evidence[:3])
                        return f"{direct_answer}\n\n*Supporting evidence ({confidence_level} confidence):*\n{evidence_text}"

                    return str(direct_answer)

                # Empty or uncertain result
                return "I checked The Locker but couldn't find anything relevant to that query."

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

    # =========================================================================
    # Orchestrator v2 Context Building (T053)
    # =========================================================================

    def _load_v2_config(self) -> dict[str, Any]:
        """
        Load orchestrator_v2 configuration.

        Returns:
            Configuration dictionary with context, execution, and proactive_behavior sections.
            Returns sensible defaults if config not available.
        """
        try:
            from klabautermann.config.manager import ConfigManager

            config_manager = ConfigManager()
            v2_config = config_manager.get("orchestrator_v2")
            if v2_config:
                # Convert Pydantic model to dict for easier access
                return v2_config.model_dump()
        except Exception as e:
            logger.warning(
                f"[SWELL] Could not load orchestrator_v2 config: {e}",
                extra={"agent_name": self.name},
            )

        # Return sensible defaults if config not available
        return {
            "context": {
                "message_window": 20,
                "summary_hours": 12,
                "include_pending_tasks": True,
                "include_recent_entities": True,
                "recent_entity_hours": 24,
                "include_islands": True,
            },
            "execution": {
                "max_research_depth": 2,
                "parallel_timeout_seconds": 30.0,
                "fire_and_forget_timeout_seconds": 60.0,
            },
            "proactive_behavior": {
                "suggest_calendar_events": True,
                "suggest_follow_ups": True,
                "ask_clarifications": True,
            },
        }

    async def _build_context(
        self,
        thread_uuid: str,
        trace_id: str,
    ) -> EnrichedContext:
        """
        Build rich context by gathering from all memory layers in parallel.

        Memory Layers (from MEMORY.md):
        - Short-Term: Current thread messages (ThreadManager)
        - Mid-Term: Recent Note summaries from archived threads
        - Long-Term: Entity references from Graphiti
        - Community: Knowledge Island context for broad awareness

        Args:
            thread_uuid: UUID of the current thread
            trace_id: For logging and tracing

        Returns:
            EnrichedContext with all memory layers populated
        """
        logger.info(
            "[CHART] Building enriched context",
            extra={"trace_id": trace_id, "thread_uuid": thread_uuid},
        )

        # Load config for context parameters
        config = self._load_v2_config()
        context_config = config.get("context", {})

        # Parallel context gathering from all memory layers
        results = await asyncio.gather(
            self.thread_manager.get_context_window(
                thread_uuid, limit=context_config.get("message_window", 20)
            )
            if self.thread_manager
            else self._build_empty_context_window(thread_uuid),
            get_recent_summaries(
                self.neo4j_client,
                hours=context_config.get("summary_hours", 12),
                trace_id=trace_id,
            )
            if self.neo4j_client and context_config.get("include_summaries", True)
            else self._return_empty_list(),
            get_pending_tasks(
                self.neo4j_client,
                trace_id=trace_id,
            )
            if self.neo4j_client and context_config.get("include_pending_tasks", True)
            else self._return_empty_list(),
            get_recent_entities(
                self.neo4j_client,
                hours=context_config.get("recent_entity_hours", 24),
                trace_id=trace_id,
            )
            if self.neo4j_client and context_config.get("include_recent_entities", True)
            else self._return_empty_list(),
            get_relevant_islands(
                self.neo4j_client,
                trace_id=trace_id,
            )
            if self.neo4j_client and context_config.get("include_islands", True)
            else self._return_empty_list(),
            return_exceptions=True,  # Don't fail if one query fails
        )

        # Unpack results, handling exceptions gracefully
        messages_ctx, summaries, tasks, entities, islands = results

        # Handle exceptions - log and use empty defaults
        if isinstance(messages_ctx, Exception):
            logger.warning(
                f"[SWELL] Failed to get messages: {messages_ctx}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            messages = []
            channel_type = ChannelType.CLI
        else:
            messages = messages_ctx.messages if hasattr(messages_ctx, "messages") else []
            channel_type = (
                messages_ctx.channel_type
                if hasattr(messages_ctx, "channel_type")
                else ChannelType.CLI
            )

        if isinstance(summaries, Exception):
            logger.warning(
                f"[SWELL] Failed to get summaries: {summaries}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            summaries = []

        if isinstance(tasks, Exception):
            logger.warning(
                f"[SWELL] Failed to get tasks: {tasks}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            tasks = []

        if isinstance(entities, Exception):
            logger.warning(
                f"[SWELL] Failed to get entities: {entities}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            entities = []

        if isinstance(islands, Exception):
            logger.warning(
                f"[SWELL] Failed to get islands: {islands}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            islands = []

        context = EnrichedContext(
            thread_uuid=thread_uuid,
            channel_type=channel_type,
            messages=messages,
            recent_summaries=summaries,
            pending_tasks=tasks,
            recent_entities=entities,
            relevant_islands=islands if islands else None,
        )

        logger.info(
            f"[BEACON] Context built: {len(messages)} msgs, {len(summaries)} summaries, "
            f"{len(tasks)} tasks, {len(entities)} entities",
            extra={"trace_id": trace_id},
        )

        return context

    async def _build_empty_context_window(self, thread_uuid: str) -> ThreadContext:
        """
        Build an empty context window when ThreadManager is not available.

        Args:
            thread_uuid: Thread UUID

        Returns:
            Empty ThreadContext
        """
        return ThreadContext(
            thread_uuid=thread_uuid,
            channel_type=ChannelType.CLI,
            messages=[],
            max_messages=20,
        )

    async def _return_empty_list(self) -> list:
        """
        Return an empty list asynchronously.

        Used as a placeholder when context queries are disabled or unavailable.

        Returns:
            Empty list
        """
        return []

    # =========================================================================
    # Orchestrator v2 Task Planning (T054)
    # =========================================================================

    async def _plan_tasks(
        self,
        text: str,
        context: EnrichedContext,
        trace_id: str,
    ) -> TaskPlan:
        """
        Use Claude Opus to analyze user message and plan tasks.

        This is the "Think" phase of Think-Dispatch-Synthesize.

        Args:
            text: User's message
            context: Enriched context from _build_context()
            trace_id: For logging

        Returns:
            TaskPlan with reasoning, tasks, and optional direct_response
        """
        logger.info("[CHART] Planning tasks for user message", extra={"trace_id": trace_id})

        # Format context for the prompt
        formatted_context = self._format_context_for_planning(context)

        # Build the full prompt
        planning_prompt = f"""
{self.TASK_PLANNING_PROMPT}

CURRENT CONTEXT:
{formatted_context}

USER MESSAGE:
{text}

Analyze this message and return a JSON task plan.
"""

        try:
            # Call Claude Opus with JSON mode
            response = await self._call_opus_for_planning(planning_prompt, trace_id)

            # Parse and validate the response
            task_plan = self._parse_task_plan(response, trace_id)

            logger.info(
                f"[BEACON] Task plan created: {len(task_plan.tasks)} tasks",
                extra={
                    "trace_id": trace_id,
                    "reasoning": task_plan.reasoning[:100],
                    "task_count": len(task_plan.tasks),
                },
            )

            return task_plan

        except Exception as e:
            logger.warning(
                f"[SWELL] Task planning failed, using fallback: {e}", extra={"trace_id": trace_id}
            )
            # Return a fallback plan with direct response
            return TaskPlan(
                reasoning="Task planning failed, responding directly",
                tasks=[],
                direct_response="I'm having trouble processing your request. Could you try again?",
            )

    def _format_context_for_planning(self, context: EnrichedContext) -> str:
        """Format EnrichedContext into a readable string for LLM."""
        parts = []

        # Recent messages
        if context.messages:
            parts.append("RECENT CONVERSATION:")
            for msg in context.messages[-5:]:  # Last 5 messages
                role = msg.get("role", "unknown")
                content = msg.get("content", "")[:200]
                parts.append(f"  [{role}]: {content}")

        # Recent summaries (cross-thread context)
        if context.recent_summaries:
            parts.append("\nRECENT THREADS:")
            for summary in context.recent_summaries[:3]:
                parts.append(f"  - {summary.summary[:100]}...")

        # Pending tasks
        if context.pending_tasks:
            parts.append("\nPENDING TASKS:")
            for task in context.pending_tasks[:5]:
                parts.append(f"  - [{task.priority or 'normal'}] {task.action}")

        # Recent entities
        if context.recent_entities:
            parts.append("\nRECENTLY MENTIONED:")
            entity_names = [e.name for e in context.recent_entities[:10]]
            parts.append(f"  {', '.join(entity_names)}")

        # Knowledge islands
        if context.relevant_islands:
            parts.append("\nKNOWLEDGE AREAS:")
            for island in context.relevant_islands[:3]:
                parts.append(f"  - {island.name}: {island.summary[:50]}...")

        return "\n".join(parts) or "No additional context available."

    async def _call_opus_for_planning(self, prompt: str, trace_id: str) -> str:
        """Call Claude Opus with JSON mode for task planning."""
        loop = asyncio.get_event_loop()

        def _sync_call() -> str:
            response = self.anthropic.messages.create(
                model="claude-opus-4-5-20251101",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            text: str = response.content[0].text
            return text

        logger.debug(
            "[WHISPER] Calling Claude Opus for task planning",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return await loop.run_in_executor(None, _sync_call)

    def _parse_task_plan(self, response: str, _trace_id: str) -> TaskPlan:
        """Parse LLM response into TaskPlan model."""
        import json as json_module
        import re

        # Try to extract JSON from response
        # Handle both raw JSON and markdown code blocks
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Assume raw JSON or find first { to last }
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                json_str = response[start : end + 1]
            else:
                raise ValueError("No JSON found in response")

        data = json_module.loads(json_str)
        return TaskPlan.model_validate(data)

    # =========================================================================
    # Orchestrator v2 Parallel Execution (T055)
    # =========================================================================

    async def _execute_parallel(
        self,
        task_plan: TaskPlan,
        trace_id: str,
    ) -> dict[str, Any]:
        """
        Execute all planned tasks in parallel.

        This is the "Dispatch" phase of Think-Dispatch-Synthesize.

        - Blocking tasks (research, execute) run in parallel with asyncio.gather()
        - Non-blocking tasks (ingest) are fire-and-forget
        - Individual task failures are captured, not propagated

        Args:
            task_plan: TaskPlan from _plan_tasks()
            trace_id: For logging

        Returns:
            Dictionary mapping task descriptions to results
        """
        logger.info(
            f"[CHART] Executing {len(task_plan.tasks)} tasks in parallel",
            extra={"trace_id": trace_id},
        )

        results: dict[str, Any] = {}
        blocking_coros: list[Any] = []
        blocking_tasks: list[Any] = []

        # Load timeout from config
        config = self._load_v2_config()
        timeout_seconds = config.get("execution", {}).get("parallel_timeout_seconds", 30)

        for task in task_plan.tasks:
            if task.blocking:
                # Create coroutine for blocking task
                coro = self._dispatch_task(task, trace_id)
                blocking_coros.append(coro)
                blocking_tasks.append(task)
            else:
                # Fire-and-forget for non-blocking tasks (ingestion)
                bg_task = asyncio.create_task(self._dispatch_task_fire_and_forget(task, trace_id))
                # Track to prevent garbage collection
                self._background_tasks.add(bg_task)
                bg_task.add_done_callback(self._background_tasks.discard)
                logger.debug(
                    f"[WHISPER] Fire-and-forget task started: {task.description}",
                    extra={"trace_id": trace_id},
                )

        # Wait for all blocking tasks in parallel with timeout
        if blocking_coros:
            try:
                task_results = await asyncio.wait_for(
                    asyncio.gather(*blocking_coros, return_exceptions=True),
                    timeout=timeout_seconds,
                )

                # Map results back to task descriptions
                for task, result in zip(blocking_tasks, task_results, strict=False):
                    if isinstance(result, Exception):
                        logger.warning(
                            f"[SWELL] Task failed: {task.description}: {result}",
                            extra={"trace_id": trace_id},
                        )
                        results[task.description] = {"error": str(result)}
                    else:
                        results[task.description] = result

            except TimeoutError:
                logger.warning(
                    f"[STORM] Parallel execution timed out after {timeout_seconds}s",
                    extra={"trace_id": trace_id},
                )
                # Mark all remaining tasks as timed out
                for task in blocking_tasks:
                    if task.description not in results:
                        results[task.description] = {"error": "Execution timed out"}

        logger.info(
            f"[BEACON] Execution complete: {len(results)} results",
            extra={"trace_id": trace_id, "result_count": len(results)},
        )

        return results

    async def _dispatch_task(
        self,
        task: Any,
        trace_id: str,
    ) -> dict[str, Any]:
        """
        Dispatch a single task to the appropriate agent and wait for result.
        """
        logger.debug(
            f"[WHISPER] Dispatching {task.task_type} to {task.agent}",
            extra={"trace_id": trace_id, "task": task.description},
        )

        agent = self._agent_registry.get(task.agent)
        if not agent:
            raise ValueError(f"Agent '{task.agent}' not found in registry")

        # Build message for the agent
        msg = AgentMessage(
            trace_id=trace_id,
            source_agent=self.name,
            target_agent=task.agent,
            intent=task.task_type,
            payload=task.payload,
        )

        # Dispatch to agent and wait for response
        response = await agent.process_message(msg)

        return {
            "agent": task.agent,
            "response": response,
            "task_type": task.task_type,
        }

    async def _dispatch_task_fire_and_forget(
        self,
        task: Any,
        trace_id: str,
    ) -> None:
        """
        Dispatch a non-blocking task (fire-and-forget).

        Errors are logged but don't propagate.
        """
        try:
            await self._dispatch_task(task, trace_id)
            logger.debug(
                f"[WHISPER] Fire-and-forget completed: {task.description}",
                extra={"trace_id": trace_id},
            )
        except Exception as e:
            logger.warning(
                f"[SWELL] Fire-and-forget failed: {task.description}: {e}",
                extra={"trace_id": trace_id},
            )

    # =========================================================================
    # Orchestrator v2 Response Synthesis (T056)
    # =========================================================================

    async def _synthesize_response(
        self,
        original_text: str,
        context: EnrichedContext,
        results: dict[str, Any],
        trace_id: str,
    ) -> str:
        """
        Synthesize final response from all gathered information.

        This is the "Synthesize" phase of Think-Dispatch-Synthesize.

        Args:
            original_text: The user's original message
            context: Enriched context used for planning
            results: Results from _execute_parallel()
            trace_id: For logging

        Returns:
            Natural language response for the user
        """
        logger.info(
            "[CHART] Synthesizing response from task results",
            extra={"trace_id": trace_id, "result_count": len(results)},
        )

        # Format context and results for the prompt
        formatted_context = self._format_context_for_synthesis(context)
        formatted_results = self._format_results_for_synthesis(results)

        # Check config for proactive behavior
        config = self._load_v2_config()
        proactive_config = config.get("proactive_behavior", {})

        # Build synthesis prompt
        prompt = self.SYNTHESIS_PROMPT.format(
            original_text=original_text,
            formatted_context=formatted_context,
            formatted_results=formatted_results,
        )

        # Add proactive behavior guidance if enabled
        if proactive_config.get("suggest_calendar_events"):
            prompt += "\n- If relevant, suggest adding calendar events."
        if proactive_config.get("suggest_follow_ups"):
            prompt += "\n- If relevant, suggest follow-up actions."

        try:
            response = await self._call_opus_for_synthesis(prompt, trace_id)

            logger.info(
                f"[BEACON] Response synthesized: {len(response)} chars",
                extra={"trace_id": trace_id},
            )

            return response

        except Exception as e:
            logger.warning(f"[SWELL] Synthesis failed: {e}", extra={"trace_id": trace_id})
            # Fallback: provide a basic response
            return self._build_fallback_response(results)

    def _format_context_for_synthesis(self, context: EnrichedContext) -> str:
        """Format context for synthesis prompt (focused on relevance)."""
        parts = []

        # Recent messages (conversation continuity)
        if context.messages:
            parts.append("RECENT CONVERSATION:")
            for msg in context.messages[-3:]:  # Last 3 messages
                role = msg.get("role", "unknown")
                content = msg.get("content", "")[:150]
                parts.append(f"  [{role}]: {content}")

        # Pending tasks (proactive awareness)
        if context.pending_tasks:
            parts.append("\nRELEVANT PENDING TASKS:")
            for task in context.pending_tasks[:3]:
                parts.append(f"  - {task.action}")

        return "\n".join(parts) if parts else "No additional context."

    def _format_results_for_synthesis(self, results: dict[str, Any]) -> str:
        """Format task results for synthesis prompt."""
        if not results:
            return "No results from subagents."

        parts = []
        for task_desc, result in results.items():
            if isinstance(result, dict) and "error" in result:
                parts.append(f"TASK: {task_desc}\nSTATUS: Failed - {result['error']}")
            elif isinstance(result, dict):
                # Format result details
                response = result.get("response", str(result))
                if isinstance(response, str):
                    response = response[:500]  # Truncate long responses
                parts.append(f"TASK: {task_desc}\nRESULT: {response}")
            else:
                parts.append(f"TASK: {task_desc}\nRESULT: {str(result)[:500]}")

        return "\n\n".join(parts)

    async def _call_opus_for_synthesis(self, prompt: str, _trace_id: str) -> str:
        """Call Claude Opus for response synthesis."""
        loop = asyncio.get_event_loop()

        response = await loop.run_in_executor(
            None,
            lambda: self.anthropic.messages.create(
                model="claude-opus-4-5-20251101",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            ),
        )

        return str(response.content[0].text)

    def _build_fallback_response(self, results: dict[str, Any]) -> str:
        """Build a basic response when synthesis fails."""
        if not results:
            return "I processed your request but couldn't find any relevant information."

        # Check for any successful results
        successful = [r for r in results.values() if isinstance(r, dict) and "error" not in r]

        if successful:
            return f"I found some information, but had trouble summarizing it. Here's what I learned: {str(successful[0])[:200]}"
        else:
            return "I had trouble processing your request. Could you try rephrasing?"

    # =========================================================================
    # Orchestrator v2 Main Workflow (T059)
    # =========================================================================

    async def handle_user_input_v2(
        self,
        text: str,
        thread_uuid: str,
        trace_id: str | None = None,
    ) -> str:
        """
        Handle user input using Think-Dispatch-Synthesize pattern.

        This is the main entry point for Orchestrator v2.

        Workflow:
        1. Build rich context from all memory layers
        2. Plan tasks using Claude Opus (Think)
        3. Handle direct responses if no tasks needed
        4. Execute tasks in parallel (Dispatch)
        5. Optional: deepen research if needed
        6. Synthesize final response (Synthesize)
        7. Apply personality and store

        Args:
            text: User's message
            thread_uuid: UUID of the current thread
            trace_id: For logging (generated if not provided)

        Returns:
            Natural language response to the user
        """
        if trace_id is None:
            trace_id = str(uuid.uuid4())

        logger.info(
            "[CHART] Starting v2 workflow", extra={"trace_id": trace_id, "thread_uuid": thread_uuid}
        )

        try:
            # 1. Build rich context
            context = await self._build_context(thread_uuid, trace_id)

            # 2. Think: Plan tasks
            task_plan = await self._plan_tasks(text, context, trace_id)

            # 3. Handle direct response (no tasks needed)
            if task_plan.direct_response and not task_plan.tasks:
                logger.info("[BEACON] Direct response (no tasks)", extra={"trace_id": trace_id})
                response = task_plan.direct_response
                response = await self._apply_personality(response, trace_id)
                await self._store_response(thread_uuid, response, trace_id)
                return response

            # 4. Dispatch: Execute tasks in parallel
            results = await self._execute_parallel(task_plan, trace_id)

            # 5. Optional: Iterative deepening
            config = self._load_v2_config()
            max_depth = config.get("execution", {}).get("max_research_depth", 2)
            current_depth = 1

            while self._needs_deeper_research(results, task_plan) and current_depth < max_depth:
                logger.info(
                    f"[CHART] Deepening research (depth {current_depth + 1})",
                    extra={"trace_id": trace_id},
                )
                deeper_results = await self._deepen_research(results, context, trace_id)
                results = self._merge_results(results, deeper_results)
                current_depth += 1

            # 6. Synthesize: Combine results into response
            response = await self._synthesize_response(text, context, results, trace_id)

            # 7. Apply personality and store
            response = await self._apply_personality(response, trace_id)
            await self._store_response(thread_uuid, response, trace_id)

            logger.info(
                "[BEACON] V2 workflow complete",
                extra={"trace_id": trace_id, "response_length": len(response)},
            )

            return response

        except Exception as e:
            logger.error(
                f"[STORM] V2 workflow failed: {e}",
                extra={"trace_id": trace_id},
                exc_info=True,
            )
            # Fallback to error response
            return "I apologize, but I had trouble processing your request. Could you try again?"

    def _needs_deeper_research(
        self,
        results: dict[str, Any],
        task_plan: TaskPlan,
    ) -> bool:
        """
        Determine if we need to gather more information.

        Deepening is triggered when:
        - All research tasks returned empty/uncertain results
        - Results mention related entities that weren't queried
        """
        # If no research tasks were in the plan, no deepening needed
        research_tasks = [t for t in task_plan.tasks if t.task_type == "research"]
        if not research_tasks:
            return False

        # Check if any research succeeded with useful results
        for task in research_tasks:
            result = results.get(task.description, {})
            if isinstance(result, dict) and "error" not in result:
                # Extract response - could be in "response" field or at root
                response = result.get("response", result)

                # Convert to string and check if we have meaningful content
                response_str = str(response) if response else ""

                # If we got a substantial response, we have enough info
                if response_str and len(response_str) >= 50:
                    return False

        # All research tasks returned minimal results - try deepening
        return True

    async def _deepen_research(
        self,
        results: dict[str, Any],
        _context: EnrichedContext,
        trace_id: str,
    ) -> dict[str, Any]:
        """
        Perform follow-up research based on initial results.

        Analyzes initial results to identify related entities or
        topics that should be queried for more context.
        """
        # Extract mentions from initial results that could be queried
        mentions = self._extract_mentions_from_results(results)

        if not mentions:
            return {}

        # Create follow-up research tasks
        follow_up_tasks = []
        for mention in mentions[:3]:  # Limit to 3 follow-ups
            follow_up_tasks.append(
                PlannedTask(
                    task_type="research",
                    description=f"Follow-up: Find more about {mention}",
                    agent="researcher",
                    payload={"query": f"What do I know about {mention}?"},
                    blocking=True,
                )
            )

        if not follow_up_tasks:
            return {}

        # Execute follow-up tasks
        follow_up_plan = TaskPlan(
            reasoning="Follow-up research for more context",
            tasks=follow_up_tasks,
        )

        return await self._execute_parallel(follow_up_plan, trace_id)

    def _extract_mentions_from_results(
        self,
        results: dict[str, Any],
    ) -> list[str]:
        """
        Extract entity mentions from results for follow-up queries.
        """
        mentions = set()

        for result in results.values():
            if isinstance(result, dict) and "response" in result:
                response = str(result["response"])
                # Simple extraction: look for capitalized words
                import re

                words = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", response)
                mentions.update(words[:5])

        return list(mentions)

    def _merge_results(
        self,
        original: dict[str, Any],
        deeper: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Merge original and deeper research results.
        """
        merged = dict(original)
        for key, value in deeper.items():
            if key not in merged:
                merged[key] = value
        return merged

    async def _store_response(
        self,
        thread_uuid: str,
        response: str,
        trace_id: str,
    ) -> None:
        """
        Store the response in the thread.
        """
        if self.thread_manager:
            try:
                await self.thread_manager.add_message(
                    thread_uuid=thread_uuid,
                    role="assistant",
                    content=response,
                    trace_id=trace_id,
                )
            except Exception as e:
                logger.warning(
                    f"[SWELL] Failed to store response: {e}", extra={"trace_id": trace_id}
                )


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Orchestrator"]
