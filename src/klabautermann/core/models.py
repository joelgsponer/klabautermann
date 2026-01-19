"""
Pydantic models for Klabautermann.

All data structures are validated through Pydantic before use.
These models define contracts between agents, graph database, and external systems.

Reference: specs/architecture/ONTOLOGY.md Section 6
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ===========================================================================
# Utility Functions
# ===========================================================================


def generate_uuid() -> str:
    """Generate a new UUID v4 string."""
    return str(uuid.uuid4())


def current_timestamp() -> float:
    """Get current Unix timestamp."""
    return time.time()


# ===========================================================================
# Base Models
# ===========================================================================


class BaseNode(BaseModel):
    """Base model for all graph nodes."""

    model_config = ConfigDict(extra="allow")

    uuid: str = Field(default_factory=generate_uuid)
    created_at: float = Field(default_factory=current_timestamp)
    updated_at: float = Field(default_factory=current_timestamp)


class BaseRelation(BaseModel):
    """Base model for temporal relationships."""

    model_config = ConfigDict(extra="allow")

    created_at: float = Field(default_factory=current_timestamp)
    expired_at: float | None = None


# ===========================================================================
# Core Entity Nodes
# ===========================================================================


class PersonNode(BaseNode):
    """Human contact in the knowledge graph."""

    name: str
    email: str | None = None
    phone: str | None = None
    bio: str | None = None
    linkedin_url: str | None = None
    twitter_handle: str | None = None
    avatar_url: str | None = None
    vector_embedding: list[float] | None = None


class OrganizationNode(BaseNode):
    """Company, group, or institution."""

    name: str
    industry: str | None = None
    website: str | None = None
    domain: str | None = None
    description: str | None = None
    logo_url: str | None = None
    vector_embedding: list[float] | None = None


class ProjectStatus(str, Enum):
    """Valid status values for Project nodes."""

    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProjectNode(BaseNode):
    """Goal-oriented endeavor."""

    name: str
    description: str | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE
    deadline: float | None = None
    priority: str | None = None
    vector_embedding: list[float] | None = None


class GoalStatus(str, Enum):
    """Valid status values for Goal nodes."""

    ACTIVE = "active"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"


class GoalNode(BaseNode):
    """High-level objective."""

    description: str
    timeframe: str | None = None
    status: GoalStatus = GoalStatus.ACTIVE
    category: str | None = None


class TaskStatus(str, Enum):
    """Valid status values for Task nodes."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskNode(BaseNode):
    """Atomic actionable item."""

    action: str
    status: TaskStatus = TaskStatus.TODO
    priority: str | None = None
    assignee: str | None = None
    due_date: float | None = None
    completed_at: float | None = None


class EventNode(BaseNode):
    """Meeting, call, or occurrence."""

    title: str
    description: str | None = None
    start_time: float
    end_time: float | None = None
    location_context: str | None = None
    is_recurring: bool = False
    calendar_id: str | None = None


class LocationNode(BaseNode):
    """Physical place."""

    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    place_id: str | None = None
    type: str | None = None  # office, home, cafe, city, venue


class NoteNode(BaseNode):
    """Knowledge artifact."""

    title: str | None = None
    content: str | None = None
    content_summarized: str | None = None
    content_format: str | None = None  # markdown, text, voice_transcript
    source: str | None = None
    vector_embedding: list[float] | None = None
    requires_user_validation: bool = False


class ResourceNode(BaseNode):
    """External link, file, or attachment."""

    url: str
    title: str | None = None
    type: str | None = None  # bookmark, pdf, email, image, video, document
    description: str | None = None
    vector_embedding: list[float] | None = None


# ===========================================================================
# System Nodes
# ===========================================================================


class ThreadStatus(str, Enum):
    """Valid status values for Thread nodes."""

    ACTIVE = "active"
    ARCHIVING = "archiving"
    ARCHIVED = "archived"


class ChannelType(str, Enum):
    """Valid channel types for Thread nodes."""

    CLI = "cli"
    TUI = "tui"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    TEST = "test"


class ThreadNode(BaseNode):
    """Conversation thread container."""

    external_id: str
    channel_type: ChannelType
    user_id: str | None = None
    status: ThreadStatus = ThreadStatus.ACTIVE
    last_message_at: float = Field(default_factory=current_timestamp)


class MessageRole(str, Enum):
    """Valid roles for Message nodes."""

    USER = "user"
    ASSISTANT = "assistant"


class MessageNode(BaseNode):
    """Individual message in a thread."""

    role: MessageRole
    content: str
    timestamp: float = Field(default_factory=current_timestamp)
    metadata: dict[str, Any] | None = None


class DayNode(BaseModel):
    """Calendar day node in temporal spine."""

    date: str  # ISO format YYYY-MM-DD
    day_of_week: str | None = None
    is_weekend: bool = False
    is_holiday: bool = False


class JournalEntryNode(BaseNode):
    """Daily reflection generated by the Scribe."""

    content: str
    summary: str | None = None
    interaction_count: int | None = None
    new_entities_count: int | None = None
    tasks_completed: int | None = None
    generated_at: float = Field(default_factory=current_timestamp)


class DailyAnalytics(BaseModel):
    """
    Aggregated statistics for a single day.

    Used by Scribe to gather data for daily journal generation.
    Reference: specs/architecture/AGENTS.md Section 1.6
    """

    date: str  # ISO format YYYY-MM-DD
    interaction_count: int
    new_entities: dict[str, int] = Field(default_factory=dict)
    tasks_completed: int
    tasks_created: int
    top_projects: list[dict[str, Any]] = Field(default_factory=list)
    notes_created: int
    events_count: int


class JournalEntry(BaseModel):
    """
    Daily journal entry generated by the Scribe.

    Contains structured reflection on the day's activities with
    Klabautermann personality. Used to create a narrative record
    of daily progress and observations.

    Reference: specs/architecture/AGENTS.md Section 1.6
    """

    content: str  # Full journal text with all sections
    summary: str  # One-line summary of the day
    highlights: list[str] = Field(default_factory=list)  # Key moments
    mood: str  # Overall sentiment (productive, challenging, calm, busy)
    forward_look: str  # What's ahead / closing thought


# ===========================================================================
# Relationship Models
# ===========================================================================


class WorksAtRelation(BaseRelation):
    """Employment relationship with temporal properties."""

    title: str | None = None
    department: str | None = None


class KnowsRelation(BaseRelation):
    """Interpersonal relationship."""

    context: str | None = None
    strength: float | None = None  # 0.0 to 1.0


class FamilyOfRelation(BaseRelation):
    """Family relationship."""

    role: str  # spouse, parent, child, sibling, grandparent, cousin, in-law


class FriendOfRelation(BaseRelation):
    """Friendship relationship."""

    since: float | None = None
    how_met: str | None = None
    strength: float | None = None  # 0.0 to 1.0


class AttendedRelation(BaseRelation):
    """Event attendance relationship."""

    role: str | None = None  # organizer, attendee, speaker, observer


# ===========================================================================
# Agent Communication Models
# ===========================================================================


class AgentMessage(BaseModel):
    """Message format for inter-agent communication."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace_id: str
    source_agent: str
    target_agent: str
    intent: str
    payload: dict[str, Any]
    timestamp: float = Field(default_factory=current_timestamp)
    priority: str = "normal"
    # Optional queue for synchronous dispatch-and-wait pattern
    response_queue: Any | None = Field(default=None, exclude=True)


# ===========================================================================
# Intent Classification Models
# ===========================================================================


class IntentType(str, Enum):
    """User intent categories for orchestrator routing."""

    SEARCH = "search"
    ACTION = "action"
    INGESTION = "ingestion"
    CONVERSATION = "conversation"


class IntentClassification(BaseModel):
    """
    Classified user intent with confidence score.

    Used by Orchestrator to route requests to appropriate sub-agents.
    Reference: specs/architecture/AGENTS.md Section 1.1
    """

    type: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    query: str | None = None  # For SEARCH intent
    action: str | None = None  # For ACTION intent
    context_query: str | None = None  # For ACTION context lookup

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class IntentClassificationResponse(BaseModel):
    """
    LLM response for intent classification.

    This model validates the structured JSON output from Claude when
    classifying user intent. It includes reasoning for debugging.
    """

    intent_type: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str  # Brief explanation for debugging/logging
    extracted_query: str | None = None  # For SEARCH: the search query
    extracted_action: str | None = None  # For ACTION: what to do


class ThreadContext(BaseModel):
    """Rolling context window for conversation."""

    thread_uuid: str
    channel_type: ChannelType
    messages: list[dict[str, Any]] = Field(default_factory=list)
    max_messages: int = 20


class SearchResult(BaseModel):
    """Search response from the knowledge graph."""

    uuid: str
    label: str
    name: str | None = None
    content: str | None = None
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityLabel(str, Enum):
    """Valid entity labels for extraction."""

    PERSON = "Person"
    ORGANIZATION = "Organization"
    PROJECT = "Project"
    LOCATION = "Location"
    EVENT = "Event"
    TASK = "Task"


class EntityExtraction(BaseModel):
    """Validated output from LLM entity extraction."""

    name: str
    label: EntityLabel
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class RelationshipExtraction(BaseModel):
    """Validated relationship extraction from LLM."""

    source_name: str
    source_label: EntityLabel
    relationship_type: str
    target_name: str
    target_label: EntityLabel
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0


class ExtractionResult(BaseModel):
    """Complete extraction result from a conversation."""

    trace_id: str
    entities: list[EntityExtraction] = Field(default_factory=list)
    relationships: list[RelationshipExtraction] = Field(default_factory=list)
    raw_text: str | None = None


# ===========================================================================
# Configuration Models
# ===========================================================================


class AgentConfig(BaseModel):
    """Configuration for an agent."""

    name: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str | None = None


class ChannelConfig(BaseModel):
    """Configuration for a channel."""

    channel_type: ChannelType
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


# ===========================================================================
# Thread Summarization Models
# ===========================================================================


class ActionStatus(str, Enum):
    """Status of action items extracted from conversation."""

    PENDING = "pending"
    COMPLETED = "completed"
    MENTIONED = "mentioned"  # Reference to existing task


class ConflictResolution(str, Enum):
    """Strategy for resolving fact contradictions."""

    EXPIRE_OLD = "expire_old"  # Mark old fact as expired
    KEEP_BOTH = "keep_both"  # Both might be valid
    USER_REVIEW = "user_review"  # Flag for human decision
    IGNORE_NEW = "ignore_new"  # Keep existing, discard new


class ActionItem(BaseModel):
    """Task/action extracted from conversation."""

    action: str
    assignee: str | None = None
    status: ActionStatus = ActionStatus.PENDING
    due_date: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class ExtractedFact(BaseModel):
    """New information to add to graph."""

    entity: str
    entity_type: str
    fact: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class FactConflict(BaseModel):
    """Contradiction with existing data."""

    existing_fact: str
    new_fact: str
    entity: str
    resolution: ConflictResolution = ConflictResolution.USER_REVIEW


class ThreadSummary(BaseModel):
    """
    Thread summary model with dual purposes:

    1. V2 Context Queries: Lightweight summaries from Note nodes for
       EnrichedContext (uses: uuid, title, summary, topics, channel, participants, created_at)

    2. Archivist Output: Full summarization with extracted facts, conflicts,
       and action items (uses all fields)

    Reference: specs/MAINAGENT.md Section 4.2, specs/architecture/AGENTS.md Section 1.5
    """

    # Core fields (used in both contexts)
    summary: str  # 2-3 sentence overview
    topics: list[str] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)

    # V2 Context fields (from Note nodes via Cypher query)
    uuid: str | None = None
    title: str | None = None
    channel: str | None = None
    created_at: float | None = None

    # Archivist-specific fields (full summarization output)
    action_items: list[ActionItem] = Field(default_factory=list)
    new_facts: list[ExtractedFact] = Field(default_factory=list)
    conflicts: list[FactConflict] = Field(default_factory=list)
    sentiment: str = "neutral"  # positive, negative, neutral, mixed


# ===========================================================================
# Orchestrator v2 Models (Think-Dispatch-Synthesize Pattern)
# ===========================================================================


class CommunityContext(BaseModel):
    """
    Summary of a Knowledge Island relevant to current context.

    Knowledge Islands are clusters of related entities and activities
    detected through community detection algorithms in the knowledge graph.
    Used by Orchestrator v2 for broad context awareness.

    Reference: specs/MAINAGENT.md Section 4.2
    """

    name: str
    theme: str
    summary: str
    pending_tasks: int = 0


class EntityReference(BaseModel):
    """
    Reference to a recently mentioned entity.

    Provides lightweight entity context for orchestrator reasoning
    without loading full entity details. Used in EnrichedContext to
    track recently active entities from Graphiti.

    Reference: specs/MAINAGENT.md Section 4.2
    """

    uuid: str
    name: str
    entity_type: str  # Person, Organization, Project, etc.
    created_at: float  # timestamp


class EnrichedContext(BaseModel):
    """
    Rich context for orchestrator reasoning.

    Integrates multiple memory layers (Short/Mid/Long-Term + Community)
    to provide comprehensive context for the Think-Dispatch-Synthesize
    workflow. This replaces simple ThreadContext in Orchestrator v2.

    Memory Layers:
    - Short-Term: Recent messages in current thread
    - Mid-Term: Summaries from other recent threads (Note nodes)
    - Long-Term: Recently mentioned entities (Graphiti)
    - Community: Knowledge Island context for broad awareness

    Reference: specs/MAINAGENT.md Section 4.2
    """

    thread_uuid: str
    channel_type: ChannelType

    # Short-Term Memory: Current conversation
    messages: list[dict[str, Any]]

    # Mid-Term Memory: Cross-thread summaries
    recent_summaries: list[ThreadSummary]

    # Active tasks/reminders
    pending_tasks: list[TaskNode]

    # Long-Term Memory: Recently mentioned entities
    recent_entities: list[EntityReference]

    # Community: Knowledge Island context
    relevant_islands: list[CommunityContext] | None = None


class PlannedTask(BaseModel):
    """
    A task identified by the orchestrator during the Think phase.

    Each task represents a unit of work to be dispatched to a subagent.
    Tasks can be blocking (wait for result) or non-blocking (fire-and-forget).

    Reference: specs/MAINAGENT.md Section 4.3
    """

    task_type: Literal["ingest", "research", "execute"]
    description: str = Field(description="Human-readable description of what this task does")
    agent: Literal["ingestor", "researcher", "executor"]
    payload: dict[str, Any] = Field(description="Agent-specific parameters for task execution")
    blocking: bool = Field(
        default=True,
        description="True if orchestrator should wait for result before synthesizing response",
    )


class TaskPlan(BaseModel):
    """
    Orchestrator's plan for handling the user message.

    Result of the Think phase - identifies all tasks needed to provide
    a complete answer. Tasks are dispatched in parallel during the
    Dispatch phase, then results are synthesized in the Synthesize phase.

    Reference: specs/MAINAGENT.md Section 4.3
    """

    reasoning: str = Field(description="Why these tasks were chosen (for debugging/logging)")
    tasks: list[PlannedTask] = Field(default_factory=list, description="All tasks to execute")
    direct_response: str | None = Field(
        default=None,
        description="If no tasks needed, respond directly with this message",
    )


# ===========================================================================
# Action Execution Models
# ===========================================================================


class ActionType(str, Enum):
    """Action types for the Executor agent."""

    EMAIL_SEND = "email_send"
    EMAIL_SEARCH = "email_search"
    CALENDAR_CREATE = "calendar_create"
    CALENDAR_LIST = "calendar_list"


class ActionRequest(BaseModel):
    """Parsed action request for Executor agent."""

    type: ActionType
    target: str | None = None  # Recipient email or calendar ID
    subject: str | None = None
    body: str | None = None
    start_time: str | None = None  # ISO format datetime string
    end_time: str | None = None  # ISO format datetime string
    draft_only: bool = False
    query: str | None = None  # For search operations


class ActionResult(BaseModel):
    """Result of action execution."""

    success: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    needs_confirmation: bool = False
    confirmation_prompt: str | None = None


# ===========================================================================
# Deduplication Models
# ===========================================================================


class DuplicateCandidate(BaseModel):
    """
    Potential duplicate entity pair detected in the knowledge graph.

    Used by the Archivist to identify entities that may represent
    the same real-world object (e.g., "Sarah" and "Sarah Johnson").

    Reference: specs/architecture/MEMORY.md Section 7.1
    """

    uuid1: str
    uuid2: str
    name1: str
    name2: str
    entity_type: str  # Person, Organization
    similarity_score: float = Field(ge=0.0, le=1.0)
    match_reasons: list[str] = Field(default_factory=list)

    @field_validator("similarity_score")
    @classmethod
    def validate_similarity_score(cls, v: float) -> float:
        """Ensure similarity score is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Similarity score must be between 0.0 and 1.0")
        return v


# ===========================================================================
# V2 Workflow Metrics
# ===========================================================================


class V2WorkflowMetrics(BaseModel):
    """
    Performance metrics for Orchestrator v2 workflow.

    Tracks request counts, latencies per phase, and task distribution
    to measure success against targets and identify bottlenecks.

    Reference: specs/MAINAGENT.md Section 10
    """

    model_config = ConfigDict(extra="forbid")

    # Request counters
    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    direct_response_count: int = 0

    # Latency tracking (in milliseconds)
    total_latency_sum: float = 0.0
    context_latency_sum: float = 0.0
    planning_latency_sum: float = 0.0
    execution_latency_sum: float = 0.0
    synthesis_latency_sum: float = 0.0

    # Task distribution
    task_count_sum: int = 0
    ingest_task_count: int = 0
    research_task_count: int = 0
    execute_task_count: int = 0

    @property
    def avg_latency_ms(self) -> float:
        """Average total latency in milliseconds."""
        if self.request_count == 0:
            return 0.0
        return self.total_latency_sum / self.request_count

    @property
    def success_rate(self) -> float:
        """Success rate as a ratio (0.0 to 1.0)."""
        if self.request_count == 0:
            return 0.0
        return self.success_count / self.request_count

    @property
    def direct_response_rate(self) -> float:
        """Direct response rate as a ratio (0.0 to 1.0)."""
        if self.request_count == 0:
            return 0.0
        return self.direct_response_count / self.request_count

    @property
    def avg_tasks_per_request(self) -> float:
        """Average number of tasks generated per request."""
        if self.request_count == 0:
            return 0.0
        return self.task_count_sum / self.request_count

    def record_request(
        self,
        success: bool,
        direct_response: bool,
        latencies: dict[str, float],
        task_counts: dict[str, int],
    ) -> None:
        """
        Record metrics for a single request.

        Args:
            success: Whether the request completed successfully.
            direct_response: Whether this was a direct response (no tasks).
            latencies: Dict with keys: total, context, planning, execution, synthesis (in ms).
            task_counts: Dict with keys: ingest, research, execute.
        """
        self.request_count += 1
        if success:
            self.success_count += 1
        else:
            self.error_count += 1

        if direct_response:
            self.direct_response_count += 1

        # Record latencies
        self.total_latency_sum += latencies.get("total", 0.0)
        self.context_latency_sum += latencies.get("context", 0.0)
        self.planning_latency_sum += latencies.get("planning", 0.0)
        self.execution_latency_sum += latencies.get("execution", 0.0)
        self.synthesis_latency_sum += latencies.get("synthesis", 0.0)

        # Record task distribution
        ingest = task_counts.get("ingest", 0)
        research = task_counts.get("research", 0)
        execute = task_counts.get("execute", 0)
        self.task_count_sum += ingest + research + execute
        self.ingest_task_count += ingest
        self.research_task_count += research
        self.execute_task_count += execute

    def to_dict(self) -> dict[str, Any]:
        """Export metrics as a dictionary for monitoring."""
        return {
            "requests": {
                "total": self.request_count,
                "success": self.success_count,
                "error": self.error_count,
                "direct_response": self.direct_response_count,
            },
            "rates": {
                "success_rate": round(self.success_rate, 3),
                "direct_response_rate": round(self.direct_response_rate, 3),
            },
            "latency_ms": {
                "avg_total": round(self.avg_latency_ms, 2),
                "sum_context": round(self.context_latency_sum, 2),
                "sum_planning": round(self.planning_latency_sum, 2),
                "sum_execution": round(self.execution_latency_sum, 2),
                "sum_synthesis": round(self.synthesis_latency_sum, 2),
            },
            "tasks": {
                "total": self.task_count_sum,
                "avg_per_request": round(self.avg_tasks_per_request, 2),
                "by_type": {
                    "ingest": self.ingest_task_count,
                    "research": self.research_task_count,
                    "execute": self.execute_task_count,
                },
            },
        }


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    # Action execution
    "ActionItem",
    "ActionRequest",
    "ActionResult",
    "ActionStatus",
    "ActionType",
    # Configuration
    "AgentConfig",
    # Agent communication
    "AgentMessage",
    "AttendedRelation",
    # Base models
    "BaseNode",
    "BaseRelation",
    "ChannelConfig",
    "ChannelType",
    # Orchestrator v2
    "CommunityContext",
    # Thread summarization
    "ConflictResolution",
    # Analytics
    "DailyAnalytics",
    "DayNode",
    # Deduplication
    "DuplicateCandidate",
    "EntityExtraction",
    "EntityLabel",
    "EntityReference",
    "EnrichedContext",
    "EventNode",
    # Extraction models
    "ExtractedFact",
    "ExtractionResult",
    # Relations
    "FamilyOfRelation",
    "FriendOfRelation",
    "FactConflict",
    "GoalNode",
    "GoalStatus",
    "IntentClassification",
    "IntentClassificationResponse",
    # Intent classification
    "IntentType",
    # Journal generation
    "JournalEntry",
    "JournalEntryNode",
    "KnowsRelation",
    "LocationNode",
    "MessageNode",
    "MessageRole",
    "NoteNode",
    "OrganizationNode",
    # Core nodes
    "PersonNode",
    "PlannedTask",
    "ProjectNode",
    "ProjectStatus",
    "RelationshipExtraction",
    "ResourceNode",
    "SearchResult",
    "TaskNode",
    "TaskPlan",
    "TaskStatus",
    "ThreadContext",
    # System nodes
    "ThreadNode",
    "ThreadStatus",
    "ThreadSummary",
    # V2 Metrics
    "V2WorkflowMetrics",
    "WorksAtRelation",
    "current_timestamp",
    # Utilities
    "generate_uuid",
]
