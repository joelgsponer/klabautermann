# RESEARCHER.md

**Version**: 2.0
**Purpose**: Specification for the Intelligent Researcher agent — an LLM-powered search planner and synthesizer
**Status**: Ready for Implementation

---

## 1. Overview

The **Researcher** is the Librarian of The Locker — Klabautermann's temporal knowledge graph. Unlike the previous regex-based implementation, this version uses **Claude Opus** to intelligently reason about search strategy, execute multiple techniques in parallel, and synthesize findings into a structured **Graph Intelligence Report**.

### 1.1 Key Capabilities

| Capability | Description |
|------------|-------------|
| **Intelligent Planning** | LLM analyzes query to determine optimal search techniques |
| **Parallel Execution** | Multiple search strategies run concurrently |
| **Strength-Aware Ranking** | Relationship strengths factor into result scoring |
| **Structured Reports** | Pydantic-based output for channel-agnostic rendering |
| **Temporal Awareness** | Handles historical queries and time-travel |

### 1.2 Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           USER QUERY                                     │
│                    "Who did Sarah work for last year?"                   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      SEARCH PLANNER (Opus)                               │
│  • Analyzes query semantics                                              │
│  • Identifies relevant techniques                                        │
│  • Outputs SearchPlan with strategies                                    │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│ VECTOR SEARCH │     │ ENTITY SEARCH │     │  STRUCTURAL   │
│  (Graphiti)   │     │  (Fulltext)   │     │   (Cypher)    │
└───────┬───────┘     └───────┬───────┘     └───────┬───────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    RESULT AGGREGATOR                                     │
│  • Deduplicates across techniques                                        │
│  • Applies strength-aware scoring                                        │
│  • Ranks by composite score                                              │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    REPORT SYNTHESIZER (Opus)                             │
│  • Generates direct answer                                               │
│  • Compiles evidence with attribution                                    │
│  • Calculates confidence                                                 │
│  • Outputs GraphIntelligenceReport                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Model Selection

| Stage | Model | Rationale |
|-------|-------|-----------|
| **Search Planning** | `claude-opus-4-5-20251101` | Complex reasoning about query intent and technique selection |
| **Report Synthesis** | `claude-opus-4-5-20251101` | Nuanced summarization with confidence calibration |

**Why Opus?** The Researcher must reason about:
- Ambiguous queries ("Tell me about the project" — which one?)
- Multi-hop relationships (person → org → project → goal)
- Temporal nuance (current vs historical state)
- Confidence calibration (strong vs weak evidence)

Haiku lacks the reasoning depth for these decisions.

---

## 2. Search Strategy Planning

The LLM analyzes each query and produces a `SearchPlan` specifying which techniques to use.

### 2.1 Available Search Techniques

| Technique | Use Case | Implementation |
|-----------|----------|----------------|
| **VECTOR** | Semantic similarity, conceptual queries | `graphiti.search(query, limit)` |
| **ENTITY_FULLTEXT** | Finding entities by name | `graphiti.search_entities(query, limit)` |
| **STRUCTURAL** | Relationship traversal, hierarchies | `neo4j.execute_query(cypher, params)` |
| **TEMPORAL** | Time-bounded queries, historical state | Cypher with `created_at`/`expired_at` filters |

### 2.2 Search Planning Prompt

```
You are the Klabautermann Researcher — the Librarian of The Locker.

Your task: Analyze the user's query and create a search plan.

═══════════════════════════════════════════════════════════════════════════
AVAILABLE SEARCH TECHNIQUES
═══════════════════════════════════════════════════════════════════════════

1. VECTOR
   When: Semantic similarity, "remind me about...", conceptual queries
   Returns: Facts/edges ranked by embedding similarity

2. ENTITY_FULLTEXT
   When: Looking for specific entities by name
   Returns: Entity nodes matching the search term

3. STRUCTURAL
   When: Relationship queries, hierarchies, chains
   Patterns:
   - WORKS_AT: Person → Organization employment
   - REPORTS_TO: Person → Person management chain
   - BLOCKS/DEPENDS_ON: Task dependencies
   - KNOWS/FRIEND_OF: Interpersonal (has strength property)
   - ATTENDED: Event participation
   - CONTRIBUTES_TO: Project → Goal alignment

4. TEMPORAL
   When: "last week", "in 2024", "yesterday", historical state
   Adds: Time filters on created_at/expired_at

═══════════════════════════════════════════════════════════════════════════
RELATIONSHIP STRENGTHS
═══════════════════════════════════════════════════════════════════════════

These edges have `strength` (0.0-1.0) properties:
- KNOWS.strength — How well people know each other
- FRIEND_OF.strength — Closeness of friendship
- CONTRIBUTES_TO.weight — Project-goal contribution
- PART_OF_ISLAND.weight — Community centrality

Set consider_strength=true when relationship closeness matters.

═══════════════════════════════════════════════════════════════════════════
PLANNING RULES
═══════════════════════════════════════════════════════════════════════════

1. PREFER PARALLEL: If multiple techniques might help, include all
2. BE SPECIFIC: For STRUCTURAL, specify the exact relationship type
3. HONOR TEMPORAL: Parse time references into TimeRange
4. DEFAULT CURRENT: Unless history requested, filter to current state
5. NEVER FABRICATE: When uncertain, include more techniques

═══════════════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════════════

Return valid JSON matching this schema:
{
  "original_query": "the user's query",
  "reasoning": "why you chose these techniques",
  "strategies": [
    {
      "technique": "VECTOR|ENTITY_FULLTEXT|STRUCTURAL|TEMPORAL",
      "query": "search string (for VECTOR/ENTITY_FULLTEXT)",
      "cypher_pattern": "relationship type (for STRUCTURAL)",
      "params": {"key": "value"},
      "time_range": {"start": timestamp, "end": timestamp, "as_of": timestamp},
      "limit": 10,
      "consider_strength": false,
      "rationale": "why this technique"
    }
  ],
  "expected_result_type": "what the user wants to know",
  "zoom_level": "micro|meso|macro"
}
```

### 2.3 Planning Pseudocode

```python
async def _plan_search(
    self,
    query: str,
    context: dict[str, Any],
    trace_id: str,
) -> SearchPlan:
    """
    Use LLM to analyze query and produce a search plan.
    """
    logger.info("[CHART] Planning search course", extra={"trace_id": trace_id})

    # Build planning prompt with query and context
    prompt = self.PLANNING_PROMPT.format(
        query=query,
        captain_uuid=context.get("captain_uuid"),
        current_time=datetime.now(UTC).isoformat(),
    )

    # Add conversation context if available
    if recent_messages := context.get("recent_messages"):
        context_str = "\n".join(
            f"{m['role']}: {m['content'][:100]}"
            for m in recent_messages[-3:]
        )
        prompt = f"Recent conversation:\n{context_str}\n\n{prompt}"

    # Call Opus for planning
    response = await self._call_opus(
        messages=[{"role": "user", "content": prompt}],
        trace_id=trace_id,
    )

    # Parse and validate response
    try:
        json_str = self._extract_json(response)
        plan = SearchPlan.model_validate_json(json_str)
        logger.info(
            "[BEACON] Search plan charted",
            extra={
                "trace_id": trace_id,
                "strategy_count": len(plan.strategies),
                "techniques": [s.technique.value for s in plan.strategies],
            }
        )
        return plan
    except ValidationError as e:
        logger.warning(
            "[SWELL] Plan validation failed, using fallback",
            extra={"trace_id": trace_id, "error": str(e)}
        )
        return self._fallback_plan(query)


def _fallback_plan(self, query: str) -> SearchPlan:
    """
    Fallback when LLM planning fails.
    Uses both vector and entity search for broad coverage.
    """
    return SearchPlan(
        original_query=query,
        reasoning="Fallback: LLM planning failed",
        strategies=[
            SearchStrategy(
                technique=SearchTechnique.VECTOR,
                query=query,
                limit=10,
                rationale="Fallback semantic search",
            ),
            SearchStrategy(
                technique=SearchTechnique.ENTITY_FULLTEXT,
                query=query,
                limit=5,
                rationale="Fallback entity lookup",
            ),
        ],
        expected_result_type="general information",
        zoom_level="micro",
    )
```

---

## 3. Parallel Execution Model

All planned strategies execute concurrently using `asyncio.gather`.

### 3.1 Execution Pseudocode

```python
async def _execute_search_plan(
    self,
    plan: SearchPlan,
    trace_id: str,
) -> dict[str, list[RawSearchResult]]:
    """
    Execute all search strategies in parallel.

    Returns results grouped by technique. Individual failures
    don't fail the entire search — they return empty lists.
    """
    logger.info(
        "[ANCHOR] Launching parallel searches",
        extra={"trace_id": trace_id, "count": len(plan.strategies)}
    )

    # Build coroutines for each strategy
    search_tasks: list[Coroutine] = []
    task_labels: list[str] = []

    for strategy in plan.strategies:
        match strategy.technique:
            case SearchTechnique.VECTOR:
                search_tasks.append(
                    self._execute_vector_search(
                        strategy.query or plan.original_query,
                        strategy.limit,
                        trace_id,
                    )
                )
                task_labels.append(f"vector:{strategy.query}")

            case SearchTechnique.ENTITY_FULLTEXT:
                search_tasks.append(
                    self._execute_entity_search(
                        strategy.query or plan.original_query,
                        strategy.limit,
                        trace_id,
                    )
                )
                task_labels.append(f"entity:{strategy.query}")

            case SearchTechnique.STRUCTURAL:
                search_tasks.append(
                    self._execute_structural_search(
                        strategy.cypher_pattern,
                        strategy.params,
                        strategy.consider_strength,
                        trace_id,
                    )
                )
                task_labels.append(f"structural:{strategy.cypher_pattern}")

            case SearchTechnique.TEMPORAL:
                search_tasks.append(
                    self._execute_temporal_search(
                        strategy.query or plan.original_query,
                        strategy.time_range,
                        trace_id,
                    )
                )
                task_labels.append(f"temporal:{strategy.time_range}")

    # Execute all in parallel
    results = await asyncio.gather(*search_tasks, return_exceptions=True)

    # Map results, handling individual failures gracefully
    results_by_technique: dict[str, list[RawSearchResult]] = {}
    for label, result in zip(task_labels, results):
        if isinstance(result, Exception):
            logger.warning(
                "[SWELL] Search strategy failed",
                extra={"trace_id": trace_id, "strategy": label, "error": str(result)}
            )
            results_by_technique[label] = []
        else:
            results_by_technique[label] = result
            logger.debug(
                "[WHISPER] Strategy returned results",
                extra={"trace_id": trace_id, "strategy": label, "count": len(result)}
            )

    return results_by_technique
```

### 3.2 Individual Search Implementations

#### Vector Search

```python
async def _execute_vector_search(
    self,
    query: str,
    limit: int,
    trace_id: str,
) -> list[RawSearchResult]:
    """
    Semantic search via Graphiti embeddings.
    Returns facts/edges ranked by similarity.
    """
    results = await self.graphiti.search(query, limit=limit)

    return [
        RawSearchResult(
            content=r.content or r.fact or "",
            source_technique=SearchTechnique.VECTOR,
            source_id=r.uuid,
            source_episode=r.metadata.get("episode_uuid"),
            vector_score=r.score,
            temporal_context=TemporalContext(
                created_at=r.metadata.get("created_at", 0),
                expired_at=r.metadata.get("expired_at"),
                is_current=r.metadata.get("expired_at") is None,
            ) if r.metadata.get("created_at") else None,
        )
        for r in results
    ]
```

#### Entity Fulltext Search

```python
async def _execute_entity_search(
    self,
    query: str,
    limit: int,
    trace_id: str,
) -> list[RawSearchResult]:
    """
    Direct entity lookup via Neo4j fulltext index.
    Returns entity nodes matching the search term.
    """
    results = await self.graphiti.search_entities(query, limit=limit, trace_id=trace_id)

    return [
        RawSearchResult(
            content=f"{r.name}: {r.content}" if r.content else r.name,
            source_technique=SearchTechnique.ENTITY_FULLTEXT,
            source_id=r.uuid,
            vector_score=r.score,
        )
        for r in results
    ]
```

#### Structural Search

```python
async def _execute_structural_search(
    self,
    relationship_type: str | None,
    params: dict[str, Any],
    consider_strength: bool,
    trace_id: str,
) -> list[RawSearchResult]:
    """
    Graph traversal via Cypher query.
    Optionally includes relationship strength in results.
    """
    cypher = self._build_structural_query(relationship_type, consider_strength)
    records = await self.neo4j.execute_query(cypher, params)

    results = []
    for record in records:
        strengths = []
        if consider_strength and "strength" in record:
            strength = record.get("strength")
            if strength is not None:
                strengths.append(float(strength))

        results.append(
            RawSearchResult(
                content=self._format_record(record),
                source_technique=SearchTechnique.STRUCTURAL,
                source_id=record.get("uuid"),
                relationship_strengths=strengths,
                temporal_context=TemporalContext(
                    created_at=record.get("created_at", 0),
                    expired_at=record.get("expired_at"),
                    is_current=record.get("expired_at") is None,
                ) if record.get("created_at") else None,
            )
        )

    return results
```

### 3.3 Cypher Patterns for Structural Search

```python
STRUCTURAL_QUERIES: dict[str, str] = {
    # Employment relationships
    "WORKS_AT": """
        MATCH (p:Person)-[r:WORKS_AT]->(o:Organization)
        WHERE p.name =~ $name_pattern
          AND r.expired_at IS NULL
        RETURN p.uuid as person_uuid, p.name as person,
               o.uuid as org_uuid, o.name as organization,
               r.title as title, r.department as department,
               r.created_at as created_at
        ORDER BY r.created_at DESC
        LIMIT $limit
    """,

    # Management chain
    "REPORTS_TO": """
        MATCH (p:Person)-[r:REPORTS_TO]->(m:Person)
        WHERE p.name =~ $name_pattern
          AND r.expired_at IS NULL
        RETURN p.name as person, m.name as manager,
               r.created_at as created_at
        LIMIT $limit
    """,

    # Task dependencies
    "BLOCKS": """
        MATCH (blocker:Task)-[r:BLOCKS]->(blocked:Task)
        WHERE blocker.status <> 'completed'
          AND r.expired_at IS NULL
        RETURN blocker.uuid as blocker_uuid, blocker.action as blocker,
               blocked.uuid as blocked_uuid, blocked.action as blocked_task,
               r.reason as reason
        LIMIT $limit
    """,

    # Interpersonal with strength
    "KNOWS": """
        MATCH (a:Person)-[r:KNOWS]->(b:Person)
        WHERE a.name =~ $name_pattern
          AND r.expired_at IS NULL
        RETURN a.name as person, b.name as knows,
               r.strength as strength, r.context as context,
               r.created_at as created_at
        ORDER BY r.strength DESC NULLS LAST
        LIMIT $limit
    """,

    # Friendship with strength
    "FRIEND_OF": """
        MATCH (a:Person)-[r:FRIEND_OF]->(b:Person)
        WHERE a.name =~ $name_pattern
          AND r.expired_at IS NULL
        RETURN a.name as person, b.name as friend,
               r.strength as strength, r.how_met as how_met,
               r.since as since
        ORDER BY r.strength DESC NULLS LAST
        LIMIT $limit
    """,

    # Historical employment (time-travel)
    "WORKS_AT_HISTORICAL": """
        MATCH (p:Person)-[r:WORKS_AT]->(o:Organization)
        WHERE p.name =~ $name_pattern
          AND r.created_at <= $as_of
          AND (r.expired_at IS NULL OR r.expired_at > $as_of)
        RETURN p.name as person, o.name as organization,
               r.title as title, r.created_at as since,
               r.expired_at as until
        ORDER BY r.created_at DESC
        LIMIT $limit
    """,

    # Project-Goal alignment with weight
    "CONTRIBUTES_TO": """
        MATCH (proj:Project)-[r:CONTRIBUTES_TO]->(goal:Goal)
        WHERE proj.name =~ $name_pattern
          AND r.expired_at IS NULL
        RETURN proj.name as project, goal.name as goal,
               r.weight as weight, r.how as contribution
        ORDER BY r.weight DESC NULLS LAST
        LIMIT $limit
    """,
}
```

---

## 4. Relationship Strength Scoring

Results from multiple techniques are aggregated and scored, with relationship strength boosting relevance.

### 4.1 Scoring Algorithm

```python
STRENGTH_BOOST_FACTOR = 0.3  # Configurable

def _calculate_result_score(
    self,
    result: RawSearchResult,
) -> float:
    """
    Calculate composite score incorporating relationship strengths.

    Formula:
    final_score = base_score * (1 + avg_strength * STRENGTH_BOOST_FACTOR)

    - base_score: vector_score if available, else 1.0
    - avg_strength: mean of relationship_strengths, or 0 if empty
    - STRENGTH_BOOST_FACTOR: configurable multiplier (default 0.3)

    Example:
    - Vector score 0.8, relationship strength 0.9
    - final = 0.8 * (1 + 0.9 * 0.3) = 0.8 * 1.27 = 1.016
    """
    base_score = result.vector_score if result.vector_score is not None else 1.0

    if result.relationship_strengths:
        avg_strength = sum(result.relationship_strengths) / len(result.relationship_strengths)
        boost = 1 + (avg_strength * STRENGTH_BOOST_FACTOR)
    else:
        boost = 1.0

    return base_score * boost
```

### 4.2 Result Aggregation

```python
def _aggregate_results(
    self,
    results_by_technique: dict[str, list[RawSearchResult]],
    max_results: int,
) -> list[RawSearchResult]:
    """
    Aggregate results from all techniques:
    1. Flatten all results
    2. Deduplicate by source_id
    3. Calculate composite scores
    4. Sort by score descending
    5. Return top N
    """
    all_results: list[RawSearchResult] = []
    seen_ids: set[str] = set()

    for technique_results in results_by_technique.values():
        for result in technique_results:
            # Deduplicate by source_id
            if result.source_id and result.source_id in seen_ids:
                continue
            if result.source_id:
                seen_ids.add(result.source_id)

            all_results.append(result)

    # Sort by composite score
    all_results.sort(
        key=lambda r: self._calculate_result_score(r),
        reverse=True
    )

    return all_results[:max_results]
```

---

## 5. Graph Intelligence Report

The final output is a structured Pydantic model. Channels (CLI, Telegram, Web) render it according to their capabilities.

### 5.1 Report Structure

```
GraphIntelligenceReport
├── query: str                      # Original user query
├── direct_answer: str              # Clear, actionable answer
├── confidence: float               # 0.0-1.0 composite score
├── confidence_level: ConfidenceLevel  # HIGH/MEDIUM/LOW/UNCERTAIN
│
├── evidence: list[EvidenceItem]    # Supporting facts with attribution
│   ├── fact: str
│   ├── relationship: str
│   ├── source: str
│   ├── confidence: float
│   └── temporal_note: str | None
│
├── relationships: list[RelationshipDetail]  # Relevant connections
│   ├── source_name, source_type
│   ├── relationship_type
│   ├── target_name, target_type
│   ├── strength: float | None
│   ├── context: str | None
│   └── temporal: TemporalContext | None
│
├── key_entities: list[str]         # Primary entities in answer
│
├── as_of_date: str                 # Report currency date
├── historical_notes: list[str]     # Notes about past state
│
├── search_techniques_used: list[SearchTechnique]
├── result_count: int
│
├── related_queries: list[str]      # Suggested follow-ups
└── gaps_identified: list[str]      # Missing information
```

### 5.2 Confidence Calculation

```python
def _calculate_confidence(
    self,
    results: list[RawSearchResult],
) -> tuple[float, ConfidenceLevel]:
    """
    Calculate overall confidence based on evidence quality.

    Factors:
    - Number of supporting sources
    - Consistency across techniques
    - Recency of information
    - Average vector similarity scores
    """
    if not results:
        return 0.0, ConfidenceLevel.UNCERTAIN

    # Factor 1: Number of sources (diminishing returns)
    source_factor = min(len(results) / 5, 1.0)  # Max out at 5 sources

    # Factor 2: Average vector score
    vector_scores = [r.vector_score for r in results if r.vector_score]
    avg_vector = sum(vector_scores) / len(vector_scores) if vector_scores else 0.5

    # Factor 3: Technique diversity (more techniques = more confident)
    techniques_used = len({r.source_technique for r in results})
    diversity_factor = min(techniques_used / 3, 1.0)  # Max out at 3 techniques

    # Factor 4: Recency (current facts weighted higher)
    current_count = sum(
        1 for r in results
        if r.temporal_context and r.temporal_context.is_current
    )
    recency_factor = current_count / len(results) if results else 0.5

    # Weighted combination
    confidence = (
        source_factor * 0.3 +
        avg_vector * 0.3 +
        diversity_factor * 0.2 +
        recency_factor * 0.2
    )

    # Map to level
    if confidence >= 0.8:
        level = ConfidenceLevel.HIGH
    elif confidence >= 0.5:
        level = ConfidenceLevel.MEDIUM
    elif confidence >= 0.3:
        level = ConfidenceLevel.LOW
    else:
        level = ConfidenceLevel.UNCERTAIN

    return confidence, level
```

---

## 6. Pydantic Models

Complete model definitions for implementation.

```python
"""
Pydantic models for the Intelligent Researcher agent.
Location: src/klabautermann/agents/researcher_models.py
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════


class SearchTechnique(str, Enum):
    """Available search techniques."""
    VECTOR = "vector"
    ENTITY_FULLTEXT = "entity_fulltext"
    STRUCTURAL = "structural"
    TEMPORAL = "temporal"


class ConfidenceLevel(str, Enum):
    """Human-readable confidence levels."""
    HIGH = "high"           # 0.8-1.0
    MEDIUM = "medium"       # 0.5-0.8
    LOW = "low"             # 0.3-0.5
    UNCERTAIN = "uncertain" # 0.0-0.3


# ═══════════════════════════════════════════════════════════════════════════
# SEARCH PLANNING MODELS
# ═══════════════════════════════════════════════════════════════════════════


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
    cypher_pattern: str | None = Field(default=None, description="Relationship type for STRUCTURAL")
    params: dict[str, Any] = Field(default_factory=dict, description="Cypher parameters")
    time_range: TimeRange | None = Field(default=None, description="Time constraints")
    limit: int = Field(default=10, ge=1, le=100)
    consider_strength: bool = Field(default=False, description="Factor relationship strength into ranking")
    rationale: str = Field(description="Why this technique was chosen")


class SearchPlan(BaseModel):
    """LLM-generated search plan."""
    original_query: str
    reasoning: str = Field(description="LLM's reasoning for technique selection")
    strategies: list[SearchStrategy] = Field(default_factory=list)
    expected_result_type: str = Field(description="What the user wants to know")
    zoom_level: str = Field(default="micro", pattern="^(auto|macro|meso|micro)$")


# ═══════════════════════════════════════════════════════════════════════════
# SEARCH RESULT MODELS
# ═══════════════════════════════════════════════════════════════════════════


class TemporalContext(BaseModel):
    """Temporal validity of a fact."""
    created_at: float
    expired_at: float | None = None
    is_current: bool = True
    human_readable: str | None = Field(default=None, description="e.g., 'since March 2024'")


class RawSearchResult(BaseModel):
    """Single result from a search technique."""
    content: str
    source_technique: SearchTechnique
    source_id: str | None = None
    source_episode: str | None = None
    vector_score: float | None = Field(default=None, ge=0.0, le=1.0)
    relationship_strengths: list[float] = Field(default_factory=list)
    temporal_context: TemporalContext | None = None


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH INTELLIGENCE REPORT MODELS
# ═══════════════════════════════════════════════════════════════════════════


class EvidenceItem(BaseModel):
    """Supporting evidence for the answer."""
    fact: str
    relationship: str = Field(description="Relationship type that supports this")
    source: str = Field(description="Episode or node ID")
    confidence: float = Field(ge=0.0, le=1.0)
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
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel

    # Supporting evidence
    evidence: list[EvidenceItem] = Field(default_factory=list)

    # Relationship context
    relationships: list[RelationshipDetail] = Field(default_factory=list)
    key_entities: list[str] = Field(default_factory=list)

    # Temporal context
    as_of_date: str
    historical_notes: list[str] = Field(default_factory=list)

    # Search metadata
    search_techniques_used: list[SearchTechnique] = Field(default_factory=list)
    result_count: int

    # Navigation
    related_queries: list[str] = Field(default_factory=list)
    gaps_identified: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# AGENT MESSAGE PAYLOADS
# ═══════════════════════════════════════════════════════════════════════════


class ResearcherRequest(BaseModel):
    """Payload for Orchestrator → Researcher."""
    query: str
    context: dict[str, Any] = Field(default_factory=dict)
    zoom_level: str = Field(default="auto")
    include_historical: bool = Field(default=False)
    max_results: int = Field(default=20, ge=1, le=100)


class ResearcherResponse(BaseModel):
    """Payload for Researcher → Orchestrator."""
    report: GraphIntelligenceReport
    raw_result_count: int
    search_latency_ms: float
    synthesis_latency_ms: float
```

---

## 7. Report Synthesis Prompt

```
You are synthesizing a Graph Intelligence Report for Klabautermann.

═══════════════════════════════════════════════════════════════════════════
INPUT
═══════════════════════════════════════════════════════════════════════════

Original Query: {query}

Search Techniques Used: {techniques}

Raw Search Results:
{formatted_results}

═══════════════════════════════════════════════════════════════════════════
YOUR TASK
═══════════════════════════════════════════════════════════════════════════

Create a GraphIntelligenceReport with these sections:

1. DIRECT ANSWER
   - Clear, actionable response to the query
   - Lead with what the user wants to know
   - If incomplete, state what you DO know
   - NEVER fabricate facts not in the results

2. CONFIDENCE (0.0-1.0)
   - Consider: number of sources, consistency, recency, relationship strengths
   - HIGH (0.8+): Multiple consistent sources, strong relationships
   - MEDIUM (0.5-0.8): Single source or some inconsistency
   - LOW (0.3-0.5): Weak evidence, inferred
   - UNCERTAIN (<0.3): Minimal evidence

3. EVIDENCE
   - List specific facts supporting the answer
   - Include source attribution (episode ID, node type)
   - Note temporal context (when facts were true)

4. RELATIONSHIPS
   - Highlight connections between entities
   - Include strength values where available
   - Note how Captain connects to mentioned entities

5. TEMPORAL CONTEXT
   - Current date: {current_date}
   - Flag historical information
   - Note recent changes

6. RELATED QUERIES
   - 1-2 natural follow-up questions

7. GAPS IDENTIFIED
   - Information that would improve the answer but wasn't found

═══════════════════════════════════════════════════════════════════════════
OUTPUT
═══════════════════════════════════════════════════════════════════════════

Return valid JSON matching the GraphIntelligenceReport schema.

Remember: You are the Librarian. Present findings with confidence but never
claim knowledge beyond what the search returned. "I don't have that in The
Locker" is an acceptable answer.
```

---

## 8. Integration

### 8.1 Orchestrator Dispatch

```python
# In Orchestrator._handle_search()
async def _handle_search(
    self,
    intent: IntentClassification,
    context: ThreadContext | None,
    trace_id: str,
) -> str:
    """Dispatch search to Researcher and format response."""

    if not self._has_agent("researcher"):
        return "The Researcher is not available."

    # Build request payload
    request = ResearcherRequest(
        query=intent.query or "",
        context={
            "captain_uuid": self.captain_uuid,
            "recent_messages": context.messages[-3:] if context else [],
        },
        zoom_level="auto",
        include_historical="history" in (intent.query or "").lower(),
    )

    # Dispatch and wait
    response = await self._dispatch_and_wait(
        "researcher",
        request.model_dump(),
        trace_id,
        timeout=60.0,  # Longer timeout for Opus
    )

    if not response:
        return "The Researcher didn't respond in time."

    # Extract report
    report_data = response.payload.get("report")
    if not report_data:
        return "The Researcher found nothing in The Locker."

    report = GraphIntelligenceReport.model_validate(report_data)

    # Format for channel (this is channel-specific)
    return self._format_intelligence_report(report)
```

### 8.2 Configuration

```yaml
# config/agents/researcher.yaml
model:
  planning: claude-opus-4-5-20251101
  synthesis: claude-opus-4-5-20251101
  temperature: 0.3  # Lower for more deterministic planning

search:
  max_parallel_strategies: 4
  default_result_limit: 10
  max_total_results: 50
  timeout_seconds: 30

scoring:
  strength_boost_factor: 0.3
  source_factor_weight: 0.3
  vector_factor_weight: 0.3
  diversity_factor_weight: 0.2
  recency_factor_weight: 0.2

confidence_thresholds:
  high: 0.8
  medium: 0.5
  low: 0.3

timeouts:
  planning: 15.0
  execution: 30.0
  synthesis: 20.0
```

### 8.3 Zoom Level Support

| Level | When Used | Query Target |
|-------|-----------|--------------|
| `auto` | Default — LLM decides | Determined by query analysis |
| `macro` | "big picture", "overview" | Community nodes, island summaries |
| `meso` | "project status", "thread" | Note, Project, Thread nodes |
| `micro` | Specific facts, details | Entity facts, relationships |

---

## 9. Examples

### 9.1 Query → Plan → Report Flow

**User Query**: "Who did Sarah work for last year?"

**SearchPlan** (from LLM):
```json
{
  "original_query": "Who did Sarah work for last year?",
  "reasoning": "This is a temporal employment query. Need STRUCTURAL for WORKS_AT relationship with historical time filter. Also ENTITY_FULLTEXT to find Sarah's node. VECTOR as fallback for semantic context.",
  "strategies": [
    {
      "technique": "ENTITY_FULLTEXT",
      "query": "Sarah",
      "limit": 3,
      "rationale": "Find Sarah's entity node"
    },
    {
      "technique": "STRUCTURAL",
      "cypher_pattern": "WORKS_AT_HISTORICAL",
      "params": {"name_pattern": "(?i).*sarah.*"},
      "time_range": {"as_of": 1704067200},
      "limit": 5,
      "rationale": "Historical employment as of Jan 2025"
    },
    {
      "technique": "VECTOR",
      "query": "Sarah employment job work",
      "limit": 5,
      "rationale": "Semantic fallback for employment context"
    }
  ],
  "expected_result_type": "historical employer",
  "zoom_level": "micro"
}
```

**GraphIntelligenceReport** (final output):
```json
{
  "query": "Who did Sarah work for last year?",
  "direct_answer": "Last year (2025), Sarah Chen worked at TechStart Inc as a Senior Engineer. She transitioned to Acme Corp in March 2025.",
  "confidence": 0.87,
  "confidence_level": "high",
  "evidence": [
    {
      "fact": "Sarah Chen → TechStart Inc (Senior Engineer)",
      "relationship": "WORKS_AT",
      "source": "episode-2024-06-15",
      "confidence": 0.92,
      "temporal_note": "Valid from June 2024 to March 2025"
    },
    {
      "fact": "Sarah Chen → Acme Corp (VP Engineering)",
      "relationship": "WORKS_AT",
      "source": "episode-2025-03-20",
      "confidence": 0.95,
      "temporal_note": "Since March 2025 (current)"
    }
  ],
  "relationships": [
    {
      "source_name": "Sarah Chen",
      "source_type": "Person",
      "relationship_type": "WORKS_AT",
      "target_name": "TechStart Inc",
      "target_type": "Organization",
      "strength": null,
      "context": null,
      "temporal": {
        "created_at": 1718409600,
        "expired_at": 1709424000,
        "is_current": false,
        "human_readable": "June 2024 - March 2025"
      }
    }
  ],
  "key_entities": ["Sarah Chen", "TechStart Inc", "Acme Corp"],
  "as_of_date": "2026-01-16",
  "historical_notes": ["Query requested historical state (last year)"],
  "search_techniques_used": ["entity_fulltext", "structural", "vector"],
  "result_count": 8,
  "related_queries": [
    "What does Sarah do at Acme Corp?",
    "Who else works at TechStart Inc?"
  ],
  "gaps_identified": []
}
```

---

## 10. Related Specifications

- [AGENTS.md](./architecture/AGENTS.md) — Agent crew overview (Section 1.3)
- [MEMORY.md](./architecture/MEMORY.md) — Temporal graph architecture
- [ONTOLOGY.md](./architecture/ONTOLOGY.md) — Entity and relationship schema
- [MAINAGENT.md](./MAINAGENT.md) — Orchestrator v2 integration

---

*"The wise Librarian searches not just the shelves, but understands what the sailor truly seeks."*
