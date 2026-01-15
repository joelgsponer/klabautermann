"""
Unit tests for entity deduplication.

Reference: specs/architecture/MEMORY.md Section 7.1
Task: T049 - Entity Deduplication

The deduplication module detects and merges duplicate entities using:
1. Exact property matches (email, domain)
2. Fuzzy name matching (rapidfuzz)
3. Combined scoring with configurable thresholds

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from unittest.mock import AsyncMock

import pytest

from klabautermann.core.models import DuplicateCandidate
from klabautermann.memory.deduplication import (
    find_duplicate_organizations,
    find_duplicate_persons,
    flag_for_review,
    merge_entities,
    process_duplicates,
)


class TestFindDuplicatePersons:
    """Test suite for person duplicate detection."""

    @pytest.mark.asyncio
    async def test_finds_exact_email_match(self) -> None:
        """Should detect persons with same email as duplicates."""
        # Mock Neo4jClient
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Email query
                [
                    {
                        "uuid1": "uuid-1",
                        "name1": "Sarah",
                        "email1": "sarah@example.com",
                        "uuid2": "uuid-2",
                        "name2": "Sarah Johnson",
                        "email2": "sarah@example.com",
                    }
                ],
                # Domain query
                [],
                # Name query
                [],
            ]
        )

        candidates = await find_duplicate_persons(mock_neo4j, min_score=0.7)

        assert len(candidates) == 1
        assert candidates[0].uuid1 == "uuid-1"
        assert candidates[0].uuid2 == "uuid-2"
        assert candidates[0].similarity_score == 1.0
        assert "same_email" in candidates[0].match_reasons
        assert candidates[0].entity_type == "Person"

    @pytest.mark.asyncio
    async def test_finds_similar_names(self) -> None:
        """Should detect persons with similar names."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Email query
                [],
                # Domain query
                [],
                # Name query
                [
                    {"uuid": "uuid-1", "name": "John Smith", "email": None},
                    {"uuid": "uuid-2", "name": "John Smyth", "email": None},
                ],
            ]
        )

        candidates = await find_duplicate_persons(mock_neo4j, min_score=0.7)

        assert len(candidates) == 1
        assert candidates[0].name1 == "John Smith"
        assert candidates[0].name2 == "John Smyth"
        assert candidates[0].similarity_score >= 0.8  # High similarity
        assert "similar_name" in candidates[0].match_reasons

    @pytest.mark.asyncio
    async def test_finds_email_domain_match(self) -> None:
        """Should detect persons with same email domain."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Email query
                [],
                # Domain query
                [
                    {
                        "uuid1": "uuid-1",
                        "name1": "John Doe",
                        "email1": "john@acme.com",
                        "uuid2": "uuid-2",
                        "name2": "John D",
                        "email2": "jdoe@acme.com",
                    }
                ],
                # Name query
                [],
            ]
        )

        candidates = await find_duplicate_persons(mock_neo4j, min_score=0.5)

        assert len(candidates) == 1
        assert candidates[0].similarity_score >= 0.5
        assert "same_email_domain" in candidates[0].match_reasons

    @pytest.mark.asyncio
    async def test_respects_min_score_threshold(self) -> None:
        """Should only return candidates above min_score."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Email query
                [],
                # Domain query
                [],
                # Name query
                [
                    {"uuid": "uuid-1", "name": "Alice", "email": None},
                    {"uuid": "uuid-2", "name": "Bob", "email": None},  # Very different
                ],
            ]
        )

        candidates = await find_duplicate_persons(mock_neo4j, min_score=0.7)

        # "Alice" and "Bob" have low similarity, should not be returned
        assert len(candidates) == 0

    @pytest.mark.asyncio
    async def test_avoids_duplicate_candidates(self) -> None:
        """Should not return same pair multiple times."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Email query - exact match
                [
                    {
                        "uuid1": "uuid-1",
                        "name1": "Sarah",
                        "email1": "sarah@example.com",
                        "uuid2": "uuid-2",
                        "name2": "Sarah",
                        "email2": "sarah@example.com",
                    }
                ],
                # Domain query
                [],
                # Name query - also has same pair
                [
                    {"uuid": "uuid-1", "name": "Sarah", "email": "sarah@example.com"},
                    {"uuid": "uuid-2", "name": "Sarah", "email": "sarah@example.com"},
                ],
            ]
        )

        candidates = await find_duplicate_persons(mock_neo4j, min_score=0.7)

        # Should only have one candidate, not two
        assert len(candidates) == 1

    @pytest.mark.asyncio
    async def test_empty_database(self) -> None:
        """Should handle empty database gracefully."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                [],  # Email query
                [],  # Domain query
                [],  # Name query
            ]
        )

        candidates = await find_duplicate_persons(mock_neo4j, min_score=0.7)

        assert len(candidates) == 0


class TestFindDuplicateOrganizations:
    """Test suite for organization duplicate detection."""

    @pytest.mark.asyncio
    async def test_finds_exact_domain_match(self) -> None:
        """Should detect organizations with same domain."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Domain query
                [
                    {
                        "uuid1": "uuid-1",
                        "name1": "Acme Corp",
                        "domain1": "acme.com",
                        "uuid2": "uuid-2",
                        "name2": "Acme Corporation",
                        "domain2": "acme.com",
                    }
                ],
                # Name query
                [],
            ]
        )

        candidates = await find_duplicate_organizations(mock_neo4j, min_score=0.7)

        assert len(candidates) == 1
        assert candidates[0].similarity_score == 1.0
        assert "same_domain" in candidates[0].match_reasons
        assert candidates[0].entity_type == "Organization"

    @pytest.mark.asyncio
    async def test_finds_similar_organization_names(self) -> None:
        """Should detect organizations with similar names."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Domain query
                [],
                # Name query
                [
                    {"uuid": "uuid-1", "name": "Microsoft Corporation", "domain": None},
                    {"uuid": "uuid-2", "name": "Microsoft Corp", "domain": None},
                ],
            ]
        )

        candidates = await find_duplicate_organizations(mock_neo4j, min_score=0.7)

        assert len(candidates) == 1
        assert candidates[0].similarity_score >= 0.8
        assert "similar_name" in candidates[0].match_reasons

    @pytest.mark.asyncio
    async def test_respects_min_score(self) -> None:
        """Should only return organizations above min_score."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Domain query
                [],
                # Name query
                [
                    {"uuid": "uuid-1", "name": "Apple", "domain": None},
                    {"uuid": "uuid-2", "name": "Google", "domain": None},
                ],
            ]
        )

        candidates = await find_duplicate_organizations(mock_neo4j, min_score=0.7)

        # Very different names
        assert len(candidates) == 0


class TestMergeEntities:
    """Test suite for entity merging."""

    @pytest.mark.asyncio
    async def test_merges_person_properties(self) -> None:
        """Should merge person properties correctly."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_write = AsyncMock(
            side_effect=[
                [{"transferred_incoming": 2}],  # Incoming rels
                [{"transferred_outgoing": 1}],  # Outgoing rels
                [{"status": "merged"}],  # Property merge and delete
            ]
        )

        success = await merge_entities(mock_neo4j, "keep-uuid", "remove-uuid", "Person")

        assert success is True
        assert mock_neo4j.execute_write.call_count == 3

    @pytest.mark.asyncio
    async def test_merges_organization_properties(self) -> None:
        """Should merge organization properties correctly."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_write = AsyncMock(
            side_effect=[
                [{"transferred_incoming": 1}],
                [{"transferred_outgoing": 3}],
                [{"status": "merged"}],
            ]
        )

        success = await merge_entities(mock_neo4j, "keep-uuid", "remove-uuid", "Organization")

        assert success is True

    @pytest.mark.asyncio
    async def test_handles_unknown_entity_type(self) -> None:
        """Should return False for unknown entity type."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_write = AsyncMock(
            side_effect=[
                [{"transferred_incoming": 0}],
                [{"transferred_outgoing": 0}],
            ]
        )

        success = await merge_entities(mock_neo4j, "keep-uuid", "remove-uuid", "UnknownType")

        assert success is False

    @pytest.mark.asyncio
    async def test_handles_merge_failure(self) -> None:
        """Should handle database errors gracefully."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_write = AsyncMock(side_effect=Exception("Database connection failed"))

        success = await merge_entities(mock_neo4j, "keep-uuid", "remove-uuid", "Person")

        assert success is False


class TestFlagForReview:
    """Test suite for flagging duplicates for review."""

    @pytest.mark.asyncio
    async def test_creates_potential_duplicate_relationship(self) -> None:
        """Should create POTENTIAL_DUPLICATE relationship."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_write = AsyncMock(return_value=[{"flag_id": "flag-123"}])

        candidate = DuplicateCandidate(
            uuid1="uuid-1",
            uuid2="uuid-2",
            name1="John Doe",
            name2="John D.",
            entity_type="Person",
            similarity_score=0.85,
            match_reasons=["similar_name"],
        )

        flag_id = await flag_for_review(mock_neo4j, candidate)

        assert flag_id == "flag-123"
        mock_neo4j.execute_write.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_flag_failure(self) -> None:
        """Should return empty string on error."""
        mock_neo4j = AsyncMock()
        mock_neo4j.execute_write = AsyncMock(side_effect=Exception("Query failed"))

        candidate = DuplicateCandidate(
            uuid1="uuid-1",
            uuid2="uuid-2",
            name1="Test",
            name2="Test2",
            entity_type="Person",
            similarity_score=0.75,
            match_reasons=["similar_name"],
        )

        flag_id = await flag_for_review(mock_neo4j, candidate)

        assert flag_id == ""


class TestProcessDuplicates:
    """Test suite for complete duplicate processing pipeline."""

    @pytest.mark.asyncio
    async def test_auto_merges_high_confidence_duplicates(self) -> None:
        """Should automatically merge duplicates with score >= 0.9."""
        mock_neo4j = AsyncMock()

        # Mock find_duplicate_persons to return high-confidence match
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Email query - exact match (score 1.0)
                [
                    {
                        "uuid1": "uuid-1",
                        "name1": "Sarah",
                        "email1": "sarah@example.com",
                        "uuid2": "uuid-2",
                        "name2": "Sarah",
                        "email2": "sarah@example.com",
                    }
                ],
                # Domain query
                [],
                # Name query
                [],
                # Organization domain query
                [],
                # Organization name query
                [],
            ]
        )

        # Mock merge_entities
        mock_neo4j.execute_write = AsyncMock(
            side_effect=[
                [{"transferred_incoming": 1}],
                [{"transferred_outgoing": 1}],
                [{"status": "merged"}],
            ]
        )

        stats = await process_duplicates(mock_neo4j, auto_merge_threshold=0.9, review_threshold=0.7)

        assert stats["auto_merged"] == 1
        assert stats["flagged_for_review"] == 0

    @pytest.mark.asyncio
    async def test_flags_medium_confidence_duplicates(self) -> None:
        """Should flag duplicates with 0.7 <= score < 0.9 for review."""
        mock_neo4j = AsyncMock()

        # Mock find_duplicate_persons to return medium-confidence match
        # Use names with medium similarity (0.7-0.9): "Michael" vs "Michelle"
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Email query
                [],
                # Domain query
                [],
                # Name query - similar names (score = 0.80)
                [
                    {"uuid": "uuid-1", "name": "Michael", "email": None},
                    {"uuid": "uuid-2", "name": "Michelle", "email": None},
                ],
                # Organization domain query
                [],
                # Organization name query
                [],
            ]
        )

        # Mock flag_for_review
        mock_neo4j.execute_write = AsyncMock(return_value=[{"flag_id": "flag-123"}])

        stats = await process_duplicates(mock_neo4j, auto_merge_threshold=0.9, review_threshold=0.7)

        assert stats["auto_merged"] == 0
        assert stats["flagged_for_review"] == 1

    @pytest.mark.asyncio
    async def test_ignores_low_confidence_duplicates(self) -> None:
        """Should ignore duplicates with score < 0.7."""
        mock_neo4j = AsyncMock()

        # Return no candidates (all below threshold)
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                [],  # Person email query
                [],  # Person domain query
                [],  # Person name query
                [],  # Org domain query
                [],  # Org name query
            ]
        )

        stats = await process_duplicates(mock_neo4j, auto_merge_threshold=0.9, review_threshold=0.7)

        assert stats["auto_merged"] == 0
        assert stats["flagged_for_review"] == 0
        assert stats["ignored"] == 0

    @pytest.mark.asyncio
    async def test_processes_both_persons_and_organizations(self) -> None:
        """Should process both person and organization duplicates."""
        mock_neo4j = AsyncMock()

        # Mock to return one person duplicate and one org duplicate
        mock_neo4j.execute_read = AsyncMock(
            side_effect=[
                # Person email query - exact match
                [
                    {
                        "uuid1": "person-1",
                        "name1": "Alice",
                        "email1": "alice@test.com",
                        "uuid2": "person-2",
                        "name2": "Alice",
                        "email2": "alice@test.com",
                    }
                ],
                # Person domain query
                [],
                # Person name query
                [],
                # Org domain query - exact match
                [
                    {
                        "uuid1": "org-1",
                        "name1": "TechCorp",
                        "domain1": "techcorp.com",
                        "uuid2": "org-2",
                        "name2": "Tech Corp",
                        "domain2": "techcorp.com",
                    }
                ],
                # Org name query
                [],
            ]
        )

        # Mock merges for both
        mock_neo4j.execute_write = AsyncMock(
            side_effect=[
                # Person merge
                [{"transferred_incoming": 1}],
                [{"transferred_outgoing": 1}],
                [{"status": "merged"}],
                # Org merge
                [{"transferred_incoming": 2}],
                [{"transferred_outgoing": 0}],
                [{"status": "merged"}],
            ]
        )

        stats = await process_duplicates(mock_neo4j, auto_merge_threshold=0.9, review_threshold=0.7)

        assert stats["auto_merged"] == 2


class TestDuplicateCandidateModel:
    """Test suite for DuplicateCandidate Pydantic model."""

    def test_valid_candidate(self) -> None:
        """Should accept valid duplicate candidate."""
        candidate = DuplicateCandidate(
            uuid1="uuid-1",
            uuid2="uuid-2",
            name1="John",
            name2="John Doe",
            entity_type="Person",
            similarity_score=0.85,
            match_reasons=["similar_name"],
        )

        assert candidate.similarity_score == 0.85
        assert "similar_name" in candidate.match_reasons

    def test_rejects_invalid_score(self) -> None:
        """Should reject similarity score outside 0.0-1.0 range."""
        with pytest.raises(ValueError):
            DuplicateCandidate(
                uuid1="uuid-1",
                uuid2="uuid-2",
                name1="Test",
                name2="Test2",
                entity_type="Person",
                similarity_score=1.5,  # Invalid
                match_reasons=["test"],
            )

    def test_defaults_to_empty_match_reasons(self) -> None:
        """Should default match_reasons to empty list."""
        candidate = DuplicateCandidate(
            uuid1="uuid-1",
            uuid2="uuid-2",
            name1="Test",
            name2="Test2",
            entity_type="Person",
            similarity_score=0.75,
        )

        assert candidate.match_reasons == []
