# Implement Researcher Agent

## Metadata
- **ID**: T024
- **Priority**: P0
- **Category**: subagent
- **Effort**: L
- **Status**: pending
- **Assignee**: @backend-engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.3
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md)
- Related: [ONTOLOGY.md](../../specs/architecture/ONTOLOGY.md)

## Dependencies
- [ ] T021 - Agent delegation pattern
- [x] T009 - Graphiti client
- [x] T010 - Neo4j client
- [x] T016 - Base Agent class

## Context
The Researcher is the "Librarian" that performs hybrid search across the knowledge graph. It combines vector search (semantic similarity) with graph traversal (structural queries) and temporal filtering (time-based queries). The Researcher NEVER fabricates results - if nothing is found, it returns empty.

## Requirements
- [ ] Create `src/klabautermann/agents/researcher.py`:

### Search Strategy Classification
- [ ] Classify query type:
  - SEMANTIC: "What was that thing about...", general recall
  - STRUCTURAL: "Who reports to...", "What blocks...", relationship queries
  - TEMPORAL: "Last week", "in 2024", time-filtered queries
  - HYBRID: Combination of above

### Vector Search
- [ ] Use Graphiti's `search()` for semantic queries
- [ ] Return results with similarity scores
- [ ] Include source attribution (Note, Event, Thread)

### Structural Search
- [ ] Execute Cypher queries for relationship traversal
- [ ] Support multi-hop paths (A->B->C)
- [ ] Handle common patterns:
  - Person relationships (WORKS_AT, REPORTS_TO)
  - Task hierarchies (PART_OF, BLOCKS)
  - Event attendance (ATTENDED, HELD_AT)

### Temporal Search
- [ ] Filter by `created_at` and `expired_at`
- [ ] Support relative time ("last week", "yesterday")
- [ ] Support absolute time ("in 2024", "on January 5")
- [ ] Return historical state for time-travel queries

### Result Formatting
- [ ] Include source attribution
- [ ] Include confidence/relevance score
- [ ] Include temporal context
- [ ] Format for Orchestrator consumption

## Acceptance Criteria
- [ ] "Who is Sarah?" returns Person node with properties
- [ ] "Who does Sarah work for?" traverses WORKS_AT relationship
- [ ] "What tasks are blocked?" finds BLOCKS relationships
- [ ] "What did I do last week?" filters by time range
- [ ] Empty results return gracefully (no fabrication)

## Implementation Notes

```python
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field
import re

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.models import AgentMessage
from klabautermann.core.logger import logger


class SearchType(str, Enum):
    SEMANTIC = "semantic"
    STRUCTURAL = "structural"
    TEMPORAL = "temporal"
    HYBRID = "hybrid"


class SearchResult(BaseModel):
    """Single search result."""
    content: str
    source: str  # Node type or "graphiti"
    source_id: Optional[str] = None
    confidence: float = 1.0
    temporal_context: Optional[str] = None


class SearchResponse(BaseModel):
    """Complete search response."""
    query: str
    search_type: SearchType
    results: List[SearchResult] = Field(default_factory=list)
    summary: Optional[str] = None


class Researcher(BaseAgent):
    """
    The Researcher: performs hybrid search across the knowledge graph.

    Uses Claude Haiku for query understanding.
    Combines vector search, graph traversal, and temporal filtering.
    NEVER fabricates results.
    """

    # Patterns for query classification
    STRUCTURAL_PATTERNS = [
        r"who (?:does|did) .+ (?:work|report)",
        r"what (?:blocks|is blocked)",
        r"who (?:attended|went to)",
        r"what (?:project|task).+ part of",
    ]

    TEMPORAL_PATTERNS = [
        r"last (?:week|month|year)",
        r"yesterday|today|tomorrow",
        r"in \d{4}",
        r"(?:on|before|after) (?:january|february|march|april|may|june|july|august|september|october|november|december)",
    ]

    def __init__(
        self,
        name: str = "researcher",
        config: Optional[dict] = None,
        graphiti_client = None,
        neo4j_client = None,
        llm_client = None,
    ):
        super().__init__(name, config)
        self.graphiti = graphiti_client
        self.neo4j = neo4j_client
        self.llm = llm_client
        self.model = config.get("model", "claude-3-haiku-20240307") if config else "claude-3-haiku-20240307"

    async def process_message(self, msg: AgentMessage) -> Optional[AgentMessage]:
        """Process search request."""
        query = msg.payload.get("query", "")

        if not query:
            logger.warning(
                f"[SWELL] Researcher received empty query",
                extra={"trace_id": msg.trace_id}
            )
            return self._create_response(msg, SearchResponse(query="", search_type=SearchType.SEMANTIC))

        try:
            # Classify search type
            search_type = self._classify_search_type(query)

            logger.debug(
                f"[WHISPER] Search type: {search_type}",
                extra={"trace_id": msg.trace_id, "query": query}
            )

            # Execute appropriate search
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
                extra={"trace_id": msg.trace_id}
            )

            return self._create_response(msg, response)

        except Exception as e:
            logger.error(
                f"[STORM] Search failed: {e}",
                extra={"trace_id": msg.trace_id},
                exc_info=True,
            )
            return self._create_response(
                msg,
                SearchResponse(query=query, search_type=SearchType.SEMANTIC, summary="Search failed.")
            )

    def _classify_search_type(self, query: str) -> SearchType:
        """Classify the type of search needed."""
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
        """Perform vector search via Graphiti."""
        results = await self.graphiti.search(query, num_results=5)

        search_results = [
            SearchResult(
                content=r.get("content", ""),
                source="graphiti",
                source_id=r.get("uuid"),
                confidence=r.get("score", 0.5),
            )
            for r in results
        ]

        return SearchResponse(
            query=query,
            search_type=SearchType.SEMANTIC,
            results=search_results,
        )

    async def _structural_search(self, query: str, trace_id: str) -> SearchResponse:
        """Perform graph traversal search."""
        # Extract entity name from query
        # "Who does Sarah work for?" -> Sarah
        entity_match = re.search(r"(?:who|what) (?:does|did|is) (\w+)", query.lower())
        entity_name = entity_match.group(1).title() if entity_match else None

        if not entity_name:
            return SearchResponse(query=query, search_type=SearchType.STRUCTURAL)

        # Determine relationship type
        if "work" in query.lower():
            cypher = """
            MATCH (p:Person {name: $name})-[r:WORKS_AT]->(o:Organization)
            WHERE r.expired_at IS NULL
            RETURN p.name as person, o.name as org, r.title as title
            """
        elif "report" in query.lower():
            cypher = """
            MATCH (p:Person {name: $name})-[r:REPORTS_TO]->(m:Person)
            WHERE r.expired_at IS NULL
            RETURN p.name as person, m.name as manager
            """
        elif "block" in query.lower():
            cypher = """
            MATCH (t:Task)-[r:BLOCKS]->(blocked:Task)
            RETURN t.action as blocker, blocked.action as blocked_task
            """
        else:
            # Generic entity lookup
            cypher = """
            MATCH (n {name: $name})
            RETURN n, labels(n) as type
            """

        records = await self.neo4j.execute_query(cypher, {"name": entity_name})

        search_results = [
            SearchResult(
                content=str(dict(record)),
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

    async def _temporal_search(self, query: str, trace_id: str) -> SearchResponse:
        """Perform time-filtered search."""
        # Parse time reference
        time_filter = self._parse_time_reference(query)

        if time_filter:
            cypher = """
            MATCH (n)
            WHERE n.created_at >= $start AND n.created_at <= $end
            RETURN n, labels(n) as type
            LIMIT 10
            """
            records = await self.neo4j.execute_query(cypher, time_filter)

            search_results = [
                SearchResult(
                    content=str(dict(record)),
                    source="neo4j",
                    confidence=1.0,
                    temporal_context=f"Between {time_filter['start']} and {time_filter['end']}",
                )
                for record in records
            ]
        else:
            search_results = []

        return SearchResponse(
            query=query,
            search_type=SearchType.TEMPORAL,
            results=search_results,
        )

    async def _hybrid_search(self, query: str, trace_id: str) -> SearchResponse:
        """Combine semantic and structural search."""
        semantic = await self._semantic_search(query, trace_id)
        structural = await self._structural_search(query, trace_id)

        combined_results = semantic.results + structural.results

        return SearchResponse(
            query=query,
            search_type=SearchType.HYBRID,
            results=combined_results,
        )

    def _parse_time_reference(self, query: str) -> Optional[dict]:
        """Parse time references from query."""
        from datetime import datetime, timedelta

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
        else:
            return None

        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

    def _create_response(self, original_msg: AgentMessage, search_response: SearchResponse) -> AgentMessage:
        """Create response message for Orchestrator."""
        # Format results for display
        if search_response.results:
            result_text = "\n".join([r.content for r in search_response.results])
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
                "search_type": search_response.search_type,
            },
            timestamp=time.time(),
        )
```

This implementation will be refined based on T025 (hybrid search queries) which provides the complete Cypher query library.
