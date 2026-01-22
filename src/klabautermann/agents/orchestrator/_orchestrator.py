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

from klabautermann.agents.bard import BardConfig as BardAgentConfig
from klabautermann.agents.bard import BardOfTheBilge
from klabautermann.agents.base_agent import BaseAgent
from klabautermann.agents.executor import Executor
from klabautermann.agents.ingestor import Ingestor

# Import prompts from new module (incremental migration)
from klabautermann.agents.orchestrator.prompts import (
    CLASSIFICATION_MODEL as PROMPTS_CLASSIFICATION_MODEL,
)
from klabautermann.agents.orchestrator.prompts import (
    CLASSIFICATION_PROMPT as PROMPTS_CLASSIFICATION_PROMPT,
)
from klabautermann.agents.orchestrator.prompts import (
    SYNTHESIS_PROMPT as PROMPTS_SYNTHESIS_PROMPT,
)
from klabautermann.agents.orchestrator.prompts import (
    SYSTEM_PROMPT as PROMPTS_SYSTEM_PROMPT,
)
from klabautermann.agents.orchestrator.prompts import (
    TASK_PLANNING_PROMPT as PROMPTS_TASK_PLANNING_PROMPT,
)
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
from klabautermann.memory.message_linking import link_entities_to_message
from klabautermann.skills.planner import SkillAwarePlanner


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

    # Prompts imported from orchestrator/prompts.py (incremental migration)
    SYNTHESIS_PROMPT: ClassVar[str] = PROMPTS_SYNTHESIS_PROMPT
    TASK_PLANNING_PROMPT: ClassVar[str] = PROMPTS_TASK_PLANNING_PROMPT
    CLASSIFICATION_PROMPT: ClassVar[str] = PROMPTS_CLASSIFICATION_PROMPT
    CLASSIFICATION_MODEL: ClassVar[str] = PROMPTS_CLASSIFICATION_MODEL
    SYSTEM_PROMPT: ClassVar[str] = PROMPTS_SYSTEM_PROMPT

    def __init__(
        self,
        graphiti: GraphitiClient | None = None,
        thread_manager: ThreadManager | None = None,
        neo4j_client: Any | None = None,
        config: dict[str, Any] | None = None,
        captain_uuid: str | None = None,
    ) -> None:
        """
        Initialize the Orchestrator.

        Args:
            graphiti: GraphitiClient for knowledge graph operations.
            thread_manager: ThreadManager for conversation persistence.
            neo4j_client: Neo4jClient for direct graph queries (context building).
            config: Agent configuration.
            captain_uuid: UUID of the Captain (user) for Bard personalization.
        """
        super().__init__(name="orchestrator", config=config)
        self.graphiti = graphiti
        self.thread_manager = thread_manager
        self.neo4j_client = neo4j_client
        self.captain_uuid = captain_uuid

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

        # Create and register Ingestor agent for entity extraction
        # Pass neo4j_client for entity linking (Bug #350)
        ingestor = Ingestor(
            name="ingestor",
            config=config,
            graphiti_client=graphiti,
            neo4j_client=neo4j_client,
        )
        self._agent_registry["ingestor"] = ingestor

        # Initialize skill-aware planner for Claude Code skill integration
        self._skill_planner = SkillAwarePlanner()

        # Initialize Bard for response salting (#109)
        self._bard: BardOfTheBilge | None = None
        self._bard_config = self._load_bard_config()
        if neo4j_client and captain_uuid and self._bard_config.get("enabled", True):
            bard_agent_config = BardAgentConfig(
                tidbit_probability=self._bard_config.get("tidbit_probability", 0.07),
                saga_continuation_probability=self._bard_config.get(
                    "saga_continuation_probability", 0.3
                ),
                max_saga_chapters=self._bard_config.get("saga_rules", {}).get("max_chapters", 5),
                max_active_sagas=self._bard_config.get("saga_rules", {}).get("max_active", 3),
                saga_timeout_days=self._bard_config.get("saga_rules", {}).get("timeout_days", 30),
                min_chapter_interval_hours=self._bard_config.get("saga_rules", {}).get(
                    "min_interval_hours", 1.0
                ),
            )
            self._bard = BardOfTheBilge(
                neo4j_client=neo4j_client,
                captain_uuid=captain_uuid,
                config=bard_agent_config,
            )
            self._agent_registry["bard"] = self._bard
            logger.info(
                "[CHART] Bard initialized for response salting",
                extra={"agent_name": self.name, "captain_uuid": captain_uuid},
            )

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
        Routes to either v1 (intent-based) or v2 (Think-Dispatch-Synthesize) workflow
        based on the use_v2_workflow config flag.

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

        # Parse thread_id to extract channel_type and external_id
        # Format: "channel-uuid" (e.g., "cli-abc123", "telegram-12345")
        if "-" in thread_id:
            parts = thread_id.split("-", 1)
            channel_type = parts[0]
            external_id = parts[1] if len(parts) > 1 else thread_id
        else:
            channel_type = "cli"
            external_id = thread_id

        # Create thread BEFORE routing to v1/v2 workflow
        # thread_uuid is the actual Neo4j UUID, thread_id is the external identifier
        thread_uuid: str | None = None
        if self.thread_manager:
            try:
                thread_node = await self.thread_manager.get_or_create_thread(
                    external_id=external_id,
                    channel_type=channel_type,
                    trace_id=trace_id,
                )
                thread_uuid = thread_node.uuid
            except Exception as e:
                logger.warning(
                    f"[SWELL] Failed to create/get thread: {e}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )

        # Check config for v2 workflow flag
        use_v2 = self.config.get("use_v2_workflow", True) if self.config else True

        if use_v2:
            logger.info(
                "[CHART] Using v2 workflow (Think-Dispatch-Synthesize)",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return await self.handle_user_input_v2(
                text=text,
                thread_uuid=thread_uuid or thread_id,  # Use actual UUID if available
                trace_id=trace_id,
            )

        # Legacy v1 workflow (intent-based routing)
        logger.info(
            "[CHART] Using v1 workflow (intent-based routing)",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )
        return await self._handle_user_input_v1(
            thread_id=thread_id,
            text=text,
            context=context,
            trace_id=trace_id,
        )

    async def _handle_user_input_v1(
        self,
        thread_id: str,
        text: str,
        context: ThreadContext | None = None,
        trace_id: str | None = None,
    ) -> str:
        """
        Legacy v1 workflow: single-intent classification and routing.

        DEPRECATED: This workflow is kept for rollback purposes.
        New code should use handle_user_input_v2() directly.

        Args:
            thread_id: Thread identifier from channel.
            text: User's message content.
            context: Optional pre-loaded context window.
            trace_id: Request trace ID for logging.

        Returns:
            Response text to send back to user.
        """
        trace_id = trace_id or f"orch-{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        logger.info(
            "[CHART] Processing user input (v1 workflow)",
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
            # Capture message UUID for entity linking (Bug #350)
            user_message_uuid: str | None = None
            if self.thread_manager:
                try:
                    user_message = await self.thread_manager.add_message(
                        thread_uuid=thread_uuid,
                        role="user",
                        content=text,
                        trace_id=trace_id,
                    )
                    user_message_uuid = user_message.uuid
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
                self._track_background_task(
                    self._ingest_conversation(
                        text, response_text, trace_id, message_uuid=user_message_uuid
                    ),
                    trace_id=trace_id,
                    task_name=f"ingest-v1-{trace_id}",
                )

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                "[BEACON] Response generated (v1)",
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
        message_uuid: str | None = None,
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

        After ingestion, creates MENTIONED_IN relationships between extracted
        entities and the source Message node (Bug #350 fix).

        Args:
            user_text: User's message to ingest.
            _assistant_text: Reserved for future use (currently ignored).
            trace_id: Request trace ID.
            message_uuid: UUID of the Message node to link entities to.
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
            episode_name = await self.graphiti.add_episode(
                content=cleaned_text,
                source="conversation",
                trace_id=trace_id,
            )

            logger.debug(
                "[WHISPER] Conversation ingested to Graphiti",
                extra={"trace_id": trace_id, "agent_name": self.name, "episode_name": episode_name},
            )

            # Link extracted entities to the message (Bug #350 fix)
            if message_uuid and self.neo4j_client:
                await self._link_ingested_entities_to_message(
                    episode_name=episode_name,
                    message_uuid=message_uuid,
                    trace_id=trace_id,
                )

        except Exception as e:
            # Don't fail the response if ingestion fails
            logger.warning(
                f"[SWELL] Ingestion failed (non-blocking): {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

    async def _link_ingested_entities_to_message(
        self,
        episode_name: str,
        message_uuid: str,
        trace_id: str,
    ) -> None:
        """
        Link entities extracted by Graphiti to the source message.

        After Graphiti ingestion, queries for entities created by that episode
        and creates MENTIONED_IN relationships to the Message node.

        This enables queries like "What did I talk about with John?" to find
        the specific message where John was mentioned.

        Bug #350 fix: Closes the gap between Graphiti extraction and message linking.

        Args:
            episode_name: Name of the Graphiti episode (from add_episode).
            message_uuid: UUID of the Message node to link entities to.
            trace_id: Request trace ID for logging.
        """
        if not self.graphiti or not self.neo4j_client:
            return

        try:
            # Get entities extracted by this episode
            entities = await self.graphiti.get_entities_from_episode(
                episode_name=episode_name,
                trace_id=trace_id,
            )

            if not entities:
                logger.debug(
                    "[WHISPER] No entities found from episode to link",
                    extra={
                        "trace_id": trace_id,
                        "episode_name": episode_name,
                        "message_uuid": message_uuid[:8],
                    },
                )
                return

            # Convert to EntityReference objects for link_entities_to_message
            from klabautermann.agents.researcher_models import EntityReference

            entity_refs = [
                EntityReference(
                    uuid=e["uuid"],
                    name=e.get("name", "Unknown"),
                    entity_type=e.get("labels", ["Entity"])[0] if e.get("labels") else "Entity",
                    confidence=1.0,  # High confidence since Graphiti extracted them
                    source_technique="graphiti_ingestion",
                )
                for e in entities
            ]

            # Create MENTIONED_IN relationships
            link_count = await link_entities_to_message(
                neo4j=self.neo4j_client,
                message_uuid=message_uuid,
                entity_refs=entity_refs,
                trace_id=trace_id,
            )

            logger.info(
                f"[BEACON] Linked {link_count} ingested entities to message",
                extra={
                    "trace_id": trace_id,
                    "episode_name": episode_name,
                    "message_uuid": message_uuid[:8],
                    "entity_count": len(entities),
                    "link_count": link_count,
                },
            )

        except Exception as e:
            # Non-blocking: log but don't fail
            logger.warning(
                f"[SWELL] Entity linking failed (non-blocking): {e}",
                extra={
                    "trace_id": trace_id,
                    "episode_name": episode_name,
                    "message_uuid": message_uuid[:8],
                },
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
    # Background Task Tracking (T074)
    # =========================================================================

    def _track_background_task(
        self,
        coro: Any,
        trace_id: str,
        task_name: str = "background_task",
    ) -> asyncio.Task[Any]:
        """
        Create and track a background task to prevent garbage collection.

        This ensures fire-and-forget tasks don't get GC'd before completion
        and provides monitoring of task lifecycle.

        Args:
            coro: Coroutine to run in background.
            trace_id: Request trace ID for logging.
            task_name: Human-readable task name for debugging.

        Returns:
            The created asyncio.Task.
        """
        task = asyncio.create_task(coro, name=task_name)
        self._background_tasks.add(task)

        def _on_done(t: asyncio.Task[Any]) -> None:
            """Callback when task completes or fails."""
            self._background_tasks.discard(t)
            if t.exception():
                logger.warning(
                    f"[SWELL] Background task failed: {t.get_name()}",
                    extra={
                        "trace_id": trace_id,
                        "agent_name": self.name,
                        "error": str(t.exception()),
                    },
                )
            else:
                logger.debug(
                    f"[WHISPER] Background task completed: {t.get_name()}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )

        task.add_done_callback(_on_done)
        return task

    def _get_background_task_count(self) -> int:
        """
        Get count of currently running background tasks.

        Used for health checks and monitoring.

        Returns:
            Number of background tasks currently tracked.
        """
        return len(self._background_tasks)

    async def shutdown(self) -> None:
        """
        Cancel all background tasks and clean up on shutdown.

        This ensures graceful shutdown by cancelling any pending
        fire-and-forget tasks and waiting for them to complete.
        """
        if not self._background_tasks:
            logger.info(
                "[CHART] No background tasks to cancel",
                extra={"agent_name": self.name},
            )
            return

        logger.info(
            f"[CHART] Cancelling {len(self._background_tasks)} background tasks",
            extra={"agent_name": self.name},
        )

        # Cancel all tasks
        for task in self._background_tasks:
            task.cancel()

        # Wait for cancellation with exceptions suppressed
        await asyncio.gather(*self._background_tasks, return_exceptions=True)

        logger.info(
            "[CHART] All background tasks cancelled",
            extra={"agent_name": self.name},
        )

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
            # AI-First: No keyword fallback - return CONVERSATION with low confidence
            # This ensures the system degrades gracefully while maintaining semantic purity
            # Issue #2 (AGT-P-001): Remove keyword-based intent classification
            logger.warning(
                f"[SWELL] LLM classification failed, defaulting to CONVERSATION: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return IntentClassification(
                type=IntentType.CONVERSATION,
                confidence=0.3,  # Low confidence signals classification uncertainty
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

    def _load_bard_config(self) -> dict[str, Any]:
        """
        Load Bard configuration from config manager.

        Returns:
            Bard configuration dictionary with defaults if not available.
        """
        try:
            from klabautermann.config.manager import ConfigManager

            config_manager = ConfigManager()
            bard_config = config_manager.get("bard")
            if bard_config:
                return bard_config.model_dump()
        except Exception as e:
            logger.warning(
                f"[SWELL] Could not load bard config: {e}",
                extra={"agent_name": self.name},
            )

        # Return sensible defaults if config not available
        return {
            "enabled": True,
            "tidbit_probability": 0.07,
            "saga_continuation_probability": 0.3,
            "saga_rules": {
                "max_chapters": 5,
                "max_active": 3,
                "timeout_days": 30,
                "min_interval_hours": 1.0,
            },
            "storm_mode": {
                "enabled": True,
                "keywords": ["urgent", "emergency", "critical", "asap"],
            },
            "display": {
                "format": "italic",
                "separator": "\n\n",
            },
        }

    def _detect_storm_mode(self, response: str) -> bool:
        """
        Detect if response should be in "storm mode" (urgent, no tidbits).

        Args:
            response: Response text to analyze.

        Returns:
            True if storm mode should be active.
        """
        storm_config = self._bard_config.get("storm_mode", {})
        if not storm_config.get("enabled", True):
            return False

        keywords = storm_config.get("keywords", ["urgent", "emergency", "critical", "asap"])
        response_lower = response.lower()
        return any(keyword.lower() in response_lower for keyword in keywords)

    async def _apply_personality(
        self,
        response: str,
        trace_id: str,
    ) -> str:
        """
        Apply Klabautermann personality formatting to response.

        Invokes the Bard for response "salting" with nautical flair.
        The Bard may add tidbits or continue sagas based on probability
        and configuration.

        Args:
            response: Raw response text.
            trace_id: Request trace ID.

        Returns:
            Response with personality applied (possibly with tidbit).
        """
        # If Bard is not initialized, pass through
        if self._bard is None:
            logger.debug(
                "[WHISPER] Personality applied (pass-through, no Bard)",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return response

        # Check storm mode - no tidbits during urgent responses
        storm_mode = self._detect_storm_mode(response)

        try:
            # Invoke the Bard for response salting
            salt_result = await self._bard.salt_response(
                clean_response=response,
                storm_mode=storm_mode,
                trace_id=trace_id,
            )

            if salt_result.tidbit_added:
                logger.info(
                    f"[BEACON] Bard added tidbit (saga={salt_result.saga_id or 'standalone'})",
                    extra={
                        "trace_id": trace_id,
                        "agent_name": self.name,
                        "tidbit_added": True,
                        "is_continuation": salt_result.is_continuation,
                        "chapter": salt_result.chapter,
                    },
                )
                return salt_result.salted_response

            logger.debug(
                "[WHISPER] Personality applied (Bard skipped tidbit)",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return response

        except Exception as e:
            # Log error but don't fail the response
            logger.warning(
                f"[SWELL] Bard error, using unsalted response: {e}",
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

        # Check for skill matches before LLM planning
        skill_match = self._skill_planner.match_and_plan(text, trace_id)
        if skill_match:
            skill, planned_task = skill_match
            logger.info(
                f"[BEACON] Skill matched, bypassing LLM planning: {skill.name}",
                extra={"trace_id": trace_id, "skill": skill.name},
            )
            return TaskPlan(
                reasoning=f"Matched skill: {skill.name}",
                tasks=[planned_task],
                direct_response=None,
            )

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

    async def _call_llm_with_fallback(
        self,
        prompt: str,
        trace_id: str,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        max_tokens: int = 2000,
    ) -> str:
        """
        Call LLM with automatic fallback on failure.

        Tries primary model first with timeout, falls back to fallback model if:
        - Primary model times out
        - Primary model raises an exception
        - Fallback model is configured (not None)

        Args:
            prompt: The prompt to send to the LLM
            trace_id: Request trace ID for logging
            primary_model: Override primary model (defaults to config_v2.model)
            fallback_model: Override fallback model (defaults to config_v2.fallback_model)
            max_tokens: Maximum tokens in response

        Returns:
            Response text from LLM

        Raises:
            Exception: If primary fails and no fallback configured, or if fallback also fails
        """
        # Load v2 config
        config = self._load_v2_config()

        # Determine models to use
        primary = primary_model or config.get("model", "claude-opus-4-5-20251101")
        fallback = fallback_model or config.get("fallback_model")

        # Get timeout from config
        timeout = config.get("timeouts", {}).get("llm_call", 60.0)

        loop = asyncio.get_event_loop()

        def _sync_call(model: str) -> str:
            response = self.anthropic.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text: str = response.content[0].text
            return text

        # Try primary model
        try:
            logger.debug(
                f"[WHISPER] Calling primary model ({primary})",
                extra={"trace_id": trace_id, "agent_name": self.name, "model": primary},
            )

            response = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: _sync_call(primary)), timeout=timeout
            )

            return response

        except (TimeoutError, Exception) as e:
            # Log the failure
            logger.warning(
                f"[SWELL] Primary model failed: {type(e).__name__}: {e}",
                extra={"trace_id": trace_id, "error": str(e), "primary_model": primary},
            )

            # If no fallback configured, re-raise
            if not fallback:
                logger.error(
                    "[STORM] No fallback model configured, propagating error",
                    extra={"trace_id": trace_id},
                )
                raise

            # Try fallback model
            logger.warning(
                f"[SWELL] Attempting fallback to {fallback}",
                extra={"trace_id": trace_id, "fallback_model": fallback},
            )

            try:
                response = await loop.run_in_executor(None, lambda: _sync_call(fallback))

                logger.info(
                    "[BEACON] Fallback model succeeded",
                    extra={"trace_id": trace_id, "fallback_model": fallback},
                )

                return response

            except Exception as fallback_error:
                logger.error(
                    f"[STORM] Fallback model also failed: {fallback_error}",
                    extra={"trace_id": trace_id, "fallback_model": fallback},
                )
                raise

    async def _call_opus_for_planning(self, prompt: str, trace_id: str) -> str:
        """
        Call Claude Opus with JSON mode for task planning.

        Uses _call_llm_with_fallback for automatic fallback to Sonnet if Opus fails.
        """
        return await self._call_llm_with_fallback(prompt=prompt, trace_id=trace_id, max_tokens=2000)

    def _parse_task_plan(self, response: str, trace_id: str) -> TaskPlan:
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
        task_plan = TaskPlan.model_validate(data)

        # Apply deduplication to tasks (T072)
        if task_plan.tasks:
            task_plan.tasks = self._deduplicate_tasks(task_plan.tasks, trace_id)

        return task_plan

    # =========================================================================
    # Orchestrator v2 Task Deduplication (T072)
    # =========================================================================

    def _deduplicate_tasks(self, tasks: list[PlannedTask], trace_id: str) -> list[PlannedTask]:
        """
        Merge similar tasks to avoid redundant work.

        Rules:
        - Never dedupe ingest tasks (each fact is unique)
        - Merge similar research queries (same entity/topic)
        - Merge execute tasks only if same action type
        - Log when deduplication occurs

        Args:
            tasks: List of planned tasks from LLM
            trace_id: For logging

        Returns:
            Deduplicated list of tasks

        Reference: T072 - Task Deduplication
        """
        if len(tasks) <= 1:
            return tasks

        deduplicated = []
        seen_queries: dict[str, int] = {}  # key -> index in deduplicated list

        for task in tasks:
            # Never dedupe ingestion - each fact matters
            if task.task_type == "ingest":
                deduplicated.append(task)
                continue

            # Generate a key for similarity check
            key = self._task_similarity_key(task)

            if key in seen_queries:
                # Merge with existing task
                existing_idx = seen_queries[key]
                deduplicated[existing_idx] = self._merge_tasks(deduplicated[existing_idx], task)
                logger.debug(
                    f"[WHISPER] Merged duplicate task: {task.description[:50]}",
                    extra={"trace_id": trace_id, "similarity_key": key},
                )
            else:
                seen_queries[key] = len(deduplicated)
                deduplicated.append(task)

        if len(deduplicated) < len(tasks):
            logger.info(
                f"[WHISPER] Deduplicated {len(tasks)} -> {len(deduplicated)} tasks",
                extra={
                    "trace_id": trace_id,
                    "original_count": len(tasks),
                    "deduplicated_count": len(deduplicated),
                },
            )

        return deduplicated

    def _task_similarity_key(self, task: PlannedTask) -> str:
        """
        Generate a similarity key for task deduplication.

        For research tasks: Extract main entity/topic from query
        For execute tasks: Use action type
        For ingest tasks: Use unique ID (never dedupe)

        Args:
            task: PlannedTask to generate key for

        Returns:
            Similarity key string
        """
        if task.task_type == "research":
            query = task.payload.get("query", "") if task.payload else ""
            # Normalize query: lowercase, strip whitespace
            normalized_query = query.lower().strip()

            # Remove common query prefixes to extract the main entity/topic
            for prefix in ["search for", "find", "look up", "get", "what about", "tell me about"]:
                if normalized_query.startswith(prefix):
                    normalized_query = normalized_query[len(prefix) :].strip()
                    break

            # Extract first word as the primary entity identifier
            # This allows "Sarah" and "Sarah Johnson" to match
            words = normalized_query.split()
            topic = words[0] if words else "unknown"
            return f"research:{topic}"

        elif task.task_type == "execute":
            action = task.payload.get("action", "") if task.payload else ""
            # Normalize action type
            normalized_action = action.lower().strip()
            # Extract action verb (first word typically)
            action_verb = normalized_action.split()[0] if normalized_action else "unknown"
            return f"execute:{action_verb}"

        # Fallback: use task object ID (ensures uniqueness)
        return f"{task.task_type}:{id(task)}"

    def _merge_tasks(self, task1: PlannedTask, task2: PlannedTask) -> PlannedTask:
        """
        Merge two similar tasks into one.

        Strategy:
        - Keep longer/more detailed description
        - Merge payloads (prefer non-None values from task2)
        - Preserve blocking status (if either is blocking, result is blocking)

        Args:
            task1: First task (existing)
            task2: Second task (to merge in)

        Returns:
            Merged PlannedTask
        """
        # Choose longer description as it's likely more detailed
        merged_description = (
            task1.description
            if len(task1.description) >= len(task2.description)
            else task2.description
        )

        # Merge payloads: start with task1, update with non-None values from task2
        merged_payload = task1.payload.copy() if task1.payload else {}
        if task2.payload:
            for key, value in task2.payload.items():
                # Only override if task2's value is not None or if task1 doesn't have it
                if value is not None or key not in merged_payload:
                    merged_payload[key] = value

        # If either task is blocking, the merged task should be blocking
        merged_blocking = task1.blocking or task2.blocking

        return PlannedTask(
            task_type=task1.task_type,
            description=merged_description,
            agent=task1.agent,
            payload=merged_payload,
            blocking=merged_blocking,
        )

    # =========================================================================
    # Orchestrator v2 Parallel Execution (T055)
    # =========================================================================

    async def _execute_parallel(
        self,
        task_plan: TaskPlan,
        trace_id: str,
        original_text: str = "",
        message_uuid: str | None = None,
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
            original_text: Original user message (fallback for ingest payloads)
            message_uuid: UUID of user message for entity linking (Bug #350)

        Returns:
            Dictionary mapping task descriptions to results
        """
        # Validate and fix ingest task payloads before dispatch
        for task in task_plan.tasks:
            if task.task_type == "ingest":
                if not task.payload.get("text"):
                    logger.warning(
                        "[SWELL] Ingest task missing 'text' in payload, using original message",
                        extra={"trace_id": trace_id, "description": task.description[:50]},
                    )
                    task.payload["text"] = original_text
                # Add message_uuid for entity linking (Bug #350)
                if message_uuid:
                    task.payload["message_uuid"] = message_uuid

        blocking_count = sum(1 for t in task_plan.tasks if t.blocking)
        non_blocking_count = len(task_plan.tasks) - blocking_count

        logger.info(
            f"[CHART] Executing {len(task_plan.tasks)} tasks in parallel",
            extra={
                "trace_id": trace_id,
                "total_tasks": len(task_plan.tasks),
                "blocking_tasks": blocking_count,
                "non_blocking_tasks": non_blocking_count,
            },
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
                logger.debug(
                    f"[WHISPER] Queued blocking task: {task.task_type} -> {task.agent}",
                    extra={"trace_id": trace_id, "description": task.description[:50]},
                )
            else:
                # Fire-and-forget for non-blocking tasks (ingestion)
                self._track_background_task(
                    self._dispatch_task_fire_and_forget(task, trace_id),
                    trace_id=trace_id,
                    task_name=f"{task.task_type}-{task.agent}-{trace_id}",
                )
                logger.info(
                    f"[WHISPER] Fire-and-forget task started: {task.task_type} -> {task.agent}",
                    extra={"trace_id": trace_id, "description": task.description[:50]},
                )

        # Wait for all blocking tasks in parallel with timeout
        if blocking_coros:
            exec_start = time.time()
            try:
                task_results = await asyncio.wait_for(
                    asyncio.gather(*blocking_coros, return_exceptions=True),
                    timeout=timeout_seconds,
                )

                # Map results back to task descriptions
                for task, result in zip(blocking_tasks, task_results, strict=False):
                    if isinstance(result, Exception):
                        logger.warning(
                            f"[SWELL] Task failed: {task.description}",
                            extra={
                                "trace_id": trace_id,
                                "task_type": task.task_type,
                                "agent": task.agent,
                                "error": str(result),
                            },
                        )
                        results[task.description] = {"error": str(result)}
                    else:
                        logger.info(
                            f"[WHISPER] Task succeeded: {task.task_type}",
                            extra={
                                "trace_id": trace_id,
                                "agent": task.agent,
                                "description": task.description[:50],
                            },
                        )
                        results[task.description] = result

            except TimeoutError:
                logger.error(
                    f"[STORM] Parallel execution timed out after {timeout_seconds}s",
                    extra={
                        "trace_id": trace_id,
                        "timeout_seconds": timeout_seconds,
                        "blocking_task_count": len(blocking_tasks),
                    },
                )
                # Mark all remaining tasks as timed out
                for task in blocking_tasks:
                    if task.description not in results:
                        results[task.description] = {"error": "Execution timed out"}

            elapsed_ms = (time.time() - exec_start) * 1000
            logger.info(
                "[BEACON] Blocking tasks complete",
                extra={
                    "trace_id": trace_id,
                    "duration_ms": round(elapsed_ms, 2),
                    "result_count": len(results),
                    "success_count": sum(1 for r in results.values() if "error" not in r),
                    "error_count": sum(1 for r in results.values() if "error" in r),
                },
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

    async def _call_opus_for_synthesis(self, prompt: str, trace_id: str) -> str:
        """
        Call Claude Opus for response synthesis.

        Uses _call_llm_with_fallback for automatic fallback to Sonnet if Opus fails.
        Can use a different model via synthesis_model config.
        """
        config = self._load_v2_config()
        synthesis_model = config.get("synthesis_model", "claude-opus-4-5-20251101")

        return await self._call_llm_with_fallback(
            prompt=prompt, trace_id=trace_id, primary_model=synthesis_model, max_tokens=1000
        )

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

        start_time = time.time()
        logger.info(
            "[CHART] Starting v2 workflow",
            extra={
                "trace_id": trace_id,
                "thread_uuid": thread_uuid,
                "text_preview": text[:50],
            },
        )

        try:
            # 1. Build rich context
            ctx_start = time.time()
            context = await self._build_context_safe(thread_uuid, trace_id)
            logger.info(
                "[BEACON] Context built",
                extra={
                    "trace_id": trace_id,
                    "duration_ms": round((time.time() - ctx_start) * 1000, 2),
                    "message_count": len(context.messages),
                    "summary_count": len(context.recent_summaries),
                    "task_count": len(context.pending_tasks),
                    "entity_count": len(context.recent_entities),
                },
            )

            # Store user message in thread
            # Capture message UUID for entity linking (Bug #350)
            user_message_uuid_v2: str | None = None
            if self.thread_manager:
                try:
                    user_message = await self.thread_manager.add_message(
                        thread_uuid=thread_uuid,
                        role="user",
                        content=text,
                        trace_id=trace_id,
                    )
                    user_message_uuid_v2 = user_message.uuid
                except Exception as e:
                    logger.warning(
                        f"[SWELL] Failed to store user message: {e}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )

            # 2. Think: Plan tasks (fallback to direct response on failure)
            plan_start = time.time()
            try:
                config = self._load_v2_config()
                planning_timeout = config.get("execution", {}).get("planning_timeout_seconds", 30.0)
                task_plan = await asyncio.wait_for(
                    self._plan_tasks(text, context, trace_id),
                    timeout=planning_timeout,
                )
                logger.info(
                    "[BEACON] Task plan created",
                    extra={
                        "trace_id": trace_id,
                        "duration_ms": round((time.time() - plan_start) * 1000, 2),
                        "task_count": len(task_plan.tasks),
                        "reasoning_preview": task_plan.reasoning[:100],
                        "has_direct_response": bool(task_plan.direct_response),
                    },
                )
            except (TimeoutError, Exception) as e:
                logger.warning(
                    f"[SWELL] Task planning failed: {e}",
                    extra={
                        "trace_id": trace_id,
                        "duration_ms": round((time.time() - plan_start) * 1000, 2),
                    },
                )
                return await self._fallback_direct_response(text, context, trace_id)

            # 3. Handle direct response (no tasks needed)
            if task_plan.direct_response and not task_plan.tasks:
                logger.info(
                    "[BEACON] Direct response (no tasks)",
                    extra={"trace_id": trace_id, "response_length": len(task_plan.direct_response)},
                )
                response = task_plan.direct_response
                response = await self._apply_personality(response, trace_id)
                await self._store_response(thread_uuid, response, trace_id)
                logger.info(
                    "[CHART] V2 workflow complete (direct response)",
                    extra={
                        "trace_id": trace_id,
                        "total_duration_ms": round((time.time() - start_time) * 1000, 2),
                    },
                )
                return response

            # 4. Dispatch: Execute tasks in parallel (individual failures captured)
            exec_start = time.time()
            results = await self._execute_parallel_safe(
                task_plan, trace_id, original_text=text, message_uuid=user_message_uuid_v2
            )
            logger.info(
                "[BEACON] Parallel execution complete",
                extra={
                    "trace_id": trace_id,
                    "duration_ms": round((time.time() - exec_start) * 1000, 2),
                    "result_count": len(results),
                },
            )

            # 5. Optional: Iterative deepening
            config = self._load_v2_config()
            max_depth = config.get("execution", {}).get("max_research_depth", 2)
            current_depth = 1

            while self._needs_deeper_research(results, task_plan) and current_depth < max_depth:
                deep_start = time.time()
                logger.info(
                    f"[CHART] Deepening research (depth {current_depth + 1})",
                    extra={"trace_id": trace_id, "current_depth": current_depth},
                )
                try:
                    deeper_results = await self._deepen_research(results, context, trace_id)
                    results = self._merge_results(results, deeper_results)
                    logger.info(
                        "[WHISPER] Deepening complete",
                        extra={
                            "trace_id": trace_id,
                            "duration_ms": round((time.time() - deep_start) * 1000, 2),
                            "new_result_count": len(deeper_results),
                        },
                    )
                    current_depth += 1
                except Exception as e:
                    logger.warning(
                        f"[SWELL] Deepening research failed: {e}",
                        extra={"trace_id": trace_id},
                    )
                    break  # Stop deepening on failure, use what we have

            # 6. Synthesize: Combine results into response (fallback to results summary on failure)
            synth_start = time.time()
            try:
                synthesis_timeout = config.get("execution", {}).get(
                    "synthesis_timeout_seconds", 30.0
                )
                response = await asyncio.wait_for(
                    self._synthesize_response(text, context, results, trace_id),
                    timeout=synthesis_timeout,
                )
                logger.info(
                    "[BEACON] Synthesis complete",
                    extra={
                        "trace_id": trace_id,
                        "duration_ms": round((time.time() - synth_start) * 1000, 2),
                        "response_length": len(response),
                        "input_result_count": len(results),
                    },
                )
            except (TimeoutError, Exception) as e:
                logger.warning(
                    f"[SWELL] Synthesis failed: {e}",
                    extra={
                        "trace_id": trace_id,
                        "duration_ms": round((time.time() - synth_start) * 1000, 2),
                    },
                )
                response = self._fallback_results_summary(results)

            # 7. Apply personality and store
            response = await self._apply_personality(response, trace_id)
            message_uuid = await self._store_response(thread_uuid, response, trace_id)

            # 8. Fire-and-forget: Link entities from research to message
            if message_uuid and results and self.neo4j_client:
                self._track_background_task(
                    self._link_message_entities(message_uuid, results, trace_id),
                    trace_id=trace_id,
                    task_name=f"entity-linking-{trace_id[:8]}",
                )

            logger.info(
                "[CHART] V2 workflow complete",
                extra={
                    "trace_id": trace_id,
                    "total_duration_ms": round((time.time() - start_time) * 1000, 2),
                    "response_length": len(response),
                },
            )

            return response

        except Exception as e:
            logger.error(
                f"[STORM] V2 workflow failed: {e}",
                extra={
                    "trace_id": trace_id,
                    "elapsed_ms": round((time.time() - start_time) * 1000, 2),
                },
                exc_info=True,
            )
            # Fallback to error response
            return "I'm having trouble processing that right now. Please try again."

    # =========================================================================
    # Orchestrator v2 Error Handling Helpers (T068)
    # =========================================================================

    async def _build_context_safe(
        self,
        thread_uuid: str,
        trace_id: str,
    ) -> EnrichedContext:
        """
        Build context with partial failure tolerance.

        If individual context queries fail (recent summaries, pending tasks, etc.),
        use empty defaults rather than failing the entire workflow.

        This allows the system to continue with partial context when some
        memory layers are unavailable.

        Args:
            thread_uuid: UUID of the current thread
            trace_id: For logging and tracing

        Returns:
            EnrichedContext with successfully loaded data (uses empty defaults for failures)
        """
        logger.debug(
            "[WHISPER] Building context with failure tolerance",
            extra={"trace_id": trace_id, "thread_uuid": thread_uuid},
        )

        # Load config for context parameters
        config = self._load_v2_config()
        context_config = config.get("context", {})

        # Parallel context gathering with return_exceptions=True
        # This allows individual queries to fail without stopping others
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

        logger.debug(
            f"[WHISPER] Safe context built: {len(messages)} msgs, {len(summaries)} summaries, "
            f"{len(tasks)} tasks, {len(entities)} entities",
            extra={"trace_id": trace_id},
        )

        return context

    async def _fallback_direct_response(
        self,
        text: str,
        context: EnrichedContext,
        trace_id: str,
    ) -> str:
        """
        Fallback when task planning fails - simple LLM call without decomposition.

        This is a degraded mode that bypasses the Think-Dispatch-Synthesize pattern
        and just calls Claude directly with the context.

        Args:
            text: User's message
            context: Enriched context (may be partial)
            trace_id: For logging

        Returns:
            Direct response from Claude
        """
        logger.info(
            "[CHART] Using fallback direct response",
            extra={"trace_id": trace_id},
        )

        try:
            # Build simple messages list from context
            messages = []

            # Add recent messages for continuity
            if context.messages:
                for msg in context.messages[-5:]:  # Last 5 messages
                    messages.append(
                        {
                            "role": msg.get("role", "user"),
                            "content": msg.get("content", ""),
                        }
                    )

            # Add current user message
            messages.append({"role": "user", "content": text})

            # Call Claude directly
            response = await asyncio.wait_for(
                self._call_claude(messages, trace_id),
                timeout=30.0,
            )

            logger.info(
                "[BEACON] Fallback response generated",
                extra={"trace_id": trace_id, "response_length": len(response)},
            )

            return response

        except Exception as e:
            logger.error(
                f"[STORM] Fallback response failed: {e}",
                extra={"trace_id": trace_id},
                exc_info=True,
            )
            return "I'm having trouble processing that right now. Please try again."

    def _fallback_results_summary(
        self,
        results: dict[str, Any],
    ) -> str:
        """
        Fallback when synthesis fails - format raw results as user-friendly text.

        This is a simple formatter that doesn't require LLM calls.

        Args:
            results: Dictionary mapping task descriptions to results

        Returns:
            User-friendly summary of results
        """
        if not results:
            return "I processed your request but couldn't find any relevant information."

        # Separate successful results from errors
        successful = []
        failed = []

        for task_desc, result in results.items():
            if isinstance(result, dict) and "error" in result:
                failed.append(f"- {task_desc}: {result['error']}")
            elif isinstance(result, dict):
                response = result.get("response", result)
                if response and str(response).strip():
                    successful.append(f"- {task_desc}: {str(response)[:200]}")

        # Build response
        parts = []

        if successful:
            parts.append("Here's what I found:")
            parts.extend(successful[:3])  # Limit to 3 results

        if failed:
            parts.append("\nSome tasks encountered issues:")
            parts.extend(failed[:2])  # Limit to 2 errors

        if not successful and not failed:
            return "I processed your request but couldn't find any relevant information."

        return "\n".join(parts)

    async def _execute_parallel_safe(
        self,
        task_plan: TaskPlan,
        trace_id: str,
        original_text: str = "",
        message_uuid: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute all planned tasks in parallel with individual failure capture.

        This wraps _execute_parallel to ensure that:
        - Individual task failures don't stop other tasks
        - All failures are captured and logged with trace_id
        - The workflow can continue with partial results

        Args:
            task_plan: TaskPlan from _plan_tasks()
            trace_id: For logging
            original_text: Original user message (fallback for ingest payloads)
            message_uuid: UUID of user message for entity linking (Bug #350)

        Returns:
            Dictionary mapping task descriptions to results (includes errors)
        """
        try:
            # Use the existing _execute_parallel which already has return_exceptions=True
            results = await self._execute_parallel(task_plan, trace_id, original_text, message_uuid)

            # Count successes and failures
            success_count = sum(
                1 for r in results.values() if isinstance(r, dict) and "error" not in r
            )
            failure_count = len(results) - success_count

            if failure_count > 0:
                logger.warning(
                    f"[SWELL] Parallel execution had {failure_count} failures out of {len(results)} tasks",
                    extra={"trace_id": trace_id},
                )

            return results

        except Exception as e:
            logger.error(
                f"[STORM] Parallel execution failed entirely: {e}",
                extra={"trace_id": trace_id},
                exc_info=True,
            )
            # Return empty results rather than crashing
            return {}

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

    async def _link_message_entities(
        self,
        message_uuid: str,
        results: dict[str, Any],
        trace_id: str,
    ) -> None:
        """
        Fire-and-forget: Link entities found by researcher to message.

        Extracts key_entity_refs from research results and creates
        MENTIONED_IN relationships in the knowledge graph.

        Args:
            message_uuid: UUID of the message to link entities to.
            results: Results dict from parallel execution (contains researcher report).
            trace_id: Request trace ID for logging.
        """
        if not self.neo4j_client:
            logger.debug(
                "[WHISPER] Neo4j client unavailable, skipping entity linking",
                extra={"trace_id": trace_id},
            )
            return

        # Extract entity refs from researcher results
        entity_refs = []
        for agent_name, result in results.items():
            if agent_name == "researcher" and isinstance(result, dict):
                report = result.get("report")
                if report and hasattr(report, "key_entity_refs"):
                    entity_refs = report.key_entity_refs
                    break
                # Also check if report is a dict
                elif isinstance(report, dict):
                    refs_data = report.get("key_entity_refs", [])
                    # Convert dicts to EntityReference objects
                    from klabautermann.agents.researcher_models import EntityReference

                    for ref_dict in refs_data:
                        if isinstance(ref_dict, dict) and "uuid" in ref_dict:
                            entity_refs.append(
                                EntityReference(
                                    uuid=ref_dict["uuid"],
                                    name=ref_dict.get("name", "Entity"),
                                    entity_type=ref_dict.get("entity_type", "Entity"),
                                    confidence=ref_dict.get("confidence", 0.5),
                                    source_technique=ref_dict.get("source_technique", ""),
                                )
                            )
                    break

        if not entity_refs:
            logger.debug(
                "[WHISPER] No entity refs to link to message",
                extra={"trace_id": trace_id, "message_uuid": message_uuid},
            )
            return

        try:
            link_count = await link_entities_to_message(
                neo4j=self.neo4j_client,
                message_uuid=message_uuid,
                entity_refs=entity_refs,
                trace_id=trace_id,
            )
            logger.info(
                f"[BEACON] Linked {link_count} entities to message",
                extra={
                    "trace_id": trace_id,
                    "message_uuid": message_uuid,
                    "link_count": link_count,
                },
            )
        except Exception as e:
            logger.warning(
                f"[SWELL] Entity linking failed: {e}",
                extra={"trace_id": trace_id, "message_uuid": message_uuid},
            )

    async def _store_response(
        self,
        thread_uuid: str,
        response: str,
        trace_id: str,
    ) -> str | None:
        """
        Store the response in the thread.

        Returns:
            Message UUID if stored successfully, None otherwise.
        """
        if self.thread_manager:
            try:
                message = await self.thread_manager.add_message(
                    thread_uuid=thread_uuid,
                    role="assistant",
                    content=response,
                    trace_id=trace_id,
                )
                return message.uuid
            except Exception as e:
                logger.warning(
                    f"[SWELL] Failed to store response: {e}", extra={"trace_id": trace_id}
                )
        return None


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Orchestrator"]
