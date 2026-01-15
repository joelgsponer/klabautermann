"""
Researcher agent for Klabautermann.

The "Librarian" that performs hybrid search across the knowledge graph.
Uses vector search via Graphiti and structural queries via Cypher.

NEVER fabricates results - returns empty if nothing found.

Reference: specs/architecture/AGENTS.md Section 1.3
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage


if TYPE_CHECKING:
    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.neo4j_client import Neo4jClient


# ===========================================================================
# Search Models
# ===========================================================================


class SearchType(str, Enum):
    """Types of search strategies."""

    SEMANTIC = "semantic"
    STRUCTURAL = "structural"
    TEMPORAL = "temporal"
    HYBRID = "hybrid"


class SearchResult(BaseModel):
    """Single search result from the knowledge graph."""

    content: str
    source: str  # "graphiti", "neo4j", or node type
    source_id: str | None = None
    confidence: float = 1.0
    temporal_context: str | None = None


class SearchResponse(BaseModel):
    """Complete search response with results."""

    query: str
    search_type: SearchType
    results: list[SearchResult] = Field(default_factory=list)
    summary: str | None = None


# ===========================================================================
# Researcher Agent
# ===========================================================================


class Researcher(BaseAgent):
    """
    The Researcher agent - the "Librarian" of The Locker.

    Performs hybrid search across the temporal knowledge graph:
    - SEMANTIC: Vector search via Graphiti
    - STRUCTURAL: Graph traversal queries (relationships, hierarchies)
    - TEMPORAL: Time-filtered queries (historical states)
    - HYBRID: Combination of above strategies

    NEVER fabricates results. If nothing found, returns empty.

    Uses Claude Haiku for query understanding (cost-effective).
    """

    # Patterns for query classification
    STRUCTURAL_PATTERNS: list[str] = [
        r"who (?:does|did) .+ (?:work|report)",
        r"what (?:tasks?|projects?) (?:are |is )?(?:blocked|blocking)",
        r"who (?:attended|went to)",
        r"what (?:project|task).+ part of",
        r"who (?:works|worked) (?:at|for)",
        r"what.+(?:status|progress)",
    ]

    TEMPORAL_PATTERNS: list[str] = [
        r"last (?:week|month|year)",
        r"yesterday|today|tomorrow",
        r"in \d{4}",
        r"(?:on|before|after) (?:january|february|march|april|may|june|july|august|september|october|november|december)",
        r"(?:\d+) (?:days?|weeks?|months?) ago",
    ]

    def __init__(
        self,
        name: str = "researcher",
        config: dict[str, Any] | None = None,
        graphiti: GraphitiClient | None = None,
        neo4j: Neo4jClient | None = None,
    ) -> None:
        """
        Initialize the Researcher.

        Args:
            name: Agent name (default: "researcher").
            config: Agent configuration.
            graphiti: GraphitiClient for vector search.
            neo4j: Neo4jClient for Cypher queries.
        """
        super().__init__(name, config)
        self.graphiti = graphiti
        self.neo4j = neo4j
        self.model = (config or {}).get("model", "claude-3-haiku-20240307")

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process search request from Orchestrator.

        Args:
            msg: AgentMessage with search intent and query.

        Returns:
            AgentMessage with search results or None.
        """
        query = msg.payload.get("query", "")

        if not query:
            logger.warning(
                "[SWELL] Researcher received empty query",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
            )
            return self._create_response(
                msg, SearchResponse(query="", search_type=SearchType.SEMANTIC)
            )

        try:
            # Classify search type
            search_type = self._classify_search_type(query)

            logger.debug(
                f"[WHISPER] Search type: {search_type.value}",
                extra={"trace_id": msg.trace_id, "query": query[:50]},
            )

            # Execute appropriate search strategy
            if search_type == SearchType.SEMANTIC:
                response = await self._semantic_search(query, msg.trace_id)
            elif search_type == SearchType.STRUCTURAL:
                response = await self._structural_search(query, msg.trace_id)
            elif search_type == SearchType.TEMPORAL:
                response = await self._temporal_search(query, msg.trace_id)
            else:
                # Hybrid: try both semantic and structural
                response = await self._hybrid_search(query, msg.trace_id)

            logger.info(
                f"[BEACON] Search returned {len(response.results)} results",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
            )

            return self._create_response(msg, response)

        except Exception as e:
            logger.error(
                f"[STORM] Search failed: {e}",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
                exc_info=True,
            )
            # Return error response with empty results
            error_response = AgentMessage(
                trace_id=msg.trace_id,
                source_agent=self.name,
                target_agent=msg.source_agent,
                intent="search_response",
                payload={
                    "result": "",
                    "results": [],
                    "search_type": SearchType.SEMANTIC.value,
                    "count": 0,
                    "error": str(e),
                },
                timestamp=time.time(),
            )
            return error_response

    def _classify_search_type(self, query: str) -> SearchType:
        """
        Classify the type of search needed based on query patterns.

        Args:
            query: User's search query.

        Returns:
            SearchType enum value.
        """
        query_lower = query.lower()

        is_structural = any(re.search(p, query_lower) for p in self.STRUCTURAL_PATTERNS)
        is_temporal = any(re.search(p, query_lower) for p in self.TEMPORAL_PATTERNS)

        if is_structural and is_temporal:
            return SearchType.HYBRID
        elif is_structural:
            return SearchType.STRUCTURAL
        elif is_temporal:
            return SearchType.TEMPORAL
        else:
            return SearchType.SEMANTIC

    async def _semantic_search(self, query: str, trace_id: str) -> SearchResponse:
        """
        Perform vector search via Graphiti.

        Args:
            query: Search query.
            trace_id: Request trace ID.

        Returns:
            SearchResponse with vector search results.
        """
        if not self.graphiti:
            logger.warning(
                "[SWELL] Graphiti client not available for semantic search",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return SearchResponse(query=query, search_type=SearchType.SEMANTIC)

        try:
            results = await self.graphiti.search(query, limit=5)

            search_results = [
                SearchResult(
                    content=r.fact if hasattr(r, "fact") else r.get("content", ""),
                    source="graphiti",
                    source_id=str(r.uuid) if hasattr(r, "uuid") else r.get("uuid"),
                    confidence=r.score if hasattr(r, "score") else r.get("score", 0.5),
                )
                for r in results
            ]

            return SearchResponse(
                query=query,
                search_type=SearchType.SEMANTIC,
                results=search_results,
            )

        except Exception as e:
            logger.error(
                f"[STORM] Semantic search failed: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return SearchResponse(query=query, search_type=SearchType.SEMANTIC)

    async def _structural_search(self, query: str, trace_id: str) -> SearchResponse:
        """
        Perform graph traversal search using Cypher.

        Args:
            query: Search query.
            trace_id: Request trace ID.

        Returns:
            SearchResponse with structural query results.
        """
        if not self.neo4j:
            logger.warning(
                "[SWELL] Neo4j client not available for structural search",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return SearchResponse(query=query, search_type=SearchType.STRUCTURAL)

        # Extract entity name from query patterns
        entity_name = self._extract_entity_name(query)

        if not entity_name:
            # Fall back to semantic search if we can't parse structure
            logger.debug(
                "[WHISPER] Could not extract entity, falling back to semantic",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return await self._semantic_search(query, trace_id)

        # Determine relationship type from query
        cypher, params = self._build_structural_query(query, entity_name)

        try:
            records = await self.neo4j.execute_query(cypher, params, trace_id=trace_id)

            search_results = [
                SearchResult(
                    content=self._format_record(record),
                    source="neo4j",
                    confidence=1.0,
                )
                for record in records
            ]

            return SearchResponse(
                query=query,
                search_type=SearchType.STRUCTURAL,
                results=search_results,
            )

        except Exception as e:
            logger.error(
                f"[STORM] Structural search failed: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return SearchResponse(query=query, search_type=SearchType.STRUCTURAL)

    async def _temporal_search(self, query: str, trace_id: str) -> SearchResponse:
        """
        Perform time-filtered search.

        Args:
            query: Search query with temporal reference.
            trace_id: Request trace ID.

        Returns:
            SearchResponse with time-filtered results.
        """
        if not self.neo4j:
            logger.warning(
                "[SWELL] Neo4j client not available for temporal search",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return SearchResponse(query=query, search_type=SearchType.TEMPORAL)

        # Parse time reference from query
        time_filter = self._parse_time_reference(query)

        if not time_filter:
            logger.debug(
                "[WHISPER] Could not parse time reference",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return SearchResponse(query=query, search_type=SearchType.TEMPORAL)

        # Build temporal query
        cypher = """
        MATCH (n)
        WHERE n.created_at >= $start AND n.created_at <= $end
        RETURN n, labels(n) as type
        LIMIT 10
        """

        try:
            records = await self.neo4j.execute_query(cypher, time_filter, trace_id=trace_id)

            search_results = [
                SearchResult(
                    content=self._format_record(record),
                    source="neo4j",
                    confidence=1.0,
                    temporal_context=f"Between {time_filter['start']} and {time_filter['end']}",
                )
                for record in records
            ]

            return SearchResponse(
                query=query,
                search_type=SearchType.TEMPORAL,
                results=search_results,
            )

        except Exception as e:
            logger.error(
                f"[STORM] Temporal search failed: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return SearchResponse(query=query, search_type=SearchType.TEMPORAL)

    async def _hybrid_search(self, query: str, trace_id: str) -> SearchResponse:
        """
        Combine semantic and structural search strategies.

        Args:
            query: Search query.
            trace_id: Request trace ID.

        Returns:
            SearchResponse with combined results.
        """
        semantic = await self._semantic_search(query, trace_id)
        structural = await self._structural_search(query, trace_id)

        combined_results = semantic.results + structural.results

        return SearchResponse(
            query=query,
            search_type=SearchType.HYBRID,
            results=combined_results,
        )

    def _extract_entity_name(self, query: str) -> str | None:
        """
        Extract entity name from query patterns.

        Args:
            query: Search query.

        Returns:
            Entity name or None if not found.
        """
        query_lower = query.lower()

        # Pattern: "who is/does/did <name>"
        match = re.search(r"who (?:is|does|did|was) (\w+)", query_lower)
        if match:
            return match.group(1).title()

        # Pattern: "what <name> ..."
        match = re.search(r"what (?:does|did|is|was) (\w+)", query_lower)
        if match:
            return match.group(1).title()

        # Pattern: "<name> works/worked at"
        match = re.search(r"(\w+) (?:works?|worked) (?:at|for)", query_lower)
        if match:
            return match.group(1).title()

        return None

    def _build_structural_query(self, query: str, entity_name: str) -> tuple[str, dict[str, Any]]:
        """
        Build Cypher query for structural search.

        Args:
            query: Search query.
            entity_name: Extracted entity name.

        Returns:
            Tuple of (cypher_query, parameters).
        """
        query_lower = query.lower()

        if "work" in query_lower:
            cypher = """
            MATCH (p:Person {name: $name})-[r:WORKS_AT]->(o:Organization)
            WHERE r.expired_at IS NULL
            RETURN p.name as person, o.name as org, r.title as title
            """
        elif "report" in query_lower:
            cypher = """
            MATCH (p:Person {name: $name})-[r:REPORTS_TO]->(m:Person)
            WHERE r.expired_at IS NULL
            RETURN p.name as person, m.name as manager
            """
        elif "block" in query_lower:
            cypher = """
            MATCH (t:Task)-[r:BLOCKS]->(blocked:Task)
            RETURN t.action as blocker, blocked.action as blocked_task
            """
        else:
            # Generic entity lookup
            cypher = """
            MATCH (n {name: $name})
            RETURN n, labels(n) as type
            LIMIT 5
            """

        return cypher, {"name": entity_name}

    def _parse_time_reference(self, query: str) -> dict[str, float] | None:
        """
        Parse time references from query into timestamp range.

        Args:
            query: Search query with temporal reference.

        Returns:
            Dict with 'start' and 'end' timestamps, or None if no time found.
        """
        query_lower = query.lower()
        now = datetime.now()

        if "yesterday" in query_lower:
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
            end = start.replace(hour=23, minute=59, second=59)
        elif "last week" in query_lower:
            start = now - timedelta(days=7)
            end = now
        elif "last month" in query_lower:
            start = now - timedelta(days=30)
            end = now
        elif "last year" in query_lower:
            start = now - timedelta(days=365)
            end = now
        else:
            # Try to extract "X days/weeks/months ago"
            match = re.search(r"(\d+) (day|week|month)s? ago", query_lower)
            if match:
                count = int(match.group(1))
                unit = match.group(2)
                if unit == "day":
                    start = now - timedelta(days=count)
                elif unit == "week":
                    start = now - timedelta(weeks=count)
                elif unit == "month":
                    start = now - timedelta(days=count * 30)
                else:
                    return None
                end = now
            else:
                return None

        return {
            "start": start.timestamp(),
            "end": end.timestamp(),
        }

    def _format_record(self, record: dict[str, Any]) -> str:
        """
        Format a Neo4j record for display.

        Args:
            record: Neo4j query result record.

        Returns:
            Formatted string representation.
        """
        # Simple formatting - convert dict to readable string
        parts = []
        for key, value in record.items():
            if value is not None and key not in ["type"]:
                parts.append(f"{key}: {value}")
        return ", ".join(parts) if parts else str(record)

    def _create_response(
        self, original_msg: AgentMessage, search_response: SearchResponse
    ) -> AgentMessage:
        """
        Create response message for Orchestrator.

        Args:
            original_msg: Original request message.
            search_response: SearchResponse with results.

        Returns:
            AgentMessage with formatted response.
        """
        # Format results for display
        if search_response.results:
            result_text = "\n".join([r.content for r in search_response.results[:5]])
        else:
            result_text = ""

        return AgentMessage(
            trace_id=original_msg.trace_id,
            source_agent=self.name,
            target_agent=original_msg.source_agent,
            intent="search_response",
            payload={
                "result": result_text,
                "results": [r.model_dump() for r in search_response.results],
                "search_type": search_response.search_type.value,
                "count": len(search_response.results),
            },
            timestamp=time.time(),
        )


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Researcher", "SearchType", "SearchResult", "SearchResponse"]
