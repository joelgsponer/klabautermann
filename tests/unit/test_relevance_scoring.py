"""
Unit tests for context relevance scoring module.

Tests scoring functions, truncation, and combined operations.
Issue: #199 - Implement context relevance scoring
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from klabautermann.memory.relevance_scoring import (
    ScoredItem,
    compute_connection_score,
    compute_priority_score,
    compute_recency_score,
    compute_text_similarity_score,
    extract_items,
    score_and_truncate,
    score_context_items,
    truncate_by_relevance,
)


# =============================================================================
# Test Data
# =============================================================================


@dataclass
class SampleItem:
    """Sample item for scoring tests."""

    name: str
    text: str
    created_at: float | None
    priority: str | None
    connections: int


# =============================================================================
# Test Individual Scoring Functions
# =============================================================================


class TestComputeRecencyScore:
    """Tests for recency score computation."""

    def test_recent_item_scores_high(self) -> None:
        """Test that recent items score close to 1.0."""
        now = datetime.now(UTC).timestamp()
        score = compute_recency_score(now)
        assert score > 0.95

    def test_old_item_scores_low(self) -> None:
        """Test that old items score low."""
        # 7 days ago with 24-hour decay
        old_time = datetime.now(UTC).timestamp() - (7 * 24 * 3600)
        score = compute_recency_score(old_time)
        assert score < 0.1

    def test_half_decay_time(self) -> None:
        """Test score at approximately half-life."""
        # At decay_hours, score should be ~0.37 (1/e)
        decay_hours = 24.0
        cutoff_time = datetime.now(UTC).timestamp() - (decay_hours * 3600)
        score = compute_recency_score(cutoff_time, decay_hours=decay_hours)
        assert 0.35 < score < 0.40

    def test_none_timestamp_returns_zero(self) -> None:
        """Test that None timestamp returns 0."""
        score = compute_recency_score(None)
        assert score == 0.0

    def test_future_timestamp_returns_one(self) -> None:
        """Test that future timestamp returns 1.0."""
        future = datetime.now(UTC).timestamp() + 3600
        score = compute_recency_score(future)
        assert score == 1.0


class TestComputeTextSimilarityScore:
    """Tests for text similarity score computation."""

    def test_identical_text_scores_high(self) -> None:
        """Test that identical text scores high."""
        text = "discuss budget planning meeting"
        score = compute_text_similarity_score(text, text)
        assert score > 0.5

    def test_overlapping_text_scores_medium(self) -> None:
        """Test that overlapping text scores medium."""
        item = "discuss the quarterly budget planning"
        query = "budget planning"
        score = compute_text_similarity_score(item, query)
        assert 0.2 < score < 0.8

    def test_no_overlap_scores_zero(self) -> None:
        """Test that completely different text scores zero."""
        item = "cats dogs pets animals"
        query = "budget finance money"
        score = compute_text_similarity_score(item, query)
        assert score == 0.0

    def test_empty_text_returns_zero(self) -> None:
        """Test that empty text returns 0."""
        assert compute_text_similarity_score("", "query") == 0.0
        assert compute_text_similarity_score("text", "") == 0.0

    def test_stopwords_are_ignored(self) -> None:
        """Test that stopwords don't affect similarity."""
        item = "the quick brown fox"
        query = "brown fox"
        score = compute_text_similarity_score(item, query)
        # Should match on "quick", "brown", "fox"
        assert score > 0.0


class TestComputePriorityScore:
    """Tests for priority score computation."""

    def test_high_priority(self) -> None:
        """Test high priority scores 1.0."""
        assert compute_priority_score("high") == 1.0
        assert compute_priority_score("critical") == 1.0

    def test_medium_priority(self) -> None:
        """Test medium priority scores 0.6."""
        assert compute_priority_score("medium") == 0.6
        assert compute_priority_score("normal") == 0.6

    def test_low_priority(self) -> None:
        """Test low priority scores 0.3."""
        assert compute_priority_score("low") == 0.3

    def test_none_priority_returns_default(self) -> None:
        """Test None priority returns default (0.5)."""
        assert compute_priority_score(None) == 0.5

    def test_unknown_priority_returns_default(self) -> None:
        """Test unknown priority returns default."""
        assert compute_priority_score("urgent") == 0.5


class TestComputeConnectionScore:
    """Tests for connection score computation."""

    def test_no_connections_returns_zero(self) -> None:
        """Test zero connections returns 0."""
        assert compute_connection_score(0) == 0.0

    def test_many_connections_scores_high(self) -> None:
        """Test many connections score high."""
        score = compute_connection_score(10, max_connections=10)
        assert score > 0.9

    def test_few_connections_scores_low(self) -> None:
        """Test few connections score lower."""
        score = compute_connection_score(1, max_connections=10)
        assert 0.2 < score < 0.4

    def test_capped_at_one(self) -> None:
        """Test score is capped at 1.0 for very connected items."""
        score = compute_connection_score(100, max_connections=10)
        assert score == 1.0


# =============================================================================
# Test Main Scoring Functions
# =============================================================================


class TestScoreContextItems:
    """Tests for the main scoring function."""

    @pytest.fixture
    def test_items(self) -> list[SampleItem]:
        """Create test items with different characteristics."""
        now = datetime.now(UTC).timestamp()
        return [
            SampleItem(
                name="recent_high",
                text="important budget meeting discussion",
                created_at=now - 3600,  # 1 hour ago
                priority="high",
                connections=5,
            ),
            SampleItem(
                name="old_low",
                text="random unrelated topic",
                created_at=now - (7 * 24 * 3600),  # 7 days ago
                priority="low",
                connections=1,
            ),
            SampleItem(
                name="recent_relevant",
                text="budget planning session notes",
                created_at=now - 1800,  # 30 minutes ago
                priority="medium",
                connections=3,
            ),
        ]

    def test_scores_items_by_recency(self, test_items: list[SampleItem]) -> None:
        """Test that items are scored and sorted."""
        scored = score_context_items(
            items=test_items,
            timestamp_extractor=lambda x: x.created_at,
        )

        assert len(scored) == 3
        # All items should have scores
        for item in scored:
            assert 0.0 <= item.score <= 1.0
            assert "recency" in item.score_breakdown

    def test_scores_with_query(self, test_items: list[SampleItem]) -> None:
        """Test scoring with text query."""
        scored = score_context_items(
            items=test_items,
            query="budget planning",
            text_extractor=lambda x: x.text,
        )

        # Item with "budget planning" in text should score higher on similarity
        assert scored[0].score_breakdown["similarity"] > 0

    def test_sorted_by_score_descending(self, test_items: list[SampleItem]) -> None:
        """Test that results are sorted by score descending."""
        scored = score_context_items(
            items=test_items,
            timestamp_extractor=lambda x: x.created_at,
        )

        scores = [item.score for item in scored]
        assert scores == sorted(scores, reverse=True)

    def test_custom_weights(self, test_items: list[SampleItem]) -> None:
        """Test with custom scoring weights."""
        scored = score_context_items(
            items=test_items,
            timestamp_extractor=lambda x: x.created_at,
            priority_extractor=lambda x: x.priority,
            weights={"recency": 0.0, "priority": 1.0, "similarity": 0.0, "connections": 0.0},
        )

        # High priority item should be first
        assert scored[0].item.name == "recent_high"

    def test_includes_breakdown(self, test_items: list[SampleItem]) -> None:
        """Test that score breakdown is included."""
        scored = score_context_items(
            items=test_items,
            query="test",
            text_extractor=lambda x: x.text,
            timestamp_extractor=lambda x: x.created_at,
            priority_extractor=lambda x: x.priority,
            connection_extractor=lambda x: x.connections,
        )

        for item in scored:
            assert "recency" in item.score_breakdown
            assert "similarity" in item.score_breakdown
            assert "priority" in item.score_breakdown
            assert "connections" in item.score_breakdown


class TestTruncateByRelevance:
    """Tests for truncation function."""

    @pytest.fixture
    def scored_items(self) -> list[ScoredItem]:
        """Create pre-scored items."""
        return [
            ScoredItem(item="A", score=0.9, score_breakdown={}),
            ScoredItem(item="B", score=0.7, score_breakdown={}),
            ScoredItem(item="C", score=0.5, score_breakdown={}),
            ScoredItem(item="D", score=0.3, score_breakdown={}),
            ScoredItem(item="E", score=0.1, score_breakdown={}),
        ]

    def test_truncate_by_max_items(self, scored_items: list[ScoredItem]) -> None:
        """Test truncation by max items."""
        result = truncate_by_relevance(scored_items, max_items=3)
        assert len(result) == 3
        assert result[0].item == "A"
        assert result[2].item == "C"

    def test_truncate_by_min_score(self, scored_items: list[ScoredItem]) -> None:
        """Test truncation by minimum score."""
        result = truncate_by_relevance(scored_items, min_score=0.5)
        assert len(result) == 3
        assert all(item.score >= 0.5 for item in result)

    def test_truncate_by_both(self, scored_items: list[ScoredItem]) -> None:
        """Test truncation by both max_items and min_score."""
        result = truncate_by_relevance(scored_items, max_items=2, min_score=0.5)
        assert len(result) == 2

    def test_no_truncation_when_all_pass(self, scored_items: list[ScoredItem]) -> None:
        """Test no truncation when all items pass criteria."""
        result = truncate_by_relevance(scored_items, max_items=10, min_score=0.0)
        assert len(result) == 5


class TestExtractItems:
    """Tests for extract_items function."""

    def test_extracts_original_items(self) -> None:
        """Test that original items are extracted."""
        scored = [
            ScoredItem(item="first", score=0.9, score_breakdown={}),
            ScoredItem(item="second", score=0.5, score_breakdown={}),
        ]

        result = extract_items(scored)

        assert result == ["first", "second"]

    def test_empty_list(self) -> None:
        """Test with empty list."""
        result = extract_items([])
        assert result == []


class TestScoreAndTruncate:
    """Tests for the convenience function."""

    def test_combines_operations(self) -> None:
        """Test that score_and_truncate combines all operations."""
        now = datetime.now(UTC).timestamp()
        items = [
            {"name": "old", "time": now - (7 * 24 * 3600)},
            {"name": "recent", "time": now - 3600},
            {"name": "medium", "time": now - (24 * 3600)},
        ]

        result = score_and_truncate(
            items=items,
            max_items=2,
            timestamp_extractor=lambda x: x["time"],  # type: ignore[index]
        )

        assert len(result) == 2
        # Recent should be first
        assert result[0]["name"] == "recent"

    def test_returns_original_type(self) -> None:
        """Test that original item types are preserved."""

        @dataclass
        class Custom:
            value: int

        items = [Custom(1), Custom(2), Custom(3)]

        result = score_and_truncate(items, max_items=2)

        assert all(isinstance(item, Custom) for item in result)
