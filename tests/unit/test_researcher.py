"""
Unit tests for the Researcher agent (T024).

Tests query classification, search strategies, and result formatting.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.agents.researcher import (
    Researcher,
    SearchResponse,
    SearchResult,
    SearchType,
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
    return Researcher(
        graphiti=mock_graphiti,
        neo4j=mock_neo4j,
    )


# ===========================================================================
# Test Query Classification
# ===========================================================================


class TestQueryClassification:
    """Tests for _classify_search_type method."""

    def test_semantic_query_basic_question(self, researcher: Researcher) -> None:
        """Basic question without structural patterns → SEMANTIC."""
        query = "Tell me about the project"
        search_type = researcher._classify_search_type(query)
        assert search_type == SearchType.SEMANTIC

    def test_semantic_query_general_recall(self, researcher: Researcher) -> None:
        """General recall query → SEMANTIC."""
        query = "What was that thing about battery density?"
        search_type = researcher._classify_search_type(query)
        assert search_type == SearchType.SEMANTIC

    def test_structural_query_works_at(self, researcher: Researcher) -> None:
        """Query about employment → STRUCTURAL."""
        query = "Who does Sarah work for?"
        search_type = researcher._classify_search_type(query)
        assert search_type == SearchType.STRUCTURAL

    def test_structural_query_reports_to(self, researcher: Researcher) -> None:
        """Query about reporting relationship → STRUCTURAL."""
        query = "Who did John report to?"
        search_type = researcher._classify_search_type(query)
        assert search_type == SearchType.STRUCTURAL

    def test_structural_query_blocks(self, researcher: Researcher) -> None:
        """Query about blocked tasks → STRUCTURAL."""
        query = "What tasks are blocked?"
        search_type = researcher._classify_search_type(query)
        assert search_type == SearchType.STRUCTURAL

    def test_temporal_query_last_week(self, researcher: Researcher) -> None:
        """Query with 'last week' → TEMPORAL."""
        query = "What did I do last week?"
        search_type = researcher._classify_search_type(query)
        assert search_type == SearchType.TEMPORAL

    def test_temporal_query_yesterday(self, researcher: Researcher) -> None:
        """Query with 'yesterday' → TEMPORAL."""
        query = "What happened yesterday?"
        search_type = researcher._classify_search_type(query)
        assert search_type == SearchType.TEMPORAL

    def test_temporal_query_year(self, researcher: Researcher) -> None:
        """Query with year → TEMPORAL."""
        query = "What did I work on in 2024?"
        search_type = researcher._classify_search_type(query)
        assert search_type == SearchType.TEMPORAL

    def test_hybrid_query_structural_and_temporal(self, researcher: Researcher) -> None:
        """Query with both structural and temporal → HYBRID."""
        query = "Who did Sarah work for last week?"
        search_type = researcher._classify_search_type(query)
        assert search_type == SearchType.HYBRID


# ===========================================================================
# Test Entity Extraction
# ===========================================================================


class TestEntityExtraction:
    """Tests for _extract_entity_name method."""

    def test_extract_name_who_is(self, researcher: Researcher) -> None:
        """Extract name from 'who is <name>' pattern."""
        query = "Who is Sarah?"
        name = researcher._extract_entity_name(query)
        assert name == "Sarah"

    def test_extract_name_who_does(self, researcher: Researcher) -> None:
        """Extract name from 'who does <name>' pattern."""
        query = "Who does Sarah work for?"
        name = researcher._extract_entity_name(query)
        assert name == "Sarah"

    def test_extract_name_works_at(self, researcher: Researcher) -> None:
        """Extract name from '<name> works at' pattern."""
        query = "Sarah works at Acme"
        name = researcher._extract_entity_name(query)
        assert name == "Sarah"

    def test_extract_name_case_insensitive(self, researcher: Researcher) -> None:
        """Extract name is case insensitive."""
        query = "WHO IS sarah?"
        name = researcher._extract_entity_name(query)
        assert name == "Sarah"

    def test_extract_name_returns_none_when_no_match(self, researcher: Researcher) -> None:
        """Returns None when no entity pattern matches."""
        query = "Tell me about the project"
        name = researcher._extract_entity_name(query)
        assert name is None


# ===========================================================================
# Test Time Reference Parsing
# ===========================================================================


class TestTimeReferenceParsing:
    """Tests for _parse_time_reference method."""

    def test_parse_yesterday(self, researcher: Researcher) -> None:
        """Parse 'yesterday' into timestamp range."""
        query = "What happened yesterday?"
        time_filter = researcher._parse_time_reference(query)

        assert time_filter is not None
        assert "start" in time_filter
        assert "end" in time_filter
        assert time_filter["start"] < time_filter["end"]

    def test_parse_last_week(self, researcher: Researcher) -> None:
        """Parse 'last week' into timestamp range."""
        query = "What did I do last week?"
        time_filter = researcher._parse_time_reference(query)

        assert time_filter is not None
        assert "start" in time_filter
        assert "end" in time_filter

    def test_parse_last_month(self, researcher: Researcher) -> None:
        """Parse 'last month' into timestamp range."""
        query = "What projects from last month?"
        time_filter = researcher._parse_time_reference(query)

        assert time_filter is not None
        assert "start" in time_filter
        assert "end" in time_filter

    def test_parse_days_ago(self, researcher: Researcher) -> None:
        """Parse '5 days ago' pattern."""
        query = "What was discussed 5 days ago?"
        time_filter = researcher._parse_time_reference(query)

        assert time_filter is not None
        assert "start" in time_filter
        assert "end" in time_filter

    def test_parse_returns_none_for_no_temporal_reference(
        self, researcher: Researcher
    ) -> None:
        """Returns None when no temporal pattern found."""
        query = "Who is Sarah?"
        time_filter = researcher._parse_time_reference(query)

        assert time_filter is None


# ===========================================================================
# Test Semantic Search
# ===========================================================================


class TestSemanticSearch:
    """Tests for _semantic_search method."""

    @pytest.mark.asyncio
    async def test_semantic_search_with_results(
        self, researcher: Researcher, mock_graphiti: MagicMock
    ) -> None:
        """Semantic search returns results from Graphiti."""
        # Mock Graphiti results
        mock_results = [
            MagicMock(
                fact="Sarah is a PM at Acme",
                uuid="uuid-1",
                score=0.9,
            ),
            MagicMock(
                fact="John works with Sarah",
                uuid="uuid-2",
                score=0.8,
            ),
        ]
        mock_graphiti.search.return_value = mock_results

        response = await researcher._semantic_search("Who is Sarah?", "trace-123")

        assert response.search_type == SearchType.SEMANTIC
        assert len(response.results) == 2
        assert response.results[0].content == "Sarah is a PM at Acme"
        assert response.results[0].confidence == 0.9
        assert response.results[0].source == "graphiti"

    @pytest.mark.asyncio
    async def test_semantic_search_empty_results(
        self, researcher: Researcher, mock_graphiti: MagicMock
    ) -> None:
        """Semantic search returns empty when nothing found."""
        mock_graphiti.search.return_value = []

        response = await researcher._semantic_search("Unknown entity", "trace-123")

        assert response.search_type == SearchType.SEMANTIC
        assert len(response.results) == 0

    @pytest.mark.asyncio
    async def test_semantic_search_without_graphiti(self) -> None:
        """Semantic search returns empty when Graphiti unavailable."""
        researcher = Researcher(graphiti=None, neo4j=None)

        response = await researcher._semantic_search("Query", "trace-123")

        assert response.search_type == SearchType.SEMANTIC
        assert len(response.results) == 0


# ===========================================================================
# Test Structural Search
# ===========================================================================


class TestStructuralSearch:
    """Tests for _structural_search method."""

    @pytest.mark.asyncio
    async def test_structural_search_works_at(
        self, researcher: Researcher, mock_neo4j: MagicMock
    ) -> None:
        """Structural search for WORKS_AT relationship."""
        # Mock Neo4j results
        mock_neo4j.execute_query.return_value = [
            {"person": "Sarah", "org": "Acme Corp", "title": "PM"}
        ]

        response = await researcher._structural_search(
            "Who does Sarah work for?", "trace-123"
        )

        assert response.search_type == SearchType.STRUCTURAL
        assert len(response.results) == 1
        assert "Sarah" in response.results[0].content
        assert "Acme Corp" in response.results[0].content

    @pytest.mark.asyncio
    async def test_structural_search_reports_to(
        self, researcher: Researcher, mock_neo4j: MagicMock
    ) -> None:
        """Structural search for REPORTS_TO relationship."""
        mock_neo4j.execute_query.return_value = [
            {"person": "John", "manager": "Sarah"}
        ]

        response = await researcher._structural_search(
            "Who does John report to?", "trace-123"
        )

        assert response.search_type == SearchType.STRUCTURAL
        assert len(response.results) == 1

    @pytest.mark.asyncio
    async def test_structural_search_empty_results(
        self, researcher: Researcher, mock_neo4j: MagicMock
    ) -> None:
        """Structural search returns empty when nothing found."""
        mock_neo4j.execute_query.return_value = []

        response = await researcher._structural_search(
            "Who does Unknown work for?", "trace-123"
        )

        assert len(response.results) == 0

    @pytest.mark.asyncio
    async def test_structural_search_fallback_to_semantic(
        self, researcher: Researcher, mock_graphiti: MagicMock
    ) -> None:
        """Structural search falls back to semantic when no entity found."""
        mock_graphiti.search.return_value = []

        # Query without clear entity
        response = await researcher._structural_search(
            "Tell me about the project", "trace-123"
        )

        # Should have fallen back to semantic search
        mock_graphiti.search.assert_called_once()


# ===========================================================================
# Test Temporal Search
# ===========================================================================


class TestTemporalSearch:
    """Tests for _temporal_search method."""

    @pytest.mark.asyncio
    async def test_temporal_search_with_results(
        self, researcher: Researcher, mock_neo4j: MagicMock
    ) -> None:
        """Temporal search returns time-filtered results."""
        mock_neo4j.execute_query.return_value = [
            {"n": {"name": "Project A", "created_at": time.time()}, "type": ["Project"]}
        ]

        response = await researcher._temporal_search(
            "What did I work on last week?", "trace-123"
        )

        assert response.search_type == SearchType.TEMPORAL
        assert len(response.results) == 1
        assert response.results[0].temporal_context is not None

    @pytest.mark.asyncio
    async def test_temporal_search_no_time_reference(
        self, researcher: Researcher
    ) -> None:
        """Temporal search returns empty when time reference can't be parsed."""
        response = await researcher._temporal_search(
            "Who is Sarah?", "trace-123"
        )

        assert response.search_type == SearchType.TEMPORAL
        assert len(response.results) == 0


# ===========================================================================
# Test Hybrid Search
# ===========================================================================


class TestHybridSearch:
    """Tests for _hybrid_search method."""

    @pytest.mark.asyncio
    async def test_hybrid_search_combines_results(
        self,
        researcher: Researcher,
        mock_graphiti: MagicMock,
        mock_neo4j: MagicMock,
    ) -> None:
        """Hybrid search combines semantic and structural results."""
        # Mock semantic results
        mock_graphiti.search.return_value = [
            MagicMock(fact="Semantic result", uuid="uuid-1", score=0.9)
        ]

        # Mock structural results
        mock_neo4j.execute_query.return_value = [
            {"person": "John", "org": "Acme"}
        ]

        response = await researcher._hybrid_search(
            "Who does John work for last week?", "trace-123"
        )

        assert response.search_type == SearchType.HYBRID
        # Should have results from both searches
        assert len(response.results) >= 1


# ===========================================================================
# Test Process Message
# ===========================================================================


class TestProcessMessage:
    """Tests for process_message method."""

    @pytest.mark.asyncio
    async def test_process_message_with_query(
        self, researcher: Researcher, mock_graphiti: MagicMock
    ) -> None:
        """process_message handles search request."""
        mock_graphiti.search.return_value = [
            MagicMock(fact="Test result", uuid="uuid-1", score=0.9)
        ]

        msg = AgentMessage(
            trace_id="trace-123",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={"query": "Who is Sarah?"},
        )

        response = await researcher.process_message(msg)

        assert response is not None
        assert response.intent == "search_response"
        assert response.target_agent == "orchestrator"
        assert "result" in response.payload
        assert "search_type" in response.payload

    @pytest.mark.asyncio
    async def test_process_message_empty_query(self, researcher: Researcher) -> None:
        """process_message handles empty query gracefully."""
        msg = AgentMessage(
            trace_id="trace-123",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={},  # No query
        )

        response = await researcher.process_message(msg)

        assert response is not None
        assert response.payload["result"] == ""

    @pytest.mark.asyncio
    async def test_process_message_error_handling(
        self, researcher: Researcher, mock_graphiti: MagicMock
    ) -> None:
        """process_message handles errors gracefully and returns empty results."""
        # Make Graphiti raise an error
        mock_graphiti.search.side_effect = Exception("Database error")

        msg = AgentMessage(
            trace_id="trace-123",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={"query": "Test query"},
        )

        response = await researcher.process_message(msg)

        # Should gracefully degrade to empty results, not crash
        assert response is not None
        assert response.payload["count"] == 0
        assert response.payload["result"] == ""
        # Error is logged but system remains stable


# ===========================================================================
# Test Response Formatting
# ===========================================================================


class TestResponseFormatting:
    """Tests for _create_response method."""

    def test_create_response_with_results(self, researcher: Researcher) -> None:
        """_create_response formats results correctly."""
        search_response = SearchResponse(
            query="Test query",
            search_type=SearchType.SEMANTIC,
            results=[
                SearchResult(
                    content="Result 1",
                    source="graphiti",
                    confidence=0.9,
                ),
                SearchResult(
                    content="Result 2",
                    source="graphiti",
                    confidence=0.8,
                ),
            ],
        )

        original_msg = AgentMessage(
            trace_id="trace-123",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={"query": "Test query"},
        )

        response = researcher._create_response(original_msg, search_response)

        assert response.intent == "search_response"
        assert response.target_agent == "orchestrator"
        assert "Result 1" in response.payload["result"]
        assert "Result 2" in response.payload["result"]
        assert response.payload["count"] == 2

    def test_create_response_empty_results(self, researcher: Researcher) -> None:
        """_create_response handles empty results."""
        search_response = SearchResponse(
            query="Test query",
            search_type=SearchType.SEMANTIC,
            results=[],
        )

        original_msg = AgentMessage(
            trace_id="trace-123",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={"query": "Test query"},
        )

        response = researcher._create_response(original_msg, search_response)

        assert response.payload["result"] == ""
        assert response.payload["count"] == 0


# ===========================================================================
# Test Never Fabricates
# ===========================================================================


class TestNeverFabricates:
    """Tests that Researcher NEVER fabricates results."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_not_fabricated(
        self, researcher: Researcher
    ) -> None:
        """Empty query returns empty, doesn't fabricate."""
        msg = AgentMessage(
            trace_id="trace-123",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={"query": ""},
        )

        response = await researcher.process_message(msg)

        assert response is not None
        assert response.payload["result"] == ""
        assert response.payload["count"] == 0

    @pytest.mark.asyncio
    async def test_no_results_returns_empty_not_fabricated(
        self, researcher: Researcher, mock_graphiti: MagicMock
    ) -> None:
        """No results returns empty, doesn't fabricate."""
        mock_graphiti.search.return_value = []

        msg = AgentMessage(
            trace_id="trace-123",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={"query": "Unknown person"},
        )

        response = await researcher.process_message(msg)

        assert response is not None
        assert response.payload["result"] == ""
        assert response.payload["count"] == 0
