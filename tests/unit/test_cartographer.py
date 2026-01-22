"""
Unit tests for Cartographer agent.

Tests community detection functionality including GDS projection,
Louvain algorithm, theme classification, and PART_OF_ISLAND relationships.

Issues: #69, #70, #71, #72, #73
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.agents.cartographer import (
    Cartographer,
    CartographerConfig,
    Community,
    CommunityMember,
    CommunityTheme,
    DetectionResult,
    classify_theme,
)
from klabautermann.core.models import AgentMessage


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_neo4j() -> MagicMock:
    """Create a mock Neo4j client."""
    mock = MagicMock()
    mock.execute_query = AsyncMock(return_value=[])
    mock.execute_write = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def cartographer(mock_neo4j: MagicMock) -> Cartographer:
    """Create a Cartographer instance with mock dependencies."""
    config = CartographerConfig(
        projection_name="test-projection",
        min_community_size=2,  # Lower for testing
    )
    return Cartographer(neo4j_client=mock_neo4j, config=config)


@pytest.fixture
def now_ms() -> int:
    """Get current timestamp in milliseconds."""
    return int(time.time() * 1000)


# =============================================================================
# Basic Tests
# =============================================================================


class TestCartographerInit:
    """Tests for Cartographer initialization."""

    def test_init_default_config(self, mock_neo4j: MagicMock) -> None:
        """Cartographer should initialize with default config."""
        cartographer = Cartographer(neo4j_client=mock_neo4j)

        assert cartographer.name == "cartographer"
        assert cartographer.cartographer_config.projection_name == "klabautermann-community"
        assert cartographer.cartographer_config.min_community_size == 3

    def test_init_custom_config(self, mock_neo4j: MagicMock) -> None:
        """Cartographer should accept custom config."""
        config = CartographerConfig(
            projection_name="custom-projection",
            min_community_size=5,
        )
        cartographer = Cartographer(neo4j_client=mock_neo4j, config=config)

        assert cartographer.cartographer_config.projection_name == "custom-projection"
        assert cartographer.cartographer_config.min_community_size == 5


# =============================================================================
# Theme Classification Tests
# =============================================================================


class TestThemeClassification:
    """Tests for theme classification logic."""

    def test_classify_professional_theme(self) -> None:
        """Should classify Organization-heavy communities as professional."""
        labels = ["Organization", "Organization", "Project", "Task"]
        theme = classify_theme(labels)
        assert theme == CommunityTheme.PROFESSIONAL

    def test_classify_hobby_theme(self) -> None:
        """Should classify Hobby-heavy communities as hobbies."""
        labels = ["Hobby", "Hobby", "Hobby", "Person"]
        theme = classify_theme(labels)
        assert theme == CommunityTheme.HOBBIES

    def test_classify_health_theme(self) -> None:
        """Should classify HealthMetric-heavy communities as health."""
        labels = ["HealthMetric", "HealthMetric", "Routine"]
        theme = classify_theme(labels)
        assert theme == CommunityTheme.HEALTH

    def test_classify_unknown_theme(self) -> None:
        """Should return unknown for unrecognized labels."""
        labels = ["CustomNode", "AnotherCustom"]
        theme = classify_theme(labels)
        assert theme == CommunityTheme.UNKNOWN

    def test_classify_mixed_labels(self) -> None:
        """Should handle mixed label sets."""
        labels = ["Person", "Person", "Note", "Note"]
        theme = classify_theme(labels)
        # Person contributes to multiple themes equally, so may vary
        assert theme in [
            CommunityTheme.FAMILY,
            CommunityTheme.SOCIAL,
            CommunityTheme.PROFESSIONAL,
            CommunityTheme.UNKNOWN,
        ]


# =============================================================================
# GDS Operations Tests
# =============================================================================


class TestGDSOperations:
    """Tests for Graph Data Science operations."""

    @pytest.mark.asyncio
    async def test_check_gds_available_true(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should return True when GDS is available."""
        mock_neo4j.execute_query.return_value = [{"version": "2.5.0"}]

        available = await cartographer._check_gds_available(trace_id="test-123")

        assert available is True

    @pytest.mark.asyncio
    async def test_check_gds_available_false(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should return False when GDS is not available."""
        mock_neo4j.execute_query.side_effect = Exception("GDS not installed")

        available = await cartographer._check_gds_available(trace_id="test-123")

        assert available is False

    @pytest.mark.asyncio
    async def test_project_graph(self, cartographer: Cartographer, mock_neo4j: MagicMock) -> None:
        """Should call GDS project with correct parameters."""
        mock_neo4j.execute_query.return_value = []

        await cartographer._project_graph(trace_id="test-123")

        mock_neo4j.execute_query.assert_called_once()
        call_args = mock_neo4j.execute_query.call_args
        params = call_args[0][1]

        assert params["projection_name"] == "test-projection"
        assert "Person" in params["node_labels"]
        assert "WORKS_AT" in params["relationship_config"]

    @pytest.mark.asyncio
    async def test_drop_projection(self, cartographer: Cartographer, mock_neo4j: MagicMock) -> None:
        """Should drop projection without error."""
        mock_neo4j.execute_query.return_value = []

        # Should not raise even if projection doesn't exist
        await cartographer._drop_projection(trace_id="test-123")

        mock_neo4j.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_louvain(self, cartographer: Cartographer, mock_neo4j: MagicMock) -> None:
        """Should run Louvain and filter by min size."""
        mock_neo4j.execute_query.return_value = [
            {"communityId": 1, "members": ["uuid-1", "uuid-2", "uuid-3"]},
            {"communityId": 2, "members": ["uuid-4"]},  # Too small
            {"communityId": 3, "members": ["uuid-5", "uuid-6"]},
        ]

        communities = await cartographer._run_louvain(trace_id="test-123")

        # Only communities with >= 2 members (config)
        assert len(communities) == 2
        assert 1 in communities
        assert 3 in communities
        assert 2 not in communities


# =============================================================================
# Community Detection Tests
# =============================================================================


class TestCommunityDetection:
    """Tests for full community detection workflow."""

    @pytest.mark.asyncio
    async def test_detect_communities_gds_unavailable(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should return error when GDS is not available."""
        mock_neo4j.execute_query.side_effect = Exception("GDS not available")

        result = await cartographer.detect_communities(trace_id="test-123")

        assert result.gds_available is False
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_detect_communities_success(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should detect and create communities successfully."""
        # Mock sequence: check_gds, project, louvain, get_labels, find_existing, create
        mock_neo4j.execute_query.side_effect = [
            [{"version": "2.5.0"}],  # GDS check
            [],  # Project
            [{"communityId": 1, "members": ["uuid-1", "uuid-2"]}],  # Louvain
            [{"labels": ["Organization"]}, {"labels": ["Project"]}],  # Get labels
            [],  # Find existing (none)
            [{"uuid": "new-community"}],  # Create
            [],  # Drop projection
        ]

        result = await cartographer.detect_communities(trace_id="test-123")

        assert result.gds_available is True
        assert result.communities_created == 1
        assert result.total_members_assigned == 2
        assert len(result.errors) == 0


# =============================================================================
# Community Operations Tests
# =============================================================================


class TestCommunityOperations:
    """Tests for community CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_community(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should create community with correct properties."""
        mock_neo4j.execute_query.return_value = [{"uuid": "new-uuid"}]

        uuid = await cartographer._create_community(
            theme=CommunityTheme.PROFESSIONAL,
            member_uuids=["uuid-1", "uuid-2"],
            trace_id="test-123",
        )

        assert uuid is not None
        call_args = mock_neo4j.execute_query.call_args
        params = call_args[0][1]

        assert params["theme"] == "professional"
        assert params["count"] == 2
        assert "uuid-1" in params["members"]

    @pytest.mark.asyncio
    async def test_update_community(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should update community members."""
        mock_neo4j.execute_query.return_value = []

        await cartographer._update_community(
            community_uuid="existing-uuid",
            member_uuids=["uuid-3", "uuid-4"],
            trace_id="test-123",
        )

        # Should call twice: remove old, add new
        assert mock_neo4j.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_find_existing_community_found(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should find existing community with overlap."""
        mock_neo4j.execute_query.return_value = [{"uuid": "existing-uuid"}]

        existing = await cartographer._find_existing_community(
            theme=CommunityTheme.PROFESSIONAL,
            member_uuids=["uuid-1", "uuid-2", "uuid-3", "uuid-4"],
            trace_id="test-123",
        )

        assert existing == "existing-uuid"

    @pytest.mark.asyncio
    async def test_find_existing_community_not_found(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should return None when no matching community."""
        mock_neo4j.execute_query.return_value = []

        existing = await cartographer._find_existing_community(
            theme=CommunityTheme.HOBBIES,
            member_uuids=["uuid-1", "uuid-2"],
            trace_id="test-123",
        )

        assert existing is None


# =============================================================================
# Query Operations Tests
# =============================================================================


class TestQueryOperations:
    """Tests for community query methods."""

    @pytest.mark.asyncio
    async def test_get_communities_all(
        self, cartographer: Cartographer, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return all communities."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "comm-1",
                "name": "Professional Island",
                "theme": "professional",
                "summary": "Work stuff",
                "node_count": 10,
                "detected_at": now_ms,
                "created_at": now_ms,
                "last_updated": None,
            },
            {
                "uuid": "comm-2",
                "name": "Hobbies Island",
                "theme": "hobbies",
                "summary": None,
                "node_count": 5,
                "detected_at": now_ms,
                "created_at": now_ms,
                "last_updated": None,
            },
        ]

        communities = await cartographer.get_communities(trace_id="test-123")

        assert len(communities) == 2
        assert communities[0].name == "Professional Island"
        assert communities[1].theme == CommunityTheme.HOBBIES

    @pytest.mark.asyncio
    async def test_get_communities_by_theme(
        self, cartographer: Cartographer, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should filter communities by theme."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "comm-1",
                "name": "Professional Island",
                "theme": "professional",
                "summary": None,
                "node_count": 10,
                "detected_at": now_ms,
                "created_at": now_ms,
                "last_updated": None,
            },
        ]

        communities = await cartographer.get_communities(
            theme=CommunityTheme.PROFESSIONAL, trace_id="test-123"
        )

        assert len(communities) == 1
        call_args = mock_neo4j.execute_query.call_args
        params = call_args[0][1]
        assert params["theme"] == "professional"

    @pytest.mark.asyncio
    async def test_get_community_members(
        self, cartographer: Cartographer, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return community members."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "member-1",
                "labels": ["Person"],
                "name": "John Doe",
                "weight": 1.0,
                "detected_at": now_ms,
            },
            {
                "uuid": "member-2",
                "labels": ["Organization"],
                "name": "Acme Corp",
                "weight": 0.8,
                "detected_at": now_ms,
            },
        ]

        members = await cartographer.get_community_members("comm-uuid", trace_id="test-123")

        assert len(members) == 2
        assert members[0].name == "John Doe"
        assert members[1].labels == ["Organization"]

    @pytest.mark.asyncio
    async def test_get_community_by_uuid_found(
        self, cartographer: Cartographer, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should return community when found."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "comm-1",
                "name": "Test Island",
                "theme": "social",
                "summary": "Social connections",
                "node_count": 7,
                "detected_at": now_ms,
                "created_at": now_ms,
                "last_updated": now_ms,
            },
        ]

        community = await cartographer.get_community_by_uuid("comm-1", trace_id="test-123")

        assert community is not None
        assert community.name == "Test Island"
        assert community.theme == CommunityTheme.SOCIAL

    @pytest.mark.asyncio
    async def test_get_community_by_uuid_not_found(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should return None when community not found."""
        mock_neo4j.execute_query.return_value = []

        community = await cartographer.get_community_by_uuid("nonexistent", trace_id="test-123")

        assert community is None


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Tests for community statistics."""

    @pytest.mark.asyncio
    async def test_get_community_statistics(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should return community statistics."""
        mock_neo4j.execute_query.side_effect = [
            [
                {
                    "total_communities": 5,
                    "avg_members": 8.2,
                    "max_members": 15,
                    "min_members": 3,
                }
            ],
            [
                {"theme": "professional", "count": 2},
                {"theme": "social", "count": 2},
                {"theme": "hobbies", "count": 1},
            ],
        ]

        stats = await cartographer.get_community_statistics(trace_id="test-123")

        assert stats["total_communities"] == 5
        assert stats["avg_members"] == 8.2
        assert stats["by_theme"]["professional"] == 2

    @pytest.mark.asyncio
    async def test_get_community_statistics_empty(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should return zero stats when no communities."""
        mock_neo4j.execute_query.return_value = []

        stats = await cartographer.get_community_statistics(trace_id="test-123")

        assert stats["total_communities"] == 0
        assert stats["avg_members"] == 0


# =============================================================================
# Process Message Tests
# =============================================================================


class TestProcessMessage:
    """Tests for message processing."""

    @pytest.mark.asyncio
    async def test_process_detect_communities_operation(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should handle detect_communities operation."""
        # GDS not available (simpler test)
        mock_neo4j.execute_query.side_effect = Exception("GDS unavailable")

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="cartographer",
            intent="detect",
            payload={"operation": "detect_communities"},
            trace_id="test-123",
        )

        response = await cartographer.process_message(msg)

        assert response is not None
        assert response.intent == "cartographer_result"
        assert response.payload["gds_available"] is False

    @pytest.mark.asyncio
    async def test_process_get_communities_operation(
        self, cartographer: Cartographer, mock_neo4j: MagicMock, now_ms: int
    ) -> None:
        """Should handle get_communities operation."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid": "comm-1",
                "name": "Test Island",
                "theme": "professional",
                "summary": None,
                "node_count": 5,
                "detected_at": now_ms,
                "created_at": now_ms,
                "last_updated": None,
            },
        ]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="cartographer",
            intent="query",
            payload={"operation": "get_communities"},
            trace_id="test-123",
        )

        response = await cartographer.process_message(msg)

        assert response is not None
        assert response.payload["count"] == 1
        assert len(response.payload["communities"]) == 1

    @pytest.mark.asyncio
    async def test_process_check_gds_operation(
        self, cartographer: Cartographer, mock_neo4j: MagicMock
    ) -> None:
        """Should handle check_gds operation."""
        mock_neo4j.execute_query.return_value = [{"version": "2.5.0"}]

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="cartographer",
            intent="check",
            payload={"operation": "check_gds"},
            trace_id="test-123",
        )

        response = await cartographer.process_message(msg)

        assert response is not None
        assert response.payload["gds_available"] is True

    @pytest.mark.asyncio
    async def test_process_unknown_operation(self, cartographer: Cartographer) -> None:
        """Should return error for unknown operation."""
        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="cartographer",
            intent="unknown",
            payload={"operation": "invalid_operation"},
            trace_id="test-123",
        )

        response = await cartographer.process_message(msg)

        assert response is not None
        assert "error" in response.payload


# =============================================================================
# Model Tests
# =============================================================================


class TestCommunityModel:
    """Tests for Community dataclass."""

    def test_community_to_dict(self, now_ms: int) -> None:
        """Community should serialize to dict."""
        community = Community(
            uuid="comm-123",
            name="Test Island",
            theme=CommunityTheme.PROFESSIONAL,
            summary="A test community",
            node_count=10,
            detected_at=now_ms,
            created_at=now_ms,
        )

        d = community.to_dict()

        assert d["uuid"] == "comm-123"
        assert d["theme"] == "professional"
        assert d["node_count"] == 10


class TestCommunityMemberModel:
    """Tests for CommunityMember dataclass."""

    def test_community_member_to_dict(self, now_ms: int) -> None:
        """CommunityMember should serialize to dict."""
        member = CommunityMember(
            uuid="member-123",
            labels=["Person", "Entity"],
            name="John Doe",
            weight=0.9,
            detected_at=now_ms,
        )

        d = member.to_dict()

        assert d["uuid"] == "member-123"
        assert d["labels"] == ["Person", "Entity"]
        assert d["weight"] == 0.9


class TestDetectionResultModel:
    """Tests for DetectionResult dataclass."""

    def test_detection_result_to_dict(self) -> None:
        """DetectionResult should serialize to dict."""
        result = DetectionResult(
            communities_created=3,
            communities_updated=2,
            total_members_assigned=25,
            execution_time_ms=1500,
            gds_available=True,
        )

        d = result.to_dict()

        assert d["communities_created"] == 3
        assert d["communities_updated"] == 2
        assert d["total_members_assigned"] == 25


# =============================================================================
# Config Tests
# =============================================================================


class TestCartographerConfig:
    """Tests for CartographerConfig dataclass."""

    def test_default_config_values(self) -> None:
        """CartographerConfig should have sensible defaults."""
        config = CartographerConfig()

        assert config.projection_name == "klabautermann-community"
        assert config.min_community_size == 3
        assert "Person" in config.node_labels
        assert "WORKS_AT" in config.relationship_types

    def test_custom_config_values(self) -> None:
        """CartographerConfig should accept custom values."""
        config = CartographerConfig(
            projection_name="custom",
            min_community_size=10,
            node_labels=["Person", "Organization"],
        )

        assert config.projection_name == "custom"
        assert config.min_community_size == 10
        assert len(config.node_labels) == 2


# =============================================================================
# Summary Generation Tests (#75)
# =============================================================================


class TestSummaryGeneration:
    """Tests for community summary generation (#75)."""

    @pytest.mark.asyncio
    async def test_generate_summaries_finds_communities_without_summaries(
        self, mock_neo4j: MagicMock, cartographer: Cartographer
    ) -> None:
        """Should find communities that need summaries."""
        # Mock finding communities without summaries
        mock_neo4j.execute_query.side_effect = [
            # First call: find communities needing summaries
            [{"uuid": "comm-1", "name": "Work Island", "theme": "professional"}],
            # Second call: get community members
            [
                {
                    "uuid": "node-1",
                    "labels": ["Person"],
                    "name": "John",
                    "weight": 1.0,
                    "detected_at": 0,
                },
                {
                    "uuid": "node-2",
                    "labels": ["Organization"],
                    "name": "Acme",
                    "weight": 1.0,
                    "detected_at": 0,
                },
            ],
        ]
        mock_neo4j.execute_write.return_value = []

        result = await cartographer.generate_summaries()

        assert result["summaries_generated"] == 1
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_generate_summaries_with_force_regenerate(
        self, mock_neo4j: MagicMock, cartographer: Cartographer
    ) -> None:
        """Should regenerate all summaries when force=True."""
        mock_neo4j.execute_query.side_effect = [
            [{"uuid": "comm-1", "name": "Work Island", "theme": "professional"}],
            [
                {
                    "uuid": "node-1",
                    "labels": ["Person"],
                    "name": "John",
                    "weight": 1.0,
                    "detected_at": 0,
                }
            ],
        ]
        mock_neo4j.execute_write.return_value = []

        await cartographer.generate_summaries(force_regenerate=True)

        # Verify query doesn't filter by last_updated
        first_call = mock_neo4j.execute_query.call_args_list[0]
        query = first_call[0][0]
        assert "last_updated" not in query

    @pytest.mark.asyncio
    async def test_generate_summaries_no_communities_needed(
        self, mock_neo4j: MagicMock, cartographer: Cartographer
    ) -> None:
        """Should handle case with no communities needing summaries."""
        mock_neo4j.execute_query.return_value = []

        result = await cartographer.generate_summaries()

        assert result["summaries_generated"] == 0
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_generate_summary_includes_member_composition(
        self, mock_neo4j: MagicMock, cartographer: Cartographer
    ) -> None:
        """Generated summary should describe member composition."""
        members = [
            CommunityMember(uuid="1", labels=["Person"], name="Alice"),
            CommunityMember(uuid="2", labels=["Person"], name="Bob"),
            CommunityMember(uuid="3", labels=["Organization"], name="Acme"),
        ]

        summary = await cartographer._generate_summary(
            community_name="Work Island",
            community_theme="professional",
            members=members,
        )

        assert "professional" in summary.lower() or "work" in summary.lower()
        assert "Person" in summary
        assert "3" in summary  # total count

    @pytest.mark.asyncio
    async def test_generate_summary_empty_members(
        self, mock_neo4j: MagicMock, cartographer: Cartographer
    ) -> None:
        """Should handle community with no members."""
        summary = await cartographer._generate_summary(
            community_name="Empty Island",
            community_theme="unknown",
            members=[],
        )

        assert "0 members" in summary or "unknown" in summary

    @pytest.mark.asyncio
    async def test_process_message_generate_summaries_operation(
        self, mock_neo4j: MagicMock, cartographer: Cartographer
    ) -> None:
        """Process message should handle generate_summaries operation."""
        mock_neo4j.execute_query.return_value = []  # No communities need summaries

        msg = AgentMessage(
            source_agent="orchestrator",
            target_agent="cartographer",
            intent="cartographer_request",
            payload={"operation": "generate_summaries"},
            trace_id="test-trace",
        )

        response = await cartographer.process_message(msg)

        assert response is not None
        assert response.payload["summaries_generated"] == 0


# =============================================================================
# Export Tests
# =============================================================================


class TestExports:
    """Tests for module exports."""

    def test_all_exports_available(self) -> None:
        """All expected items should be exported."""
        from klabautermann.agents.cartographer import __all__

        expected = [
            "Cartographer",
            "CartographerConfig",
            "Community",
            "CommunityMember",
            "CommunityTheme",
            "DetectionResult",
            "classify_theme",
        ]

        for item in expected:
            assert item in __all__

    def test_agents_init_exports_cartographer(self) -> None:
        """Cartographer should be exported from agents package."""
        from klabautermann.agents import (
            Cartographer,
            CartographerConfig,
            Community,
            CommunityTheme,
        )

        assert Cartographer is not None
        assert CartographerConfig is not None
        assert Community is not None
        assert CommunityTheme is not None
