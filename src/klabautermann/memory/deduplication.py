"""
Entity deduplication for Klabautermann knowledge graph.

Detects and merges duplicate Person and Organization nodes using
similarity scoring based on name fuzzy matching and property overlap.

Reference: specs/architecture/MEMORY.md Section 7.1
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rapidfuzz import fuzz

from klabautermann.core.logger import logger
from klabautermann.core.models import DuplicateCandidate


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# ===========================================================================
# Duplicate Detection
# ===========================================================================


async def find_duplicate_persons(
    neo4j: Neo4jClient,
    min_score: float = 0.7,
    trace_id: str | None = None,
) -> list[DuplicateCandidate]:
    """
    Find potential duplicate Person nodes.

    Detects duplicates using:
    1. Exact email match (score = 1.0)
    2. Email domain match (score = 0.5)
    3. Name similarity using fuzzy matching (score = 0.0-1.0)

    Args:
        neo4j: Connected Neo4jClient instance
        min_score: Minimum similarity score to return (0.0-1.0)
        trace_id: Optional trace ID for logging

    Returns:
        List of DuplicateCandidate objects with similarity scores
    """
    logger.info(
        f"[CHART] Finding duplicate persons (min_score={min_score})",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    candidates: list[DuplicateCandidate] = []

    # Find exact email matches
    email_query = """
    MATCH (p1:Person), (p2:Person)
    WHERE p1.uuid < p2.uuid
      AND p1.email IS NOT NULL
      AND p2.email IS NOT NULL
      AND p1.email = p2.email
    RETURN p1.uuid as uuid1, p1.name as name1, p1.email as email1,
           p2.uuid as uuid2, p2.name as name2, p2.email as email2
    """

    email_records = await neo4j.execute_read(email_query, trace_id=trace_id)

    for record in email_records:
        candidates.append(
            DuplicateCandidate(
                uuid1=record["uuid1"],
                uuid2=record["uuid2"],
                name1=record["name1"],
                name2=record["name2"],
                entity_type="Person",
                similarity_score=1.0,
                match_reasons=["same_email"],
            )
        )

    logger.debug(
        f"[WHISPER] Found {len(candidates)} exact email matches",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    # Find email domain matches (e.g., john@acme.com and jane@acme.com)
    domain_query = """
    MATCH (p1:Person), (p2:Person)
    WHERE p1.uuid < p2.uuid
      AND p1.email IS NOT NULL
      AND p2.email IS NOT NULL
      AND p1.email <> p2.email
      AND split(p1.email, '@')[1] = split(p2.email, '@')[1]
    RETURN p1.uuid as uuid1, p1.name as name1, p1.email as email1,
           p2.uuid as uuid2, p2.name as name2, p2.email as email2
    """

    domain_records = await neo4j.execute_read(domain_query, trace_id=trace_id)

    for record in domain_records:
        # Check if already in candidates (from email match)
        if _already_candidate(candidates, record["uuid1"], record["uuid2"]):
            continue

        # Calculate name similarity for domain matches
        name_similarity = fuzz.ratio(record["name1"].lower(), record["name2"].lower()) / 100.0

        # Combined score: domain match (0.5) + name similarity (0.0-1.0) / 2
        combined_score = (0.5 + name_similarity) / 2

        if combined_score >= min_score:
            candidates.append(
                DuplicateCandidate(
                    uuid1=record["uuid1"],
                    uuid2=record["uuid2"],
                    name1=record["name1"],
                    name2=record["name2"],
                    entity_type="Person",
                    similarity_score=combined_score,
                    match_reasons=["same_email_domain", "similar_name"],
                )
            )

    logger.debug(
        f"[WHISPER] Found {len(candidates) - len(email_records)} domain matches",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    # Find similar names
    name_query = """
    MATCH (p:Person)
    WHERE p.name IS NOT NULL
    RETURN p.uuid as uuid, p.name as name, p.email as email
    ORDER BY p.name
    """

    name_records = await neo4j.execute_read(name_query, trace_id=trace_id)

    # Compare all pairs (O(n^2) - acceptable for person counts in the hundreds)
    for i, p1 in enumerate(name_records):
        for p2 in name_records[i + 1 :]:
            # Skip if already in candidates
            if _already_candidate(candidates, p1["uuid"], p2["uuid"]):
                continue

            # Calculate name similarity
            name_similarity = fuzz.ratio(p1["name"].lower(), p2["name"].lower()) / 100.0

            if name_similarity >= min_score:
                reasons = ["similar_name"]

                # Boost score if emails exist and match exactly
                if p1.get("email") and p2.get("email") and p1["email"] == p2["email"]:
                    name_similarity = 1.0
                    reasons = ["same_email", "similar_name"]

                candidates.append(
                    DuplicateCandidate(
                        uuid1=p1["uuid"],
                        uuid2=p2["uuid"],
                        name1=p1["name"],
                        name2=p2["name"],
                        entity_type="Person",
                        similarity_score=name_similarity,
                        match_reasons=reasons,
                    )
                )

    logger.info(
        f"[BEACON] Found {len(candidates)} duplicate person candidates",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    return candidates


async def find_duplicate_organizations(
    neo4j: Neo4jClient,
    min_score: float = 0.7,
    trace_id: str | None = None,
) -> list[DuplicateCandidate]:
    """
    Find potential duplicate Organization nodes.

    Detects duplicates using:
    1. Exact domain match (score = 1.0)
    2. Name similarity using fuzzy matching (score = 0.0-1.0)

    Args:
        neo4j: Connected Neo4jClient instance
        min_score: Minimum similarity score to return (0.0-1.0)
        trace_id: Optional trace ID for logging

    Returns:
        List of DuplicateCandidate objects with similarity scores
    """
    logger.info(
        f"[CHART] Finding duplicate organizations (min_score={min_score})",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    candidates: list[DuplicateCandidate] = []

    # Find exact domain matches
    domain_query = """
    MATCH (o1:Organization), (o2:Organization)
    WHERE o1.uuid < o2.uuid
      AND o1.domain IS NOT NULL
      AND o2.domain IS NOT NULL
      AND o1.domain = o2.domain
    RETURN o1.uuid as uuid1, o1.name as name1, o1.domain as domain1,
           o2.uuid as uuid2, o2.name as name2, o2.domain as domain2
    """

    domain_records = await neo4j.execute_read(domain_query, trace_id=trace_id)

    for record in domain_records:
        candidates.append(
            DuplicateCandidate(
                uuid1=record["uuid1"],
                uuid2=record["uuid2"],
                name1=record["name1"],
                name2=record["name2"],
                entity_type="Organization",
                similarity_score=1.0,
                match_reasons=["same_domain"],
            )
        )

    logger.debug(
        f"[WHISPER] Found {len(candidates)} exact domain matches",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    # Find similar names
    name_query = """
    MATCH (o:Organization)
    WHERE o.name IS NOT NULL
    RETURN o.uuid as uuid, o.name as name, o.domain as domain
    ORDER BY o.name
    """

    name_records = await neo4j.execute_read(name_query, trace_id=trace_id)

    # Compare all pairs
    for i, o1 in enumerate(name_records):
        for o2 in name_records[i + 1 :]:
            # Skip if already in candidates
            if _already_candidate(candidates, o1["uuid"], o2["uuid"]):
                continue

            # Calculate name similarity
            name_similarity = fuzz.ratio(o1["name"].lower(), o2["name"].lower()) / 100.0

            if name_similarity >= min_score:
                candidates.append(
                    DuplicateCandidate(
                        uuid1=o1["uuid"],
                        uuid2=o2["uuid"],
                        name1=o1["name"],
                        name2=o2["name"],
                        entity_type="Organization",
                        similarity_score=name_similarity,
                        match_reasons=["similar_name"],
                    )
                )

    logger.info(
        f"[BEACON] Found {len(candidates)} duplicate organization candidates",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    return candidates


def _already_candidate(candidates: list[DuplicateCandidate], uuid1: str, uuid2: str) -> bool:
    """Check if a pair of UUIDs is already in the candidates list."""
    for candidate in candidates:
        if (candidate.uuid1 == uuid1 and candidate.uuid2 == uuid2) or (
            candidate.uuid1 == uuid2 and candidate.uuid2 == uuid1
        ):
            return True
    return False


# ===========================================================================
# Merge Operations
# ===========================================================================


async def merge_entities(
    neo4j: Neo4jClient,
    keep_uuid: str,
    remove_uuid: str,
    entity_type: str,
    trace_id: str | None = None,
) -> bool:
    """
    Merge duplicate entities, keeping all relationships and properties.

    Transfers all relationships from remove_uuid to keep_uuid, merges
    properties (keeps existing on keep_uuid, fills in missing from remove_uuid),
    and deletes the duplicate node.

    Args:
        neo4j: Connected Neo4jClient instance
        keep_uuid: UUID of the entity to keep
        remove_uuid: UUID of the entity to remove
        entity_type: Entity type ("Person" or "Organization")
        trace_id: Optional trace ID for logging

    Returns:
        True if merge was successful, False otherwise
    """
    logger.info(
        f"[CHART] Merging {entity_type} {remove_uuid} into {keep_uuid}",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    try:
        # Transfer incoming relationships
        # Using type-specific queries to avoid APOC dependency
        incoming_simple_query = f"""
        MATCH (keep:{entity_type} {{uuid: $keep_uuid}})
        MATCH (remove:{entity_type} {{uuid: $remove_uuid}})
        MATCH (other)-[r]->(remove)
        WHERE other <> keep
        WITH keep, remove, other, r, type(r) as rel_type
        // Handle common relationship types
        FOREACH (_ IN CASE WHEN rel_type = 'WORKS_AT' THEN [1] ELSE [] END |
            MERGE (other)-[new_r:WORKS_AT]->(keep)
            SET new_r = properties(r)
        )
        FOREACH (_ IN CASE WHEN rel_type = 'KNOWS' THEN [1] ELSE [] END |
            MERGE (other)-[new_r:KNOWS]->(keep)
            SET new_r = properties(r)
        )
        FOREACH (_ IN CASE WHEN rel_type = 'REPORTS_TO' THEN [1] ELSE [] END |
            MERGE (other)-[new_r:REPORTS_TO]->(keep)
            SET new_r = properties(r)
        )
        FOREACH (_ IN CASE WHEN rel_type = 'ATTENDED' THEN [1] ELSE [] END |
            MERGE (other)-[new_r:ATTENDED]->(keep)
            SET new_r = properties(r)
        )
        FOREACH (_ IN CASE WHEN rel_type = 'ASSIGNED_TO' THEN [1] ELSE [] END |
            MERGE (other)-[new_r:ASSIGNED_TO]->(keep)
            SET new_r = properties(r)
        )
        DELETE r
        RETURN count(*) as transferred_incoming
        """

        result = await neo4j.execute_write(
            incoming_simple_query,
            {"keep_uuid": keep_uuid, "remove_uuid": remove_uuid},
            trace_id=trace_id,
        )
        incoming_count = result[0].get("transferred_incoming", 0) if result else 0

        # Transfer outgoing relationships
        outgoing_simple_query = f"""
        MATCH (keep:{entity_type} {{uuid: $keep_uuid}})
        MATCH (remove:{entity_type} {{uuid: $remove_uuid}})
        MATCH (remove)-[r]->(other)
        WHERE other <> keep
        WITH keep, remove, other, r, type(r) as rel_type
        // Handle common relationship types
        FOREACH (_ IN CASE WHEN rel_type = 'WORKS_AT' THEN [1] ELSE [] END |
            MERGE (keep)-[new_r:WORKS_AT]->(other)
            SET new_r = properties(r)
        )
        FOREACH (_ IN CASE WHEN rel_type = 'KNOWS' THEN [1] ELSE [] END |
            MERGE (keep)-[new_r:KNOWS]->(other)
            SET new_r = properties(r)
        )
        FOREACH (_ IN CASE WHEN rel_type = 'REPORTS_TO' THEN [1] ELSE [] END |
            MERGE (keep)-[new_r:REPORTS_TO]->(other)
            SET new_r = properties(r)
        )
        FOREACH (_ IN CASE WHEN rel_type = 'PART_OF' THEN [1] ELSE [] END |
            MERGE (keep)-[new_r:PART_OF]->(other)
            SET new_r = properties(r)
        )
        FOREACH (_ IN CASE WHEN rel_type = 'LOCATED_IN' THEN [1] ELSE [] END |
            MERGE (keep)-[new_r:LOCATED_IN]->(other)
            SET new_r = properties(r)
        )
        DELETE r
        RETURN count(*) as transferred_outgoing
        """

        result = await neo4j.execute_write(
            outgoing_simple_query,
            {"keep_uuid": keep_uuid, "remove_uuid": remove_uuid},
            trace_id=trace_id,
        )
        outgoing_count = result[0].get("transferred_outgoing", 0) if result else 0

        logger.debug(
            f"[WHISPER] Transferred {incoming_count} incoming, {outgoing_count} outgoing relationships",
            extra={"trace_id": trace_id, "agent_name": "deduplication"},
        )

        # Merge properties and delete duplicate
        # Property merging is entity-type specific
        if entity_type == "Person":
            merge_query = """
            MATCH (keep:Person {uuid: $keep_uuid})
            MATCH (remove:Person {uuid: $remove_uuid})
            SET keep.email = COALESCE(keep.email, remove.email),
                keep.phone = COALESCE(keep.phone, remove.phone),
                keep.bio = COALESCE(keep.bio, remove.bio),
                keep.linkedin_url = COALESCE(keep.linkedin_url, remove.linkedin_url),
                keep.twitter_handle = COALESCE(keep.twitter_handle, remove.twitter_handle),
                keep.avatar_url = COALESCE(keep.avatar_url, remove.avatar_url),
                keep.updated_at = timestamp()
            WITH remove
            DELETE remove
            RETURN 'merged' as status
            """
        elif entity_type == "Organization":
            merge_query = """
            MATCH (keep:Organization {uuid: $keep_uuid})
            MATCH (remove:Organization {uuid: $remove_uuid})
            SET keep.industry = COALESCE(keep.industry, remove.industry),
                keep.website = COALESCE(keep.website, remove.website),
                keep.domain = COALESCE(keep.domain, remove.domain),
                keep.description = COALESCE(keep.description, remove.description),
                keep.logo_url = COALESCE(keep.logo_url, remove.logo_url),
                keep.updated_at = timestamp()
            WITH remove
            DELETE remove
            RETURN 'merged' as status
            """
        else:
            logger.error(
                f"[STORM] Unknown entity type: {entity_type}",
                extra={"trace_id": trace_id, "agent_name": "deduplication"},
            )
            return False

        await neo4j.execute_write(
            merge_query,
            {"keep_uuid": keep_uuid, "remove_uuid": remove_uuid},
            trace_id=trace_id,
        )

        logger.info(
            f"[BEACON] Successfully merged {entity_type} {remove_uuid} into {keep_uuid}",
            extra={"trace_id": trace_id, "agent_name": "deduplication"},
        )

        return True

    except Exception as e:
        logger.error(
            f"[STORM] Merge failed: {e}",
            extra={"trace_id": trace_id, "agent_name": "deduplication"},
        )
        return False


async def flag_for_review(
    neo4j: Neo4jClient,
    candidate: DuplicateCandidate,
    trace_id: str | None = None,
) -> str:
    """
    Flag a duplicate candidate for user review.

    Creates a [:POTENTIAL_DUPLICATE] relationship between the two entities
    with the similarity score and match reasons.

    Args:
        neo4j: Connected Neo4jClient instance
        candidate: DuplicateCandidate to flag
        trace_id: Optional trace ID for logging

    Returns:
        Flag UUID (relationship UUID) if successful, empty string otherwise
    """
    logger.info(
        f"[CHART] Flagging {candidate.entity_type} pair for review: "
        f"{candidate.name1} <-> {candidate.name2} (score={candidate.similarity_score:.2f})",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    query = f"""
    MATCH (e1:{candidate.entity_type} {{uuid: $uuid1}})
    MATCH (e2:{candidate.entity_type} {{uuid: $uuid2}})
    MERGE (e1)-[r:POTENTIAL_DUPLICATE]->(e2)
    SET r.similarity_score = $score,
        r.match_reasons = $reasons,
        r.flagged_at = timestamp(),
        r.reviewed = false
    RETURN elementId(r) as flag_id
    """

    try:
        result = await neo4j.execute_write(
            query,
            {
                "uuid1": candidate.uuid1,
                "uuid2": candidate.uuid2,
                "score": candidate.similarity_score,
                "reasons": candidate.match_reasons,
            },
            trace_id=trace_id,
        )

        flag_id: str = str(result[0]["flag_id"]) if result else ""

        logger.debug(
            f"[WHISPER] Created POTENTIAL_DUPLICATE flag: {flag_id}",
            extra={"trace_id": trace_id, "agent_name": "deduplication"},
        )

        return flag_id

    except Exception as e:
        logger.error(
            f"[STORM] Failed to flag for review: {e}",
            extra={"trace_id": trace_id, "agent_name": "deduplication"},
        )
        return ""


# ===========================================================================
# Processing Pipeline
# ===========================================================================


async def process_duplicates(
    neo4j: Neo4jClient,
    auto_merge_threshold: float = 0.9,
    review_threshold: float = 0.7,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """
    Find and process all duplicate entities.

    High-confidence duplicates (score >= auto_merge_threshold) are merged automatically.
    Medium-confidence duplicates (review_threshold <= score < auto_merge_threshold)
    are flagged for user review.

    Args:
        neo4j: Connected Neo4jClient instance
        auto_merge_threshold: Score threshold for automatic merging (default: 0.9)
        review_threshold: Minimum score to flag for review (default: 0.7)
        trace_id: Optional trace ID for logging

    Returns:
        Dictionary with processing statistics:
        {
            "auto_merged": int,
            "flagged_for_review": int,
            "ignored": int
        }
    """
    logger.info(
        "[CHART] Processing duplicates (auto_merge_threshold="
        f"{auto_merge_threshold}, review_threshold={review_threshold})",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    stats: dict[str, Any] = {
        "auto_merged": 0,
        "flagged_for_review": 0,
        "ignored": 0,
    }

    # Process persons
    person_candidates = await find_duplicate_persons(
        neo4j, min_score=review_threshold, trace_id=trace_id
    )

    for candidate in person_candidates:
        if candidate.similarity_score >= auto_merge_threshold:
            success = await merge_entities(
                neo4j,
                candidate.uuid1,
                candidate.uuid2,
                candidate.entity_type,
                trace_id=trace_id,
            )
            if success:
                stats["auto_merged"] += 1
        elif candidate.similarity_score >= review_threshold:
            flag_id = await flag_for_review(neo4j, candidate, trace_id=trace_id)
            if flag_id:
                stats["flagged_for_review"] += 1
        else:
            stats["ignored"] += 1

    # Process organizations
    org_candidates = await find_duplicate_organizations(
        neo4j, min_score=review_threshold, trace_id=trace_id
    )

    for candidate in org_candidates:
        if candidate.similarity_score >= auto_merge_threshold:
            success = await merge_entities(
                neo4j,
                candidate.uuid1,
                candidate.uuid2,
                candidate.entity_type,
                trace_id=trace_id,
            )
            if success:
                stats["auto_merged"] += 1
        elif candidate.similarity_score >= review_threshold:
            flag_id = await flag_for_review(neo4j, candidate, trace_id=trace_id)
            if flag_id:
                stats["flagged_for_review"] += 1
        else:
            stats["ignored"] += 1

    logger.info(
        f"[BEACON] Deduplication complete: {stats['auto_merged']} merged, "
        f"{stats['flagged_for_review']} flagged, {stats['ignored']} ignored",
        extra={"trace_id": trace_id, "agent_name": "deduplication"},
    )

    return stats


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "find_duplicate_organizations",
    "find_duplicate_persons",
    "flag_for_review",
    "merge_entities",
    "process_duplicates",
]
