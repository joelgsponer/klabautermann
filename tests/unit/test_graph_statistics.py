"""
Unit tests for graph statistics module.

Tests node counting, relationship counting, and statistics aggregation.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.graph_statistics import (
    GraphStatistics,
    NodeCountByType,
    RelationshipCountByType,
    get_graph_statistics,
    get_node_counts_by_type,
    get_relationship_counts_by_type,
    get_total_node_count,
    get_total_relationship_count,
    statistics_to_dict,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Create a mock Neo4jClient."""
    client = MagicMock()
    client.execute_query = AsyncMock()
    return client


# =============================================================================
# Test Data Classes
# =============================================================================


class TestNodeCountByType:
    """Tests for NodeCountByType dataclass."""

    def test_creation(self) -> None:
        """Test creating NodeCountByType."""
        node_count = NodeCountByType(label="Person", count=42)
        assert node_count.label == "Person"
        assert node_count.count == 42


class TestRelationshipCountByType:
    """Tests for RelationshipCountByType dataclass."""

    def test_creation(self) -> None:
        """Test creating RelationshipCountByType."""
        rel_count = RelationshipCountByType(relationship_type="KNOWS", count=100)
        assert rel_count.relationship_type == "KNOWS"
        assert rel_count.count == 100


class TestGraphStatistics:
    """Tests for GraphStatistics dataclass."""

    def test_creation(self) -> None:
        """Test creating GraphStatistics."""
        stats = GraphStatistics(
            total_nodes=100,
            nodes_by_type=[NodeCountByType("Person", 50), NodeCountByType("Task", 50)],
            total_relationships=75,
            relationships_by_type=[RelationshipCountByType("KNOWS", 75)],
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
            database_name="test",
        )
        assert stats.total_nodes == 100
        assert len(stats.nodes_by_type) == 2
        assert stats.total_relationships == 75
        assert len(stats.relationships_by_type) == 1
        assert stats.database_name == "test"


# =============================================================================
# Test Node Counting
# =============================================================================


class TestGetNodeCountsByType:
    """Tests for get_node_counts_by_type function."""

    @pytest.mark.asyncio
    async def test_returns_counts(self, mock_neo4j: MagicMock) -> None:
        """Test that node counts are returned correctly."""
        mock_neo4j.execute_query.return_value = [
            {"label": "Person", "count": 50},
            {"label": "Task", "count": 30},
            {"label": "Project", "count": 20},
        ]

        result = await get_node_counts_by_type(mock_neo4j)

        assert len(result) == 3
        assert result[0].label == "Person"
        assert result[0].count == 50
        assert result[1].label == "Task"
        assert result[1].count == 30

    @pytest.mark.asyncio
    async def test_empty_graph(self, mock_neo4j: MagicMock) -> None:
        """Test counting nodes in empty graph."""
        mock_neo4j.execute_query.return_value = []

        result = await get_node_counts_by_type(mock_neo4j)

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_passes_trace_id(self, mock_neo4j: MagicMock) -> None:
        """Test that trace_id is passed to query."""
        mock_neo4j.execute_query.return_value = []

        await get_node_counts_by_type(mock_neo4j, trace_id="test-trace")

        mock_neo4j.execute_query.assert_called_once()
        call_kwargs = mock_neo4j.execute_query.call_args.kwargs
        assert call_kwargs.get("trace_id") == "test-trace"


class TestGetTotalNodeCount:
    """Tests for get_total_node_count function."""

    @pytest.mark.asyncio
    async def test_returns_count(self, mock_neo4j: MagicMock) -> None:
        """Test that total node count is returned."""
        mock_neo4j.execute_query.return_value = [{"total": 150}]

        result = await get_total_node_count(mock_neo4j)

        assert result == 150

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_neo4j: MagicMock) -> None:
        """Test handling empty result."""
        mock_neo4j.execute_query.return_value = []

        result = await get_total_node_count(mock_neo4j)

        assert result == 0


# =============================================================================
# Test Relationship Counting
# =============================================================================


class TestGetRelationshipCountsByType:
    """Tests for get_relationship_counts_by_type function."""

    @pytest.mark.asyncio
    async def test_returns_counts(self, mock_neo4j: MagicMock) -> None:
        """Test that relationship counts are returned correctly."""
        mock_neo4j.execute_query.return_value = [
            {"relationshipType": "KNOWS", "count": 100},
            {"relationshipType": "WORKS_AT", "count": 50},
        ]

        result = await get_relationship_counts_by_type(mock_neo4j)

        assert len(result) == 2
        assert result[0].relationship_type == "KNOWS"
        assert result[0].count == 100

    @pytest.mark.asyncio
    async def test_empty_graph(self, mock_neo4j: MagicMock) -> None:
        """Test counting relationships in empty graph."""
        mock_neo4j.execute_query.return_value = []

        result = await get_relationship_counts_by_type(mock_neo4j)

        assert len(result) == 0


class TestGetTotalRelationshipCount:
    """Tests for get_total_relationship_count function."""

    @pytest.mark.asyncio
    async def test_returns_count(self, mock_neo4j: MagicMock) -> None:
        """Test that total relationship count is returned."""
        mock_neo4j.execute_query.return_value = [{"total": 200}]

        result = await get_total_relationship_count(mock_neo4j)

        assert result == 200

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_neo4j: MagicMock) -> None:
        """Test handling empty result."""
        mock_neo4j.execute_query.return_value = []

        result = await get_total_relationship_count(mock_neo4j)

        assert result == 0


# =============================================================================
# Test Complete Statistics
# =============================================================================


class TestGetGraphStatistics:
    """Tests for get_graph_statistics function."""

    @pytest.mark.asyncio
    async def test_aggregates_all_stats(self, mock_neo4j: MagicMock) -> None:
        """Test that all statistics are aggregated."""
        # Mock responses for each query
        mock_neo4j.execute_query.side_effect = [
            # Node counts by type
            [{"label": "Person", "count": 50}, {"label": "Task", "count": 30}],
            # Relationship counts by type
            [{"relationshipType": "KNOWS", "count": 75}],
            # Total nodes
            [{"total": 80}],
            # Total relationships
            [{"total": 75}],
        ]

        result = await get_graph_statistics(mock_neo4j)

        assert result.total_nodes == 80
        assert result.total_relationships == 75
        assert len(result.nodes_by_type) == 2
        assert len(result.relationships_by_type) == 1
        assert isinstance(result.timestamp, datetime)


# =============================================================================
# Test Serialization
# =============================================================================


class TestStatisticsToDict:
    """Tests for statistics_to_dict function."""

    def test_converts_to_dict(self) -> None:
        """Test converting statistics to dictionary."""
        stats = GraphStatistics(
            total_nodes=100,
            nodes_by_type=[NodeCountByType("Person", 60), NodeCountByType("Task", 40)],
            total_relationships=50,
            relationships_by_type=[RelationshipCountByType("KNOWS", 50)],
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
        )

        result = statistics_to_dict(stats)

        assert result["total_nodes"] == 100
        assert result["total_relationships"] == 50
        assert result["nodes_by_type"]["Person"] == 60
        assert result["nodes_by_type"]["Task"] == 40
        assert result["relationships_by_type"]["KNOWS"] == 50
        assert "timestamp" in result
