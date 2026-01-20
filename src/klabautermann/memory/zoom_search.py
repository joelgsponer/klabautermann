"""
Multi-level retrieval (zoom mechanics) for Klabautermann.

Implements three levels of retrieval granularity:
- Macro: Community/Island level (high-level overviews)
- Meso: Project/Note level (thread-level context)
- Micro: Entity level (specific facts)

Reference: specs/architecture/MEMORY.md Section 9
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from klabautermann.core.logger import logger
from klabautermann.utils.retry import retry_on_llm_errors


if TYPE_CHECKING:
    from collections.abc import Sequence

    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Constants
# =============================================================================

# Model to use for zoom level classification (Haiku for cost-effectiveness)
ZOOM_CLASSIFICATION_MODEL = "claude-3-5-haiku-20241022"

# System prompt for zoom level classification
ZOOM_CLASSIFIER_SYSTEM_PROMPT = """You are a query analyzer for a personal knowledge management system.

Your task is to classify user queries into one of three retrieval zoom levels:

## MACRO Level
Use for high-level overviews and broad questions about themes or life areas.
Examples:
- "What are the main themes in my life right now?"
- "Give me an overview of my activities"
- "What areas need attention?"
- "Summarize what's been happening"

## MESO Level
Use for project-level or note-level context.
Examples:
- "What's the status of the Q1 budget project?"
- "What did I discuss about the marketing campaign?"
- "What are my current projects?"
- "Show me notes about the conference"

## MICRO Level
Use for specific entity facts, exact details, or pointed questions.
Examples:
- "What is Sarah's email address?"
- "When did John change jobs?"
- "Who reported the bug last Tuesday?"
- "Where does Alice work?"

Analyze the semantic intent of the query, not just keywords. Consider:
1. Is the user asking for broad context or specific facts?
2. Does the query reference a particular entity or a general theme?
3. Would the answer be a summary or a precise data point?

Always classify into exactly one level."""


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class MacroSearchResult:
    """Result from macro (community/island) level search."""

    island_uuid: str
    island_name: str
    theme: str | None
    summary: str | None
    member_count: int
    pending_tasks: int
    last_activity: float | None


@dataclass
class MesoSearchResult:
    """Result from meso (project/note) level search."""

    uuid: str
    item_type: str  # "Project" or "Note"
    title: str | None
    summary: str | None
    created_at: float | None
    score: float
    related_projects: list[str]
    mentioned_persons: list[str]
    aligned_goals: list[str]


@dataclass
class MicroSearchResult:
    """Result from micro (entity) level search."""

    entity_uuid: str
    entity_type: str
    entity_properties: dict[str, Any]
    score: float
    relationships: list[dict[str, Any]]


@dataclass
class ZoomSearchResponse:
    """Combined response from zoom level search."""

    zoom_level: str  # "macro", "meso", or "micro"
    results: Sequence[MacroSearchResult | MesoSearchResult | MicroSearchResult]
    result_count: int


# =============================================================================
# Macro Level Search (#187)
# =============================================================================


async def macro_search(
    neo4j: Neo4jClient,
    captain_uuid: str | None = None,
    limit: int = 20,
    trace_id: str | None = None,
) -> list[MacroSearchResult]:
    """
    Macro-level retrieval: Get Knowledge Island summaries.

    Use for:
    - "What are the big themes in my life right now?"
    - "Give me an overview of my activities"
    - "What areas need attention?"

    Args:
        neo4j: Connected Neo4jClient instance
        captain_uuid: Optional captain filter (unused for now)
        limit: Maximum results to return
        trace_id: Optional trace ID for logging

    Returns:
        List of MacroSearchResult with community/island summaries
    """
    logger.debug(
        f"[WHISPER] Macro search (limit={limit})",
        extra={"trace_id": trace_id, "agent_name": "zoom_search"},
    )

    query = """
    MATCH (c:Community)
    WHERE EXISTS((c)<-[:PART_OF_ISLAND]-())

    // Get node counts and recent activity
    OPTIONAL MATCH (c)<-[:PART_OF_ISLAND]-(member)
    WITH c, count(member) as member_count,
         max(member.updated_at) as last_activity

    // Get pending tasks for each island
    OPTIONAL MATCH (c)<-[:PART_OF_ISLAND]-(t:Task)
    WHERE t.status = 'todo' OR t.status = 'pending'
    WITH c, member_count, last_activity, count(t) as pending_tasks

    RETURN c.uuid as island_uuid,
           c.name as island_name,
           c.theme as theme,
           c.summary as summary,
           member_count,
           pending_tasks,
           last_activity
    ORDER BY pending_tasks DESC, last_activity DESC
    LIMIT $limit
    """

    result = await neo4j.execute_query(query, {"limit": limit}, trace_id=trace_id)

    results = [
        MacroSearchResult(
            island_uuid=row["island_uuid"],
            island_name=row["island_name"],
            theme=row.get("theme"),
            summary=row.get("summary"),
            member_count=row.get("member_count", 0),
            pending_tasks=row.get("pending_tasks", 0),
            last_activity=row.get("last_activity"),
        )
        for row in result
    ]

    logger.debug(
        f"[WHISPER] Macro search found {len(results)} islands",
        extra={"trace_id": trace_id, "agent_name": "zoom_search"},
    )

    return results


# =============================================================================
# Meso Level Search (#188)
# =============================================================================


async def meso_search(
    neo4j: Neo4jClient,
    query_text: str | None = None,
    island_filter: str | None = None,
    limit: int = 10,
    trace_id: str | None = None,
) -> list[MesoSearchResult]:
    """
    Meso-level retrieval: Get Project and Note context.

    Use for:
    - "What's the status of the Q1 budget?"
    - "What have I discussed about the marketing campaign?"
    - "What are my current projects?"

    Args:
        neo4j: Connected Neo4jClient instance
        query_text: Optional text to filter by (unused without vector index)
        island_filter: Optional island name to filter by
        limit: Maximum results to return
        trace_id: Optional trace ID for logging

    Returns:
        List of MesoSearchResult with project/note context
    """
    logger.debug(
        f"[WHISPER] Meso search (query={query_text}, island={island_filter}, limit={limit})",
        extra={"trace_id": trace_id, "agent_name": "zoom_search"},
    )

    # Build island filter clause
    island_clause = ""
    params: dict[str, Any] = {"limit": limit}

    if island_filter:
        island_clause = "AND (item)-[:PART_OF_ISLAND]->(:Community {name: $island_filter})"
        params["island_filter"] = island_filter

    query = f"""
    // Get projects and notes
    MATCH (item)
    WHERE (item:Project OR item:Note)
    {island_clause}

    // Get related projects (for notes)
    OPTIONAL MATCH (item)-[:DISCUSSED]->(proj:Project)

    // Get related persons
    OPTIONAL MATCH (person:Person)-[:MENTIONED_IN]->(item)

    // Get goal alignment
    OPTIONAL MATCH (item)-[:CONTRIBUTES_TO]->(goal:Goal)
    OPTIONAL MATCH (proj)-[:CONTRIBUTES_TO]->(proj_goal:Goal)

    WITH item,
         labels(item)[0] as item_type,
         collect(DISTINCT proj.name) as related_projects,
         collect(DISTINCT person.name) as mentioned_persons,
         collect(DISTINCT COALESCE(goal.description, proj_goal.description)) as aligned_goals

    RETURN item.uuid as uuid,
           item_type,
           COALESCE(item.title, item.name) as title,
           COALESCE(item.content_summarized, item.summary, item.description) as summary,
           item.created_at as created_at,
           1.0 as score,
           related_projects,
           mentioned_persons,
           aligned_goals
    ORDER BY item.updated_at DESC, item.created_at DESC
    LIMIT $limit
    """

    result = await neo4j.execute_query(query, params, trace_id=trace_id)

    results = [
        MesoSearchResult(
            uuid=row["uuid"],
            item_type=row["item_type"],
            title=row.get("title"),
            summary=row.get("summary"),
            created_at=row.get("created_at"),
            score=row.get("score", 1.0),
            related_projects=[p for p in row.get("related_projects", []) if p],
            mentioned_persons=[p for p in row.get("mentioned_persons", []) if p],
            aligned_goals=[g for g in row.get("aligned_goals", []) if g],
        )
        for row in result
    ]

    logger.debug(
        f"[WHISPER] Meso search found {len(results)} items",
        extra={"trace_id": trace_id, "agent_name": "zoom_search"},
    )

    return results


async def get_project_context(
    neo4j: Neo4jClient,
    project_uuid: str,
    trace_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Get comprehensive meso-level context for a specific project.

    Args:
        neo4j: Connected Neo4jClient instance
        project_uuid: UUID of the project
        trace_id: Optional trace ID for logging

    Returns:
        Dictionary with project context or None if not found
    """
    query = """
    MATCH (p:Project {uuid: $project_uuid})

    // Get goal alignment
    OPTIONAL MATCH (p)-[:CONTRIBUTES_TO]->(g:Goal)

    // Get related notes
    OPTIONAL MATCH (n:Note)-[:DISCUSSED]->(p)

    // Get tasks
    OPTIONAL MATCH (t:Task)-[:PART_OF]->(p)

    // Get involved persons
    OPTIONAL MATCH (person:Person)-[:MENTIONED_IN]->(n)
    WHERE (n)-[:DISCUSSED]->(p)

    // Get community/island
    OPTIONAL MATCH (p)-[:PART_OF_ISLAND]->(c:Community)

    RETURN p.name as project_name,
           p.status as status,
           p.deadline as deadline,
           g.description as goal,
           c.name as island,
           collect(DISTINCT {
             title: n.title,
             summary: n.content_summarized,
             date: n.created_at
           })[0..5] as recent_notes,
           collect(DISTINCT {
             action: t.action,
             status: t.status,
             priority: t.priority
           }) as tasks,
           collect(DISTINCT person.name) as key_persons
    """

    result = await neo4j.execute_query(query, {"project_uuid": project_uuid}, trace_id=trace_id)

    if result:
        return result[0]
    return None


# =============================================================================
# Micro Level Search (#189)
# =============================================================================


async def micro_search(
    neo4j: Neo4jClient,
    query_text: str | None = None,
    entity_type: str | None = None,
    include_historical: bool = False,
    limit: int = 10,
    trace_id: str | None = None,
) -> list[MicroSearchResult]:
    """
    Micro-level retrieval: Get specific Entity facts and relationships.

    This is the default search behavior for specific queries.

    Use for:
    - "When did Sarah change jobs?"
    - "What's John's email address?"
    - "Who reported the bug last Tuesday?"

    Args:
        neo4j: Connected Neo4jClient instance
        query_text: Optional text filter (for name matching)
        entity_type: Optional entity type filter (Person, Organization, etc.)
        include_historical: Whether to include expired relationships
        limit: Maximum results to return
        trace_id: Optional trace ID for logging

    Returns:
        List of MicroSearchResult with entity facts
    """
    logger.debug(
        f"[WHISPER] Micro search (query={query_text}, type={entity_type}, "
        f"historical={include_historical}, limit={limit})",
        extra={"trace_id": trace_id, "agent_name": "zoom_search"},
    )

    # Build clauses
    type_clause = f"AND n:{entity_type}" if entity_type else ""
    temporal_clause = "" if include_historical else "WHERE r.expired_at IS NULL"
    name_clause = ""

    params: dict[str, Any] = {"limit": limit}

    if query_text:
        name_clause = "AND (toLower(n.name) CONTAINS toLower($query_text) OR toLower(COALESCE(n.title, '')) CONTAINS toLower($query_text))"
        params["query_text"] = query_text

    query = f"""
    // Find entities matching criteria
    MATCH (n)
    WHERE NOT n:Thread AND NOT n:Message AND NOT n:Day AND NOT n:Community
    {type_clause}
    {name_clause}

    // Get all relationships (respecting temporal filter)
    OPTIONAL MATCH (n)-[r]-(related)
    {temporal_clause}

    WITH n, collect(DISTINCT {{
        relationship: type(r),
        target: properties(related),
        target_type: labels(related)[0],
        created_at: r.created_at,
        expired_at: r.expired_at
    }}) as relationships

    RETURN n.uuid as entity_uuid,
           labels(n)[0] as entity_type,
           properties(n) as entity_properties,
           1.0 as score,
           relationships
    ORDER BY n.updated_at DESC, n.created_at DESC
    LIMIT $limit
    """

    result = await neo4j.execute_query(query, params, trace_id=trace_id)

    results = [
        MicroSearchResult(
            entity_uuid=row["entity_uuid"],
            entity_type=row["entity_type"],
            entity_properties=row.get("entity_properties", {}),
            score=row.get("score", 1.0),
            relationships=[r for r in row.get("relationships", []) if r.get("target")],
        )
        for row in result
    ]

    logger.debug(
        f"[WHISPER] Micro search found {len(results)} entities",
        extra={"trace_id": trace_id, "agent_name": "zoom_search"},
    )

    return results


async def get_entity_timeline(
    neo4j: Neo4jClient,
    entity_uuid: str,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get chronological history of an entity's relationships.

    Args:
        neo4j: Connected Neo4jClient instance
        entity_uuid: UUID of the entity
        trace_id: Optional trace ID for logging

    Returns:
        List of relationship records ordered by creation time
    """
    query = """
    MATCH (e {uuid: $entity_uuid})-[r]-(related)
    RETURN type(r) as relationship,
           labels(related)[0] as related_type,
           related.name as related_name,
           r.created_at as started,
           r.expired_at as ended,
           properties(r) as relationship_props
    ORDER BY r.created_at DESC
    """

    return await neo4j.execute_query(query, {"entity_uuid": entity_uuid}, trace_id=trace_id)


# =============================================================================
# Zoom Level Classification
# =============================================================================


class ZoomLevel(str, Enum):
    """Zoom level for retrieval granularity."""

    MACRO = "macro"
    MESO = "meso"
    MICRO = "micro"


@dataclass
class ZoomClassification:
    """Result from AI-based zoom level classification."""

    level: ZoomLevel
    confidence: float
    reasoning: str


# =============================================================================
# AI-First Zoom Level Selection (#190)
# =============================================================================


class AIZoomLevelSelector:
    """
    Selects retrieval zoom level using LLM semantic understanding.

    This is the AI-first approach that uses Claude to understand query
    semantics rather than keyword matching.

    Reference: Issue #190 - Auto zoom detection (AI-first)
    """

    @retry_on_llm_errors(max_retries=2)
    async def classify_query(
        self,
        query: str,
        trace_id: str | None = None,
    ) -> ZoomClassification:
        """
        Classify a query into a zoom level using LLM semantic understanding.

        Args:
            query: Natural language search query
            trace_id: Trace ID for logging

        Returns:
            ZoomClassification with level, confidence, and reasoning
        """
        import anthropic

        trace_id = trace_id or f"zoom-{os.urandom(4).hex()}"

        logger.debug(
            f"[WHISPER] AI zoom classification for query: {query[:50]}...",
            extra={"trace_id": trace_id, "agent_name": "zoom_search"},
        )

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning(
                "[SWELL] ANTHROPIC_API_KEY not set, falling back to keyword selector",
                extra={"trace_id": trace_id, "agent_name": "zoom_search"},
            )
            return self._fallback_classification(query)

        client = anthropic.Anthropic(api_key=api_key)

        # Tool schema for structured output
        tool_schema = {
            "name": "classify_zoom_level",
            "description": "Classify a query into a retrieval zoom level",
            "input_schema": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["macro", "meso", "micro"],
                        "description": "The zoom level for this query",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Confidence in the classification (0.0-1.0)",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Brief explanation for the classification",
                    },
                },
                "required": ["level", "confidence", "reasoning"],
            },
        }

        try:
            response = client.messages.create(
                model=ZOOM_CLASSIFICATION_MODEL,
                max_tokens=200,
                system=ZOOM_CLASSIFIER_SYSTEM_PROMPT,
                tools=[tool_schema],
                tool_choice={"type": "tool", "name": "classify_zoom_level"},
                messages=[
                    {
                        "role": "user",
                        "content": f"Classify this query into a zoom level:\n\n{query}",
                    }
                ],
            )

            # Extract tool use block
            tool_use_block = None
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    tool_use_block = block
                    break

            if not tool_use_block:
                logger.warning(
                    "[SWELL] No tool_use block in AI zoom response, using fallback",
                    extra={"trace_id": trace_id, "agent_name": "zoom_search"},
                )
                return self._fallback_classification(query)

            result = tool_use_block.input
            classification = ZoomClassification(
                level=ZoomLevel(result["level"]),
                confidence=float(result.get("confidence", 0.8)),
                reasoning=result.get("reasoning", ""),
            )

            logger.info(
                f"[CHART] AI zoom classification: {classification.level.value} "
                f"(confidence: {classification.confidence:.2f})",
                extra={
                    "trace_id": trace_id,
                    "agent_name": "zoom_search",
                    "level": classification.level.value,
                    "confidence": classification.confidence,
                },
            )

            return classification

        except anthropic.APIError as e:
            logger.error(
                f"[STORM] Anthropic API error during zoom classification: {e}",
                extra={"trace_id": trace_id, "agent_name": "zoom_search"},
            )
            return self._fallback_classification(query)

        except Exception as e:
            logger.error(
                f"[STORM] Unexpected error during zoom classification: {e}",
                extra={"trace_id": trace_id, "agent_name": "zoom_search"},
            )
            return self._fallback_classification(query)

    def _fallback_classification(self, query: str) -> ZoomClassification:
        """
        Fallback to keyword-based classification when AI is unavailable.

        This provides graceful degradation when the LLM call fails.
        """
        # Use the keyword-based selector as fallback
        keyword_selector = ZoomLevelSelector()
        level_str = keyword_selector.select_zoom_level(query)

        return ZoomClassification(
            level=ZoomLevel(level_str),
            confidence=0.5,  # Lower confidence for keyword fallback
            reasoning="Fallback to keyword-based classification",
        )


async def ai_zoom_search(
    neo4j: Neo4jClient,
    query: str,
    captain_uuid: str | None = None,
    limit: int = 10,
    trace_id: str | None = None,
) -> ZoomSearchResponse:
    """
    Execute search using AI-based zoom level selection.

    Uses LLM semantic understanding to determine the appropriate
    retrieval granularity instead of keyword matching.

    Args:
        neo4j: Connected Neo4jClient instance
        query: Natural language search query
        captain_uuid: Optional captain filter
        limit: Maximum results to return
        trace_id: Optional trace ID for logging

    Returns:
        ZoomSearchResponse with results at the AI-selected level
    """
    selector = AIZoomLevelSelector()
    classification = await selector.classify_query(query, trace_id)

    logger.info(
        f"[CHART] AI zoom search: {classification.level.value} for query: {query[:50]}...",
        extra={
            "trace_id": trace_id,
            "agent_name": "zoom_search",
            "reasoning": classification.reasoning,
        },
    )

    if classification.level == ZoomLevel.MACRO:
        macro_results = await macro_search(neo4j, captain_uuid, limit, trace_id)
        return ZoomSearchResponse(
            zoom_level="macro",
            results=macro_results,
            result_count=len(macro_results),
        )

    elif classification.level == ZoomLevel.MESO:
        meso_results = await meso_search(neo4j, query, None, limit, trace_id)
        return ZoomSearchResponse(
            zoom_level="meso",
            results=meso_results,
            result_count=len(meso_results),
        )

    else:  # ZoomLevel.MICRO
        micro_results = await micro_search(neo4j, query, None, False, limit, trace_id)
        return ZoomSearchResponse(
            zoom_level="micro",
            results=micro_results,
            result_count=len(micro_results),
        )


# =============================================================================
# Keyword-Based Zoom Level Selection (Legacy)
# =============================================================================


class ZoomLevelSelector:
    """Automatically selects appropriate retrieval zoom level based on query."""

    MACRO_INDICATORS: ClassVar[list[str]] = [
        "overview",
        "summary",
        "themes",
        "big picture",
        "main areas",
        "life",
        "everything",
        "all",
        "islands",
        "communities",
    ]

    MESO_INDICATORS: ClassVar[list[str]] = [
        "project",
        "status",
        "progress",
        "discussed",
        "meeting",
        "notes",
        "recent",
        "working on",
    ]

    MICRO_INDICATORS: ClassVar[list[str]] = [
        "who",
        "what",
        "when",
        "where",
        "exactly",
        "specific",
        "email",
        "phone",
        "address",
        "date",
    ]

    def select_zoom_level(self, query: str) -> str:
        """
        Analyze query to determine optimal zoom level.

        Args:
            query: Natural language search query

        Returns:
            'macro', 'meso', or 'micro'
        """
        query_lower = query.lower()

        # Count indicators
        macro_score = sum(1 for i in self.MACRO_INDICATORS if i in query_lower)
        meso_score = sum(1 for i in self.MESO_INDICATORS if i in query_lower)
        micro_score = sum(1 for i in self.MICRO_INDICATORS if i in query_lower)

        # Question words tend toward micro
        if query.startswith(("Who ", "When ", "What is", "What's", "Where ")):
            micro_score += 2

        # Determine level
        if macro_score > meso_score and macro_score > micro_score:
            return "macro"
        elif meso_score > micro_score:
            return "meso"
        else:
            return "micro"


async def auto_zoom_search(
    neo4j: Neo4jClient,
    query: str,
    captain_uuid: str | None = None,
    limit: int = 10,
    trace_id: str | None = None,
) -> ZoomSearchResponse:
    """
    Execute search at automatically selected zoom level.

    Args:
        neo4j: Connected Neo4jClient instance
        query: Natural language search query
        captain_uuid: Optional captain filter
        limit: Maximum results to return
        trace_id: Optional trace ID for logging

    Returns:
        ZoomSearchResponse with results at the appropriate level
    """
    selector = ZoomLevelSelector()
    level = selector.select_zoom_level(query)

    logger.info(
        f"[CHART] Auto-zoom selected level: {level} for query: {query[:50]}...",
        extra={"trace_id": trace_id, "agent_name": "zoom_search"},
    )

    if level == "macro":
        macro_results = await macro_search(neo4j, captain_uuid, limit, trace_id)
        return ZoomSearchResponse(
            zoom_level="macro",
            results=macro_results,
            result_count=len(macro_results),
        )

    elif level == "meso":
        meso_results = await meso_search(neo4j, query, None, limit, trace_id)
        return ZoomSearchResponse(
            zoom_level="meso",
            results=meso_results,
            result_count=len(meso_results),
        )

    else:  # micro
        micro_results = await micro_search(neo4j, query, None, False, limit, trace_id)
        return ZoomSearchResponse(
            zoom_level="micro",
            results=micro_results,
            result_count=len(micro_results),
        )


# =============================================================================
# Export
# =============================================================================

__all__ = [
    # AI-First Zoom Selection (#190)
    "AIZoomLevelSelector",
    # Data Classes
    "MacroSearchResult",
    "MesoSearchResult",
    "MicroSearchResult",
    "ZoomClassification",
    "ZoomLevel",
    # Auto Selection (Keyword-based - legacy)
    "ZoomLevelSelector",
    "ZoomSearchResponse",
    "ai_zoom_search",
    "auto_zoom_search",
    "get_entity_timeline",
    "get_project_context",
    # Search Functions
    "macro_search",
    "meso_search",
    "micro_search",
]
