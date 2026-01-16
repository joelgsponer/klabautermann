"""
Pydantic models for the Intelligent Researcher agent.

Reference: specs/RESEARCHER.md Section 6
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ===========================================================================
# ENUMS
# ===========================================================================


class SearchTechnique(str, Enum):
    """Available search techniques."""

    VECTOR = "vector"
    ENTITY_FULLTEXT = "entity_fulltext"
    STRUCTURAL = "structural"
    TEMPORAL = "temporal"


class ConfidenceLevel(str, Enum):
    """Human-readable confidence levels."""

    HIGH = "high"  # 0.8-1.0
    MEDIUM = "medium"  # 0.5-0.8
    LOW = "low"  # 0.3-0.5
    UNCERTAIN = "uncertain"  # 0.0-0.3


class ZoomLevel(str, Enum):
    """Zoom levels for retrieval granularity."""

    AUTO = "auto"
    MACRO = "macro"  # Knowledge Islands, broad themes
    MESO = "meso"  # Projects, Notes, mid-level context
    MICRO = "micro"  # Entity facts, specific details


# ===========================================================================
# SEARCH PLANNING MODELS
# ===========================================================================


class TimeRange(BaseModel):
    """Time range for temporal queries."""

    start: float | None = Field(default=None, description="Start timestamp (Unix)")
    end: float | None = Field(default=None, description="End timestamp (Unix)")
    as_of: float | None = Field(default=None, description="Point-in-time for time-travel")
    relative: str | None = Field(default=None, description="Original expression ('last week')")


class SearchStrategy(BaseModel):
    """Single search strategy within a plan."""

    technique: SearchTechnique
    query: str | None = Field(default=None, description="Search string for VECTOR/ENTITY")
    cypher_pattern: str | None = Field(
        default=None, description="Relationship type or raw Cypher for STRUCTURAL"
    )
    params: dict[str, Any] = Field(default_factory=dict, description="Cypher parameters")
    time_range: TimeRange | None = Field(default=None, description="Time constraints")
    limit: int = Field(default=10, ge=1, le=100)
    consider_strength: bool = Field(
        default=False, description="Factor relationship strength into ranking"
    )
    rationale: str = Field(default="", description="Why this technique was chosen")

    @field_validator("technique", mode="before")
    @classmethod
    def normalize_technique(cls, v: Any) -> str:
        """Handle case-insensitive technique values from LLM."""
        if isinstance(v, str):
            return v.lower()
        return str(v)


class SearchPlan(BaseModel):
    """LLM-generated search plan."""

    original_query: str
    reasoning: str = Field(default="", description="LLM's reasoning for technique selection")
    strategies: list[SearchStrategy] = Field(default_factory=list)
    expected_result_type: str = Field(default="", description="What the user wants to know")
    zoom_level: str = Field(default="micro", pattern="^(auto|macro|meso|micro)$")


# ===========================================================================
# SEARCH RESULT MODELS
# ===========================================================================


class TemporalContext(BaseModel):
    """Temporal validity of a fact."""

    created_at: float | str | None = None  # Accept Unix timestamp, ISO date, or None
    expired_at: float | str | None = None
    is_current: bool = True
    human_readable: str | None = Field(default=None, description="e.g., 'since March 2024'")


class RawSearchResult(BaseModel):
    """Single result from a search technique."""

    content: str
    source_technique: SearchTechnique
    source_id: str | None = None
    source_episode: str | None = None
    vector_score: float | None = Field(
        default=None, ge=0.0
    )  # No upper bound - Graphiti can exceed 1.0
    relationship_strengths: list[float] = Field(default_factory=list)
    temporal_context: TemporalContext | None = None


# ===========================================================================
# GRAPH INTELLIGENCE REPORT MODELS
# ===========================================================================


class EvidenceItem(BaseModel):
    """Supporting evidence for the answer."""

    fact: str
    relationship: str = Field(default="", description="Relationship type that supports this")
    source: str = Field(default="", description="Episode or node ID")
    confidence: float = Field(
        default=0.5, ge=0.0
    )  # No upper bound - Graphiti scores can exceed 1.0
    temporal_note: str | None = None


class RelationshipDetail(BaseModel):
    """Details about a discovered relationship."""

    source_name: str
    source_type: str
    relationship_type: str
    target_name: str
    target_type: str
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    context: str | None = None
    temporal: TemporalContext | None = None


class GraphIntelligenceReport(BaseModel):
    """
    The Researcher's final output.

    Structured for channel-agnostic rendering.
    """

    # Core answer
    query: str
    direct_answer: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel = Field(default=ConfidenceLevel.UNCERTAIN)

    # Supporting evidence
    evidence: list[EvidenceItem] = Field(default_factory=list)

    # Relationship context
    relationships: list[RelationshipDetail] = Field(default_factory=list)
    key_entities: list[str] = Field(default_factory=list)

    # Temporal context
    as_of_date: str = Field(default="")
    historical_notes: list[str] = Field(default_factory=list)

    # Search metadata
    search_techniques_used: list[SearchTechnique] = Field(default_factory=list)
    result_count: int = Field(default=0)

    # Navigation
    related_queries: list[str] = Field(default_factory=list)
    gaps_identified: list[str] = Field(default_factory=list)


# ===========================================================================
# AGENT MESSAGE PAYLOADS
# ===========================================================================


class ResearcherRequest(BaseModel):
    """Payload for Orchestrator -> Researcher."""

    query: str
    context: dict[str, Any] = Field(default_factory=dict)
    zoom_level: str = Field(default="auto")
    include_historical: bool = Field(default=False)
    max_results: int = Field(default=20, ge=1, le=100)


class ResearcherResponse(BaseModel):
    """Payload for Researcher -> Orchestrator."""

    report: GraphIntelligenceReport
    raw_result_count: int = Field(default=0)
    search_latency_ms: float = Field(default=0.0)
    synthesis_latency_ms: float = Field(default=0.0)


# ===========================================================================
# EXPORTS
# ===========================================================================

__all__ = [
    # Enums
    "SearchTechnique",
    "ConfidenceLevel",
    "ZoomLevel",
    # Planning
    "TimeRange",
    "SearchStrategy",
    "SearchPlan",
    # Results
    "TemporalContext",
    "RawSearchResult",
    # Report
    "EvidenceItem",
    "RelationshipDetail",
    "GraphIntelligenceReport",
    # Payloads
    "ResearcherRequest",
    "ResearcherResponse",
]
