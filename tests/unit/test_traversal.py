"""Unit tests for memory/traversal.py - relationship traversal optimization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.core.ontology import NodeLabel, RelationType
from klabautermann.memory.traversal import (
    NODE_SEARCH_INDEXES,
    RELATIONSHIP_INDEXES,
    BenchmarkResult,
    TraversalConfig,
    TraversalDirection,
    TraversalResult,
    TraversalStats,
    _build_relationship_pattern,
    benchmark_traversal,
    find_connected_entities,
    find_shortest_path,
    get_index_hint,
    get_search_index,
    traverse_dependency_chain,
    traverse_from_node,
    traverse_reporting_chain,
)


# =============================================================================
# TraversalDirection Tests
# =============================================================================


class TestTraversalDirection:
    """Tests for TraversalDirection enum."""

    def test_direction_values(self):
        """Test enum values are strings."""
        assert TraversalDirection.OUTGOING == "outgoing"
        assert TraversalDirection.INCOMING == "incoming"
        assert TraversalDirection.BOTH == "both"

    def test_direction_is_str(self):
        """Test that directions can be used as strings."""
        direction = TraversalDirection.OUTGOING
        assert isinstance(direction, str)
        assert direction.upper() == "OUTGOING"


# =============================================================================
# TraversalConfig Tests
# =============================================================================


class TestTraversalConfig:
    """Tests for TraversalConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = TraversalConfig()
        assert config.max_depth == 3
        assert config.direction == TraversalDirection.BOTH
        assert config.relationship_types is None
        assert config.include_expired is False
        assert config.limit == 100
        assert config.use_index_hints is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = TraversalConfig(
            max_depth=5,
            direction=TraversalDirection.OUTGOING,
            relationship_types=[RelationType.WORKS_AT, RelationType.FRIEND_OF],
            include_expired=True,
            limit=50,
            use_index_hints=False,
        )
        assert config.max_depth == 5
        assert config.direction == TraversalDirection.OUTGOING
        assert len(config.relationship_types) == 2
        assert config.include_expired is True
        assert config.limit == 50
        assert config.use_index_hints is False


# =============================================================================
# TraversalStats Tests
# =============================================================================


class TestTraversalStats:
    """Tests for TraversalStats dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        stats = TraversalStats(
            query_time_ms=123.456,
            nodes_visited=10,
            relationships_traversed=15,
            paths_found=5,
            depth_reached=3,
            used_index="person_search",
        )
        result = stats.to_dict()

        assert result["query_time_ms"] == 123.46  # Rounded to 2 decimal places
        assert result["nodes_visited"] == 10
        assert result["relationships_traversed"] == 15
        assert result["paths_found"] == 5
        assert result["depth_reached"] == 3
        assert result["used_index"] == "person_search"

    def test_to_dict_without_index(self):
        """Test to_dict when no index was used."""
        stats = TraversalStats(
            query_time_ms=50.0,
            nodes_visited=5,
            relationships_traversed=4,
            paths_found=3,
            depth_reached=2,
        )
        result = stats.to_dict()
        assert result["used_index"] is None


# =============================================================================
# TraversalResult Tests
# =============================================================================


class TestTraversalResult:
    """Tests for TraversalResult dataclass."""

    def test_is_empty_true(self):
        """Test is_empty when no nodes found."""
        result = TraversalResult(
            nodes=[],
            relationships=[],
            paths=[],
            stats=TraversalStats(
                query_time_ms=10.0,
                nodes_visited=0,
                relationships_traversed=0,
                paths_found=0,
                depth_reached=0,
            ),
        )
        assert result.is_empty is True

    def test_is_empty_false(self):
        """Test is_empty when nodes found."""
        result = TraversalResult(
            nodes=[{"uuid": "test-uuid", "labels": ["Person"]}],
            relationships=[{"type": "WORKS_AT"}],
            paths=[],
            stats=TraversalStats(
                query_time_ms=10.0,
                nodes_visited=1,
                relationships_traversed=1,
                paths_found=1,
                depth_reached=1,
            ),
        )
        assert result.is_empty is False


# =============================================================================
# BenchmarkResult Tests
# =============================================================================


class TestBenchmarkResult:
    """Tests for BenchmarkResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = BenchmarkResult(
            operation="test_query",
            iterations=10,
            total_time_ms=1000.123,
            avg_time_ms=100.0123,
            min_time_ms=50.567,
            max_time_ms=150.234,
            times_ms=[50.567, 75.0, 100.0, 125.0, 150.234],
        )
        d = result.to_dict()

        assert d["operation"] == "test_query"
        assert d["iterations"] == 10
        assert d["total_time_ms"] == 1000.12
        assert d["avg_time_ms"] == 100.01
        assert d["min_time_ms"] == 50.57
        assert d["max_time_ms"] == 150.23
        # times_ms is not included in to_dict
        assert "times_ms" not in d


# =============================================================================
# Index Hint Tests
# =============================================================================


class TestIndexHints:
    """Tests for index hint functions."""

    def test_relationship_indexes_defined(self):
        """Test that relationship indexes are defined."""
        assert RelationType.WORKS_AT in RELATIONSHIP_INDEXES
        assert RelationType.LOCATED_IN in RELATIONSHIP_INDEXES
        assert RelationType.SPOUSE_OF in RELATIONSHIP_INDEXES
        assert RelationType.FRIEND_OF in RELATIONSHIP_INDEXES
        assert RelationType.PRACTICES in RELATIONSHIP_INDEXES

    def test_node_search_indexes_defined(self):
        """Test that node search indexes are defined."""
        assert NodeLabel.PERSON in NODE_SEARCH_INDEXES
        assert NodeLabel.ORGANIZATION in NODE_SEARCH_INDEXES
        assert NodeLabel.NOTE in NODE_SEARCH_INDEXES
        assert NodeLabel.PROJECT in NODE_SEARCH_INDEXES
        assert NodeLabel.EMAIL in NODE_SEARCH_INDEXES
        assert NodeLabel.CALENDAR_EVENT in NODE_SEARCH_INDEXES
        assert NodeLabel.COMMUNITY in NODE_SEARCH_INDEXES

    def test_get_index_hint_found(self):
        """Test getting index hint for existing relationship."""
        hint = get_index_hint(RelationType.WORKS_AT)
        assert hint == "works_at_temporal"

    def test_get_index_hint_not_found(self):
        """Test getting index hint for non-indexed relationship."""
        hint = get_index_hint(RelationType.BLOCKS)
        assert hint is None

    def test_get_search_index_found(self):
        """Test getting search index for existing label."""
        index = get_search_index(NodeLabel.PERSON)
        assert index == "person_search"

    def test_get_search_index_not_found(self):
        """Test getting search index for non-indexed label."""
        index = get_search_index(NodeLabel.MESSAGE)
        assert index is None


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestBuildRelationshipPattern:
    """Tests for _build_relationship_pattern helper."""

    def test_pattern_without_types(self):
        """Test pattern when no relationship types specified."""
        config = TraversalConfig(max_depth=3)
        pattern = _build_relationship_pattern(config)
        assert pattern == "r*1..3"

    def test_pattern_with_single_type(self):
        """Test pattern with single relationship type."""
        config = TraversalConfig(max_depth=2, relationship_types=[RelationType.WORKS_AT])
        pattern = _build_relationship_pattern(config)
        assert pattern == "r:WORKS_AT*1..2"

    def test_pattern_with_multiple_types(self):
        """Test pattern with multiple relationship types."""
        config = TraversalConfig(
            max_depth=4,
            relationship_types=[RelationType.WORKS_AT, RelationType.FRIEND_OF],
        )
        pattern = _build_relationship_pattern(config)
        assert "WORKS_AT" in pattern
        assert "FRIEND_OF" in pattern
        assert "*1..4" in pattern


# =============================================================================
# traverse_from_node Tests
# =============================================================================


class TestTraverseFromNode:
    """Tests for traverse_from_node function."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_traverse_with_results(self, mock_client):
        """Test traversal that finds nodes."""
        mock_client.execute_query.return_value = [
            {
                "props": {"uuid": "uuid-1", "name": "John"},
                "labels": ["Person"],
                "rel_types": ["WORKS_AT"],
                "depth": 1,
            },
            {
                "props": {"uuid": "uuid-2", "name": "Acme Corp"},
                "labels": ["Organization"],
                "rel_types": ["WORKS_AT", "LOCATED_IN"],
                "depth": 2,
            },
        ]

        result = await traverse_from_node(
            client=mock_client,
            start_uuid="start-uuid",
            start_label=NodeLabel.PERSON,
        )

        assert len(result.nodes) == 2
        assert result.stats.nodes_visited == 2
        assert result.stats.depth_reached == 2
        assert not result.is_empty

    @pytest.mark.asyncio
    async def test_traverse_empty_results(self, mock_client):
        """Test traversal that finds nothing."""
        mock_client.execute_query.return_value = []

        result = await traverse_from_node(
            client=mock_client,
            start_uuid="isolated-uuid",
            start_label=NodeLabel.PERSON,
        )

        assert result.is_empty
        assert result.stats.nodes_visited == 0
        assert result.stats.depth_reached == 0

    @pytest.mark.asyncio
    async def test_traverse_with_custom_config(self, mock_client):
        """Test traversal with custom configuration."""
        mock_client.execute_query.return_value = []

        config = TraversalConfig(
            max_depth=5,
            direction=TraversalDirection.OUTGOING,
            relationship_types=[RelationType.WORKS_AT],
            include_expired=True,
            limit=50,
        )

        await traverse_from_node(
            client=mock_client,
            start_uuid="test-uuid",
            start_label=NodeLabel.PERSON,
            config=config,
        )

        # Verify query was called with correct parameters
        call_args = mock_client.execute_query.call_args
        params = call_args[0][1]
        assert params["max_depth"] == 5
        assert params["limit"] == 50


# =============================================================================
# find_shortest_path Tests
# =============================================================================


class TestFindShortestPath:
    """Tests for find_shortest_path function."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_path_found(self, mock_client):
        """Test finding a path between nodes."""
        mock_client.execute_query.return_value = [
            {
                "path_nodes": [
                    {"uuid": "uuid-1", "labels": ["Person"], "name": "John"},
                    {"uuid": "uuid-2", "labels": ["Organization"], "name": "Acme"},
                    {"uuid": "uuid-3", "labels": ["Person"], "name": "Jane"},
                ],
                "path_rels": [
                    {"type": "WORKS_AT", "properties": {}},
                    {"type": "WORKS_AT", "properties": {}},
                ],
                "path_length": 2,
            }
        ]

        result = await find_shortest_path(
            client=mock_client,
            from_uuid="uuid-1",
            to_uuid="uuid-3",
        )

        assert len(result.nodes) == 3
        assert len(result.relationships) == 2
        assert result.stats.paths_found == 1
        assert result.stats.depth_reached == 2

    @pytest.mark.asyncio
    async def test_no_path_found(self, mock_client):
        """Test when no path exists."""
        mock_client.execute_query.return_value = []

        result = await find_shortest_path(
            client=mock_client,
            from_uuid="uuid-1",
            to_uuid="uuid-disconnected",
        )

        assert result.is_empty
        assert result.stats.paths_found == 0


# =============================================================================
# traverse_dependency_chain Tests
# =============================================================================


class TestTraverseDependencyChain:
    """Tests for traverse_dependency_chain function."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_find_blockers(self, mock_client):
        """Test finding tasks that block a target task."""
        mock_client.execute_query.return_value = [
            {
                "uuid": "blocker-1",
                "name": "Blocker Task 1",
                "status": "pending",
                "priority": "high",
                "depth": 1,
            },
            {
                "uuid": "blocker-2",
                "name": "Blocker Task 2",
                "status": "in_progress",
                "priority": "medium",
                "depth": 2,
            },
        ]

        result = await traverse_dependency_chain(
            client=mock_client,
            task_uuid="target-task",
            direction=TraversalDirection.INCOMING,
        )

        assert len(result.nodes) == 2
        assert result.nodes[0]["name"] == "Blocker Task 1"
        assert result.stats.depth_reached == 2

    @pytest.mark.asyncio
    async def test_find_dependents(self, mock_client):
        """Test finding tasks that depend on target task."""
        mock_client.execute_query.return_value = []

        result = await traverse_dependency_chain(
            client=mock_client,
            task_uuid="target-task",
            direction=TraversalDirection.OUTGOING,
        )

        assert result.is_empty


# =============================================================================
# traverse_reporting_chain Tests (#19)
# =============================================================================


class TestTraverseReportingChain:
    """Tests for traverse_reporting_chain function (Issue #19)."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_find_managers_by_uuid(self, mock_client):
        """Test finding managers above a person by UUID."""
        mock_client.execute_query.return_value = [
            {
                "uuid": "manager-1",
                "name": "John Manager",
                "depth": 1,
                "titles": ["Senior Engineer"],
            },
            {"uuid": "cto-1", "name": "Sarah CTO", "depth": 2, "titles": ["VP Engineering", "CTO"]},
        ]

        result = await traverse_reporting_chain(
            client=mock_client,
            person_uuid="employee-uuid",
            direction=TraversalDirection.OUTGOING,
        )

        assert len(result.nodes) == 2
        assert result.nodes[0]["name"] == "John Manager"
        assert result.nodes[0]["role"] == "manager"
        assert result.stats.depth_reached == 2

    @pytest.mark.asyncio
    async def test_find_managers_by_name(self, mock_client):
        """Test finding managers above a person by name."""
        mock_client.execute_query.return_value = [
            {"uuid": "manager-1", "name": "Alice Manager", "depth": 1, "titles": ["Team Lead"]},
        ]

        result = await traverse_reporting_chain(
            client=mock_client,
            person_name="Bob Employee",
            direction=TraversalDirection.OUTGOING,
        )

        assert len(result.nodes) == 1
        assert result.nodes[0]["name"] == "Alice Manager"
        # Check query used name matching
        call_args = mock_client.execute_query.call_args
        query = call_args[0][0]
        assert "toLower(start.name)" in query

    @pytest.mark.asyncio
    async def test_find_reports_incoming(self, mock_client):
        """Test finding direct reports (people who report to someone)."""
        mock_client.execute_query.return_value = [
            {"uuid": "report-1", "name": "Alice Report", "depth": 1, "titles": ["Engineer"]},
            {"uuid": "report-2", "name": "Bob Report", "depth": 1, "titles": ["Designer"]},
            {"uuid": "report-3", "name": "Charlie Indirect", "depth": 2, "titles": ["Junior Dev"]},
        ]

        result = await traverse_reporting_chain(
            client=mock_client,
            person_uuid="manager-uuid",
            direction=TraversalDirection.INCOMING,
        )

        assert len(result.nodes) == 3
        assert result.nodes[0]["role"] == "report"
        assert result.stats.depth_reached == 2

    @pytest.mark.asyncio
    async def test_no_person_identifier_returns_empty(self, mock_client):
        """Test that missing both uuid and name returns empty result."""
        result = await traverse_reporting_chain(
            client=mock_client,
            direction=TraversalDirection.OUTGOING,
        )

        assert result.is_empty
        assert result.stats.nodes_visited == 0
        mock_client.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_respects_max_depth(self, mock_client):
        """Test that max_depth is used in the query."""
        mock_client.execute_query.return_value = []

        await traverse_reporting_chain(
            client=mock_client,
            person_uuid="employee-uuid",
            max_depth=3,
        )

        call_args = mock_client.execute_query.call_args
        query = call_args[0][0]
        assert "*1..3" in query

    @pytest.mark.asyncio
    async def test_respects_include_expired(self, mock_client):
        """Test that include_expired=False adds temporal filter."""
        mock_client.execute_query.return_value = []

        await traverse_reporting_chain(
            client=mock_client,
            person_uuid="employee-uuid",
            include_expired=False,
        )

        call_args = mock_client.execute_query.call_args
        query = call_args[0][0]
        assert "expired_at IS NULL" in query

    @pytest.mark.asyncio
    async def test_no_temporal_filter_when_expired_included(self, mock_client):
        """Test that include_expired=True skips temporal filter."""
        mock_client.execute_query.return_value = []

        await traverse_reporting_chain(
            client=mock_client,
            person_uuid="employee-uuid",
            include_expired=True,
        )

        call_args = mock_client.execute_query.call_args
        query = call_args[0][0]
        assert "expired_at IS NULL" not in query


# =============================================================================
# find_connected_entities Tests
# =============================================================================


class TestFindConnectedEntities:
    """Tests for find_connected_entities function."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_find_within_hops(self, mock_client):
        """Test finding connected entities within N hops."""
        mock_client.execute_query.return_value = [
            {"type": "Person", "uuid": "uuid-1", "name": "John", "distance": 1},
            {"type": "Organization", "uuid": "uuid-2", "name": "Acme", "distance": 1},
            {"type": "Location", "uuid": "uuid-3", "name": "NYC", "distance": 2},
        ]

        result = await find_connected_entities(
            client=mock_client,
            entity_uuid="center-uuid",
            hops=2,
        )

        assert len(result.nodes) == 3
        assert result.stats.depth_reached == 2
        # Check relationships traversed (sum of distances)
        assert result.stats.relationships_traversed == 4  # 1 + 1 + 2

    @pytest.mark.asyncio
    async def test_hops_capped_at_three(self, mock_client):
        """Test that hops are capped at 3 for performance."""
        mock_client.execute_query.return_value = []

        await find_connected_entities(
            client=mock_client,
            entity_uuid="center-uuid",
            hops=10,  # Should be capped to 3
        )

        # Verify query was constructed with capped hops
        call_args = mock_client.execute_query.call_args
        query = call_args[0][0]
        assert "*1..3" in query  # Capped at 3


# =============================================================================
# benchmark_traversal Tests
# =============================================================================


class TestBenchmarkTraversal:
    """Tests for benchmark_traversal function."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Neo4j client."""
        client = MagicMock()
        client.execute_query = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_benchmark_runs_iterations(self, mock_client):
        """Test that benchmark runs specified iterations."""
        result = await benchmark_traversal(
            client=mock_client,
            operation_name="test_op",
            query="MATCH (n) RETURN n LIMIT 1",
            params={},
            iterations=5,
        )

        assert result.iterations == 5
        assert mock_client.execute_query.call_count == 5
        assert len(result.times_ms) == 5

    @pytest.mark.asyncio
    async def test_benchmark_calculates_stats(self, mock_client):
        """Test that benchmark calculates timing statistics."""
        result = await benchmark_traversal(
            client=mock_client,
            operation_name="test_op",
            query="MATCH (n) RETURN n",
            params={},
            iterations=3,
        )

        assert result.operation == "test_op"
        assert result.total_time_ms > 0
        assert result.avg_time_ms > 0
        assert result.min_time_ms <= result.avg_time_ms
        assert result.max_time_ms >= result.avg_time_ms


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that module exports are accessible."""

    def test_exports_from_memory_module(self):
        """Test that traversal exports are available from memory module."""
        from klabautermann.memory import (
            NODE_SEARCH_INDEXES,
            RELATIONSHIP_INDEXES,
            BenchmarkResult,
            TraversalConfig,
            TraversalDirection,
            TraversalResult,
            TraversalStats,
            benchmark_traversal,
            find_connected_entities,
            find_shortest_path,
            get_index_hint,
            get_search_index,
            traverse_dependency_chain,
            traverse_from_node,
            traverse_reporting_chain,
        )

        # Verify imports succeeded
        assert TraversalDirection is not None
        assert TraversalConfig is not None
        assert TraversalStats is not None
        assert TraversalResult is not None
        assert BenchmarkResult is not None
        assert RELATIONSHIP_INDEXES is not None
        assert NODE_SEARCH_INDEXES is not None
        assert traverse_from_node is not None
        assert find_shortest_path is not None
        assert traverse_dependency_chain is not None
        assert traverse_reporting_chain is not None
        assert find_connected_entities is not None
        assert benchmark_traversal is not None
        assert get_index_hint is not None
        assert get_search_index is not None
