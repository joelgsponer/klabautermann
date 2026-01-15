"""
Note-related graph queries for thread summarization.

Provides functions to create Note nodes from thread summaries and link them
to threads and mentioned entities.

Reference: specs/architecture/ONTOLOGY.md Section 1.1 (Note node)
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger
from klabautermann.core.models import generate_uuid


if TYPE_CHECKING:
    from klabautermann.core.models import ThreadSummary
    from klabautermann.memory.neo4j_client import Neo4jClient


def generate_note_title(topics: list[str], max_length: int = 60) -> str:
    """
    Generate a concise title from thread topics.

    Args:
        topics: List of topic strings extracted from summary
        max_length: Maximum title length (default 60)

    Returns:
        Generated title string

    Examples:
        >>> generate_note_title(["Project Planning", "Budget Review"])
        'Project Planning / Budget Review'
        >>> generate_note_title(["Very Long Topic Name", "Another Topic"], max_length=20)
        'Very Long Topic N...'
    """
    if not topics:
        return "Conversation Summary"

    # Join first 2-3 topics with " / " separator
    title = " / ".join(topics[:3])

    # Truncate if needed
    if len(title) > max_length:
        title = title[: max_length - 3] + "..."

    return title


async def create_note_from_summary(
    neo4j: Neo4jClient,
    thread_uuid: str,
    summary: ThreadSummary,
    trace_id: str | None = None,
) -> str:
    """
    Create Note node from ThreadSummary.

    Creates a Note node with properties extracted from the thread summary,
    including title, content, topics, action items, and sentiment.

    Args:
        neo4j: Connected Neo4j client
        thread_uuid: UUID of the thread being summarized
        summary: ThreadSummary object from Archivist
        trace_id: Optional trace ID for logging

    Returns:
        UUID of created Note node

    Raises:
        GraphConnectionError: If database connection fails
    """
    note_uuid = generate_uuid()
    title = generate_note_title(summary.topics)

    # Serialize action items to JSON
    action_items_json = json.dumps([item.model_dump() for item in summary.action_items])

    # Check if conflicts exist (requires user validation)
    requires_validation = len(summary.conflicts) > 0

    query = """
    CREATE (n:Note {
        uuid: $uuid,
        title: $title,
        content_summarized: $content_summarized,
        topics: $topics,
        action_items: $action_items,
        sentiment: $sentiment,
        source: $source,
        requires_user_validation: $requires_user_validation,
        created_at: $created_at,
        updated_at: $updated_at
    })
    RETURN n.uuid as uuid
    """

    parameters = {
        "uuid": note_uuid,
        "title": title,
        "content_summarized": summary.summary,
        "topics": summary.topics,  # Neo4j accepts lists directly
        "action_items": action_items_json,
        "sentiment": summary.sentiment,
        "source": "thread_summary",
        "requires_user_validation": requires_validation,
        "created_at": time.time(),
        "updated_at": time.time(),
    }

    logger.debug(
        f"[WHISPER] Creating Note node from thread {thread_uuid[:8]}",
        extra={
            "trace_id": trace_id,
            "agent_name": "note_queries",
            "note_uuid": note_uuid,
            "thread_uuid": thread_uuid,
        },
    )

    result = await neo4j.execute_write(query, parameters, trace_id=trace_id)

    if not result or "uuid" not in result[0]:
        logger.error(
            "[STORM] Failed to create Note node",
            extra={"trace_id": trace_id, "agent_name": "note_queries"},
        )
        raise RuntimeError("Failed to create Note node")

    logger.info(
        f"[BEACON] Created Note {note_uuid[:8]} with {len(summary.topics)} topics",
        extra={
            "trace_id": trace_id,
            "agent_name": "note_queries",
            "note_uuid": note_uuid,
        },
    )

    return note_uuid


async def link_note_to_thread(
    neo4j: Neo4jClient,
    note_uuid: str,
    thread_uuid: str,
    trace_id: str | None = None,
) -> None:
    """
    Create SUMMARY_OF relationship from Note to Thread.

    Links a Note node to the Thread it summarizes, enabling retrieval
    of thread summaries via graph traversal.

    Args:
        neo4j: Connected Neo4j client
        note_uuid: UUID of the Note node
        thread_uuid: UUID of the Thread node
        trace_id: Optional trace ID for logging

    Raises:
        GraphConnectionError: If database connection fails
        RuntimeError: If Note or Thread not found
    """
    query = """
    MATCH (n:Note {uuid: $note_uuid})
    MATCH (t:Thread {uuid: $thread_uuid})
    CREATE (n)-[:SUMMARY_OF {created_at: $created_at}]->(t)
    RETURN n.uuid as note_uuid, t.uuid as thread_uuid
    """

    parameters = {
        "note_uuid": note_uuid,
        "thread_uuid": thread_uuid,
        "created_at": time.time(),
    }

    logger.debug(
        f"[WHISPER] Linking Note {note_uuid[:8]} to Thread {thread_uuid[:8]}",
        extra={
            "trace_id": trace_id,
            "agent_name": "note_queries",
        },
    )

    result = await neo4j.execute_write(query, parameters, trace_id=trace_id)

    if not result:
        logger.error(
            "[STORM] Failed to link Note to Thread - nodes not found",
            extra={
                "trace_id": trace_id,
                "agent_name": "note_queries",
                "note_uuid": note_uuid,
                "thread_uuid": thread_uuid,
            },
        )
        raise RuntimeError(f"Note {note_uuid} or Thread {thread_uuid} not found")

    logger.debug(
        "[WHISPER] Linked Note to Thread",
        extra={
            "trace_id": trace_id,
            "agent_name": "note_queries",
        },
    )


async def link_entities_to_note(
    neo4j: Neo4jClient,
    note_uuid: str,
    entity_names: list[str],
    trace_id: str | None = None,
) -> int:
    """
    Link entities mentioned in thread to Note via MENTIONED_IN relationships.

    Searches for Person and Organization nodes by name (case-insensitive)
    and creates MENTIONED_IN relationships pointing to the Note.

    Args:
        neo4j: Connected Neo4j client
        note_uuid: UUID of the Note node
        entity_names: List of entity names (people, organizations)
        trace_id: Optional trace ID for logging

    Returns:
        Number of relationships created

    Raises:
        GraphConnectionError: If database connection fails
    """
    if not entity_names:
        logger.debug(
            "[WHISPER] No entities to link to Note",
            extra={"trace_id": trace_id, "agent_name": "note_queries"},
        )
        return 0

    # Match entities by name (Person or Organization) and create relationships
    # Use MERGE to avoid duplicate relationships
    query = """
    MATCH (n:Note {uuid: $note_uuid})
    UNWIND $entity_names as name
    MATCH (e)
    WHERE (e:Person OR e:Organization)
      AND toLower(e.name) = toLower(name)
    MERGE (e)-[r:MENTIONED_IN {created_at: $created_at}]->(n)
    RETURN count(DISTINCT r) as link_count
    """

    parameters = {
        "note_uuid": note_uuid,
        "entity_names": entity_names,
        "created_at": time.time(),
    }

    logger.debug(
        f"[WHISPER] Linking {len(entity_names)} entities to Note {note_uuid[:8]}",
        extra={
            "trace_id": trace_id,
            "agent_name": "note_queries",
            "entity_names": entity_names,
        },
    )

    result = await neo4j.execute_write(query, parameters, trace_id=trace_id)

    link_count: int = int(result[0]["link_count"]) if result else 0

    logger.info(
        f"[BEACON] Linked {link_count}/{len(entity_names)} entities to Note",
        extra={
            "trace_id": trace_id,
            "agent_name": "note_queries",
            "note_uuid": note_uuid,
            "link_count": link_count,
        },
    )

    return link_count


# ===========================================================================
# Convenience function for complete Note creation
# ===========================================================================


async def create_note_with_links(
    neo4j: Neo4jClient,
    thread_uuid: str,
    summary: ThreadSummary,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """
    Create Note from summary and link to thread and entities in one operation.

    This convenience function orchestrates all three operations:
    1. Create Note node from summary
    2. Link Note to Thread via SUMMARY_OF
    3. Link mentioned entities via MENTIONED_IN

    Args:
        neo4j: Connected Neo4j client
        thread_uuid: UUID of the thread being summarized
        summary: ThreadSummary object from Archivist
        trace_id: Optional trace ID for logging

    Returns:
        Dictionary with note_uuid and entity_link_count

    Raises:
        GraphConnectionError: If database connection fails
    """
    logger.info(
        f"[CHART] Creating Note for thread {thread_uuid[:8]}",
        extra={"trace_id": trace_id, "agent_name": "note_queries"},
    )

    # Step 1: Create Note node
    note_uuid = await create_note_from_summary(neo4j, thread_uuid, summary, trace_id)

    # Step 2: Link Note to Thread
    await link_note_to_thread(neo4j, note_uuid, thread_uuid, trace_id)

    # Step 3: Link entities (participants) to Note
    entity_link_count = await link_entities_to_note(
        neo4j, note_uuid, summary.participants, trace_id
    )

    logger.info(
        f"[BEACON] Completed Note creation for thread {thread_uuid[:8]}",
        extra={
            "trace_id": trace_id,
            "agent_name": "note_queries",
            "note_uuid": note_uuid,
            "entity_links": entity_link_count,
        },
    )

    return {
        "note_uuid": note_uuid,
        "entity_link_count": entity_link_count,
    }


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "create_note_from_summary",
    "create_note_with_links",
    "generate_note_title",
    "link_entities_to_note",
    "link_note_to_thread",
]
