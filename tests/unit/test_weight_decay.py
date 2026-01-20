"""
Unit tests for relationship weight decay module.

Tests weight calculation, decay application, and pruning operations.
Issue: #195 - Implement relationship weight decay
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.weight_decay import (
    DEFAULT_HALF_LIFE_SECONDS,
    DEFAULT_INITIAL_WEIGHT,
    DEFAULT_MIN_WEIGHT,
    DecayResult,
    RelationshipWeight,
    apply_decay_to_relationships,
    calculate_boosted_weight,
    calculate_decayed_weight,
    get_low_weight_relationships,
    get_weight_statistics,
    initialize_relationship_weights,
    update_relationship_access,
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


class TestRelationshipWeight:
    """Tests for RelationshipWeight dataclass."""

    def test_creation(self) -> None:
        """Test creating RelationshipWeight."""
        rw = RelationshipWeight(
            relationship_id=123,
            relationship_type="WORKS_AT",
            source_name="John",
            target_name="Acme Corp",
            current_weight=0.75,
            last_accessed=1705320000.0,
            days_since_access=5.0,
        )
        assert rw.relationship_id == 123
        assert rw.relationship_type == "WORKS_AT"
        assert rw.current_weight == 0.75


class TestDecayResult:
    """Tests for DecayResult dataclass."""

    def test_creation(self) -> None:
        """Test creating DecayResult."""
        result = DecayResult(
            relationships_updated=100,
            relationships_pruned=5,
            average_weight_before=0.8,
            average_weight_after=0.6,
        )
        assert result.relationships_updated == 100
        assert result.relationships_pruned == 5


# =============================================================================
# Test Weight Calculation
# =============================================================================


class TestCalculateDecayedWeight:
    """Tests for calculate_decayed_weight function."""

    def test_no_decay_for_recent_access(self) -> None:
        """Test that weight barely decays for recent access."""
        now = time.time()
        weight = calculate_decayed_weight(1.0, now - 60)  # 1 minute ago
        # Should still be close to 1.0
        assert weight > 0.99

    def test_half_decay_at_half_life(self) -> None:
        """Test weight is approximately half at half-life."""
        now = time.time()
        last_accessed = now - DEFAULT_HALF_LIFE_SECONDS
        weight = calculate_decayed_weight(1.0, last_accessed)
        # Should be approximately 0.5
        assert 0.49 < weight < 0.51

    def test_quarter_decay_at_two_half_lives(self) -> None:
        """Test weight is approximately quarter at two half-lives."""
        now = time.time()
        last_accessed = now - (2 * DEFAULT_HALF_LIFE_SECONDS)
        weight = calculate_decayed_weight(1.0, last_accessed)
        # Should be approximately 0.25
        assert 0.24 < weight < 0.26

    def test_returns_original_for_none_timestamp(self) -> None:
        """Test returns original weight when last_accessed is None."""
        weight = calculate_decayed_weight(0.8, None)
        assert weight == 0.8

    def test_returns_original_for_future_timestamp(self) -> None:
        """Test returns original weight for future timestamp."""
        future = time.time() + 3600
        weight = calculate_decayed_weight(0.8, future)
        assert weight == 0.8

    def test_respects_half_life_parameter(self) -> None:
        """Test custom half-life is respected."""
        now = time.time()
        # Use 1 day half-life
        half_life = 24 * 60 * 60
        last_accessed = now - half_life
        weight = calculate_decayed_weight(1.0, last_accessed, half_life)
        assert 0.49 < weight < 0.51


class TestCalculateBoostedWeight:
    """Tests for calculate_boosted_weight function."""

    def test_boost_increases_weight(self) -> None:
        """Test that boost increases weight."""
        new_weight = calculate_boosted_weight(0.5, boost=0.1)
        assert new_weight == 0.6

    def test_boost_capped_at_max(self) -> None:
        """Test that weight is capped at max."""
        new_weight = calculate_boosted_weight(0.95, boost=0.1, max_weight=1.0)
        assert new_weight == 1.0

    def test_default_boost_value(self) -> None:
        """Test default boost value."""
        from klabautermann.memory.weight_decay import DEFAULT_ACCESS_BOOST

        new_weight = calculate_boosted_weight(0.5)
        assert new_weight == 0.5 + DEFAULT_ACCESS_BOOST


# =============================================================================
# Test Database Operations
# =============================================================================


class TestUpdateRelationshipAccess:
    """Tests for update_relationship_access function."""

    @pytest.mark.asyncio
    async def test_updates_access(self, mock_neo4j: MagicMock) -> None:
        """Test successful access update."""
        mock_neo4j.execute_query.return_value = [{"new_weight": 0.9}]

        result = await update_relationship_access(
            mock_neo4j,
            source_uuid="person-001",
            target_uuid="org-001",
            relationship_type="WORKS_AT",
        )

        assert result is True
        mock_neo4j.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self, mock_neo4j: MagicMock) -> None:
        """Test returning False when relationship not found."""
        mock_neo4j.execute_query.return_value = []

        result = await update_relationship_access(
            mock_neo4j,
            source_uuid="nonexistent",
            target_uuid="org-001",
            relationship_type="WORKS_AT",
        )

        assert result is False


class TestApplyDecayToRelationships:
    """Tests for apply_decay_to_relationships function."""

    @pytest.mark.asyncio
    async def test_applies_decay(self, mock_neo4j: MagicMock) -> None:
        """Test applying decay to relationships."""
        mock_neo4j.execute_query.side_effect = [
            [{"avg_weight": 0.8, "rel_count": 100}],  # Pre-decay stats
            [{"updated": 90}],  # Decay applied
            [{"pruned": 5}],  # Pruned
            [{"avg_weight": 0.6, "rel_count": 95}],  # Post-decay stats
        ]

        result = await apply_decay_to_relationships(mock_neo4j)

        assert isinstance(result, DecayResult)
        assert result.relationships_updated == 90
        assert result.relationships_pruned == 5
        assert result.average_weight_before == 0.8
        assert result.average_weight_after == 0.6

    @pytest.mark.asyncio
    async def test_with_relationship_type_filter(self, mock_neo4j: MagicMock) -> None:
        """Test decay with relationship type filter."""
        mock_neo4j.execute_query.side_effect = [
            [{"avg_weight": 0.7, "rel_count": 50}],
            [{"updated": 45}],
            [{"pruned": 2}],
            [{"avg_weight": 0.5, "rel_count": 48}],
        ]

        result = await apply_decay_to_relationships(
            mock_neo4j,
            relationship_types=["WORKS_AT", "KNOWS"],
        )

        assert result.relationships_updated == 45
        # Check that query includes type filter
        first_call = mock_neo4j.execute_query.call_args_list[0]
        query = first_call[0][0]
        assert "WORKS_AT" in query or ":WORKS_AT|KNOWS" in query


class TestGetLowWeightRelationships:
    """Tests for get_low_weight_relationships function."""

    @pytest.mark.asyncio
    async def test_returns_low_weight_relationships(self, mock_neo4j: MagicMock) -> None:
        """Test returning low weight relationships."""
        now = time.time()
        mock_neo4j.execute_query.return_value = [
            {
                "rel_id": 1,
                "rel_type": "KNOWS",
                "source_name": "John",
                "target_name": "Jane",
                "weight": 0.2,
                "last_accessed": now - (7 * 24 * 60 * 60),  # 7 days ago
            },
            {
                "rel_id": 2,
                "rel_type": "WORKS_AT",
                "source_name": "John",
                "target_name": "Acme",
                "weight": 0.1,
                "last_accessed": now - (30 * 24 * 60 * 60),  # 30 days ago
            },
        ]

        result = await get_low_weight_relationships(mock_neo4j, threshold=0.3)

        assert len(result) == 2
        assert result[0].current_weight == 0.2
        assert result[1].current_weight == 0.1
        assert result[0].days_since_access > 6

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_neo4j: MagicMock) -> None:
        """Test empty result when no low weight relationships."""
        mock_neo4j.execute_query.return_value = []

        result = await get_low_weight_relationships(mock_neo4j, threshold=0.3)

        assert len(result) == 0


class TestInitializeRelationshipWeights:
    """Tests for initialize_relationship_weights function."""

    @pytest.mark.asyncio
    async def test_initializes_weights(self, mock_neo4j: MagicMock) -> None:
        """Test initializing relationship weights."""
        mock_neo4j.execute_query.return_value = [{"initialized": 50}]

        result = await initialize_relationship_weights(mock_neo4j)

        assert result == 50

    @pytest.mark.asyncio
    async def test_with_relationship_types(self, mock_neo4j: MagicMock) -> None:
        """Test initializing specific relationship types."""
        mock_neo4j.execute_query.return_value = [{"initialized": 25}]

        result = await initialize_relationship_weights(
            mock_neo4j,
            relationship_types=["KNOWS"],
        )

        assert result == 25
        # Check query includes type filter
        call_args = mock_neo4j.execute_query.call_args
        query = call_args[0][0]
        assert "KNOWS" in query


class TestGetWeightStatistics:
    """Tests for get_weight_statistics function."""

    @pytest.mark.asyncio
    async def test_returns_statistics(self, mock_neo4j: MagicMock) -> None:
        """Test returning weight statistics."""
        mock_neo4j.execute_query.return_value = [
            {
                "total_relationships": 1000,
                "avg_weight": 0.65,
                "min_weight": 0.1,
                "max_weight": 1.0,
                "low_weight_count": 150,
                "high_weight_count": 400,
            }
        ]

        result = await get_weight_statistics(mock_neo4j)

        assert result["total_relationships"] == 1000
        assert result["avg_weight"] == 0.65
        assert result["low_weight_count"] == 150
        assert result["high_weight_count"] == 400

    @pytest.mark.asyncio
    async def test_handles_empty_result(self, mock_neo4j: MagicMock) -> None:
        """Test handling empty result."""
        mock_neo4j.execute_query.return_value = []

        result = await get_weight_statistics(mock_neo4j)

        assert result["total_relationships"] == 0
        assert result["avg_weight"] == 0.0


# =============================================================================
# Test Constants
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_half_life_is_30_days(self) -> None:
        """Test default half-life is 30 days."""
        expected = 30 * 24 * 60 * 60
        assert expected == DEFAULT_HALF_LIFE_SECONDS

    def test_initial_weight_is_one(self) -> None:
        """Test default initial weight is 1.0."""
        assert DEFAULT_INITIAL_WEIGHT == 1.0

    def test_min_weight_is_reasonable(self) -> None:
        """Test default min weight is between 0 and 1."""
        assert 0 < DEFAULT_MIN_WEIGHT < 1
