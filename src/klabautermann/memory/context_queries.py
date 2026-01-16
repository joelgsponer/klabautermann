"""
Context retrieval queries for Orchestrator v2.

Provides Cypher queries that gather context from all memory layers:
- Short-Term: Current thread messages (handled by ThreadManager)
- Mid-Term: Recent thread summaries (Note nodes)
- Long-Term: Recently created entities (Graphiti)
- Community: Knowledge Island summaries

All queries are parametrized for injection safety.
Reference: specs/MAINAGENT.md Section 4.2
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from klabautermann.core.logger import logger
from klabautermann.core.models import (
    CommunityContext,
    EntityReference,
    TaskNode,
    TaskStatus,
    ThreadSummary,
)


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


async def get_recent_summaries(
    neo4j: Neo4jClient,
    hours: int = 12,
    limit: int = 10,
    trace_id: str | None = None,
) -> list[ThreadSummary]:
    """
    Retrieve Note nodes from recently archived threads.

    Provides cross-thread awareness - what was discussed in other
    channels/threads recently. This is the Mid-Term memory layer.

    Args:
        neo4j: Connected Neo4jClient instance
        hours: How many hours back to look
        limit: Maximum number of summaries to return
        trace_id: Optional trace ID for logging

    Returns:
        List of ThreadSummary models from Note nodes
    """
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).timestamp()

    logger.debug(
        f"[WHISPER] Retrieving thread summaries from last {hours} hours",
        extra={"trace_id": trace_id, "agent_name": "context_queries"},
    )

    query = """
    MATCH (n:Note)-[:SUMMARY_OF]->(t:Thread)
    WHERE n.created_at >= $cutoff
    OPTIONAL MATCH (n)<-[:MENTIONED_IN]-(p:Person)
    RETURN n.uuid as uuid,
           n.title as title,
           n.content_summarized as summary,
           n.topics as topics,
           t.channel_type as channel,
           collect(DISTINCT p.name) as participants
    ORDER BY n.created_at DESC
    LIMIT $limit
    """

    result = await neo4j.execute_query(
        query,
        {"cutoff": cutoff, "limit": limit},
        trace_id=trace_id,
    )

    summaries = []
    for record in result:
        # Convert to ThreadSummary model
        # Note: Some fields may not be in Note nodes, using sensible defaults
        summary = ThreadSummary(
            summary=record.get("summary") or "",
            topics=record.get("topics") or [],
            participants=record.get("participants") or [],
            action_items=[],  # Not stored in Note nodes
            new_facts=[],  # Not stored in Note nodes
            conflicts=[],  # Not stored in Note nodes
            sentiment="neutral",  # Not stored in Note nodes
        )
        summaries.append(summary)

    logger.debug(
        f"[WHISPER] Found {len(summaries)} recent thread summaries",
        extra={"trace_id": trace_id, "agent_name": "context_queries"},
    )

    return summaries


async def get_relevant_islands(
    neo4j: Neo4jClient,
    limit: int = 5,
    trace_id: str | None = None,
) -> list[CommunityContext]:
    """
    Get Knowledge Island summaries for broad context.

    Uses Macro-level retrieval from MEMORY.md Section 9.2.
    Knowledge Islands are clusters of related entities detected
    through community detection algorithms.

    Args:
        neo4j: Connected Neo4jClient instance
        limit: Maximum number of communities to return
        trace_id: Optional trace ID for logging

    Returns:
        List of CommunityContext models
    """
    logger.debug(
        "[WHISPER] Retrieving Knowledge Island summaries",
        extra={"trace_id": trace_id, "agent_name": "context_queries"},
    )

    query = """
    MATCH (c:Community)
    WHERE EXISTS((c)<-[:PART_OF_ISLAND]-())
    OPTIONAL MATCH (c)<-[:PART_OF_ISLAND]-(t:Task {status: 'todo'})
    RETURN c.name as name,
           c.theme as theme,
           c.summary as summary,
           count(t) as pending_tasks
    ORDER BY pending_tasks DESC
    LIMIT $limit
    """

    result = await neo4j.execute_query(
        query,
        {"limit": limit},
        trace_id=trace_id,
    )

    islands = []
    for record in result:
        island = CommunityContext(
            name=record.get("name") or "Unknown Island",
            theme=record.get("theme") or "",
            summary=record.get("summary") or "",
            pending_tasks=record.get("pending_tasks") or 0,
        )
        islands.append(island)

    logger.debug(
        f"[WHISPER] Found {len(islands)} Knowledge Islands",
        extra={"trace_id": trace_id, "agent_name": "context_queries"},
    )

    return islands


async def get_pending_tasks(
    neo4j: Neo4jClient,
    limit: int = 20,
    trace_id: str | None = None,
) -> list[TaskNode]:
    """
    Retrieve pending tasks for proactive reminders.

    Queries Task nodes with status in [pending, todo, in_progress].
    Orders by priority (high > medium > low) and due date.

    Args:
        neo4j: Connected Neo4jClient instance
        limit: Maximum number of tasks to return
        trace_id: Optional trace ID for logging

    Returns:
        List of TaskNode models with pending status
    """
    logger.debug(
        "[WHISPER] Retrieving pending tasks",
        extra={"trace_id": trace_id, "agent_name": "context_queries"},
    )

    query = """
    MATCH (t:Task)
    WHERE t.status IN ['pending', 'todo', 'in_progress']
    OPTIONAL MATCH (t)-[:ASSIGNED_TO]->(p:Person)
    RETURN t.uuid as uuid,
           t.action as action,
           t.status as status,
           t.priority as priority,
           t.due_date as due_date,
           t.completed_at as completed_at,
           t.created_at as created_at,
           t.updated_at as updated_at,
           p.name as assignee
    ORDER BY
        CASE t.priority
            WHEN 'high' THEN 1
            WHEN 'medium' THEN 2
            ELSE 3
        END,
        t.due_date
    LIMIT $limit
    """

    result = await neo4j.execute_query(
        query,
        {"limit": limit},
        trace_id=trace_id,
    )

    tasks = []
    for record in result:
        # Map to TaskNode model
        status_str = record.get("status") or "todo"
        # Convert string to TaskStatus enum
        try:
            status = TaskStatus(status_str)
        except ValueError:
            status = TaskStatus.TODO

        task = TaskNode(
            uuid=record.get("uuid") or "",
            action=record.get("action") or "",
            status=status,
            priority=record.get("priority"),
            due_date=record.get("due_date"),
            completed_at=record.get("completed_at"),
            created_at=record.get("created_at") or 0.0,
            updated_at=record.get("updated_at") or 0.0,
        )
        tasks.append(task)

    logger.debug(
        f"[WHISPER] Found {len(tasks)} pending tasks",
        extra={"trace_id": trace_id, "agent_name": "context_queries"},
    )

    return tasks


async def get_recent_entities(
    neo4j: Neo4jClient,
    hours: int = 24,
    limit: int = 20,
    trace_id: str | None = None,
) -> list[EntityReference]:
    """
    Retrieve recently created/updated entities.

    Provides Long-Term memory context by surfacing entities that were
    recently added to the knowledge graph. Excludes system nodes
    (Message, Thread, Day, Note) and focuses on knowledge entities.

    Args:
        neo4j: Connected Neo4jClient instance
        hours: How many hours back to look
        limit: Maximum number of entities to return
        trace_id: Optional trace ID for logging

    Returns:
        List of EntityReference models
    """
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).timestamp()

    logger.debug(
        f"[WHISPER] Retrieving entities created in last {hours} hours",
        extra={"trace_id": trace_id, "agent_name": "context_queries"},
    )

    query = """
    MATCH (n)
    WHERE n.created_at >= $cutoff
      AND NOT n:Message AND NOT n:Thread AND NOT n:Day AND NOT n:Note
      AND n.name IS NOT NULL
    WITH n, labels(n)[0] as entity_type
    WHERE entity_type IN ['Person', 'Organization', 'Project', 'Task', 'Event']
    RETURN n.uuid as uuid,
           n.name as name,
           entity_type,
           n.created_at as created_at
    ORDER BY n.created_at DESC
    LIMIT $limit
    """

    result = await neo4j.execute_query(
        query,
        {"cutoff": cutoff, "limit": limit},
        trace_id=trace_id,
    )

    entities = []
    for record in result:
        entity = EntityReference(
            uuid=record.get("uuid") or "",
            name=record.get("name") or "",
            entity_type=record.get("entity_type") or "Unknown",
            created_at=record.get("created_at") or 0.0,
        )
        entities.append(entity)

    logger.debug(
        f"[WHISPER] Found {len(entities)} recent entities",
        extra={"trace_id": trace_id, "agent_name": "context_queries"},
    )

    return entities


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "get_pending_tasks",
    "get_recent_entities",
    "get_recent_summaries",
    "get_relevant_islands",
]
