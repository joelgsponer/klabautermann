"""
Unit tests for the Intelligent Researcher agent.

Tests the Opus-powered search planning, parallel execution,
strength-aware scoring, and report synthesis.

Reference: specs/RESEARCHER.md
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.agents.researcher import STRUCTURAL_QUERIES, Researcher
from klabautermann.agents.researcher_models import (
    ConfidenceLevel,
    GraphIntelligenceReport,
    RawSearchResult,
    SearchPlan,
    SearchStrategy,
    SearchTechnique,
)
from klabautermann.core.models import AgentMessage


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_graphiti() -> MagicMock:
    """Create mock GraphitiClient."""
    graphiti = MagicMock()
    graphiti.search = AsyncMock(return_value=[])
    graphiti.search_entities = AsyncMock(return_value=[])
    return graphiti


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Create mock Neo4jClient."""
    neo4j = MagicMock()
    neo4j.execute_query = AsyncMock(return_value=[])
    return neo4j


@pytest.fixture
def researcher(mock_graphiti: MagicMock, mock_neo4j: MagicMock) -> Researcher:
    """Create Researcher with mocked dependencies."""
    config = {
        "model": {
            "planning": "claude-opus-4-5-20251101",
            "synthesis": "claude-opus-4-5-20251101",
            "temperature": 0.3,
        },
        "search": {
            "max_parallel_strategies": 4,
            "default_result_limit": 10,
        },
        "scoring": {
            "strength_boost_factor": 0.3,
        },
    }
    return Researcher(
        config=config,
        graphiti=mock_graphiti,
        neo4j=mock_neo4j,
    )


@pytest.fixture
def sample_search_plan() -> SearchPlan:
    """Sample search plan for testing."""
    return SearchPlan(
        original_query="Who does Sarah work for?",
        reasoning="Employment query requires structural and entity search",
        strategies=[
            SearchStrategy(
                technique=SearchTechnique.ENTITY_FULLTEXT,
                query="Sarah",
                limit=5,
                rationale="Find Sarah's entity",
            ),
            SearchStrategy(
                technique=SearchTechnique.STRUCTURAL,
                cypher_pattern="WORKS_AT",
                params={"name_pattern": "(?i).*sarah.*"},
                limit=10,
                rationale="Find employment relationships",
            ),
        ],
        expected_result_type="employer",
        zoom_level="micro",
    )


@pytest.fixture
def sample_results() -> list[RawSearchResult]:
    """Sample search results for testing."""
    return [
        RawSearchResult(
            content="Sarah Chen works at TechCorp as Senior Engineer",
            source_technique=SearchTechnique.STRUCTURAL,
            source_id="rel-123",
            relationship_strengths=[0.9],
        ),
        RawSearchResult(
            content="Sarah Chen: Software engineer with 10 years experience",
            source_technique=SearchTechnique.ENTITY_FULLTEXT,
            source_id="person-456",
            vector_score=0.85,
        ),
        RawSearchResult(
            content="TechCorp hired Sarah in 2023",
            source_technique=SearchTechnique.VECTOR,
            source_id="fact-789",
            vector_score=0.72,
        ),
    ]


# ===========================================================================
# Test Pydantic Models
# ===========================================================================


class TestModels:
    """Tests for Pydantic model validation."""

    def test_search_technique_enum(self) -> None:
        """SearchTechnique enum values."""
        assert SearchTechnique.VECTOR.value == "vector"
        assert SearchTechnique.STRUCTURAL.value == "structural"
        assert SearchTechnique.TEMPORAL.value == "temporal"
        assert SearchTechnique.ENTITY_FULLTEXT.value == "entity_fulltext"

    def test_confidence_level_enum(self) -> None:
        """ConfidenceLevel enum values."""
        assert ConfidenceLevel.HIGH.value == "high"
        assert ConfidenceLevel.MEDIUM.value == "medium"
        assert ConfidenceLevel.LOW.value == "low"
        assert ConfidenceLevel.UNCERTAIN.value == "uncertain"

    def test_search_strategy_defaults(self) -> None:
        """SearchStrategy has sensible defaults."""
        strategy = SearchStrategy(
            technique=SearchTechnique.VECTOR,
            rationale="Test search",
        )
        assert strategy.limit == 10
        assert strategy.consider_strength is False
        assert strategy.params == {}

    def test_search_plan_validation(self) -> None:
        """SearchPlan validates zoom_level pattern."""
        plan = SearchPlan(
            original_query="test",
            strategies=[],
            expected_result_type="info",
            zoom_level="micro",
        )
        assert plan.zoom_level == "micro"

    def test_raw_search_result_with_strength(self) -> None:
        """RawSearchResult can include relationship strengths."""
        result = RawSearchResult(
            content="Test content",
            source_technique=SearchTechnique.STRUCTURAL,
            relationship_strengths=[0.8, 0.9],
        )
        assert len(result.relationship_strengths) == 2
        assert result.vector_score is None

    def test_graph_intelligence_report_structure(self) -> None:
        """GraphIntelligenceReport has all required fields."""
        report = GraphIntelligenceReport(
            query="Who is John?",
            direct_answer="John is a software engineer.",
            confidence=0.85,
            confidence_level=ConfidenceLevel.HIGH,
            as_of_date="2026-01-16",
            result_count=5,
        )
        assert report.evidence == []
        assert report.relationships == []
        assert report.key_entities == []


# ===========================================================================
# Test Scoring Algorithm
# ===========================================================================


class TestScoring:
    """Tests for strength-aware scoring."""

    def test_score_without_strength(self, researcher: Researcher) -> None:
        """Score without strength uses vector_score only."""
        result = RawSearchResult(
            content="Test",
            source_technique=SearchTechnique.VECTOR,
            vector_score=0.8,
        )
        score = researcher._calculate_result_score(result)
        assert score == 0.8  # No boost

    def test_score_with_strength_boost(self, researcher: Researcher) -> None:
        """Score with strength gets boosted."""
        result = RawSearchResult(
            content="Test",
            source_technique=SearchTechnique.STRUCTURAL,
            vector_score=0.8,
            relationship_strengths=[1.0],  # Maximum strength
        )
        # Formula: 0.8 * (1 + 1.0 * 0.3) = 0.8 * 1.3 = 1.04
        score = researcher._calculate_result_score(result)
        assert score == pytest.approx(1.04)

    def test_score_with_multiple_strengths(self, researcher: Researcher) -> None:
        """Score averages multiple relationship strengths."""
        result = RawSearchResult(
            content="Test",
            source_technique=SearchTechnique.STRUCTURAL,
            vector_score=0.8,
            relationship_strengths=[0.6, 1.0],  # Average = 0.8
        )
        # Formula: 0.8 * (1 + 0.8 * 0.3) = 0.8 * 1.24 = 0.992
        score = researcher._calculate_result_score(result)
        assert score == pytest.approx(0.992)

    def test_score_without_vector_score(self, researcher: Researcher) -> None:
        """Score defaults to 0.5 when no vector_score."""
        result = RawSearchResult(
            content="Test",
            source_technique=SearchTechnique.STRUCTURAL,
        )
        score = researcher._calculate_result_score(result)
        assert score == 0.5  # Default base score


# ===========================================================================
# Test Result Aggregation
# ===========================================================================


class TestAggregation:
    """Tests for result aggregation and deduplication."""

    def test_deduplication_by_source_id(self, researcher: Researcher) -> None:
        """Results with same source_id are deduplicated."""
        results = {
            "vector:0": [
                RawSearchResult(
                    content="Duplicate",
                    source_technique=SearchTechnique.VECTOR,
                    source_id="same-id",
                    vector_score=0.9,
                ),
            ],
            "entity:1": [
                RawSearchResult(
                    content="Duplicate again",
                    source_technique=SearchTechnique.ENTITY_FULLTEXT,
                    source_id="same-id",
                    vector_score=0.8,
                ),
            ],
        }
        aggregated = researcher._aggregate_results(results, max_results=10)
        assert len(aggregated) == 1

    def test_aggregation_sorts_by_score(self, researcher: Researcher) -> None:
        """Results are sorted by composite score descending."""
        results = {
            "vector:0": [
                RawSearchResult(
                    content="Low score",
                    source_technique=SearchTechnique.VECTOR,
                    source_id="id-1",
                    vector_score=0.3,
                ),
                RawSearchResult(
                    content="High score",
                    source_technique=SearchTechnique.VECTOR,
                    source_id="id-2",
                    vector_score=0.9,
                ),
            ],
        }
        aggregated = researcher._aggregate_results(results, max_results=10)
        assert aggregated[0].vector_score == 0.9
        assert aggregated[1].vector_score == 0.3

    def test_aggregation_respects_max_results(self, researcher: Researcher) -> None:
        """Aggregation limits results to max_results."""
        results = {
            "vector:0": [
                RawSearchResult(
                    content=f"Result {i}",
                    source_technique=SearchTechnique.VECTOR,
                    source_id=f"id-{i}",
                    vector_score=0.5,
                )
                for i in range(20)
            ],
        }
        aggregated = researcher._aggregate_results(results, max_results=5)
        assert len(aggregated) == 5


# ===========================================================================
# Test JSON Extraction
# ===========================================================================


class TestJsonExtraction:
    """Tests for extracting JSON from LLM responses."""

    def test_extract_from_code_block(self, researcher: Researcher) -> None:
        """Extract JSON from markdown code block."""
        text = '```json\n{"key": "value"}\n```'
        result = researcher._extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_from_code_block_no_lang(self, researcher: Researcher) -> None:
        """Extract JSON from code block without language."""
        text = '```\n{"key": "value"}\n```'
        result = researcher._extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_raw_json(self, researcher: Researcher) -> None:
        """Extract raw JSON object from text."""
        text = 'Here is the result: {"key": "value"} and more text'
        result = researcher._extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_returns_text_if_no_json(self, researcher: Researcher) -> None:
        """Return original text if no JSON found."""
        text = "No JSON here"
        result = researcher._extract_json(text)
        assert result == text


# ===========================================================================
# Test Confidence Calculation
# ===========================================================================


class TestConfidenceCalculation:
    """Tests for confidence score calculation."""

    def test_empty_results_uncertain(self, researcher: Researcher) -> None:
        """Empty results give uncertain confidence."""
        confidence, level = researcher._calculate_confidence([])
        assert confidence == 0.0
        assert level == ConfidenceLevel.UNCERTAIN

    def test_high_confidence_multiple_sources(self, researcher: Researcher) -> None:
        """Multiple high-quality sources give high confidence."""
        results = [
            RawSearchResult(
                content=f"Result {i}",
                source_technique=SearchTechnique.VECTOR
                if i % 2 == 0
                else SearchTechnique.STRUCTURAL,
                vector_score=0.9,
                relationship_strengths=[0.9] if i % 2 == 1 else [],
            )
            for i in range(5)
        ]
        confidence, level = researcher._calculate_confidence(results)
        assert confidence >= 0.5  # Should be at least medium
        assert level in [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM]


# ===========================================================================
# Test Time Reference Parsing
# ===========================================================================


class TestTimeReferenceParsing:
    """Tests for parsing time references."""

    def test_parse_yesterday(self, researcher: Researcher) -> None:
        """Parse 'yesterday' time reference."""
        result = researcher._parse_time_reference("What happened yesterday?")
        assert result is not None
        assert result.relative == "yesterday"
        assert result.start is not None
        assert result.end is not None

    def test_parse_last_week(self, researcher: Researcher) -> None:
        """Parse 'last week' time reference."""
        result = researcher._parse_time_reference("Events from last week")
        assert result is not None
        assert result.relative == "last week"

    def test_parse_days_ago(self, researcher: Researcher) -> None:
        """Parse 'X days ago' time reference."""
        result = researcher._parse_time_reference("What happened 5 days ago?")
        assert result is not None
        assert result.relative == "5 days ago"

    def test_parse_no_time_reference(self, researcher: Researcher) -> None:
        """Return None for queries without time reference."""
        result = researcher._parse_time_reference("Who is John?")
        assert result is None


# ===========================================================================
# Test Structural Queries
# ===========================================================================


class TestStructuralQueries:
    """Tests for predefined Cypher patterns."""

    def test_works_at_pattern_exists(self) -> None:
        """WORKS_AT pattern is defined."""
        assert "WORKS_AT" in STRUCTURAL_QUERIES
        assert "MATCH" in STRUCTURAL_QUERIES["WORKS_AT"]
        assert "$name_pattern" in STRUCTURAL_QUERIES["WORKS_AT"]

    def test_knows_pattern_includes_strength(self) -> None:
        """KNOWS pattern returns strength."""
        assert "KNOWS" in STRUCTURAL_QUERIES
        assert "strength" in STRUCTURAL_QUERIES["KNOWS"]
        assert "ORDER BY r.strength" in STRUCTURAL_QUERIES["KNOWS"]

    def test_historical_pattern_uses_as_of(self) -> None:
        """WORKS_AT_HISTORICAL uses as_of parameter."""
        assert "WORKS_AT_HISTORICAL" in STRUCTURAL_QUERIES
        assert "$as_of" in STRUCTURAL_QUERIES["WORKS_AT_HISTORICAL"]


# ===========================================================================
# Test Process Message Flow
# ===========================================================================


class TestProcessMessage:
    """Tests for the main process_message flow."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_report(self, researcher: Researcher) -> None:
        """Empty query returns empty report."""
        msg = AgentMessage(
            trace_id="test-123",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={"query": ""},
            timestamp=time.time(),
        )

        response = await researcher.process_message(msg)

        assert response is not None
        assert response.payload["report"]["confidence"] == 0.0
        assert "No query provided" in response.payload["report"]["direct_answer"]

    @pytest.mark.asyncio
    async def test_process_message_with_mocked_opus(
        self,
        researcher: Researcher,
        sample_search_plan: SearchPlan,
    ) -> None:
        """Process message with mocked Opus calls."""
        # Mock the Opus client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=sample_search_plan.model_dump_json())]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        researcher._anthropic = mock_client

        msg = AgentMessage(
            trace_id="test-456",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={"query": "Who does Sarah work for?"},
            timestamp=time.time(),
        )

        response = await researcher.process_message(msg)

        assert response is not None
        assert response.intent == "search_response"
        assert "report" in response.payload

    @pytest.mark.asyncio
    async def test_fallback_on_opus_timeout(self, researcher: Researcher) -> None:
        """Falls back to simple plan on Opus timeout."""
        # Configure very short timeout
        researcher.planning_timeout = 0.001

        # Make the call hang
        async def slow_call(*args, **kwargs):
            import asyncio

            await asyncio.sleep(10)

        mock_client = MagicMock()
        mock_client.messages.create = slow_call
        researcher._anthropic = mock_client

        msg = AgentMessage(
            trace_id="test-timeout",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={"query": "Test query"},
            timestamp=time.time(),
        )

        response = await researcher.process_message(msg)

        # Should still return a response (using fallback)
        assert response is not None


# ===========================================================================
# Test Custom Cypher Support
# ===========================================================================


class TestCustomCypher:
    """Tests for custom Cypher query support."""

    @pytest.mark.asyncio
    async def test_custom_cypher_detection(
        self, researcher: Researcher, mock_neo4j: MagicMock
    ) -> None:
        """Custom Cypher queries starting with MATCH are executed directly."""
        custom_cypher = "MATCH (p:Person)-[:KNOWS]->(f) WHERE p.name = $name RETURN f"
        params = {"name": "John"}

        mock_neo4j.execute_query = AsyncMock(return_value=[{"f": {"name": "Jane"}}])

        _results = await researcher._execute_structural_search(
            cypher_pattern=custom_cypher,
            params=params,
            consider_strength=False,
            limit=10,
            trace_id="test",
        )

        # Verify the custom query was used (results not needed for this test)
        mock_neo4j.execute_query.assert_called_once()
        call_args = mock_neo4j.execute_query.call_args
        assert "MATCH (p:Person)" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_predefined_pattern_lookup(
        self, researcher: Researcher, mock_neo4j: MagicMock
    ) -> None:
        """Predefined patterns like 'WORKS_AT' are looked up."""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        await researcher._execute_structural_search(
            cypher_pattern="WORKS_AT",
            params={"name_pattern": "(?i).*john.*"},
            consider_strength=False,
            limit=10,
            trace_id="test",
        )

        # Verify the predefined pattern was used
        mock_neo4j.execute_query.assert_called_once()
        call_args = mock_neo4j.execute_query.call_args
        assert "WORKS_AT" in call_args[0][0]


# ===========================================================================
# Test Report Formatting
# ===========================================================================


class TestReportFormatting:
    """Tests for result and report formatting."""

    def test_format_record(self, researcher: Researcher) -> None:
        """Format Neo4j record for display."""
        record = {
            "person": "John",
            "organization": "TechCorp",
            "title": "Engineer",
            "uuid": "should-be-hidden",
        }
        formatted = researcher._format_record(record)
        assert "John" in formatted
        assert "TechCorp" in formatted
        assert "uuid" not in formatted

    def test_format_results_for_synthesis(
        self,
        researcher: Researcher,
        sample_results: list[RawSearchResult],
    ) -> None:
        """Format results for synthesis prompt."""
        formatted = researcher._format_results_for_synthesis(sample_results)
        assert "[structural]" in formatted
        assert "[entity_fulltext]" in formatted
        assert "[vector]" in formatted
        assert "Sarah" in formatted


# ===========================================================================
# Test Fallback Report
# ===========================================================================


class TestFallbackReport:
    """Tests for fallback report generation."""

    def test_fallback_report_structure(
        self,
        researcher: Researcher,
        sample_results: list[RawSearchResult],
        sample_search_plan: SearchPlan,
    ) -> None:
        """Fallback report has correct structure."""
        report = researcher._fallback_report(
            query="Test query",
            results=sample_results,
            plan=sample_search_plan,
        )

        assert report.query == "Test query"
        assert "what i found" in report.direct_answer.lower()
        assert len(report.evidence) <= 5
        assert report.result_count == len(sample_results)
