"""
Context relevance scoring for Klabautermann.

Computes relevance scores for context items based on recency, query similarity,
and connection strength. Used to prioritize context items and truncate
low-relevance content.

Reference: specs/architecture/MEMORY.md
Issue: #199 - Implement context relevance scoring
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from collections.abc import Callable


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ScoredItem:
    """A context item with its computed relevance score."""

    item: Any
    score: float
    score_breakdown: dict[str, float]


T = TypeVar("T")


# =============================================================================
# Scoring Functions
# =============================================================================


def compute_recency_score(
    created_at: float | None,
    decay_hours: float = 24.0,
) -> float:
    """
    Compute recency score with exponential decay.

    Items created recently score higher. Score decays exponentially
    over time based on the decay_hours parameter.

    Args:
        created_at: Unix timestamp when item was created
        decay_hours: Half-life for score decay (default 24 hours)

    Returns:
        Score between 0.0 and 1.0
    """
    if created_at is None:
        return 0.0

    now = datetime.now(UTC).timestamp()
    age_hours = (now - created_at) / 3600

    if age_hours < 0:
        return 1.0  # Future timestamps (shouldn't happen, but handle gracefully)

    # Exponential decay: score = e^(-age/decay)
    # This gives 0.5 at age = decay_hours * ln(2)
    return math.exp(-age_hours / decay_hours)


def compute_text_similarity_score(
    item_text: str,
    query_text: str,
) -> float:
    """
    Compute basic text similarity score using word overlap.

    This is a simple bag-of-words approach for basic relevance.
    For production use, consider using embeddings.

    Args:
        item_text: Text content of the item
        query_text: Query to match against

    Returns:
        Score between 0.0 and 1.0 based on word overlap
    """
    if not item_text or not query_text:
        return 0.0

    # Normalize and tokenize
    item_words = set(item_text.lower().split())
    query_words = set(query_text.lower().split())

    # Remove common stopwords
    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "up",
        "about",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "and",
        "but",
        "if",
        "or",
        "because",
        "as",
        "until",
        "while",
        "this",
        "that",
        "these",
        "those",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "it",
        "they",
        "them",
    }

    item_words -= stopwords
    query_words -= stopwords

    if not query_words:
        return 0.0

    # Jaccard similarity
    intersection = len(item_words & query_words)
    union = len(item_words | query_words)

    if union == 0:
        return 0.0

    return intersection / union


def compute_priority_score(
    priority: str | None,
) -> float:
    """
    Compute score based on priority level.

    Args:
        priority: Priority string (high, medium, low, or None)

    Returns:
        Score between 0.0 and 1.0
    """
    priority_map = {
        "high": 1.0,
        "critical": 1.0,
        "medium": 0.6,
        "normal": 0.6,
        "low": 0.3,
    }

    if priority is None:
        return 0.5  # Default to medium

    return priority_map.get(priority.lower(), 0.5)


def compute_connection_score(
    connection_count: int,
    max_connections: int = 10,
) -> float:
    """
    Compute score based on number of connections/relationships.

    Items with more connections are considered more central/important.

    Args:
        connection_count: Number of relationships
        max_connections: Cap for normalization

    Returns:
        Score between 0.0 and 1.0
    """
    if connection_count <= 0:
        return 0.0

    # Logarithmic scaling to prevent very connected items from dominating
    normalized = math.log(1 + connection_count) / math.log(1 + max_connections)
    return min(1.0, normalized)


# =============================================================================
# Main Scoring Functions
# =============================================================================


def score_context_items(
    items: list[T],
    query: str | None = None,
    text_extractor: Callable[[T], str] | None = None,
    timestamp_extractor: Callable[[T], float | None] | None = None,
    priority_extractor: Callable[[T], str | None] | None = None,
    connection_extractor: Callable[[T], int] | None = None,
    weights: dict[str, float] | None = None,
    trace_id: str | None = None,
) -> list[ScoredItem]:
    """
    Score a list of context items based on multiple factors.

    Combines recency, text similarity, priority, and connection scores
    with configurable weights.

    Args:
        items: List of context items to score
        query: Optional query for text similarity scoring
        text_extractor: Function to get text from an item
        timestamp_extractor: Function to get created_at from an item
        priority_extractor: Function to get priority from an item
        connection_extractor: Function to get connection count from an item
        weights: Weight for each scoring factor (default: equal weights)
        trace_id: Optional trace ID for logging

    Returns:
        List of ScoredItem sorted by score descending
    """
    logger.debug(
        f"[WHISPER] Scoring {len(items)} context items",
        extra={"trace_id": trace_id, "agent_name": "relevance_scoring"},
    )

    # Default weights
    default_weights = {
        "recency": 0.3,
        "similarity": 0.3,
        "priority": 0.2,
        "connections": 0.2,
    }
    weights = weights or default_weights

    scored_items: list[ScoredItem] = []

    for item in items:
        breakdown: dict[str, float] = {}

        # Recency score
        if timestamp_extractor:
            created_at = timestamp_extractor(item)
            breakdown["recency"] = compute_recency_score(created_at)
        else:
            breakdown["recency"] = 0.5  # Default to neutral

        # Text similarity score
        if query and text_extractor:
            item_text = text_extractor(item)
            breakdown["similarity"] = compute_text_similarity_score(item_text, query)
        else:
            breakdown["similarity"] = 0.5  # Default to neutral

        # Priority score
        if priority_extractor:
            priority = priority_extractor(item)
            breakdown["priority"] = compute_priority_score(priority)
        else:
            breakdown["priority"] = 0.5  # Default to neutral

        # Connection score
        if connection_extractor:
            connections = connection_extractor(item)
            breakdown["connections"] = compute_connection_score(connections)
        else:
            breakdown["connections"] = 0.5  # Default to neutral

        # Compute weighted total
        total_score = sum(weights.get(key, 0) * score for key, score in breakdown.items())

        # Normalize by total weight
        total_weight = sum(weights.get(key, 0) for key in breakdown)
        if total_weight > 0:
            total_score /= total_weight

        scored_items.append(
            ScoredItem(
                item=item,
                score=total_score,
                score_breakdown=breakdown,
            )
        )

    # Sort by score descending
    scored_items.sort(key=lambda x: x.score, reverse=True)

    logger.debug(
        f"[WHISPER] Scored {len(scored_items)} items, "
        f"top score: {scored_items[0].score if scored_items else 0:.3f}",
        extra={"trace_id": trace_id, "agent_name": "relevance_scoring"},
    )

    return scored_items


def truncate_by_relevance(
    scored_items: list[ScoredItem],
    max_items: int | None = None,
    min_score: float | None = None,
    trace_id: str | None = None,
) -> list[ScoredItem]:
    """
    Truncate scored items by count and/or minimum score.

    Args:
        scored_items: List of ScoredItem (should be pre-sorted by score)
        max_items: Maximum number of items to keep
        min_score: Minimum score threshold
        trace_id: Optional trace ID for logging

    Returns:
        Filtered list of ScoredItem
    """
    result = scored_items

    # Filter by minimum score
    if min_score is not None:
        result = [item for item in result if item.score >= min_score]
        logger.debug(
            f"[WHISPER] Filtered to {len(result)} items with score >= {min_score}",
            extra={"trace_id": trace_id, "agent_name": "relevance_scoring"},
        )

    # Limit by max items
    if max_items is not None and len(result) > max_items:
        result = result[:max_items]
        logger.debug(
            f"[WHISPER] Truncated to {max_items} items",
            extra={"trace_id": trace_id, "agent_name": "relevance_scoring"},
        )

    return result


def extract_items(scored_items: list[ScoredItem]) -> list[Any]:
    """
    Extract the original items from a list of ScoredItem.

    Args:
        scored_items: List of ScoredItem

    Returns:
        List of original items in score order
    """
    return [si.item for si in scored_items]


# =============================================================================
# Convenience Functions
# =============================================================================


def score_and_truncate(
    items: list[T],
    query: str | None = None,
    max_items: int | None = None,
    min_score: float | None = None,
    text_extractor: Callable[[T], str] | None = None,
    timestamp_extractor: Callable[[T], float | None] | None = None,
    trace_id: str | None = None,
) -> list[T]:
    """
    Score items and return truncated list of original items.

    Convenience function that combines scoring, truncation, and extraction.

    Args:
        items: List of items to score
        query: Optional query for text similarity
        max_items: Maximum items to return
        min_score: Minimum score threshold
        text_extractor: Function to get text from item
        timestamp_extractor: Function to get timestamp from item
        trace_id: Optional trace ID for logging

    Returns:
        List of original items, sorted by relevance and truncated
    """
    scored = score_context_items(
        items=items,
        query=query,
        text_extractor=text_extractor,
        timestamp_extractor=timestamp_extractor,
        trace_id=trace_id,
    )

    truncated = truncate_by_relevance(
        scored_items=scored,
        max_items=max_items,
        min_score=min_score,
        trace_id=trace_id,
    )

    return extract_items(truncated)


# =============================================================================
# Export
# =============================================================================

__all__ = [
    # Data Classes
    "ScoredItem",
    # Individual Scoring Functions
    "compute_connection_score",
    "compute_priority_score",
    "compute_recency_score",
    "compute_text_similarity_score",
    # Main Functions
    "extract_items",
    "score_and_truncate",
    "score_context_items",
    "truncate_by_relevance",
]
