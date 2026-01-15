"""
Graph ontology constants for Klabautermann.

Defines all valid node labels and relationship types for the temporal knowledge graph.
These enums serve as the source of truth for database initialization and query validation.

Reference: specs/architecture/ONTOLOGY.md
"""

from enum import Enum

from pydantic import BaseModel, Field


# ===========================================================================
# Entity Type Models for Graphiti
# ===========================================================================
# These Pydantic models define entity types for Graphiti's extraction.
# The docstrings and field descriptions guide Graphiti's LLM to extract
# structured attributes from conversations.
#
# Per Zep/Graphiti docs: Custom entity types REQUIRE at least one field
# with a description to guide extraction effectively.


class PersonType(BaseModel):
    """A human individual - employee, contact, family member, friend, or acquaintance."""

    email: str | None = Field(description="Email address of the person", default=None)
    title: str | None = Field(description="Job title, role, or position", default=None)
    phone: str | None = Field(description="Phone number", default=None)


class OrganizationType(BaseModel):
    """A company, institution, team, government body, or organized group."""

    industry: str | None = Field(
        description="Industry or sector (tech, finance, healthcare, etc.)", default=None
    )
    domain: str | None = Field(description="Website domain (e.g., acme.com)", default=None)


class ProjectType(BaseModel):
    """A work project, initiative, product, or collaborative effort."""

    status: str | None = Field(
        description="Project status: active, on_hold, completed, cancelled", default=None
    )
    deadline: str | None = Field(description="Project deadline or due date", default=None)


class LocationType(BaseModel):
    """A physical place - city, country, building, venue, neighborhood, or address."""

    address: str | None = Field(description="Street address or full address", default=None)
    location_type: str | None = Field(
        description="Type of location: city, office, venue, home, restaurant", default=None
    )


class EventType(BaseModel):
    """A meeting, conference, appointment, deadline, or scheduled occurrence."""

    start_time: str | None = Field(description="When the event starts (date/time)", default=None)
    event_location: str | None = Field(description="Where the event takes place", default=None)


class TaskType(BaseModel):
    """An action item, to-do, assignment, or work task."""

    status: str | None = Field(
        description="Task status: todo, in_progress, done, cancelled", default=None
    )
    priority: str | None = Field(description="Task priority: high, medium, low", default=None)
    due_date: str | None = Field(description="When the task is due", default=None)


# Entity types dict for Graphiti's add_episode()
ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Person": PersonType,
    "Organization": OrganizationType,
    "Project": ProjectType,
    "Location": LocationType,
    "Event": EventType,
    "Task": TaskType,
}


# ===========================================================================
# Node Labels Enum
# ===========================================================================


class NodeLabel(str, Enum):
    """Valid node labels for the knowledge graph."""

    # Core Entities
    PERSON = "Person"
    ORGANIZATION = "Organization"
    PROJECT = "Project"
    GOAL = "Goal"
    TASK = "Task"
    EVENT = "Event"
    LOCATION = "Location"
    NOTE = "Note"
    RESOURCE = "Resource"

    # Personal Life Entities
    HOBBY = "Hobby"
    HEALTH_METRIC = "HealthMetric"
    PET = "Pet"
    MILESTONE = "Milestone"
    ROUTINE = "Routine"
    PREFERENCE = "Preference"
    COMMUNITY = "Community"
    LORE_EPISODE = "LoreEpisode"

    # System Entities
    THREAD = "Thread"
    MESSAGE = "Message"
    DAY = "Day"
    JOURNAL_ENTRY = "JournalEntry"
    TAG = "Tag"


class RelationType(str, Enum):
    """Valid relationship types for the knowledge graph."""

    # Professional Context
    WORKS_AT = "WORKS_AT"
    REPORTS_TO = "REPORTS_TO"
    AFFILIATED_WITH = "AFFILIATED_WITH"

    # Action Hierarchy
    CONTRIBUTES_TO = "CONTRIBUTES_TO"
    PART_OF = "PART_OF"
    SUBTASK_OF = "SUBTASK_OF"
    BLOCKS = "BLOCKS"
    DEPENDS_ON = "DEPENDS_ON"
    ASSIGNED_TO = "ASSIGNED_TO"

    # Spatial Context
    HELD_AT = "HELD_AT"
    LOCATED_IN = "LOCATED_IN"
    CREATED_AT_LOCATION = "CREATED_AT_LOCATION"

    # Knowledge Linking
    REFERENCES = "REFERENCES"
    SUMMARIZES = "SUMMARIZES"
    SUMMARY_OF = "SUMMARY_OF"
    MENTIONED_IN = "MENTIONED_IN"
    DISCUSSED = "DISCUSSED"

    # Event Context
    ATTENDED = "ATTENDED"
    ORGANIZED_BY = "ORGANIZED_BY"

    # Information Lineage
    VERSION_OF = "VERSION_OF"
    REPLIES_TO = "REPLIES_TO"
    ATTACHED_TO = "ATTACHED_TO"

    # Interpersonal Context
    KNOWS = "KNOWS"
    INTRODUCED_BY = "INTRODUCED_BY"

    # Family & Personal Relationships
    FAMILY_OF = "FAMILY_OF"
    SPOUSE_OF = "SPOUSE_OF"
    PARENT_OF = "PARENT_OF"
    CHILD_OF = "CHILD_OF"
    SIBLING_OF = "SIBLING_OF"
    FRIEND_OF = "FRIEND_OF"

    # Personal Life
    PRACTICES = "PRACTICES"
    INTERESTED_IN = "INTERESTED_IN"
    PREFERS = "PREFERS"
    OWNS = "OWNS"
    CARES_FOR = "CARES_FOR"
    RECORDED = "RECORDED"
    ACHIEVES = "ACHIEVES"
    FOLLOWS_ROUTINE = "FOLLOWS_ROUTINE"

    # Community (Knowledge Islands)
    PART_OF_ISLAND = "PART_OF_ISLAND"

    # Lore System (Progressive Storytelling)
    EXPANDS_UPON = "EXPANDS_UPON"
    TOLD_TO = "TOLD_TO"
    SAGA_STARTED_BY = "SAGA_STARTED_BY"

    # Thread Management
    CONTAINS = "CONTAINS"
    PRECEDES = "PRECEDES"

    # Temporal Spine
    OCCURRED_ON = "OCCURRED_ON"

    # Categorization
    TAGGED_WITH = "TAGGED_WITH"


# ===========================================================================
# Status Enums
# ===========================================================================


class ProjectStatus(str, Enum):
    """Valid status values for Project nodes."""

    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    """Valid status values for Task nodes."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class GoalStatus(str, Enum):
    """Valid status values for Goal nodes."""

    ACTIVE = "active"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"


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


# ===========================================================================
# Database Constraints (ONTOLOGY.md Section 4.1)
# ===========================================================================

# Uniqueness constraints - work on all Neo4j editions
CONSTRAINTS: list[str] = [
    # Core entity UUID constraints
    "CREATE CONSTRAINT person_uuid IF NOT EXISTS FOR (p:Person) REQUIRE p.uuid IS UNIQUE",
    "CREATE CONSTRAINT organization_uuid IF NOT EXISTS FOR (o:Organization) REQUIRE o.uuid IS UNIQUE",
    "CREATE CONSTRAINT project_uuid IF NOT EXISTS FOR (p:Project) REQUIRE p.uuid IS UNIQUE",
    "CREATE CONSTRAINT goal_uuid IF NOT EXISTS FOR (g:Goal) REQUIRE g.uuid IS UNIQUE",
    "CREATE CONSTRAINT task_uuid IF NOT EXISTS FOR (t:Task) REQUIRE t.uuid IS UNIQUE",
    "CREATE CONSTRAINT event_uuid IF NOT EXISTS FOR (e:Event) REQUIRE e.uuid IS UNIQUE",
    "CREATE CONSTRAINT location_uuid IF NOT EXISTS FOR (l:Location) REQUIRE l.uuid IS UNIQUE",
    "CREATE CONSTRAINT note_uuid IF NOT EXISTS FOR (n:Note) REQUIRE n.uuid IS UNIQUE",
    "CREATE CONSTRAINT resource_uuid IF NOT EXISTS FOR (r:Resource) REQUIRE r.uuid IS UNIQUE",
    "CREATE CONSTRAINT thread_uuid IF NOT EXISTS FOR (t:Thread) REQUIRE t.uuid IS UNIQUE",
    "CREATE CONSTRAINT message_uuid IF NOT EXISTS FOR (m:Message) REQUIRE m.uuid IS UNIQUE",
    "CREATE CONSTRAINT day_date IF NOT EXISTS FOR (d:Day) REQUIRE d.date IS UNIQUE",
    "CREATE CONSTRAINT journal_uuid IF NOT EXISTS FOR (j:JournalEntry) REQUIRE j.uuid IS UNIQUE",
    # Personal Life entity UUID constraints
    "CREATE CONSTRAINT hobby_uuid IF NOT EXISTS FOR (h:Hobby) REQUIRE h.uuid IS UNIQUE",
    "CREATE CONSTRAINT healthmetric_uuid IF NOT EXISTS FOR (h:HealthMetric) REQUIRE h.uuid IS UNIQUE",
    "CREATE CONSTRAINT pet_uuid IF NOT EXISTS FOR (p:Pet) REQUIRE p.uuid IS UNIQUE",
    "CREATE CONSTRAINT milestone_uuid IF NOT EXISTS FOR (m:Milestone) REQUIRE m.uuid IS UNIQUE",
    "CREATE CONSTRAINT routine_uuid IF NOT EXISTS FOR (r:Routine) REQUIRE r.uuid IS UNIQUE",
    "CREATE CONSTRAINT preference_uuid IF NOT EXISTS FOR (p:Preference) REQUIRE p.uuid IS UNIQUE",
    "CREATE CONSTRAINT community_uuid IF NOT EXISTS FOR (c:Community) REQUIRE c.uuid IS UNIQUE",
    "CREATE CONSTRAINT loreepisode_uuid IF NOT EXISTS FOR (le:LoreEpisode) REQUIRE le.uuid IS UNIQUE",
]

# Property existence constraints - require Neo4j Enterprise Edition
# These are optional and will be skipped on Community Edition
ENTERPRISE_CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT person_name IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS NOT NULL",
    "CREATE CONSTRAINT thread_status IF NOT EXISTS FOR (t:Thread) REQUIRE t.status IS NOT NULL",
    "CREATE CONSTRAINT hobby_name IF NOT EXISTS FOR (h:Hobby) REQUIRE h.name IS NOT NULL",
    "CREATE CONSTRAINT pet_name IF NOT EXISTS FOR (p:Pet) REQUIRE p.name IS NOT NULL",
    "CREATE CONSTRAINT routine_name IF NOT EXISTS FOR (r:Routine) REQUIRE r.name IS NOT NULL",
    "CREATE CONSTRAINT community_name IF NOT EXISTS FOR (c:Community) REQUIRE c.name IS NOT NULL",
    "CREATE CONSTRAINT loreepisode_saga IF NOT EXISTS FOR (le:LoreEpisode) REQUIRE le.saga_id IS NOT NULL",
]


# ===========================================================================
# Database Indexes (ONTOLOGY.md Section 4.2)
# ===========================================================================

INDEXES: list[str] = [
    # Full-text search indexes
    "CREATE FULLTEXT INDEX person_search IF NOT EXISTS FOR (p:Person) ON EACH [p.name, p.email, p.bio]",
    "CREATE FULLTEXT INDEX org_search IF NOT EXISTS FOR (o:Organization) ON EACH [o.name, o.description]",
    "CREATE FULLTEXT INDEX note_search IF NOT EXISTS FOR (n:Note) ON EACH [n.title, n.content_summarized]",
    "CREATE FULLTEXT INDEX project_search IF NOT EXISTS FOR (p:Project) ON EACH [p.name, p.description]",
    # Temporal indexes for time-travel queries
    "CREATE INDEX works_at_temporal IF NOT EXISTS FOR ()-[r:WORKS_AT]-() ON (r.created_at, r.expired_at)",
    "CREATE INDEX located_in_temporal IF NOT EXISTS FOR ()-[r:LOCATED_IN]-() ON (r.created_at, r.expired_at)",
    # Message traversal optimization
    "CREATE INDEX message_timestamp IF NOT EXISTS FOR (m:Message) ON (m.timestamp)",
    # Thread status for archival queries
    "CREATE INDEX thread_status IF NOT EXISTS FOR (t:Thread) ON (t.status, t.last_message_at)",
    # Task status for task management
    "CREATE INDEX task_status IF NOT EXISTS FOR (t:Task) ON (t.status, t.due_date)",
    # Spatial index for location queries
    "CREATE POINT INDEX location_coords IF NOT EXISTS FOR (l:Location) ON (l.coordinate)",
    # Personal Life indexes
    "CREATE INDEX hobby_category IF NOT EXISTS FOR (h:Hobby) ON (h.category)",
    "CREATE INDEX healthmetric_type IF NOT EXISTS FOR (h:HealthMetric) ON (h.type, h.recorded_at)",
    "CREATE INDEX pet_species IF NOT EXISTS FOR (p:Pet) ON (p.species)",
    "CREATE INDEX milestone_category IF NOT EXISTS FOR (m:Milestone) ON (m.category, m.achieved_at)",
    "CREATE INDEX routine_frequency IF NOT EXISTS FOR (r:Routine) ON (r.frequency, r.is_active)",
    "CREATE INDEX preference_category IF NOT EXISTS FOR (p:Preference) ON (p.category, p.sentiment)",
    # Community/Island indexes
    "CREATE INDEX community_theme IF NOT EXISTS FOR (c:Community) ON (c.theme)",
    "CREATE FULLTEXT INDEX community_search IF NOT EXISTS FOR (c:Community) ON EACH [c.name, c.summary]",
    # Lore System indexes
    "CREATE INDEX loreepisode_saga IF NOT EXISTS FOR (le:LoreEpisode) ON (le.saga_id, le.chapter)",
    "CREATE INDEX loreepisode_told IF NOT EXISTS FOR (le:LoreEpisode) ON (le.told_at)",
    # Family relationship temporal indexes
    "CREATE INDEX spouse_temporal IF NOT EXISTS FOR ()-[r:SPOUSE_OF]-() ON (r.created_at, r.expired_at)",
    "CREATE INDEX friend_temporal IF NOT EXISTS FOR ()-[r:FRIEND_OF]-() ON (r.created_at, r.expired_at)",
    "CREATE INDEX practices_temporal IF NOT EXISTS FOR ()-[r:PRACTICES]-() ON (r.created_at, r.expired_at)",
]


# ===========================================================================
# Vector Indexes (ONTOLOGY.md Section 4.3)
# ===========================================================================

VECTOR_INDEXES: list[str] = [
    # Vector similarity search (HNSW algorithm)
    # Note: These require OpenAI text-embedding-3-small (1536 dimensions)
    """CREATE VECTOR INDEX person_vector IF NOT EXISTS FOR (p:Person) ON (p.vector_embedding)
       OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}""",
    """CREATE VECTOR INDEX note_vector IF NOT EXISTS FOR (n:Note) ON (n.vector_embedding)
       OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}""",
    """CREATE VECTOR INDEX resource_vector IF NOT EXISTS FOR (r:Resource) ON (r.vector_embedding)
       OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}""",
]


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    # Entity type models for Graphiti
    "ENTITY_TYPES",
    "PersonType",
    "OrganizationType",
    "ProjectType",
    "LocationType",
    "EventType",
    "TaskType",
    # Enums
    "NodeLabel",
    "RelationType",
    "ProjectStatus",
    "TaskStatus",
    "GoalStatus",
    "ThreadStatus",
    "ChannelType",
    # Schema definitions
    "CONSTRAINTS",
    "ENTERPRISE_CONSTRAINTS",
    "INDEXES",
    "VECTOR_INDEXES",
]
