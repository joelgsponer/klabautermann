"""
Unit tests for entity merge utility.

Tests duplicate detection and entity merging functionality.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from klabautermann.memory.entity_merge import (
    DuplicateCandidate,
    MergePreview,
    MergeResult,
    auto_merge_duplicates,
    find_duplicate_organizations,
    find_duplicate_persons,
    merge_entities,
    merge_persons,
    preview_merge,
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


class TestDuplicateCandidate:
    """Tests for DuplicateCandidate dataclass."""

    def test_creation(self) -> None:
        """Test creating DuplicateCandidate."""
        candidate = DuplicateCandidate(
            uuid1="person-001",
            uuid2="person-002",
            name1="John Smith",
            name2="John Smith",
            email1="john@example.com",
            email2="john@example.com",
            match_reason="both",
            similarity_score=1.0,
        )
        assert candidate.uuid1 == "person-001"
        assert candidate.uuid2 == "person-002"
        assert candidate.match_reason == "both"
        assert candidate.similarity_score == 1.0

    def test_with_none_values(self) -> None:
        """Test creating with None values."""
        candidate = DuplicateCandidate(
            uuid1="person-001",
            uuid2="person-002",
            name1="John",
            name2="John",
            email1=None,
            email2=None,
            match_reason="name",
            similarity_score=0.7,
        )
        assert candidate.email1 is None
        assert candidate.email2 is None


class TestMergePreview:
    """Tests for MergePreview dataclass."""

    def test_creation(self) -> None:
        """Test creating MergePreview."""
        preview = MergePreview(
            source_uuid="person-002",
            source_label="Person",
            source_properties={"name": "John", "phone": "555-1234"},
            target_uuid="person-001",
            target_label="Person",
            target_properties={"name": "John Smith", "email": "john@example.com"},
            incoming_relationships=3,
            outgoing_relationships=5,
            properties_to_merge=["phone"],
        )
        assert preview.source_uuid == "person-002"
        assert preview.incoming_relationships == 3
        assert preview.outgoing_relationships == 5
        assert "phone" in preview.properties_to_merge


class TestMergeResult:
    """Tests for MergeResult dataclass."""

    def test_creation(self) -> None:
        """Test creating MergeResult."""
        result = MergeResult(
            source_uuid="person-002",
            target_uuid="person-001",
            relationships_transferred=8,
            properties_merged=["phone", "bio"],
            source_deleted=True,
            timestamp=datetime(2024, 1, 15, 10, 0, 0),
        )
        assert result.source_uuid == "person-002"
        assert result.relationships_transferred == 8
        assert result.source_deleted is True


# =============================================================================
# Test Duplicate Detection
# =============================================================================


class TestFindDuplicatePersons:
    """Tests for find_duplicate_persons function."""

    @pytest.mark.asyncio
    async def test_finds_duplicates(self, mock_neo4j: MagicMock) -> None:
        """Test finding duplicate persons."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid1": "person-001",
                "uuid2": "person-002",
                "name1": "John Smith",
                "name2": "John Smith",
                "email1": "john@example.com",
                "email2": "john@example.com",
                "match_reason": "both",
                "similarity_score": 1.0,
            },
            {
                "uuid1": "person-003",
                "uuid2": "person-004",
                "name1": "Sarah",
                "name2": "Sarah",
                "email1": None,
                "email2": None,
                "match_reason": "name",
                "similarity_score": 0.7,
            },
        ]

        results = await find_duplicate_persons(mock_neo4j)

        assert len(results) == 2
        assert results[0].similarity_score == 1.0
        assert results[1].match_reason == "name"

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_neo4j: MagicMock) -> None:
        """Test when no duplicates found."""
        mock_neo4j.execute_query.return_value = []

        results = await find_duplicate_persons(mock_neo4j)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self, mock_neo4j: MagicMock) -> None:
        """Test that limit parameter is passed."""
        mock_neo4j.execute_query.return_value = []

        await find_duplicate_persons(mock_neo4j, limit=25)

        call_args = mock_neo4j.execute_query.call_args
        assert call_args[0][1]["limit"] == 25


class TestFindDuplicateOrganizations:
    """Tests for find_duplicate_organizations function."""

    @pytest.mark.asyncio
    async def test_finds_duplicates(self, mock_neo4j: MagicMock) -> None:
        """Test finding duplicate organizations."""
        mock_neo4j.execute_query.return_value = [
            {
                "uuid1": "org-001",
                "uuid2": "org-002",
                "name1": "Acme Corp",
                "name2": "Acme Corp",
                "email1": "acme.com",  # domain stored in email1 field
                "email2": "acme.com",
                "match_reason": "both",
                "similarity_score": 1.0,
            }
        ]

        results = await find_duplicate_organizations(mock_neo4j)

        assert len(results) == 1
        assert results[0].name1 == "Acme Corp"

    @pytest.mark.asyncio
    async def test_empty_result(self, mock_neo4j: MagicMock) -> None:
        """Test when no duplicates found."""
        mock_neo4j.execute_query.return_value = []

        results = await find_duplicate_organizations(mock_neo4j)

        assert len(results) == 0


# =============================================================================
# Test Merge Preview
# =============================================================================


class TestPreviewMerge:
    """Tests for preview_merge function."""

    @pytest.mark.asyncio
    async def test_returns_preview(self, mock_neo4j: MagicMock) -> None:
        """Test getting merge preview."""
        mock_neo4j.execute_query.return_value = [
            {
                "source_label": "Person",
                "target_label": "Person",
                "source_properties": {"name": "John", "phone": "555-1234"},
                "target_properties": {"name": "John Smith", "email": "john@example.com"},
                "incoming": 3,
                "outgoing": 5,
                "props_to_merge": ["phone"],
            }
        ]

        result = await preview_merge(mock_neo4j, "person-002", "person-001")

        assert result is not None
        assert result.source_uuid == "person-002"
        assert result.target_uuid == "person-001"
        assert result.incoming_relationships == 3
        assert result.outgoing_relationships == 5
        assert "phone" in result.properties_to_merge

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, mock_neo4j: MagicMock) -> None:
        """Test returns None when entities not found."""
        mock_neo4j.execute_query.return_value = []

        result = await preview_merge(mock_neo4j, "nonexistent", "also-nonexistent")

        assert result is None


# =============================================================================
# Test Entity Merge
# =============================================================================


class TestMergeEntities:
    """Tests for merge_entities function."""

    @pytest.mark.asyncio
    async def test_successful_merge(self, mock_neo4j: MagicMock) -> None:
        """Test successful entity merge."""
        # First call: preview_merge query
        # Second call: merge query
        mock_neo4j.execute_query.side_effect = [
            [
                {
                    "source_label": "Person",
                    "target_label": "Person",
                    "source_properties": {"name": "John"},
                    "target_properties": {"name": "John Smith"},
                    "incoming": 2,
                    "outgoing": 3,
                    "props_to_merge": ["bio"],
                }
            ],
            [{"total_rels": 5}],
        ]

        result = await merge_entities(mock_neo4j, "person-002", "person-001")

        assert result.source_uuid == "person-002"
        assert result.target_uuid == "person-001"
        assert result.relationships_transferred == 5
        assert result.source_deleted is True

    @pytest.mark.asyncio
    async def test_merge_fails_when_not_found(self, mock_neo4j: MagicMock) -> None:
        """Test merge fails gracefully when entities not found."""
        mock_neo4j.execute_query.return_value = []

        result = await merge_entities(mock_neo4j, "nonexistent", "also-nonexistent")

        assert result.source_deleted is False
        assert result.relationships_transferred == 0


class TestMergePersons:
    """Tests for merge_persons function."""

    @pytest.mark.asyncio
    async def test_wraps_merge_entities(self, mock_neo4j: MagicMock) -> None:
        """Test merge_persons is a convenience wrapper."""
        mock_neo4j.execute_query.side_effect = [
            [
                {
                    "source_label": "Person",
                    "target_label": "Person",
                    "source_properties": {},
                    "target_properties": {},
                    "incoming": 1,
                    "outgoing": 1,
                    "props_to_merge": [],
                }
            ],
            [{"total_rels": 2}],
        ]

        result = await merge_persons(mock_neo4j, "keep-uuid", "remove-uuid")

        # Note: merge_persons swaps order (keep becomes target)
        assert result.target_uuid == "keep-uuid"
        assert result.source_uuid == "remove-uuid"


# =============================================================================
# Test Auto Merge
# =============================================================================


class TestAutoMergeDuplicates:
    """Tests for auto_merge_duplicates function."""

    @pytest.mark.asyncio
    async def test_dry_run_mode(self, mock_neo4j: MagicMock) -> None:
        """Test dry run doesn't actually merge."""
        # First call: find_duplicate_persons
        # Second call: find_duplicate_organizations
        # Third call: preview_merge for first duplicate
        mock_neo4j.execute_query.side_effect = [
            [
                {
                    "uuid1": "person-001",
                    "uuid2": "person-002",
                    "name1": "John",
                    "name2": "John",
                    "email1": "john@example.com",
                    "email2": "john@example.com",
                    "match_reason": "both",
                    "similarity_score": 0.95,
                }
            ],
            [],  # no org duplicates
            [
                {
                    "source_label": "Person",
                    "target_label": "Person",
                    "source_properties": {},
                    "target_properties": {},
                    "incoming": 2,
                    "outgoing": 3,
                    "props_to_merge": [],
                }
            ],
        ]

        results = await auto_merge_duplicates(mock_neo4j, min_similarity=0.9, dry_run=True)

        assert len(results) == 1
        assert results[0].source_deleted is False  # dry run

    @pytest.mark.asyncio
    async def test_filters_by_similarity(self, mock_neo4j: MagicMock) -> None:
        """Test that low similarity duplicates are skipped."""
        mock_neo4j.execute_query.side_effect = [
            [
                {
                    "uuid1": "person-001",
                    "uuid2": "person-002",
                    "name1": "John",
                    "name2": "John",
                    "email1": None,
                    "email2": None,
                    "match_reason": "name",
                    "similarity_score": 0.7,  # Below threshold
                }
            ],
            [],  # no org duplicates
        ]

        results = await auto_merge_duplicates(mock_neo4j, min_similarity=0.9, dry_run=True)

        assert len(results) == 0  # Filtered out

    @pytest.mark.asyncio
    async def test_no_duplicates(self, mock_neo4j: MagicMock) -> None:
        """Test when no duplicates exist."""
        mock_neo4j.execute_query.side_effect = [
            [],  # no person duplicates
            [],  # no org duplicates
        ]

        results = await auto_merge_duplicates(mock_neo4j, dry_run=True)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_actual_merge(self, mock_neo4j: MagicMock) -> None:
        """Test actual merge (not dry run)."""
        mock_neo4j.execute_query.side_effect = [
            [
                {
                    "uuid1": "person-001",
                    "uuid2": "person-002",
                    "name1": "John",
                    "name2": "John",
                    "email1": "john@example.com",
                    "email2": "john@example.com",
                    "match_reason": "both",
                    "similarity_score": 0.95,
                }
            ],
            [],  # no org duplicates
            # preview_merge call
            [
                {
                    "source_label": "Person",
                    "target_label": "Person",
                    "source_properties": {},
                    "target_properties": {},
                    "incoming": 2,
                    "outgoing": 3,
                    "props_to_merge": [],
                }
            ],
            # merge query
            [{"total_rels": 5}],
        ]

        results = await auto_merge_duplicates(mock_neo4j, min_similarity=0.9, dry_run=False)

        assert len(results) == 1
        assert results[0].source_deleted is True
