"""
Analytics queries for the Scribe agent.

Provides daily statistics gathering for journal generation:
- Message counts, entity creation, task completion
- Project discussion tracking
- Aggregated daily summaries

All queries are parametrized for injection safety.
Reference: specs/architecture/AGENTS.md Section 1.6
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from klabautermann.core.logger import logger
from klabautermann.core.models import DailyAnalytics, SagaProgress


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


def get_day_bounds(date: str) -> tuple[float, float]:
    """
    Get Unix timestamp bounds for a day (start, end).

    Args:
        date: Date in YYYY-MM-DD format

    Returns:
        Tuple of (day_start_timestamp, day_end_timestamp)
    """
    day_dt = datetime.strptime(date, "%Y-%m-%d")
    day_start = day_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    day_end = (
        (day_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    )
    return day_start, day_end


async def get_daily_interaction_count(
    neo4j: Neo4jClient,
    date: str,
    trace_id: str | None = None,
) -> int:
    """
    Count all messages for a specific day.

    Counts both user and assistant messages across all threads.

    Args:
        neo4j: Connected Neo4jClient instance
        date: Date in YYYY-MM-DD format
        trace_id: Optional trace ID for logging

    Returns:
        Total count of messages for the day
    """
    day_start, day_end = get_day_bounds(date)

    logger.debug(
        f"[WHISPER] Counting interactions for {date}",
        extra={"trace_id": trace_id, "agent_name": "analytics"},
    )

    query = """
    MATCH (t:Thread)-[:CONTAINS]->(m:Message)
    WHERE m.timestamp >= $day_start AND m.timestamp < $day_end
    RETURN count(m) as interaction_count
    """

    result = await neo4j.execute_query(
        query,
        {"day_start": day_start, "day_end": day_end},
        trace_id=trace_id,
    )

    count: int = int(result[0]["interaction_count"]) if result else 0

    logger.debug(
        f"[WHISPER] Found {count} interactions on {date}",
        extra={"trace_id": trace_id, "agent_name": "analytics"},
    )

    return count


async def get_daily_entity_counts(
    neo4j: Neo4jClient,
    date: str,
    trace_id: str | None = None,
) -> dict[str, int]:
    """
    Count new entities created on a specific day by type.

    Excludes system nodes (Message, Thread, Day) and focuses on
    knowledge entities (Person, Organization, Project, etc.).

    Args:
        neo4j: Connected Neo4jClient instance
        date: Date in YYYY-MM-DD format
        trace_id: Optional trace ID for logging

    Returns:
        Dictionary mapping entity type to count (e.g., {"Person": 2, "Organization": 1})
    """
    day_start, day_end = get_day_bounds(date)

    logger.debug(
        f"[WHISPER] Counting new entities for {date}",
        extra={"trace_id": trace_id, "agent_name": "analytics"},
    )

    query = """
    MATCH (n)
    WHERE n.created_at >= $day_start AND n.created_at < $day_end
      AND NOT n:Message AND NOT n:Thread AND NOT n:Day
      AND n.created_at IS NOT NULL
    WITH labels(n)[0] as type, count(n) as count
    WHERE type IN ['Person', 'Organization', 'Project', 'Task', 'Event',
                   'Note', 'Goal', 'Location', 'Resource']
    RETURN type, count
    """

    result = await neo4j.execute_query(
        query,
        {"day_start": day_start, "day_end": day_end},
        trace_id=trace_id,
    )

    entity_counts = {r["type"]: r["count"] for r in result}

    logger.debug(
        f"[WHISPER] Found {sum(entity_counts.values())} new entities on {date}",
        extra={"trace_id": trace_id, "agent_name": "analytics", "counts": entity_counts},
    )

    return entity_counts


async def get_daily_task_stats(
    neo4j: Neo4jClient,
    date: str,
    trace_id: str | None = None,
) -> dict[str, int]:
    """
    Get task completion and creation statistics for a day.

    Args:
        neo4j: Connected Neo4jClient instance
        date: Date in YYYY-MM-DD format
        trace_id: Optional trace ID for logging

    Returns:
        Dictionary with 'completed' and 'created' counts
    """
    day_start, day_end = get_day_bounds(date)

    logger.debug(
        f"[WHISPER] Gathering task stats for {date}",
        extra={"trace_id": trace_id, "agent_name": "analytics"},
    )

    # Count tasks completed on this day
    completed_query = """
    MATCH (t:Task)
    WHERE t.completed_at >= $day_start AND t.completed_at < $day_end
    RETURN count(t) as count
    """

    completed_result = await neo4j.execute_query(
        completed_query,
        {"day_start": day_start, "day_end": day_end},
        trace_id=trace_id,
    )
    completed_count = completed_result[0]["count"] if completed_result else 0

    # Count tasks created on this day
    created_query = """
    MATCH (t:Task)
    WHERE t.created_at >= $day_start AND t.created_at < $day_end
    RETURN count(t) as count
    """

    created_result = await neo4j.execute_query(
        created_query,
        {"day_start": day_start, "day_end": day_end},
        trace_id=trace_id,
    )
    created_count = created_result[0]["count"] if created_result else 0

    stats = {"completed": completed_count, "created": created_count}

    logger.debug(
        f"[WHISPER] Task stats for {date}: {stats}",
        extra={"trace_id": trace_id, "agent_name": "analytics"},
    )

    return stats


async def get_daily_projects_discussed(
    neo4j: Neo4jClient,
    date: str,
    limit: int = 3,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get top projects mentioned in notes/events on a specific day.

    Projects are ranked by the number of times they were mentioned
    across all notes and events that occurred on the day.

    Args:
        neo4j: Connected Neo4jClient instance
        date: Date in YYYY-MM-DD format
        limit: Maximum number of projects to return
        trace_id: Optional trace ID for logging

    Returns:
        List of dictionaries with project data (name, uuid, mentions)
    """
    logger.debug(
        f"[WHISPER] Finding top projects discussed on {date}",
        extra={"trace_id": trace_id, "agent_name": "analytics"},
    )

    query = """
    MATCH (d:Day {date: $date})<-[:OCCURRED_ON]-(n:Note)
    MATCH (n)-[:DISCUSSED]->(p:Project)
    RETURN p.name as name, p.uuid as uuid, count(n) as mentions
    ORDER BY mentions DESC
    LIMIT $limit
    """

    result = await neo4j.execute_query(
        query,
        {"date": date, "limit": limit},
        trace_id=trace_id,
    )

    logger.debug(
        f"[WHISPER] Found {len(result)} projects discussed on {date}",
        extra={"trace_id": trace_id, "agent_name": "analytics"},
    )

    return result


async def get_daily_saga_progress(
    neo4j: Neo4jClient,
    date: str,
    trace_id: str | None = None,
) -> list[SagaProgress]:
    """
    Get saga progress (lore episodes) for a specific day.

    Queries LoreEpisode nodes told on the given day and returns
    saga progress information for inclusion in daily journal.

    Reference: specs/architecture/LORE_SYSTEM.md Section 5.2 (#110)

    Args:
        neo4j: Connected Neo4jClient instance
        date: Date in YYYY-MM-DD format
        trace_id: Optional trace ID for logging

    Returns:
        List of SagaProgress models with saga information
    """
    day_start, day_end = get_day_bounds(date)

    # Convert to milliseconds for told_at comparison (stored as Unix ms)
    day_start_ms = day_start * 1000
    day_end_ms = day_end * 1000

    logger.debug(
        f"[WHISPER] Gathering saga progress for {date}",
        extra={"trace_id": trace_id, "agent_name": "analytics"},
    )

    query = """
    MATCH (le:LoreEpisode)
    WHERE le.told_at >= $day_start_ms AND le.told_at < $day_end_ms
      AND le.saga_id IS NOT NULL
    RETURN le.saga_id as saga_id,
           le.saga_name as saga_name,
           le.chapter as chapter,
           le.channel as channel
    ORDER BY le.told_at ASC
    """

    result = await neo4j.execute_query(
        query,
        {"day_start_ms": day_start_ms, "day_end_ms": day_end_ms},
        trace_id=trace_id,
    )

    saga_progress = [
        SagaProgress(
            saga_id=r["saga_id"],
            saga_name=r["saga_name"] or r["saga_id"],
            chapter=r["chapter"],
            channel=r.get("channel"),
        )
        for r in result
    ]

    logger.debug(
        f"[WHISPER] Found {len(saga_progress)} saga episodes told on {date}",
        extra={"trace_id": trace_id, "agent_name": "analytics"},
    )

    return saga_progress


async def get_daily_analytics(
    neo4j: Neo4jClient,
    date: str,
    trace_id: str | None = None,
) -> DailyAnalytics:
    """
    Get comprehensive daily analytics for journal generation.

    Aggregates all daily statistics into a single model:
    - Interaction count (messages)
    - New entities by type
    - Task completion and creation
    - Top projects discussed
    - Notes and events created

    Args:
        neo4j: Connected Neo4jClient instance
        date: Date in YYYY-MM-DD format
        trace_id: Optional trace ID for logging

    Returns:
        DailyAnalytics model with all statistics
    """
    logger.info(
        f"[CHART] Gathering daily analytics for {date}",
        extra={"trace_id": trace_id, "agent_name": "analytics"},
    )

    # Gather all statistics
    interaction_count = await get_daily_interaction_count(neo4j, date, trace_id)
    new_entities = await get_daily_entity_counts(neo4j, date, trace_id)
    task_stats = await get_daily_task_stats(neo4j, date, trace_id)
    top_projects = await get_daily_projects_discussed(neo4j, date, limit=3, trace_id=trace_id)
    saga_progress = await get_daily_saga_progress(neo4j, date, trace_id)

    # Extract specific entity counts
    notes_created = new_entities.get("Note", 0)
    events_count = new_entities.get("Event", 0)

    analytics = DailyAnalytics(
        date=date,
        interaction_count=interaction_count,
        new_entities=new_entities,
        tasks_completed=task_stats["completed"],
        tasks_created=task_stats["created"],
        top_projects=top_projects,
        notes_created=notes_created,
        events_count=events_count,
        saga_progress=saga_progress,
    )

    logger.info(
        f"[BEACON] Daily analytics gathered for {date}",
        extra={
            "trace_id": trace_id,
            "agent_name": "analytics",
            "interaction_count": interaction_count,
            "new_entities_total": sum(new_entities.values()),
            "tasks_completed": task_stats["completed"],
        },
    )

    return analytics


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "get_daily_analytics",
    "get_daily_entity_counts",
    "get_daily_interaction_count",
    "get_daily_projects_discussed",
    "get_daily_saga_progress",
    "get_daily_task_stats",
    "get_day_bounds",
]
