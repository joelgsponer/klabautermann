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
from typing import Any

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
# Export
# ===========================================================================

__all__ = [
    # Utilities
    "generate_uuid",
    "current_timestamp",
    # Base models
    "BaseNode",
    "BaseRelation",
    # Core nodes
    "PersonNode",
    "OrganizationNode",
    "ProjectNode",
    "ProjectStatus",
    "GoalNode",
    "GoalStatus",
    "TaskNode",
    "TaskStatus",
    "EventNode",
    "LocationNode",
    "NoteNode",
    "ResourceNode",
    # System nodes
    "ThreadNode",
    "ThreadStatus",
    "ChannelType",
    "MessageNode",
    "MessageRole",
    "DayNode",
    "JournalEntryNode",
    # Relations
    "WorksAtRelation",
    "KnowsRelation",
    "FamilyOfRelation",
    "FriendOfRelation",
    "AttendedRelation",
    # Agent communication
    "AgentMessage",
    "ThreadContext",
    "SearchResult",
    "EntityExtraction",
    "EntityLabel",
    "RelationshipExtraction",
    "ExtractionResult",
    # Intent classification
    "IntentType",
    "IntentClassification",
    # Action execution
    "ActionType",
    "ActionRequest",
    "ActionResult",
    # Configuration
    "AgentConfig",
    "ChannelConfig",
]
