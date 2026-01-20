"""
Message-entity linking for researcher results.

Creates MENTIONED_IN relationships between entities found by the Researcher
agent and Message nodes, enabling graph traversal from messages to relevant
entities.

Reference: specs/architecture/ONTOLOGY.md
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.agents.researcher_models import EntityReference
    from klabautermann.memory.neo4j_client import Neo4jClient


async def link_entities_to_message(
    neo4j: Neo4jClient,
    message_uuid: str,
    entity_refs: list[EntityReference],
    trace_id: str | None = None,
) -> int:
    """
    Link entities to a message via MENTIONED_IN relationships.

    Creates (Entity)-[:MENTIONED_IN]->(Message) relationships for each
    entity reference. Uses MERGE to prevent duplicate relationships.

    Args:
        neo4j: Connected Neo4j client.
        message_uuid: UUID of the Message node to link to.
        entity_refs: List of EntityReference objects with UUIDs.
        trace_id: Optional trace ID for logging.

    Returns:
        Number of relationships created.

    Raises:
        GraphConnectionError: If database connection fails.
    """
    if not entity_refs:
        logger.debug(
            "[WHISPER] No entities to link to message",
            extra={"trace_id": trace_id, "message_uuid": message_uuid},
        )
        return 0

    # Convert EntityReference objects to dicts for Cypher
    entities_data: list[dict[str, Any]] = [
        {
            "uuid": ref.uuid,
            "confidence": ref.confidence,
            "source_technique": ref.source_technique,
        }
        for ref in entity_refs
    ]

    # Use UNWIND for batch creation with MERGE to prevent duplicates
    query = """
    UNWIND $entities as entity
    MATCH (m:Message {uuid: $message_uuid})
    MATCH (e {uuid: entity.uuid})
    MERGE (e)-[r:MENTIONED_IN]->(m)
    ON CREATE SET
        r.created_at = $created_at,
        r.confidence = entity.confidence,
        r.source_technique = entity.source_technique,
        r.trace_id = $trace_id
    RETURN count(DISTINCT r) as link_count
    """

    parameters = {
        "message_uuid": message_uuid,
        "entities": entities_data,
        "created_at": time.time(),
        "trace_id": trace_id or "",
    }

    logger.debug(
        f"[WHISPER] Linking {len(entity_refs)} entities to message {message_uuid[:8]}",
        extra={
            "trace_id": trace_id,
            "message_uuid": message_uuid,
            "entity_count": len(entity_refs),
        },
    )

    try:
        result = await neo4j.execute_write(query, parameters, trace_id=trace_id)
        link_count: int = int(result[0]["link_count"]) if result else 0

        logger.info(
            f"[BEACON] Linked {link_count}/{len(entity_refs)} entities to message",
            extra={
                "trace_id": trace_id,
                "message_uuid": message_uuid,
                "link_count": link_count,
            },
        )

        return link_count

    except Exception as e:
        logger.warning(
            f"[SWELL] Failed to link entities to message: {e}",
            extra={
                "trace_id": trace_id,
                "message_uuid": message_uuid,
                "error": str(e),
            },
        )
        return 0


__all__ = ["link_entities_to_message"]
