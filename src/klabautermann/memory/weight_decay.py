"""
Relationship weight decay for Klabautermann.

Implements time-based decay of relationship weights in the knowledge graph.
Relationships that aren't accessed lose weight over time and can be
pruned when weight drops below threshold.

This helps keep the graph focused on active, relevant connections.

Reference: specs/architecture/MEMORY.md
Issue: #195 - Implement relationship weight decay
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Constants
# =============================================================================

# Default half-life for weight decay (30 days in seconds)
DEFAULT_HALF_LIFE_SECONDS = 30 * 24 * 60 * 60

# Default minimum weight before pruning
DEFAULT_MIN_WEIGHT = 0.1

# Default initial weight for new relationships
DEFAULT_INITIAL_WEIGHT = 1.0

# Weight boost when a relationship is accessed
DEFAULT_ACCESS_BOOST = 0.1


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RelationshipWeight:
    """Weight information for a relationship."""

    relationship_id: int
    relationship_type: str
    source_name: str | None
    target_name: str | None
    current_weight: float
    last_accessed: float | None
    days_since_access: float


@dataclass
class DecayResult:
    """Result of a decay operation."""

    relationships_updated: int
    relationships_pruned: int
    average_weight_before: float
    average_weight_after: float


# =============================================================================
# Weight Calculation
# =============================================================================


def calculate_decayed_weight(
    original_weight: float,
    last_accessed: float | None,
    half_life_seconds: float = DEFAULT_HALF_LIFE_SECONDS,
) -> float:
    """
    Calculate current weight after decay.

    Uses exponential decay: weight = original * 2^(-time/half_life)

    Args:
        original_weight: Weight at time of last access
        last_accessed: Unix timestamp of last access
        half_life_seconds: Time for weight to decay by half

    Returns:
        Current decayed weight (between 0 and original_weight)
    """
    if last_accessed is None:
        return original_weight

    now = time.time()
    elapsed_seconds = now - last_accessed

    if elapsed_seconds <= 0:
        return original_weight

    # Exponential decay: weight = original * 2^(-elapsed/half_life)
    decay_factor = math.pow(2, -elapsed_seconds / half_life_seconds)
    return original_weight * decay_factor


def calculate_boosted_weight(
    current_weight: float,
    boost: float = DEFAULT_ACCESS_BOOST,
    max_weight: float = DEFAULT_INITIAL_WEIGHT,
) -> float:
    """
    Calculate boosted weight when relationship is accessed.

    Weight increases but is capped at max_weight.

    Args:
        current_weight: Current relationship weight
        boost: Amount to boost weight by
        max_weight: Maximum allowed weight

    Returns:
        New weight (capped at max_weight)
    """
    return min(max_weight, current_weight + boost)


# =============================================================================
# Database Operations
# =============================================================================


async def update_relationship_access(
    neo4j: Neo4jClient,
    source_uuid: str,
    target_uuid: str,
    relationship_type: str,
    trace_id: str | None = None,
) -> bool:
    """
    Update last_accessed timestamp and boost weight for a relationship.

    Call this when a relationship is used/accessed to keep it active.

    Args:
        neo4j: Connected Neo4jClient instance
        source_uuid: UUID of source node
        target_uuid: UUID of target node
        relationship_type: Type of relationship (e.g., WORKS_AT, KNOWS)
        trace_id: Optional trace ID for logging

    Returns:
        True if relationship was found and updated, False otherwise
    """
    now = time.time()

    logger.debug(
        f"[WHISPER] Updating access for {relationship_type} relationship",
        extra={"trace_id": trace_id, "agent_name": "weight_decay"},
    )

    query = f"""
    MATCH (s {{uuid: $source_uuid}})-[r:{relationship_type}]->(t {{uuid: $target_uuid}})
    SET r.last_accessed = $now,
        r.weight = CASE
            WHEN r.weight IS NULL THEN $initial_weight
            ELSE CASE
                WHEN r.weight + $boost > $max_weight THEN $max_weight
                ELSE r.weight + $boost
            END
        END,
        r.access_count = COALESCE(r.access_count, 0) + 1
    RETURN r.weight as new_weight
    """

    result = await neo4j.execute_query(
        query,
        {
            "source_uuid": source_uuid,
            "target_uuid": target_uuid,
            "now": now,
            "initial_weight": DEFAULT_INITIAL_WEIGHT,
            "boost": DEFAULT_ACCESS_BOOST,
            "max_weight": DEFAULT_INITIAL_WEIGHT,
        },
        trace_id=trace_id,
    )

    updated = len(result) > 0

    if updated:
        new_weight = result[0]["new_weight"]
        logger.debug(
            f"[WHISPER] Updated relationship weight to {new_weight:.3f}",
            extra={"trace_id": trace_id, "agent_name": "weight_decay"},
        )

    return updated


async def apply_decay_to_relationships(
    neo4j: Neo4jClient,
    relationship_types: list[str] | None = None,
    half_life_days: float = 30.0,
    min_weight: float = DEFAULT_MIN_WEIGHT,
    trace_id: str | None = None,
) -> DecayResult:
    """
    Apply weight decay to relationships based on time since last access.

    Updates weight property on relationships and removes those below min_weight.

    Args:
        neo4j: Connected Neo4jClient instance
        relationship_types: List of relationship types to decay (None = all)
        half_life_days: Days for weight to decay by half
        min_weight: Minimum weight before relationship is pruned
        trace_id: Optional trace ID for logging

    Returns:
        DecayResult with statistics about the operation
    """
    half_life_seconds = half_life_days * 24 * 60 * 60
    now = time.time()

    logger.info(
        f"[CHART] Applying weight decay (half-life: {half_life_days} days)",
        extra={"trace_id": trace_id, "agent_name": "weight_decay"},
    )

    # Build relationship type filter
    type_filter = ""
    if relationship_types:
        types_str = "|".join(relationship_types)
        type_filter = f":{types_str}"

    # Step 1: Get average weight before decay
    pre_query = f"""
    MATCH ()-[r{type_filter}]->()
    WHERE r.weight IS NOT NULL
    RETURN avg(r.weight) as avg_weight, count(r) as rel_count
    """

    pre_result = await neo4j.execute_query(pre_query, {}, trace_id=trace_id)
    avg_before = pre_result[0]["avg_weight"] if pre_result and pre_result[0]["avg_weight"] else 1.0

    # Step 2: Apply decay to all relationships
    # Using the formula: new_weight = weight * 2^(-(now - last_accessed) / half_life)
    decay_query = f"""
    MATCH ()-[r{type_filter}]->()
    WHERE r.last_accessed IS NOT NULL
    WITH r,
         r.weight * (0.5 ^ (($now - r.last_accessed) / $half_life)) as decayed_weight
    SET r.weight = decayed_weight
    RETURN count(r) as updated
    """

    decay_result = await neo4j.execute_query(
        decay_query,
        {"now": now, "half_life": half_life_seconds},
        trace_id=trace_id,
    )

    updated_count = decay_result[0]["updated"] if decay_result else 0

    # Step 3: Prune relationships below minimum weight
    prune_query = f"""
    MATCH ()-[r{type_filter}]->()
    WHERE r.weight IS NOT NULL AND r.weight < $min_weight
    WITH r, type(r) as rel_type
    DELETE r
    RETURN count(r) as pruned
    """

    prune_result = await neo4j.execute_query(
        prune_query,
        {"min_weight": min_weight},
        trace_id=trace_id,
    )

    pruned_count = prune_result[0]["pruned"] if prune_result else 0

    # Step 4: Get average weight after decay
    post_result = await neo4j.execute_query(pre_query, {}, trace_id=trace_id)
    avg_after = (
        post_result[0]["avg_weight"] if post_result and post_result[0]["avg_weight"] else 0.0
    )

    result = DecayResult(
        relationships_updated=updated_count,
        relationships_pruned=pruned_count,
        average_weight_before=avg_before,
        average_weight_after=avg_after,
    )

    logger.info(
        f"[BEACON] Weight decay complete: {updated_count} updated, {pruned_count} pruned",
        extra={
            "trace_id": trace_id,
            "agent_name": "weight_decay",
            "updated": updated_count,
            "pruned": pruned_count,
        },
    )

    return result


async def get_low_weight_relationships(
    neo4j: Neo4jClient,
    threshold: float = 0.3,
    limit: int = 100,
    trace_id: str | None = None,
) -> list[RelationshipWeight]:
    """
    Get relationships with weight below threshold.

    Useful for reviewing relationships that may be pruned.

    Args:
        neo4j: Connected Neo4jClient instance
        threshold: Weight threshold
        limit: Maximum number of relationships to return
        trace_id: Optional trace ID for logging

    Returns:
        List of RelationshipWeight objects
    """
    now = time.time()

    query = """
    MATCH (s)-[r]->(t)
    WHERE r.weight IS NOT NULL AND r.weight < $threshold
    RETURN id(r) as rel_id,
           type(r) as rel_type,
           s.name as source_name,
           t.name as target_name,
           r.weight as weight,
           r.last_accessed as last_accessed
    ORDER BY r.weight ASC
    LIMIT $limit
    """

    result = await neo4j.execute_query(
        query,
        {"threshold": threshold, "limit": limit},
        trace_id=trace_id,
    )

    relationships = []
    for row in result:
        last_accessed = row.get("last_accessed")
        days_since = (now - last_accessed) / (24 * 60 * 60) if last_accessed else 0

        relationships.append(
            RelationshipWeight(
                relationship_id=row["rel_id"],
                relationship_type=row["rel_type"],
                source_name=row.get("source_name"),
                target_name=row.get("target_name"),
                current_weight=row.get("weight") or 0.0,
                last_accessed=last_accessed,
                days_since_access=days_since,
            )
        )

    logger.debug(
        f"[WHISPER] Found {len(relationships)} relationships below weight {threshold}",
        extra={"trace_id": trace_id, "agent_name": "weight_decay"},
    )

    return relationships


async def initialize_relationship_weights(
    neo4j: Neo4jClient,
    relationship_types: list[str] | None = None,
    initial_weight: float = DEFAULT_INITIAL_WEIGHT,
    trace_id: str | None = None,
) -> int:
    """
    Initialize weight and last_accessed for relationships that don't have them.

    Should be run once to set up existing relationships for decay.

    Args:
        neo4j: Connected Neo4jClient instance
        relationship_types: List of relationship types to initialize (None = all)
        initial_weight: Initial weight value
        trace_id: Optional trace ID for logging

    Returns:
        Number of relationships initialized
    """
    now = time.time()

    type_filter = ""
    if relationship_types:
        types_str = "|".join(relationship_types)
        type_filter = f":{types_str}"

    query = f"""
    MATCH ()-[r{type_filter}]->()
    WHERE r.weight IS NULL
    SET r.weight = $initial_weight,
        r.last_accessed = COALESCE(r.created_at, $now),
        r.access_count = 0
    RETURN count(r) as initialized
    """

    result = await neo4j.execute_query(
        query,
        {"initial_weight": initial_weight, "now": now},
        trace_id=trace_id,
    )

    initialized: int = int(result[0]["initialized"]) if result else 0

    logger.info(
        f"[BEACON] Initialized weights for {initialized} relationships",
        extra={"trace_id": trace_id, "agent_name": "weight_decay"},
    )

    return initialized


async def get_weight_statistics(
    neo4j: Neo4jClient,
    trace_id: str | None = None,
) -> dict:
    """
    Get statistics about relationship weights.

    Args:
        neo4j: Connected Neo4jClient instance
        trace_id: Optional trace ID for logging

    Returns:
        Dictionary with weight statistics
    """
    query = """
    MATCH ()-[r]->()
    WHERE r.weight IS NOT NULL
    RETURN
        count(r) as total_relationships,
        avg(r.weight) as avg_weight,
        min(r.weight) as min_weight,
        max(r.weight) as max_weight,
        sum(CASE WHEN r.weight < 0.3 THEN 1 ELSE 0 END) as low_weight_count,
        sum(CASE WHEN r.weight >= 0.7 THEN 1 ELSE 0 END) as high_weight_count
    """

    result = await neo4j.execute_query(query, {}, trace_id=trace_id)

    if not result:
        return {
            "total_relationships": 0,
            "avg_weight": 0.0,
            "min_weight": 0.0,
            "max_weight": 0.0,
            "low_weight_count": 0,
            "high_weight_count": 0,
        }

    row = result[0]
    return {
        "total_relationships": row.get("total_relationships") or 0,
        "avg_weight": row.get("avg_weight") or 0.0,
        "min_weight": row.get("min_weight") or 0.0,
        "max_weight": row.get("max_weight") or 0.0,
        "low_weight_count": row.get("low_weight_count") or 0,
        "high_weight_count": row.get("high_weight_count") or 0,
    }


# =============================================================================
# Export
# =============================================================================

__all__ = [
    # Constants
    "DEFAULT_ACCESS_BOOST",
    "DEFAULT_HALF_LIFE_SECONDS",
    "DEFAULT_INITIAL_WEIGHT",
    "DEFAULT_MIN_WEIGHT",
    # Data Classes
    "DecayResult",
    "RelationshipWeight",
    # Database Operations
    "apply_decay_to_relationships",
    # Calculation Functions
    "calculate_boosted_weight",
    "calculate_decayed_weight",
    "get_low_weight_relationships",
    "get_weight_statistics",
    "initialize_relationship_weights",
    "update_relationship_access",
]
