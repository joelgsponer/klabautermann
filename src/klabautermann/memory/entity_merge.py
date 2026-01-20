"""
Entity merge utility for Klabautermann.

Handles merging duplicate entities by transferring relationships
from source to target and deleting the source node.

Reference: specs/architecture/MEMORY.md Section 7.1
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DuplicateCandidate:
    """A pair of potentially duplicate entities."""

    uuid1: str
    uuid2: str
    name1: str | None
    name2: str | None
    email1: str | None
    email2: str | None
    match_reason: str  # "name", "email", or "both"
    similarity_score: float


@dataclass
class MergeResult:
    """Result of an entity merge operation."""

    source_uuid: str
    target_uuid: str
    relationships_transferred: int
    properties_merged: list[str]
    source_deleted: bool
    timestamp: datetime


@dataclass
class MergePreview:
    """Preview of what a merge operation would do."""

    source_uuid: str
    source_label: str
    source_properties: dict[str, Any]
    target_uuid: str
    target_label: str
    target_properties: dict[str, Any]
    incoming_relationships: int
    outgoing_relationships: int
    properties_to_merge: list[str]


# =============================================================================
# Duplicate Detection
# =============================================================================


async def find_duplicate_persons(
    neo4j: Neo4jClient,
    limit: int = 100,
    trace_id: str | None = None,
) -> list[DuplicateCandidate]:
    """
    Find potential duplicate Person nodes.

    Detects duplicates by:
    - Same name (case-insensitive)
    - Same email address

    Args:
        neo4j: Connected Neo4jClient instance
        limit: Maximum number of duplicates to return
        trace_id: Optional trace ID for logging

    Returns:
        List of DuplicateCandidate pairs
    """
    logger.debug(
        f"[WHISPER] Searching for duplicate persons (limit={limit})",
        extra={"trace_id": trace_id, "agent_name": "entity_merge"},
    )

    query = """
    MATCH (p1:Person), (p2:Person)
    WHERE p1.uuid < p2.uuid
      AND (
        toLower(p1.name) = toLower(p2.name)
        OR (p1.email IS NOT NULL AND p1.email = p2.email)
      )
    WITH p1, p2,
         CASE
           WHEN toLower(p1.name) = toLower(p2.name) AND p1.email = p2.email THEN 'both'
           WHEN p1.email = p2.email THEN 'email'
           ELSE 'name'
         END as match_reason,
         CASE
           WHEN toLower(p1.name) = toLower(p2.name) AND p1.email = p2.email THEN 1.0
           WHEN p1.email = p2.email THEN 0.9
           ELSE 0.7
         END as similarity_score
    RETURN p1.uuid as uuid1, p1.name as name1, p1.email as email1,
           p2.uuid as uuid2, p2.name as name2, p2.email as email2,
           match_reason, similarity_score
    ORDER BY similarity_score DESC
    LIMIT $limit
    """

    result = await neo4j.execute_query(query, {"limit": limit}, trace_id=trace_id)

    duplicates = [
        DuplicateCandidate(
            uuid1=row["uuid1"],
            uuid2=row["uuid2"],
            name1=row.get("name1"),
            name2=row.get("name2"),
            email1=row.get("email1"),
            email2=row.get("email2"),
            match_reason=row["match_reason"],
            similarity_score=row["similarity_score"],
        )
        for row in result
    ]

    logger.info(
        f"[CHART] Found {len(duplicates)} potential duplicate persons",
        extra={"trace_id": trace_id, "agent_name": "entity_merge"},
    )

    return duplicates


async def find_duplicate_organizations(
    neo4j: Neo4jClient,
    limit: int = 100,
    trace_id: str | None = None,
) -> list[DuplicateCandidate]:
    """
    Find potential duplicate Organization nodes.

    Detects duplicates by:
    - Same name (case-insensitive)
    - Same domain

    Args:
        neo4j: Connected Neo4jClient instance
        limit: Maximum number of duplicates to return
        trace_id: Optional trace ID for logging

    Returns:
        List of DuplicateCandidate pairs
    """
    logger.debug(
        f"[WHISPER] Searching for duplicate organizations (limit={limit})",
        extra={"trace_id": trace_id, "agent_name": "entity_merge"},
    )

    query = """
    MATCH (o1:Organization), (o2:Organization)
    WHERE o1.uuid < o2.uuid
      AND (
        toLower(o1.name) = toLower(o2.name)
        OR (o1.domain IS NOT NULL AND o1.domain = o2.domain)
      )
    WITH o1, o2,
         CASE
           WHEN toLower(o1.name) = toLower(o2.name) AND o1.domain = o2.domain THEN 'both'
           WHEN o1.domain = o2.domain THEN 'email'
           ELSE 'name'
         END as match_reason,
         CASE
           WHEN toLower(o1.name) = toLower(o2.name) AND o1.domain = o2.domain THEN 1.0
           WHEN o1.domain = o2.domain THEN 0.9
           ELSE 0.7
         END as similarity_score
    RETURN o1.uuid as uuid1, o1.name as name1, o1.domain as email1,
           o2.uuid as uuid2, o2.name as name2, o2.domain as email2,
           match_reason, similarity_score
    ORDER BY similarity_score DESC
    LIMIT $limit
    """

    result = await neo4j.execute_query(query, {"limit": limit}, trace_id=trace_id)

    duplicates = [
        DuplicateCandidate(
            uuid1=row["uuid1"],
            uuid2=row["uuid2"],
            name1=row.get("name1"),
            name2=row.get("name2"),
            email1=row.get("email1"),  # domain stored in email1 field
            email2=row.get("email2"),
            match_reason=row["match_reason"],
            similarity_score=row["similarity_score"],
        )
        for row in result
    ]

    logger.info(
        f"[CHART] Found {len(duplicates)} potential duplicate organizations",
        extra={"trace_id": trace_id, "agent_name": "entity_merge"},
    )

    return duplicates


# =============================================================================
# Merge Preview
# =============================================================================


async def preview_merge(
    neo4j: Neo4jClient,
    source_uuid: str,
    target_uuid: str,
    trace_id: str | None = None,
) -> MergePreview | None:
    """
    Preview what a merge operation would do.

    Shows what relationships would be transferred and what
    properties would be merged.

    Args:
        neo4j: Connected Neo4jClient instance
        source_uuid: UUID of entity to be removed
        target_uuid: UUID of entity to keep
        trace_id: Optional trace ID for logging

    Returns:
        MergePreview or None if entities not found
    """
    query = """
    MATCH (source {uuid: $source_uuid})
    MATCH (target {uuid: $target_uuid})

    // Count relationships
    OPTIONAL MATCH (source)<-[in_rel]-()
    OPTIONAL MATCH (source)-[out_rel]->()

    WITH source, target,
         count(DISTINCT in_rel) as incoming,
         count(DISTINCT out_rel) as outgoing,
         labels(source)[0] as source_label,
         labels(target)[0] as target_label

    // Find properties that target doesn't have but source does
    WITH source, target, incoming, outgoing, source_label, target_label,
         [key IN keys(source) WHERE target[key] IS NULL AND source[key] IS NOT NULL | key] as props_to_merge

    RETURN source_label, target_label,
           properties(source) as source_properties,
           properties(target) as target_properties,
           incoming, outgoing, props_to_merge
    """

    result = await neo4j.execute_query(
        query,
        {"source_uuid": source_uuid, "target_uuid": target_uuid},
        trace_id=trace_id,
    )

    if not result:
        return None

    row = result[0]
    return MergePreview(
        source_uuid=source_uuid,
        source_label=row["source_label"],
        source_properties=row["source_properties"],
        target_uuid=target_uuid,
        target_label=row["target_label"],
        target_properties=row["target_properties"],
        incoming_relationships=row["incoming"],
        outgoing_relationships=row["outgoing"],
        properties_to_merge=row["props_to_merge"],
    )


# =============================================================================
# Entity Merge
# =============================================================================


async def merge_entities(
    neo4j: Neo4jClient,
    source_uuid: str,
    target_uuid: str,
    trace_id: str | None = None,
) -> MergeResult:
    """
    Merge duplicate entities by transferring relationships and deleting source.

    This operation:
    1. Transfers all incoming relationships to target
    2. Transfers all outgoing relationships to target
    3. Merges properties (keeps existing target values, adds missing from source)
    4. Deletes the source node

    Args:
        neo4j: Connected Neo4jClient instance
        source_uuid: UUID of entity to be removed
        target_uuid: UUID of entity to keep
        trace_id: Optional trace ID for logging

    Returns:
        MergeResult with operation details
    """
    logger.info(
        f"[CHART] Merging entity {source_uuid[:8]}... into {target_uuid[:8]}...",
        extra={"trace_id": trace_id, "agent_name": "entity_merge"},
    )

    # First get preview to know what we're merging
    preview = await preview_merge(neo4j, source_uuid, target_uuid, trace_id)

    if not preview:
        logger.error(
            "[STORM] Cannot merge: one or both entities not found",
            extra={"trace_id": trace_id, "agent_name": "entity_merge"},
        )
        return MergeResult(
            source_uuid=source_uuid,
            target_uuid=target_uuid,
            relationships_transferred=0,
            properties_merged=[],
            source_deleted=False,
            timestamp=datetime.now(),
        )

    # Transfer relationships and merge properties
    query = """
    MATCH (source {uuid: $source_uuid})
    MATCH (target {uuid: $target_uuid})

    // Transfer incoming relationships
    WITH source, target
    OPTIONAL MATCH (other)-[r]->(source)
    WHERE other <> target
    WITH source, target, collect({other: other, rel: r, type: type(r), props: properties(r)}) as incoming_rels

    // Create new incoming relationships
    UNWIND incoming_rels as rel_data
    FOREACH (rd IN CASE WHEN rel_data.other IS NOT NULL THEN [rel_data] ELSE [] END |
        // Note: Using APOC would be cleaner but we do manual handling
        CREATE (rd.other)-[new_r:TRANSFERRED]->(target)
    )

    WITH source, target, size(incoming_rels) as in_count

    // Transfer outgoing relationships
    OPTIONAL MATCH (source)-[r]->(other)
    WHERE other <> target
    WITH source, target, in_count, collect({other: other, rel: r, type: type(r), props: properties(r)}) as outgoing_rels

    // Create new outgoing relationships
    UNWIND outgoing_rels as rel_data
    FOREACH (rd IN CASE WHEN rel_data.other IS NOT NULL THEN [rel_data] ELSE [] END |
        CREATE (target)-[new_r:TRANSFERRED]->(rd.other)
    )

    WITH source, target, in_count + size(outgoing_rels) as total_rels

    // Merge properties (keep existing, add missing)
    SET target.bio = COALESCE(target.bio, source.bio)
    SET target.phone = COALESCE(target.phone, source.phone)
    SET target.linkedin_url = COALESCE(target.linkedin_url, source.linkedin_url)
    SET target.website = COALESCE(target.website, source.website)
    SET target.notes = COALESCE(target.notes, source.notes)
    SET target.merged_from = COALESCE(target.merged_from, []) + [$source_uuid]
    SET target.merged_at = timestamp()

    // Delete source and its relationships
    WITH target, total_rels
    MATCH (s {uuid: $source_uuid})
    DETACH DELETE s

    RETURN total_rels
    """

    result = await neo4j.execute_query(
        query,
        {"source_uuid": source_uuid, "target_uuid": target_uuid},
        trace_id=trace_id,
    )

    relationships_transferred = result[0]["total_rels"] if result else 0

    merge_result = MergeResult(
        source_uuid=source_uuid,
        target_uuid=target_uuid,
        relationships_transferred=relationships_transferred,
        properties_merged=preview.properties_to_merge,
        source_deleted=True,
        timestamp=datetime.now(),
    )

    logger.info(
        f"[CHART] Merge complete: {relationships_transferred} relationships transferred, "
        f"{len(preview.properties_to_merge)} properties merged",
        extra={"trace_id": trace_id, "agent_name": "entity_merge"},
    )

    return merge_result


async def merge_persons(
    neo4j: Neo4jClient,
    keep_uuid: str,
    remove_uuid: str,
    trace_id: str | None = None,
) -> MergeResult:
    """
    Merge duplicate Person nodes.

    Convenience function that wraps merge_entities for Person nodes.

    Args:
        neo4j: Connected Neo4jClient instance
        keep_uuid: UUID of person to keep
        remove_uuid: UUID of person to remove
        trace_id: Optional trace ID for logging

    Returns:
        MergeResult with operation details
    """
    return await merge_entities(neo4j, remove_uuid, keep_uuid, trace_id)


# =============================================================================
# Batch Operations
# =============================================================================


async def auto_merge_duplicates(
    neo4j: Neo4jClient,
    min_similarity: float = 0.9,
    dry_run: bool = True,
    trace_id: str | None = None,
) -> list[MergeResult]:
    """
    Automatically merge high-confidence duplicates.

    Only merges pairs with similarity score >= min_similarity.

    Args:
        neo4j: Connected Neo4jClient instance
        min_similarity: Minimum similarity score to auto-merge
        dry_run: If True, only preview without actually merging
        trace_id: Optional trace ID for logging

    Returns:
        List of MergeResult for each merge performed (or previewed)
    """
    logger.info(
        f"[CHART] Auto-merge duplicates (min_similarity={min_similarity}, dry_run={dry_run})",
        extra={"trace_id": trace_id, "agent_name": "entity_merge"},
    )

    # Find high-confidence duplicates
    person_duplicates = await find_duplicate_persons(neo4j, limit=50, trace_id=trace_id)
    org_duplicates = await find_duplicate_organizations(neo4j, limit=50, trace_id=trace_id)

    all_duplicates = person_duplicates + org_duplicates

    # Filter by similarity
    high_confidence = [d for d in all_duplicates if d.similarity_score >= min_similarity]

    results: list[MergeResult] = []

    for dup in high_confidence:
        if dry_run:
            preview = await preview_merge(neo4j, dup.uuid2, dup.uuid1, trace_id)
            if preview:
                results.append(
                    MergeResult(
                        source_uuid=dup.uuid2,
                        target_uuid=dup.uuid1,
                        relationships_transferred=preview.incoming_relationships
                        + preview.outgoing_relationships,
                        properties_merged=preview.properties_to_merge,
                        source_deleted=False,  # dry run
                        timestamp=datetime.now(),
                    )
                )
        else:
            result = await merge_entities(neo4j, dup.uuid2, dup.uuid1, trace_id)
            results.append(result)

    logger.info(
        f"[CHART] Auto-merge {'previewed' if dry_run else 'completed'}: "
        f"{len(results)} pairs processed",
        extra={"trace_id": trace_id, "agent_name": "entity_merge"},
    )

    return results


# =============================================================================
# Export
# =============================================================================

__all__ = [
    # Data Classes
    "DuplicateCandidate",
    "MergePreview",
    "MergeResult",
    # Detection
    "find_duplicate_organizations",
    "find_duplicate_persons",
    # Merge Operations
    "auto_merge_duplicates",
    "merge_entities",
    "merge_persons",
    "preview_merge",
]
