"""
Intelligent Researcher agent for Klabautermann.

The "Librarian" that uses Claude Opus to intelligently plan searches,
execute multiple techniques in parallel, and synthesize findings into
a Graph Intelligence Report.

NEVER fabricates results - returns empty if nothing found.

Reference: specs/RESEARCHER.md
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import anthropic
from pydantic import ValidationError

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.agents.researcher_models import (
    ConfidenceLevel,
    EvidenceItem,
    GraphIntelligenceReport,
    RawSearchResult,
    SearchPlan,
    SearchStrategy,
    SearchTechnique,
    TemporalContext,
    TimeRange,
    ZoomLevel,
)
from klabautermann.agents.researcher_prompts import PLANNING_PROMPT, SYNTHESIS_PROMPT
from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage


if TYPE_CHECKING:
    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.neo4j_client import Neo4jClient


# ===========================================================================
# Predefined Cypher Patterns
# ===========================================================================

STRUCTURAL_QUERIES: dict[str, str] = {
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
    "REPORTS_TO": """
        MATCH (p:Person)-[r:REPORTS_TO]->(m:Person)
        WHERE p.name =~ $name_pattern
          AND r.expired_at IS NULL
        RETURN p.name as person, m.name as manager,
               r.created_at as created_at
        LIMIT $limit
    """,
    "BLOCKS": """
        MATCH (blocker:Task)-[r:BLOCKS]->(blocked:Task)
        WHERE blocker.status <> 'completed'
          AND r.expired_at IS NULL
        RETURN blocker.uuid as blocker_uuid, blocker.action as blocker,
               blocked.uuid as blocked_uuid, blocked.action as blocked_task,
               r.reason as reason
        LIMIT $limit
    """,
    "DEPENDS_ON": """
        MATCH (t:Task)-[r:DEPENDS_ON]->(dep:Task)
        WHERE t.status <> 'completed'
          AND r.expired_at IS NULL
        RETURN t.action as task, dep.action as dependency,
               dep.status as dep_status, r.reason as reason
        LIMIT $limit
    """,
    # NOTE: Graphiti stores semantic relationships as RELATES_TO with r.name property
    "KNOWS": """
        MATCH (a:Person)-[r:RELATES_TO]->(b:Person)
        WHERE a.name =~ $name_pattern
          AND r.name =~ '(?i).*(knows|friend|connected|acquainted).*'
          AND r.expired_at IS NULL
        RETURN a.name as person, b.name as knows,
               r.name as relationship_type, r.fact as context,
               r.created_at as created_at
        ORDER BY r.created_at DESC
        LIMIT $limit
    """,
    "FRIEND_OF": """
        MATCH (a:Person)-[r:RELATES_TO]->(b:Person)
        WHERE a.name =~ $name_pattern
          AND r.name =~ '(?i).*(friend|close|best friend).*'
          AND r.expired_at IS NULL
        RETURN a.name as person, b.name as friend,
               r.name as relationship_type, r.fact as how_met,
               r.created_at as since
        ORDER BY r.created_at DESC
        LIMIT $limit
    """,
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
    "CONTRIBUTES_TO": """
        MATCH (proj:Project)-[r:CONTRIBUTES_TO]->(goal:Goal)
        WHERE proj.name =~ $name_pattern
          AND r.expired_at IS NULL
        RETURN proj.name as project, goal.name as goal,
               r.weight as weight, r.how as contribution
        ORDER BY r.weight DESC NULLS LAST
        LIMIT $limit
    """,
    "ATTENDED": """
        MATCH (p:Person)-[r:ATTENDED]->(e:Event)
        WHERE p.name =~ $name_pattern
        RETURN p.name as person, e.name as event,
               e.date as event_date, r.role as role
        ORDER BY e.date DESC
        LIMIT $limit
    """,
}


# ===========================================================================
# Intelligent Researcher Agent
# ===========================================================================


class Researcher(BaseAgent):
    """
    Intelligent Researcher agent - the "Librarian" of The Locker.

    Uses Claude Opus to:
    1. Plan optimal search strategies based on query analysis
    2. Execute multiple search techniques in parallel
    3. Aggregate results with strength-aware scoring
    4. Synthesize findings into a Graph Intelligence Report

    NEVER fabricates results. If nothing found, returns empty report.

    Reference: specs/RESEARCHER.md
    """

    def __init__(
        self,
        name: str = "researcher",
        config: dict[str, Any] | None = None,
        graphiti: GraphitiClient | None = None,
        neo4j: Neo4jClient | None = None,
    ) -> None:
        """
        Initialize the Intelligent Researcher.

        Args:
            name: Agent name (default: "researcher").
            config: Agent configuration with model settings.
            graphiti: GraphitiClient for vector search.
            neo4j: Neo4jClient for Cypher queries.
        """
        super().__init__(name, config)
        self.graphiti = graphiti
        self.neo4j = neo4j

        # Load configuration
        self.config = config or {}
        model_config = self.config.get("model", {})

        # Model settings - handle both dict format and simple string format
        if isinstance(model_config, dict):
            self.planning_model = model_config.get("planning", "claude-opus-4-5-20251101")
            self.synthesis_model = model_config.get("synthesis", "claude-opus-4-5-20251101")
            self.temperature = model_config.get("temperature", 0.3)
        else:
            # Simple string format: model is just the model name
            self.planning_model = "claude-opus-4-5-20251101"
            self.synthesis_model = "claude-opus-4-5-20251101"
            self.temperature = 0.3

        # Search settings
        search_config = self.config.get("search", {})
        self.max_parallel = search_config.get("max_parallel_strategies", 4)
        self.default_limit = search_config.get("default_result_limit", 10)
        self.max_results = search_config.get("max_total_results", 50)
        self.search_timeout = search_config.get("timeout_seconds", 30)

        # Scoring settings
        scoring_config = self.config.get("scoring", {})
        self.strength_boost_factor = scoring_config.get("strength_boost_factor", 0.3)

        # Timeout settings
        timeout_config = self.config.get("timeouts", {})
        self.planning_timeout = timeout_config.get("planning", 15.0)
        self.execution_timeout = timeout_config.get("execution", 30.0)
        self.synthesis_timeout = timeout_config.get("synthesis", 20.0)

        # Anthropic client
        self._anthropic: anthropic.AsyncAnthropic | None = None

    @property
    def anthropic_client(self) -> anthropic.AsyncAnthropic:
        """Lazy-initialize Anthropic client."""
        if self._anthropic is None:
            self._anthropic = anthropic.AsyncAnthropic()
        return self._anthropic

    # =========================================================================
    # Main Entry Point
    # =========================================================================

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process search request from Orchestrator.

        Args:
            msg: AgentMessage with search query and context.

        Returns:
            AgentMessage with GraphIntelligenceReport.
        """
        trace_id = msg.trace_id
        query = msg.payload.get("query", "")
        context = msg.payload.get("context", {})
        _zoom_level = msg.payload.get("zoom_level", "auto")  # Reserved for future use
        max_results = msg.payload.get("max_results", self.max_results)

        if not query:
            logger.warning(
                "[SWELL] Researcher received empty query",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return self._create_empty_response(msg, "No query provided")

        logger.info(
            "[CHART] Researcher processing query",
            extra={"trace_id": trace_id, "query": query[:100]},
        )

        try:
            start_time = time.time()

            # Step 1: Plan search strategies using Opus
            plan = await self._plan_search(query, context, trace_id)

            planning_time = (time.time() - start_time) * 1000
            logger.info(
                "[BEACON] Search plan ready",
                extra={
                    "trace_id": trace_id,
                    "strategies": len(plan.strategies),
                    "planning_ms": planning_time,
                },
            )

            # Step 2: Execute search strategies in parallel
            exec_start = time.time()
            results_by_technique = await self._execute_search_plan(plan, trace_id)
            execution_time = (time.time() - exec_start) * 1000

            # Step 3: Aggregate and score results
            aggregated = self._aggregate_results(results_by_technique, max_results)

            logger.info(
                "[BEACON] Search execution complete",
                extra={
                    "trace_id": trace_id,
                    "raw_results": sum(len(r) for r in results_by_technique.values()),
                    "aggregated": len(aggregated),
                    "execution_ms": execution_time,
                },
            )

            # Step 4: Synthesize report using Opus
            synth_start = time.time()
            report = await self._synthesize_report(query, aggregated, plan, trace_id)
            synthesis_time = (time.time() - synth_start) * 1000

            total_time = (time.time() - start_time) * 1000
            logger.info(
                "[ANCHOR] Research complete",
                extra={
                    "trace_id": trace_id,
                    "total_ms": total_time,
                    "confidence": report.confidence,
                },
            )

            return self._create_response(
                msg,
                report,
                raw_count=len(aggregated),
                search_ms=execution_time,
                synthesis_ms=synthesis_time,
            )

        except Exception as e:
            logger.error(
                f"[STORM] Research failed: {e}",
                extra={"trace_id": trace_id},
                exc_info=True,
            )
            return self._create_empty_response(msg, f"Research failed: {e}")

    # =========================================================================
    # Search Planning (Opus)
    # =========================================================================

    async def _plan_search(
        self,
        query: str,
        context: dict[str, Any],
        trace_id: str,
    ) -> SearchPlan:
        """
        Use Opus to analyze query and generate search plan.

        Args:
            query: User's search query.
            context: Additional context (captain_uuid, recent_messages).
            trace_id: Request trace ID.

        Returns:
            SearchPlan with strategies to execute.
        """
        logger.debug(
            "[WHISPER] Planning search strategy",
            extra={"trace_id": trace_id},
        )

        prompt = PLANNING_PROMPT.format(
            query=query,
            captain_uuid=context.get("captain_uuid", "unknown"),
            current_time=datetime.now(UTC).isoformat(),
        )

        try:
            response = await asyncio.wait_for(
                self._call_opus(prompt, self.planning_model, trace_id),
                timeout=self.planning_timeout,
            )

            # Extract JSON from response
            json_str = self._extract_json(response)
            plan = SearchPlan.model_validate_json(json_str)

            logger.debug(
                "[WHISPER] Search plan parsed",
                extra={
                    "trace_id": trace_id,
                    "strategies": [s.technique.value for s in plan.strategies],
                },
            )

            return plan

        except TimeoutError:
            logger.warning(
                "[SWELL] Planning timeout, using fallback",
                extra={"trace_id": trace_id},
            )
            return self._fallback_plan(query)

        except (ValidationError, json.JSONDecodeError) as e:
            logger.warning(
                f"[SWELL] Plan parsing failed: {e}, using fallback",
                extra={"trace_id": trace_id},
            )
            return self._fallback_plan(query)

    def _fallback_plan(self, query: str) -> SearchPlan:
        """
        Generate fallback search plan when LLM planning fails.

        Uses both vector and entity search for broad coverage.
        """
        return SearchPlan(
            original_query=query,
            reasoning="Fallback plan: LLM planning unavailable",
            strategies=[
                SearchStrategy(
                    technique=SearchTechnique.VECTOR,
                    query=query,
                    limit=self.default_limit,
                    rationale="Semantic search fallback",
                ),
                SearchStrategy(
                    technique=SearchTechnique.ENTITY_FULLTEXT,
                    query=query,
                    limit=5,
                    rationale="Entity lookup fallback",
                ),
            ],
            expected_result_type="general information",
            zoom_level="micro",
        )

    # =========================================================================
    # Parallel Search Execution
    # =========================================================================

    async def _execute_search_plan(
        self,
        plan: SearchPlan,
        trace_id: str,
    ) -> dict[str, list[RawSearchResult]]:
        """
        Execute all search strategies in parallel.

        Args:
            plan: SearchPlan with strategies to execute.
            trace_id: Request trace ID.

        Returns:
            Results grouped by technique label.
        """
        logger.debug(
            "[ANCHOR] Launching parallel searches",
            extra={"trace_id": trace_id, "count": len(plan.strategies)},
        )

        # Build coroutines for each strategy
        tasks: list[asyncio.Task] = []
        labels: list[str] = []

        for i, strategy in enumerate(plan.strategies[: self.max_parallel]):
            label = f"{strategy.technique.value}:{i}"
            labels.append(label)

            task: asyncio.Task
            match strategy.technique:
                case SearchTechnique.VECTOR:
                    task = asyncio.create_task(
                        self._execute_vector_search(
                            strategy.query or plan.original_query,
                            strategy.limit,
                            trace_id,
                        )
                    )
                case SearchTechnique.ENTITY_FULLTEXT:
                    task = asyncio.create_task(
                        self._execute_entity_search(
                            strategy.query or plan.original_query,
                            strategy.limit,
                            trace_id,
                        )
                    )
                case SearchTechnique.STRUCTURAL:
                    task = asyncio.create_task(
                        self._execute_structural_search(
                            strategy.cypher_pattern,
                            strategy.params,
                            strategy.consider_strength,
                            strategy.limit,
                            trace_id,
                        )
                    )
                case SearchTechnique.TEMPORAL:
                    task = asyncio.create_task(
                        self._execute_temporal_search(
                            strategy.query or plan.original_query,
                            strategy.time_range,
                            strategy.limit,
                            trace_id,
                        )
                    )

            tasks.append(task)

        # Execute all in parallel with timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.execution_timeout,
            )
        except TimeoutError:
            logger.warning(
                "[SWELL] Search execution timeout",
                extra={"trace_id": trace_id},
            )
            # Cancel remaining tasks
            for task in tasks:
                task.cancel()
            results = [[] for _ in tasks]

        # Map results by label
        results_by_technique: dict[str, list[RawSearchResult]] = {}
        for label, result in zip(labels, results, strict=False):
            if isinstance(result, Exception):
                logger.warning(
                    f"[SWELL] Strategy {label} failed: {result}",
                    extra={"trace_id": trace_id},
                )
                results_by_technique[label] = []
            else:
                typed_result: list[RawSearchResult] = result  # type: ignore[assignment]
                results_by_technique[label] = typed_result
                logger.debug(
                    f"[WHISPER] Strategy {label} returned {len(typed_result)} results",
                    extra={"trace_id": trace_id},
                )

        return results_by_technique

    # =========================================================================
    # Individual Search Implementations
    # =========================================================================

    async def _execute_vector_search(
        self,
        query: str,
        limit: int,
        trace_id: str,
    ) -> list[RawSearchResult]:
        """Execute semantic search via Graphiti."""
        if not self.graphiti:
            logger.debug(
                "[WHISPER] Graphiti not available for vector search",
                extra={"trace_id": trace_id},
            )
            return []

        try:
            results = await self.graphiti.search(query, limit=limit)
            return [
                RawSearchResult(
                    content=r.fact if hasattr(r, "fact") else str(r),
                    source_technique=SearchTechnique.VECTOR,
                    source_id=str(r.uuid) if hasattr(r, "uuid") else None,
                    vector_score=r.score if hasattr(r, "score") else None,
                )
                for r in results
            ]
        except Exception as e:
            logger.warning(
                f"[SWELL] Vector search failed: {e}",
                extra={"trace_id": trace_id},
            )
            return []

    async def _execute_entity_search(
        self,
        query: str,
        limit: int,
        trace_id: str,
    ) -> list[RawSearchResult]:
        """Execute entity fulltext search via Graphiti."""
        if not self.graphiti:
            logger.debug(
                "[WHISPER] Graphiti not available for entity search",
                extra={"trace_id": trace_id},
            )
            return []

        try:
            results = await self.graphiti.search_entities(query, limit=limit, trace_id=trace_id)
            return [
                RawSearchResult(
                    content=(
                        f"{r.name}: {r.content}"
                        if hasattr(r, "content") and r.content
                        else str(r.name or "Unknown")
                    ),
                    source_technique=SearchTechnique.ENTITY_FULLTEXT,
                    source_id=r.uuid if hasattr(r, "uuid") else None,
                    vector_score=r.score if hasattr(r, "score") else None,
                )
                for r in results
            ]
        except Exception as e:
            logger.warning(
                f"[SWELL] Entity search failed: {e}",
                extra={"trace_id": trace_id},
            )
            return []

    async def _execute_structural_search(
        self,
        cypher_pattern: str | None,
        params: dict[str, Any],
        consider_strength: bool,
        limit: int,
        trace_id: str,
    ) -> list[RawSearchResult]:
        """
        Execute structural search via Cypher.

        Supports both predefined patterns and custom Cypher queries.
        """
        if not self.neo4j:
            logger.debug(
                "[WHISPER] Neo4j not available for structural search",
                extra={"trace_id": trace_id},
            )
            return []

        if not cypher_pattern:
            return []

        try:
            # Check if this is a raw Cypher query (starts with MATCH)
            if cypher_pattern.strip().upper().startswith("MATCH"):
                # LLM-generated custom Cypher - use directly
                cypher = cypher_pattern
                query_params = {**params, "limit": limit}
            elif cypher_pattern.upper() in STRUCTURAL_QUERIES:
                # Predefined pattern
                cypher = STRUCTURAL_QUERIES[cypher_pattern.upper()]
                query_params = {**params, "limit": limit}
            else:
                logger.warning(
                    f"[SWELL] Unknown cypher pattern: {cypher_pattern}",
                    extra={"trace_id": trace_id},
                )
                return []

            records = await self.neo4j.execute_query(cypher, query_params, trace_id=trace_id)

            results = []
            for record in records:
                # Extract strength if present
                strengths = []
                if consider_strength:
                    for key in ["strength", "weight", "closeness"]:
                        if key in record and record[key] is not None:
                            strengths.append(float(record[key]))

                # Format record content
                content = self._format_record(record)

                # Extract temporal context if present
                temporal = None
                if "created_at" in record:
                    temporal = TemporalContext(
                        created_at=record.get("created_at", 0),
                        expired_at=record.get("expired_at"),
                        is_current=record.get("expired_at") is None,
                    )

                results.append(
                    RawSearchResult(
                        content=content,
                        source_technique=SearchTechnique.STRUCTURAL,
                        source_id=record.get("uuid") or record.get("person_uuid"),
                        relationship_strengths=strengths,
                        temporal_context=temporal,
                    )
                )

            return results

        except Exception as e:
            logger.warning(
                f"[SWELL] Structural search failed: {e}",
                extra={"trace_id": trace_id},
            )
            return []

    async def _execute_temporal_search(
        self,
        query: str,
        time_range: TimeRange | None,
        limit: int,
        trace_id: str,
    ) -> list[RawSearchResult]:
        """Execute time-filtered search."""
        if not self.neo4j:
            logger.debug(
                "[WHISPER] Neo4j not available for temporal search",
                extra={"trace_id": trace_id},
            )
            return []

        # Parse time range if not provided
        if not time_range:
            time_range = self._parse_time_reference(query)

        if not time_range or (time_range.start is None and time_range.end is None):
            return []

        try:
            cypher = """
            MATCH (n)
            WHERE n.created_at >= $start AND n.created_at <= $end
            RETURN n, labels(n) as labels
            ORDER BY n.created_at DESC
            LIMIT $limit
            """

            params = {
                "start": time_range.start or 0,
                "end": time_range.end or datetime.now(UTC).timestamp(),
                "limit": limit,
            }

            records = await self.neo4j.execute_query(cypher, params, trace_id=trace_id)

            return [
                RawSearchResult(
                    content=self._format_node(record),
                    source_technique=SearchTechnique.TEMPORAL,
                    source_id=record.get("n", {}).get("uuid"),
                    temporal_context=TemporalContext(
                        created_at=record.get("n", {}).get("created_at", 0),
                        is_current=True,
                        human_readable=time_range.relative,
                    ),
                )
                for record in records
            ]

        except Exception as e:
            logger.warning(
                f"[SWELL] Temporal search failed: {e}",
                extra={"trace_id": trace_id},
            )
            return []

    # =========================================================================
    # Result Aggregation and Scoring
    # =========================================================================

    def _aggregate_results(
        self,
        results_by_technique: dict[str, list[RawSearchResult]],
        max_results: int,
    ) -> list[RawSearchResult]:
        """
        Aggregate results from all techniques with deduplication and scoring.

        Args:
            results_by_technique: Results grouped by technique.
            max_results: Maximum results to return.

        Returns:
            Deduplicated, scored, and sorted results.
        """
        all_results: list[RawSearchResult] = []
        seen_ids: set[str] = set()
        seen_content: set[str] = set()

        for technique_results in results_by_technique.values():
            for result in technique_results:
                # Deduplicate by source_id
                if result.source_id and result.source_id in seen_ids:
                    continue
                if result.source_id:
                    seen_ids.add(result.source_id)

                # Also deduplicate by content (for results without IDs)
                content_key = result.content[:100].lower()
                if content_key in seen_content:
                    continue
                seen_content.add(content_key)

                all_results.append(result)

        # Sort by composite score (strength-aware)
        all_results.sort(key=self._calculate_result_score, reverse=True)

        return all_results[:max_results]

    def _calculate_result_score(self, result: RawSearchResult) -> float:
        """
        Calculate composite score with relationship strength boost.

        Formula: final_score = base_score * (1 + avg_strength * strength_boost_factor)
        """
        base_score: float = result.vector_score if result.vector_score is not None else 0.5

        if result.relationship_strengths:
            avg_strength = sum(result.relationship_strengths) / len(result.relationship_strengths)
            boost = 1 + (avg_strength * self.strength_boost_factor)
        else:
            boost = 1.0

        return float(base_score * boost)

    # =========================================================================
    # Report Synthesis (Opus)
    # =========================================================================

    async def _synthesize_report(
        self,
        query: str,
        results: list[RawSearchResult],
        plan: SearchPlan,
        trace_id: str,
    ) -> GraphIntelligenceReport:
        """
        Use Opus to synthesize results into a Graph Intelligence Report.

        Args:
            query: Original user query.
            results: Aggregated search results.
            plan: The search plan that was executed.
            trace_id: Request trace ID.

        Returns:
            GraphIntelligenceReport with synthesized answer.
        """
        if not results:
            return GraphIntelligenceReport(
                query=query,
                direct_answer="I don't have any information about that in The Locker.",
                confidence=0.0,
                confidence_level=ConfidenceLevel.UNCERTAIN,
                as_of_date=datetime.now(UTC).strftime("%Y-%m-%d"),
                search_techniques_used=[s.technique for s in plan.strategies],
                result_count=0,
                gaps_identified=["No matching information found"],
            )

        # Format results for the prompt
        formatted_results = self._format_results_for_synthesis(results)
        techniques_used = list({r.source_technique.value for r in results})

        prompt = SYNTHESIS_PROMPT.format(
            query=query,
            plan_reasoning=plan.reasoning,
            techniques=", ".join(techniques_used),
            formatted_results=formatted_results,
            current_date=datetime.now(UTC).strftime("%Y-%m-%d"),
        )

        try:
            response = await asyncio.wait_for(
                self._call_opus(prompt, self.synthesis_model, trace_id),
                timeout=self.synthesis_timeout,
            )

            json_str = self._extract_json(response)
            report = GraphIntelligenceReport.model_validate_json(json_str)

            # Ensure search metadata is accurate
            report.search_techniques_used = [SearchTechnique(t) for t in techniques_used]
            report.result_count = len(results)

            return report

        except TimeoutError:
            logger.warning(
                "[SWELL] Synthesis timeout, using fallback",
                extra={"trace_id": trace_id},
            )
            return self._fallback_report(query, results, plan)

        except (ValidationError, json.JSONDecodeError) as e:
            logger.warning(
                f"[SWELL] Report parsing failed: {e}, using fallback",
                extra={"trace_id": trace_id},
            )
            return self._fallback_report(query, results, plan)

    def _fallback_report(
        self,
        query: str,
        results: list[RawSearchResult],
        plan: SearchPlan,
    ) -> GraphIntelligenceReport:
        """Generate fallback report when synthesis fails."""
        # Calculate confidence from results
        confidence, level = self._calculate_confidence(results)

        # Extract key content
        direct_answer = "Here's what I found:\n" + "\n".join(
            f"- {r.content[:200]}" for r in results[:5]
        )

        return GraphIntelligenceReport(
            query=query,
            direct_answer=direct_answer,
            confidence=confidence,
            confidence_level=level,
            evidence=[
                EvidenceItem(
                    fact=r.content[:200],
                    relationship=r.source_technique.value,
                    source=r.source_id or "unknown",
                    confidence=r.vector_score or 0.5,
                )
                for r in results[:5]
            ],
            key_entities=[],
            as_of_date=datetime.now(UTC).strftime("%Y-%m-%d"),
            search_techniques_used=[s.technique for s in plan.strategies],
            result_count=len(results),
        )

    def _calculate_confidence(
        self,
        results: list[RawSearchResult],
    ) -> tuple[float, ConfidenceLevel]:
        """Calculate confidence score from results."""
        if not results:
            return 0.0, ConfidenceLevel.UNCERTAIN

        # Factor 1: Number of sources (diminishing returns)
        source_factor = min(len(results) / 5, 1.0)

        # Factor 2: Average vector score
        scores = [r.vector_score for r in results if r.vector_score]
        avg_score = sum(scores) / len(scores) if scores else 0.5

        # Factor 3: Technique diversity
        techniques = len({r.source_technique for r in results})
        diversity = min(techniques / 3, 1.0)

        # Factor 4: Strength signals
        strengths = [s for r in results for s in r.relationship_strengths]
        avg_strength = sum(strengths) / len(strengths) if strengths else 0.5

        # Weighted combination
        confidence = (
            source_factor * 0.25 + avg_score * 0.30 + diversity * 0.20 + avg_strength * 0.25
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

    # =========================================================================
    # Opus LLM Interface
    # =========================================================================

    async def _call_opus(
        self,
        prompt: str,
        model: str,
        trace_id: str,
    ) -> str:
        """
        Call Claude Opus for reasoning.

        Args:
            prompt: The prompt to send.
            model: Model ID to use.
            trace_id: Request trace ID.

        Returns:
            Model response text.
        """
        logger.debug(
            f"[WHISPER] Calling {model}",
            extra={"trace_id": trace_id, "prompt_len": len(prompt)},
        )

        response = await self.anthropic_client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )

        return str(response.content[0].text)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _extract_json(self, text: str) -> str:
        """Extract JSON from LLM response (handles markdown code blocks)."""
        # Try to find JSON in code blocks first
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if json_match:
            return json_match.group(1).strip()

        # Try to find raw JSON object
        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            return brace_match.group(0)

        # Return as-is and let JSON parser handle errors
        return text

    def _format_record(self, record: dict[str, Any]) -> str:
        """Format a Neo4j record for display."""
        parts = []
        for key, value in record.items():
            if value is not None and key not in ["uuid", "labels", "type"]:
                if isinstance(value, float):
                    parts.append(f"{key}: {value:.2f}")
                else:
                    parts.append(f"{key}: {value}")
        return ", ".join(parts) if parts else str(record)

    def _format_node(self, record: dict[str, Any]) -> str:
        """Format a node record for display."""
        node = record.get("n", {})
        labels = record.get("labels", [])
        label_str = ":".join(labels) if labels else "Node"

        if isinstance(node, dict):
            name = node.get("name") or node.get("action") or node.get("content", "")[:50]
            return f"[{label_str}] {name}"
        return f"[{label_str}] {node}"

    def _format_results_for_synthesis(self, results: list[RawSearchResult]) -> str:
        """Format results for the synthesis prompt."""
        lines = []
        for i, r in enumerate(results[:20], 1):
            line = f"{i}. [{r.source_technique.value}] {r.content}"
            if r.vector_score:
                line += f" (score: {r.vector_score:.2f})"
            if r.relationship_strengths:
                avg = sum(r.relationship_strengths) / len(r.relationship_strengths)
                line += f" (strength: {avg:.2f})"
            if r.temporal_context and r.temporal_context.human_readable:
                line += f" ({r.temporal_context.human_readable})"
            lines.append(line)
        return "\n".join(lines)

    def _parse_time_reference(self, query: str) -> TimeRange | None:
        """Parse time references from query into TimeRange."""
        query_lower = query.lower()
        now = datetime.now(UTC)

        if "yesterday" in query_lower:
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
            end = start.replace(hour=23, minute=59, second=59)
            relative = "yesterday"
        elif "last week" in query_lower:
            start = now - timedelta(days=7)
            end = now
            relative = "last week"
        elif "last month" in query_lower:
            start = now - timedelta(days=30)
            end = now
            relative = "last month"
        elif "last year" in query_lower:
            start = now - timedelta(days=365)
            end = now
            relative = "last year"
        else:
            # Try "X days/weeks/months ago"
            match = re.search(r"(\d+)\s*(day|week|month)s?\s*ago", query_lower)
            if match:
                count = int(match.group(1))
                unit = match.group(2)
                if unit == "day":
                    start = now - timedelta(days=count)
                elif unit == "week":
                    start = now - timedelta(weeks=count)
                else:
                    start = now - timedelta(days=count * 30)
                end = now
                relative = f"{count} {unit}s ago"
            else:
                return None

        return TimeRange(
            start=start.timestamp(),
            end=end.timestamp(),
            relative=relative,
        )

    # =========================================================================
    # Response Creation
    # =========================================================================

    def _create_response(
        self,
        original_msg: AgentMessage,
        report: GraphIntelligenceReport,
        raw_count: int,
        search_ms: float,
        synthesis_ms: float,
    ) -> AgentMessage:
        """Create response message with GraphIntelligenceReport."""
        return AgentMessage(
            trace_id=original_msg.trace_id,
            source_agent=self.name,
            target_agent=original_msg.source_agent,
            intent="search_response",
            payload={
                "report": report.model_dump(),
                "raw_result_count": raw_count,
                "search_latency_ms": search_ms,
                "synthesis_latency_ms": synthesis_ms,
            },
            timestamp=time.time(),
        )

    def _create_empty_response(
        self,
        original_msg: AgentMessage,
        reason: str,
    ) -> AgentMessage:
        """Create empty response for error cases."""
        report = GraphIntelligenceReport(
            query=original_msg.payload.get("query", ""),
            direct_answer=reason,
            confidence=0.0,
            confidence_level=ConfidenceLevel.UNCERTAIN,
            as_of_date=datetime.now(UTC).strftime("%Y-%m-%d"),
            result_count=0,
        )
        return self._create_response(original_msg, report, 0, 0.0, 0.0)


# ===========================================================================
# Exports
# ===========================================================================

__all__ = [
    "Researcher",
    # Re-export models for convenience
    "SearchTechnique",
    "ConfidenceLevel",
    "ZoomLevel",
    "GraphIntelligenceReport",
    "RawSearchResult",
    "SearchPlan",
]
